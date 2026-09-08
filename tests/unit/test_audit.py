"""Unit coverage for governance/audit.py's build_query_session — the
ownership check + decrypt path GET /v1/session/{id} (api/routers/session.py)
delegates to, matching this codebase's router-thin convention. Doesn't need
a real Session/database: AuditEvent rows are constructed in memory (no
db.add/flush), since build_query_session only reads their attributes.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wardline.common.errors import AccessDeniedError
from wardline.governance.audit import build_query_session
from wardline.security import vault
from wardline.storage.models.governance import ROLE_ADMIN, ROLE_VIEWER, AuditEvent, User

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _opened(*, user_id: str | None, payload: dict) -> AuditEvent:
    return AuditEvent(
        session_id="qs_1",
        event_type="query_opened",
        user_id=user_id,
        payload=payload,
        created_at=_NOW,
    )


def test_no_events_is_not_found():
    with pytest.raises(AccessDeniedError, match="not found"):
        build_query_session([], User(id="u1", email="a@example.com", role=ROLE_VIEWER), None)


def test_plaintext_session_is_readable_by_anyone_authenticated():
    """The shared-audit-log model: unchanged from before Phase 2."""
    events = [
        _opened(user_id="owner", payload={"question": "what's CVE-2024-1234?", "mode": "auto"})
    ]
    caller = User(id="someone_else", email="b@example.com", role=ROLE_VIEWER)
    result = build_query_session(events, caller, None)
    assert result.question == "what's CVE-2024-1234?"
    assert result.user_id == "owner"


def test_encrypted_session_readable_by_its_owner():
    dek = vault.generate_dek()
    events = [
        _opened(
            user_id="owner",
            payload={
                "question_enc": vault.encrypt_field(dek, "a private question"),
                "mode": "auto",
            },
        )
    ]
    owner = User(id="owner", email="a@example.com", role=ROLE_VIEWER)
    result = build_query_session(events, owner, dek)
    assert result.question == "a private question"


def test_encrypted_session_hides_from_a_non_owner_non_admin():
    dek = vault.generate_dek()
    events = [
        _opened(
            user_id="owner",
            payload={
                "question_enc": vault.encrypt_field(dek, "a private question"),
                "mode": "auto",
            },
        )
    ]
    someone_else = User(id="someone_else", email="b@example.com", role=ROLE_VIEWER)
    with pytest.raises(AccessDeniedError, match="not found"):
        build_query_session(events, someone_else, None)


def test_encrypted_session_readable_by_an_admin():
    dek = vault.generate_dek()
    events = [
        _opened(
            user_id="owner",
            payload={
                "question_enc": vault.encrypt_field(dek, "a private question"),
                "mode": "auto",
            },
        )
    ]
    admin = User(id="admin_1", email="admin@example.com", role=ROLE_ADMIN)
    result = build_query_session(events, admin, dek)
    assert result.question == "a private question"


def test_encrypted_session_with_no_resolvable_dek_fails_loudly_not_silently():
    dek = vault.generate_dek()
    events = [
        _opened(
            user_id="owner",
            payload={
                "question_enc": vault.encrypt_field(dek, "a private question"),
                "mode": "auto",
            },
        )
    ]
    owner = User(id="owner", email="a@example.com", role=ROLE_VIEWER)
    with pytest.raises(RuntimeError, match="vault key"):
        build_query_session(events, owner, None)
