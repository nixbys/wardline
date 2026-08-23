"""Human-in-the-loop review (report 4.5): borderline-confidence merges are
routed here instead of auto-merged. Wrong merges are worse than misses —
they fabricate connections — so anything below the high-confidence
threshold waits for a decision.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from wardline.storage.models.base import utcnow
from wardline.storage.models.entities import Entity
from wardline.storage.models.entity_resolution import EntityResolutionReview

HIGH_CONFIDENCE_THRESHOLD = 0.92
REVIEW_THRESHOLD = 0.75


def queue_for_review(db: Session, entity_a_id: str, entity_b_id: str, score: float) -> EntityResolutionReview:
    review = EntityResolutionReview(entity_a_id=entity_a_id, entity_b_id=entity_b_id, score=score)
    db.add(review)
    db.flush()
    return review


def list_pending(db: Session) -> list[EntityResolutionReview]:
    stmt = select(EntityResolutionReview).where(EntityResolutionReview.status == "pending")
    return list(db.execute(stmt).scalars())


def decide(db: Session, review_id: str, decision: str, decided_by: str | None) -> EntityResolutionReview:
    review = db.get(EntityResolutionReview, review_id)
    if review is None:
        raise KeyError(f"No review row {review_id}")
    review.status = decision  # "merged" | "rejected"
    review.decided_by = decided_by
    review.decided_at = utcnow()
    if decision == "merged":
        merge_entities(db, review.entity_a_id, review.entity_b_id)
    db.flush()
    return review


def merge_entities(db: Session, keep_id: str, drop_id: str) -> None:
    """Fold `drop_id` into `keep_id`: union aliases, repoint edges/mentions,
    delete the dropped row. Shared by the human review decision above and
    the Splink batch pass (`splink_batch.py`) so both merge paths behave
    identically.
    """
    keep = db.get(Entity, keep_id)
    drop = db.get(Entity, drop_id)
    if keep is None or drop is None:
        return
    keep.aliases = list(set(keep.aliases) | {drop.canonical_name} | set(drop.aliases))
    from wardline.storage.models.edges import Edge
    from wardline.storage.models.entity_resolution import EntityMention

    db.execute(
        Edge.__table__.update().where(Edge.from_entity_id == drop_id).values(from_entity_id=keep_id)
    )
    db.execute(Edge.__table__.update().where(Edge.to_entity_id == drop_id).values(to_entity_id=keep_id))
    db.execute(
        EntityMention.__table__.update()
        .where(EntityMention.suggested_entity_id == drop_id)
        .values(suggested_entity_id=keep_id)
    )
    db.delete(drop)
