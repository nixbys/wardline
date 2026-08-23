"""Human-in-the-loop entity resolution review queue (report 4.5). Admin/analyst only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from wardline.api.deps import get_db, require_role
from wardline.graph.entity_resolution import review
from wardline.graph.entity_resolution.splink_batch import run_batch_resolution
from wardline.storage.models.entities import Entity
from wardline.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, User

router = APIRouter(prefix="/v1/admin/entity-review", tags=["entity-review"])
_reviewer_role = require_role(ROLE_ADMIN, ROLE_ANALYST)
_admin_only = require_role(ROLE_ADMIN)


class ReviewDecision(BaseModel):
    decision: str  # "merged" | "rejected"


@router.get("/queue")
def list_queue(db: Session = Depends(get_db), _user: User = Depends(_reviewer_role)) -> list[dict]:
    pending = review.list_pending(db)
    out = []
    for r in pending:
        entity_a = db.get(Entity, r.entity_a_id) if r.entity_a_id else None
        entity_b = db.get(Entity, r.entity_b_id) if r.entity_b_id else None
        out.append(
            {
                "id": r.id,
                "score": r.score,
                "entity_a": {"id": entity_a.id, "name": entity_a.canonical_name} if entity_a else None,
                "entity_b": {"id": entity_b.id, "name": entity_b.canonical_name} if entity_b else None,
                "created_at": r.created_at,
            }
        )
    return out


@router.post("/{review_id}/decision")
def decide(
    review_id: str,
    body: ReviewDecision,
    db: Session = Depends(get_db),
    user: User = Depends(_reviewer_role),
) -> dict:
    result = review.decide(db, review_id, body.decision, user.id)
    return {"id": result.id, "status": result.status}


@router.post("/batch-resolve")
def batch_resolve(
    entity_type: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(_admin_only),
) -> dict:
    """Run one Splink batch dedupe pass on demand (also runs on the
    `entity_resolution_batch_interval_seconds` schedule -- see
    `worker/main.py`). Admin-only: this can queue reviews and merge
    entities outright above the high-confidence threshold.
    """
    return run_batch_resolution(db, entity_type=entity_type)
