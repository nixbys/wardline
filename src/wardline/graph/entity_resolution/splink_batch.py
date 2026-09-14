"""Batch entity resolution via Splink -- report 4.5's noted upgrade path
from the incremental homemade blocking/scoring resolver used at ingestion
time (`graph/pipeline.py::_resolve_mention`, `blocking.py`, `scoring.py`).

That per-mention resolver runs synchronously on the ingestion hot path and
has to decide in milliseconds against a fixed, hand-weighted scoring
function -- there's no room in that path for proper parameter estimation.
This module does the complementary job: periodically re-examine the
*whole* entity table for one type at a time and catch duplicates the fast
incremental path's blocking missed (a spelling variant that landed in a
different metaphone block, e.g.), using Splink's real DuckDB-backed
Fellegi-Sunter comparison engine instead of a fixed 60/30/10 average.

Match weights are set explicitly rather than trained via
`estimate_parameters_using_expectation_maximisation`: EM needs a genuinely
large, representative sample to converge to well-calibrated probabilities
(Splink's own guidance is comfortably four-plus-digit record counts), and
on the small-to-medium entity tables this batch job actually sees, EM's
prior-probability estimate is dominated by noise -- in testing it swung
between wildly overconfident and (more often) so conservative that even
exact-name duplicates scored under 0.1. Manually-specified m/u values are
an officially documented Splink workflow for exactly this situation
("you may already know the appropriate parameter values ... from domain
knowledge"). The values below were chosen from the Fellegi-Sunter log-odds
arithmetic directly (see the comment on each), not guessed, and verified
against a labelled synthetic set covering all four cases: exact duplicate,
strong near-duplicate (nickname/suffix), weak similarity (different given
name, same surname), and unrelated. An operator with enough volume in one
`Entity.type` to make EM worthwhile can swap `_comparison()` for a
trained `Linker` without changing anything else in this module.

Decisions still flow through the same governance the incremental resolver
uses (`review.py`): match_probability at or above HIGH_CONFIDENCE_THRESHOLD
merges immediately, at or above REVIEW_THRESHOLD queues for human review,
below that is discarded. Wrong merges are worse than misses either way
this runs.

--- Phase 5 (active learning from human review decisions, tracked
locally, not in this repo) ---

The upgrade path this module's own docstring above already named --
"swap `_comparison()` for a trained `Linker`" -- turned out to need one
real fix first: `EntityResolutionReview.entity_b_id` is `ON DELETE SET
NULL` (see that model's docstring), so by the time a "merged" decision's
row could be used as training data, the entity it names is already gone.
`review.queue_for_review` now snapshots both names (and the shared type)
at queue time, while both entities still exist, specifically so this
training step has something to learn from later.

Splink 4.0's `estimate_m_from_pairwise_labels` only accepts *positive*
labels (every row in the labels table is treated as a confirmed match) --
there is no corresponding negative/"rejected"-pair input in this version,
so `status == "rejected"` reviews aren't usable for training at all. Only
`m` gets trained this way; `u` keeps the manually-specified values above
regardless (verified directly: a trained level's `u_probability` is
untouched after `estimate_m_from_pairwise_labels` runs). An untrained
level (one no labeled pair happened to exercise) keeps its prior manual
`m_probability` too, rather than becoming zero or `None` -- confirmed by
inspecting `linker.misc.save_model_to_json()`'s output directly, not
assumed from the library's docs.

Training runs against a throwaway linker built from the labeled *names*
only, decoupled from whatever entity ids exist live right now -- the
resulting m-probabilities are properties of the comparison function's
general behavior on real confirmed matches, not tied to the specific rows
trained on, so they're reused for the *next* `_resolve_type` pass over
the live entity table exactly like the manually-specified defaults are.

Gated by `settings.entity_resolution_training_enabled` (default off) and
a minimum labeled-pair count (`entity_resolution_min_labels_for_training`,
default 20 -- a starting point to revisit once there's real decision
volume, not derived from Splink's own EM guidance the way the manual m/u
values above were, since supervised training from real labels is a
different, more label-efficient regime than the unsupervised EM that
guidance was about).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from wardline.common.config import get_settings
from wardline.common.logging import get_logger
from wardline.graph.entity_resolution.review import (
    HIGH_CONFIDENCE_THRESHOLD,
    REVIEW_THRESHOLD,
    merge_entities,
    queue_for_review,
)
from wardline.storage.models.entities import Entity
from wardline.storage.models.entity_resolution import EntityResolutionReview

logger = get_logger(__name__)

# Below this many records in a type, a batch pass has too little to work
# with to be worth the DuckDB round-trip; leave it to the incremental
# resolver alone.
MIN_RECORDS_FOR_BATCH = 4

# Fellegi-Sunter comparison levels for `canonical_name`: exact / Jaro-Winkler
# >= 0.9 / Jaro-Winkler >= 0.7 / else. m = P(this level | same entity),
# u = P(this level | different entities) -- each column sums to ~1 across
# the four levels. Chosen so that, combined with PRIOR below via
# log2(m/u) + log2(prior/(1-prior)):
#   exact match            -> ~0.99  (comfortably above HIGH_CONFIDENCE_THRESHOLD)
#   strong near-duplicate  -> ~0.78  (just above REVIEW_THRESHOLD)
#   weak similarity        -> ~0.08  (discarded, not even queued)
#   unrelated              -> ~0.001 (discarded)
_M_PROBABILITIES = [0.83, 0.12, 0.04, 0.01]
_U_PROBABILITIES = [0.0005, 0.003, 0.04, 0.9565]
_PRIOR_PROBABILITY_MATCH = 0.08


def _comparison(m_probabilities: list[float] | None = None):
    import splink.comparison_library as cl

    return cl.JaroWinklerAtThresholds("canonical_name", [0.9, 0.7]).configure(
        m_probabilities=m_probabilities or _M_PROBABILITIES,
        u_probabilities=_U_PROBABILITIES,
    )


def _predict_pairs(
    records: list[dict], m_probabilities: list[float] | None = None
) -> list[tuple[str, str, float]]:
    """Runs a Splink dedupe pass over `records` (each a dict with
    "unique_id" and "canonical_name") and returns every candidate pair
    Splink scored above REVIEW_THRESHOLD as (id_a, id_b, match_probability).
    Imports Splink lazily so importing this module doesn't pull in
    duckdb/pandas for code paths that never run a batch pass.

    `m_probabilities`, when given, is this type's trained values (Phase 5)
    in place of the manually-specified defaults -- `u_probabilities` is
    never overridden here (see this module's Phase 5 docstring section).
    """
    import pandas as pd
    from splink import DuckDBAPI, Linker, SettingsCreator

    df = pd.DataFrame(records)
    settings = SettingsCreator(
        link_type="dedupe_only",
        probability_two_random_records_match=_PRIOR_PROBABILITY_MATCH,
        comparisons=[_comparison(m_probabilities)],
        # Every candidate pair within a type: callers already scope one
        # `Entity.type` per call, and the table sizes this batch job runs
        # over don't need blocking to stay fast.
        blocking_rules_to_generate_predictions=["1=1"],
    )
    linker = Linker(df, settings, db_api=DuckDBAPI())
    preds_df = linker.inference.predict(
        threshold_match_probability=REVIEW_THRESHOLD
    ).as_pandas_dataframe()
    return [
        (row.unique_id_l, row.unique_id_r, float(row.match_probability))
        for row in preds_df.itertuples()
    ]


def _labeled_merge_pairs(db: Session, entity_type: str) -> list[tuple[str, str]]:
    """Real, human-confirmed positive (name_a, name_b) pairs for this
    entity type, from EntityResolutionReview rows decided "merged" --
    "rejected" reviews aren't usable here, see this module's Phase 5
    docstring section for why.
    """
    stmt = select(EntityResolutionReview).where(
        EntityResolutionReview.status == "merged",
        EntityResolutionReview.entity_type == entity_type,
        EntityResolutionReview.entity_a_name.is_not(None),
        EntityResolutionReview.entity_b_name.is_not(None),
    )
    return [(r.entity_a_name, r.entity_b_name) for r in db.execute(stmt).scalars()]


def _train_m_probabilities(labeled_pairs: list[tuple[str, str]]) -> list[float] | None:
    """Fits `canonical_name`'s m-probabilities from real labeled pairs via
    Splink's supervised `estimate_m_from_pairwise_labels`, using a
    throwaway linker built from the labeled *names* only -- decoupled
    from whatever entity ids exist live right now, since a pair's names
    outlive the entities `merge_entities` deletes. Returns `None` (never
    raises) on any failure -- training must never sink a batch pass that
    would otherwise still work with the manual defaults.
    """
    if not labeled_pairs:
        return None
    try:
        import pandas as pd
        from splink import DuckDBAPI, Linker, SettingsCreator

        records, label_rows = [], []
        for i, (name_a, name_b) in enumerate(labeled_pairs):
            left_id, right_id = f"a_{i}", f"b_{i}"
            records.append({"unique_id": left_id, "canonical_name": name_a})
            records.append({"unique_id": right_id, "canonical_name": name_b})
            label_rows.append({"unique_id_l": left_id, "unique_id_r": right_id})

        settings = SettingsCreator(
            link_type="dedupe_only",
            probability_two_random_records_match=_PRIOR_PROBABILITY_MATCH,
            comparisons=[_comparison()],
            blocking_rules_to_generate_predictions=["1=1"],
        )
        linker = Linker(pd.DataFrame(records), settings, db_api=DuckDBAPI())
        linker.table_management.register_table(pd.DataFrame(label_rows), "labels", overwrite=True)
        linker.training.estimate_m_from_pairwise_labels("labels")

        trained = linker.misc.save_model_to_json()
        levels = trained["comparisons"][0]["comparison_levels"]
        # levels[0] is the null-check level (never in _M_PROBABILITIES);
        # the rest map 1:1 onto [exact, >=0.9, >=0.7, else] in that order.
        return [level["m_probability"] for level in levels[1:]]
    except Exception as exc:
        logger.error("entity_resolution.training_failed", error=str(exc))
        return None


def _resolve_type(db: Session, entity_type: str, stats: dict) -> None:
    entities = list(db.execute(select(Entity).where(Entity.type == entity_type)).scalars())
    if len(entities) < MIN_RECORDS_FOR_BATCH:
        return

    records = [{"unique_id": e.id, "canonical_name": e.canonical_name} for e in entities]
    by_id = {e.id: e for e in entities}

    settings = get_settings()
    trained_m = None
    if settings.entity_resolution_training_enabled:
        labeled_pairs = _labeled_merge_pairs(db, entity_type)
        if len(labeled_pairs) >= settings.entity_resolution_min_labels_for_training:
            trained_m = _train_m_probabilities(labeled_pairs)
            if trained_m is not None:
                stats["types_trained"] = stats.get("types_trained", 0) + 1
                logger.info(
                    "entity_resolution.trained_from_labels",
                    entity_type=entity_type,
                    labeled_pairs=len(labeled_pairs),
                )

    try:
        pairs = _predict_pairs(records, m_probabilities=trained_m)
    except Exception as exc:  # Splink failing on this type must not sink the whole batch
        logger.error("entity_resolution.batch_type_failed", entity_type=entity_type, error=str(exc))
        return

    stats["pairs_scored"] += len(pairs)
    dropped: set[str] = set()
    for id_a, id_b, prob in sorted(pairs, key=lambda p: p[2], reverse=True):
        if id_a in dropped or id_b in dropped or id_a not in by_id or id_b not in by_id:
            continue  # one side already merged away earlier in this pass
        if prob >= HIGH_CONFIDENCE_THRESHOLD:
            merge_entities(db, keep_id=id_a, drop_id=id_b)
            dropped.add(id_b)
            stats["merged"] += 1
        elif prob >= REVIEW_THRESHOLD:
            queue_for_review(db, by_id[id_a].id, by_id[id_b].id, prob)
            stats["queued_for_review"] += 1


def run_batch_resolution(db: Session, entity_type: str | None = None) -> dict:
    """One dedupe pass. Scoped to a single entity `type` at a time --
    blocking across types makes no sense, a Person can't be a duplicate of
    an Organization -- so with no `entity_type` given this loops over every
    type currently present.
    """
    types = (
        [entity_type]
        if entity_type
        else [row[0] for row in db.execute(select(Entity.type).distinct())]
    )

    stats = {"types_scanned": 0, "pairs_scored": 0, "merged": 0, "queued_for_review": 0}
    for t in types:
        stats["types_scanned"] += 1
        _resolve_type(db, t, stats)

    db.flush()
    logger.info("entity_resolution.batch_complete", **stats)
    return stats


def run_scheduled_batch_resolution() -> None:
    """`worker/scheduler.py` periodic-job entrypoint: opens its own session
    since apscheduler calls jobs with no arguments.
    """
    from wardline.storage.db import sync_session

    with sync_session() as db:
        run_batch_resolution(db)
