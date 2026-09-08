"""The public, append-only audit log (report 4.6): every query is logged
*before* it runs, and the result is appended to the same session when it
finishes. Immutability is enforced at the database level — see
migrations/versions/0001 and storage/models/governance.py.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from wardline.common.errors import AccessDeniedError
from wardline.common.schemas import QuerySession
from wardline.security import vault
from wardline.storage.models.base import new_id
from wardline.storage.models.governance import ROLE_ADMIN, AuditEvent, User


def open_session(
    db: Session, user_id: str | None, question: str, mode: str, *, dek: bytes | None = None
) -> str:
    """`dek`, when given (a Pro solo user's vault key, resolved by the
    caller via api/deps.get_vault_dek — commercialization roadmap Phase 2),
    stores the question encrypted (`question_enc`) instead of plaintext
    (`question`). `get_session_events`/anything else reading this payload
    checks which key is present rather than assuming one or the other."""
    session_id = new_id("qs")
    payload: dict = {"mode": mode}
    if dek is not None:
        payload["question_enc"] = vault.encrypt_field(dek, question)
    else:
        payload["question"] = question
    event = AuditEvent(
        session_id=session_id,
        event_type="query_opened",
        user_id=user_id,
        payload=payload,
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


def build_query_session(events: list[AuditEvent], caller: User, dek: bytes | None) -> QuerySession:
    """Folds one session's events into the report's QuerySession shape
    (api/routers/session.py's `GET /v1/session/{id}`). Raises
    AccessDeniedError — the router maps this to a 404, not a 403, so a
    non-owner can't tell an encrypted session exists at all — for a
    session with no events, or an *encrypted* one (a Pro solo user's
    private history) the caller doesn't own and isn't an admin. A
    plaintext session (the Team/shared-audit-log model) stays readable by
    any authenticated caller, unchanged from before Phase 2."""
    if not events:
        raise AccessDeniedError("session not found")

    opened = next((e for e in events if e.event_type == "query_opened"), None)
    closed = next((e for e in events if e.event_type == "query_closed"), None)

    question_enc = opened.payload.get("question_enc") if opened else None
    if question_enc is not None:
        owner_id = opened.user_id if opened else None
        if not (caller.role == ROLE_ADMIN or (owner_id is not None and owner_id == caller.id)):
            raise AccessDeniedError("session not found")
        if dek is None:
            # Shouldn't happen for the owner on an active session -- fail
            # loudly (a plain 500, not a 404 -- this isn't an access-denial)
            # rather than return garbage or silently omit the question.
            raise RuntimeError("could not resolve vault key for an encrypted session's owner")
        question = vault.decrypt_field(dek, question_enc)
    else:
        question = (opened.payload.get("question") if opened else "") or ""

    return QuerySession(
        session_id=events[0].session_id,
        user_id=(opened.user_id if opened else None) or "anonymous",
        question=question,
        asked_at=opened.created_at if opened else events[0].created_at,
        retrieved=(closed.payload.get("retrieved") if closed else []) or [],
        answer_hash=(closed.payload.get("answer_hash") if closed else None),
        latency_ms=(closed.payload.get("latency_ms") if closed else None),
        token_cost=(closed.payload.get("token_cost") if closed else None),
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
