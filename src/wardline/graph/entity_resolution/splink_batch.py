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
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from wardline.common.logging import get_logger
from wardline.graph.entity_resolution.review import (
    HIGH_CONFIDENCE_THRESHOLD,
    REVIEW_THRESHOLD,
    merge_entities,
    queue_for_review,
)
from wardline.storage.models.entities import Entity

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


def _comparison():
    import splink.comparison_library as cl

    return cl.JaroWinklerAtThresholds("canonical_name", [0.9, 0.7]).configure(
        m_probabilities=_M_PROBABILITIES,
        u_probabilities=_U_PROBABILITIES,
    )


def _predict_pairs(records: list[dict]) -> list[tuple[str, str, float]]:
    """Runs a Splink dedupe pass over `records` (each a dict with
    "unique_id" and "canonical_name") and returns every candidate pair
    Splink scored above REVIEW_THRESHOLD as (id_a, id_b, match_probability).
    Imports Splink lazily so importing this module doesn't pull in
    duckdb/pandas for code paths that never run a batch pass.
    """
    import pandas as pd
    from splink import DuckDBAPI, Linker, SettingsCreator

    df = pd.DataFrame(records)
    settings = SettingsCreator(
        link_type="dedupe_only",
        probability_two_random_records_match=_PRIOR_PROBABILITY_MATCH,
        comparisons=[_comparison()],
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


def _resolve_type(db: Session, entity_type: str, stats: dict) -> None:
    entities = list(db.execute(select(Entity).where(Entity.type == entity_type)).scalars())
    if len(entities) < MIN_RECORDS_FOR_BATCH:
        return

    records = [{"unique_id": e.id, "canonical_name": e.canonical_name} for e in entities]
    by_id = {e.id: e for e in entities}

    try:
        pairs = _predict_pairs(records)
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
