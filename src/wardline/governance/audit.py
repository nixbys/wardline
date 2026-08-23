"""The public, append-only audit log (report 4.6): every query is logged
*before* it runs, and the result is appended to the same session when it
finishes. Immutability is enforced at the database level — see
migrations/versions/0001 and storage/models/governance.py.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from wardline.storage.models.base import new_id
from wardline.storage.models.governance import AuditEvent


def open_session(db: Session, user_id: str | None, question: str, mode: str) -> str:
    session_id = new_id("qs")
    event = AuditEvent(
        session_id=session_id,
        event_type="query_opened",
        user_id=user_id,
        payload={"question": question, "mode": mode},
    )
    db.add(event)
    db.flush()
    return session_id


def log_event(db: Session, session_id: str, event_type: str, user_id: str | None, payload: dict) -> None:
    db.add(AuditEvent(session_id=session_id, event_type=event_type, user_id=user_id, payload=payload))
    db.flush()


def close_session(
    db: Session,
    session_id: str,
    user_id: str | None,
    *,
    retrieved: list[str],
    latency_ms: int,
    answer_hash: str,
    token_cost: int | None = None,
) -> None:
    log_event(
        db,
        session_id,
        "query_closed",
        user_id,
        {
            "retrieved": retrieved,
            "latency_ms": latency_ms,
            "answer_hash": answer_hash,
            "token_cost": token_cost,
        },
    )


def get_session_events(db: Session, session_id: str) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.session_id == session_id).order_by(AuditEvent.created_at)
    return list(db.execute(stmt).scalars())


def get_events(
    db: Session, user_id: str | None = None, since=None, limit: int = 200
) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if user_id:
        stmt = stmt.where(AuditEvent.user_id == user_id)
    if since:
        stmt = stmt.where(AuditEvent.created_at >= since)
    return list(db.execute(stmt).scalars())
