"""POST /v1/feedback — thumbs + correction, feeds the evaluation regression
set (report 5.11).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from wardline.api.deps import get_current_user, get_db
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
) -> dict:
    fb = Feedback(
        session_id=request.session_id, user_id=user.id, rating=request.rating, comment=request.comment
    )
    db.add(fb)
    db.flush()
    return {"id": fb.id}
