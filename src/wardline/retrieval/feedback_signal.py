"""Retrieval feedback loop (Phase 4 of a broader adaptive-intelligence
initiative, tracked locally, not in this repo -- see .gitignore's note).

The join path this rides on: `Feedback.session_id` -> the same session's
`AuditEvent(event_type="query_closed").payload["retrieved"]` (chunk/edge
ids) -> `Chunk.doc_id`. Feedback is never encrypted (unlike a vault user's
`question`/`comment` text), so this doesn't touch the privacy boundary
`security/vault.py` protects -- it aggregates ratings and chunk ids only.

Deliberately a **dampened, bounded nudge, not a hard filter**: while
Feedback volume is sparse relative to total query traffic, a handful of
downvotes on a document shouldn't be able to zero out its rank, and a
document with only one or two votes either way shouldn't move as much as
one with a real sample -- `_aggregate_ratings` scales the adjustment by
both average rating and a confidence term that grows with vote count.

Computed and cached periodically (`worker/main.py`'s
`run_scheduled_trust_refresh`, mirroring `entity_resolution/splink_batch.py`'s
own periodic-batch convention), not recomputed per retrieval call -- the
underlying join is too expensive to redo on every search.

Applying the result to real ranking is gated by
`settings.retrieval_feedback_apply_enabled` (default off): scores are
still computed and logged either way, so an operator can see what the
signal would do before turning it on -- the staged rollout this module's
own design calls for while there isn't yet enough Feedback volume to
trust it unconditionally.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from wardline.common.config import get_settings
from wardline.common.logging import get_logger

logger = get_logger(__name__)

# Bounded so the adjustment can never more than +/-20% a document's score --
# see this module's docstring on why this stays a nudge, not a filter.
MAX_ADJUSTMENT = 0.2

# Vote count at which confidence saturates to 1.0 (full weight). Below
# this, the adjustment is scaled down proportionally so one or two early
# votes can't swing a score as hard as a real sample would.
_CONFIDENCE_SATURATION_VOTES = 10

_trust_cache: dict[str, float] = {}

_RATINGS_QUERY = """
SELECT c.doc_id, f.rating
FROM feedback f
JOIN audit_events ae ON ae.session_id = f.session_id AND ae.event_type = 'query_closed'
JOIN chunks c ON c.id IN (
    SELECT jsonb_array_elements_text(ae.payload -> 'retrieved')
)
"""


def get_trust_multiplier(doc_id: str) -> float:
    """What `retrieval/fusion.py` actually calls. Returns 1.0 (a no-op) for
    any document with no cached score, and unconditionally when the apply
    flag is off -- callers never need to check the setting themselves."""
    if not get_settings().retrieval_feedback_apply_enabled:
        return 1.0
    return _trust_cache.get(doc_id, 1.0)


def _aggregate_ratings(rows: list[tuple[str, int]]) -> dict[str, float]:
    """Pure function, unit-tested directly with plain tuples -- the SQL
    fetch above needs real Postgres JSONB support and isn't unit-testable
    against sqlite, but the aggregation math has nothing Postgres-specific
    in it and shouldn't need a live database to verify.
    """
    ratings_by_doc: dict[str, list[int]] = {}
    for doc_id, rating in rows:
        ratings_by_doc.setdefault(doc_id, []).append(rating)

    result: dict[str, float] = {}
    for doc_id, ratings in ratings_by_doc.items():
        avg_rating = sum(ratings) / len(ratings)  # Feedback.rating is -1 | 0 | 1
        confidence = min(len(ratings) / _CONFIDENCE_SATURATION_VOTES, 1.0)
        result[doc_id] = 1.0 + (avg_rating * MAX_ADJUSTMENT * confidence)
    return result


def refresh_trust_scores(db: Session) -> dict[str, float]:
    """Recomputes and replaces the whole cache. Always runs the real
    aggregation and logs the result regardless of
    `retrieval_feedback_apply_enabled` -- see this module's docstring on
    why "computed and visible" and "applied to ranking" are separate
    questions.
    """
    rows = [(str(r[0]), int(r[1])) for r in db.execute(text(_RATINGS_QUERY)).fetchall()]
    scores = _aggregate_ratings(rows)
    _trust_cache.clear()
    _trust_cache.update(scores)
    logger.info(
        "feedback_signal.refreshed",
        documents_scored=len(scores),
        applied=get_settings().retrieval_feedback_apply_enabled,
    )
    return scores


def run_scheduled_trust_refresh() -> None:
    """`worker/scheduler.py` periodic-job entrypoint -- opens its own
    session since apscheduler calls jobs with no arguments, mirroring
    `splink_batch.run_scheduled_batch_resolution`'s exact shape.
    """
    from wardline.storage.db import sync_session

    with sync_session() as db:
        refresh_trust_scores(db)
