"""Knowledge-graph browsing for the Ops Console. `graph/repository.py`'s
`find_entity_by_name`/`traverse` already existed (used internally by
`graph/relation_extraction.py` and friends) but had no API route -- nothing
let an operator actually look at what's in Neo4j. Admin/analyst only, same
gate as `entity_review.py`'s queue: this is operational visibility into the
graph, not a public query surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from wardline.api.deps import require_role
from wardline.graph import repository
from wardline.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, User

router = APIRouter(prefix="/v1/admin/graph", tags=["admin-graph"])
_operator_role = require_role(ROLE_ADMIN, ROLE_ANALYST)


@router.get("/entities/search")
def search_entity(name: str = Query(...), _user: User = Depends(_operator_role)) -> dict:
    entity = repository.find_entity_by_name(name)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"no entity named {name!r}")
    return entity


@router.get("/entities/{entity_id}/traverse")
def traverse_entity(
    entity_id: str, hops: int = Query(default=1, ge=1, le=3), _user: User = Depends(_operator_role)
) -> list[dict]:
    return repository.traverse(entity_id, hops=hops)
