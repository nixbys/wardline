"""POST /v1/feedback — thumbs + correction, feeds the evaluation regression
set (report 5.11).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from wardline.api.deps import get_current_user, get_db, get_vault_dek
from wardline.security.vault import encrypt_field, should_encrypt_history
from wardline.storage.models.feedback import Feedback
from wardline.storage.models.governance import User

router = APIRouter(prefix="/v1", tags=["feedback"])


class FeedbackRequest(BaseModel):
    session_id: str
    rating: int
    comment: str | None = None


@router.post("/feedback")
def submit_feedback(
    request: FeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    dek: bytes | None = Depends(get_vault_dek),
) -> dict:
    comment = request.comment
    if comment and dek is not None and should_encrypt_history(db, user):
        comment = encrypt_field(dek, comment)
    fb = Feedback(
        session_id=request.session_id, user_id=user.id, rating=request.rating, comment=comment
    )
    db.add(fb)
    db.flush()
    return {"id": fb.id}
