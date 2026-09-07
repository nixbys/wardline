"""Unit coverage for api/routers/query.py's per-plan rate limit (commercialization
roadmap Pillar 5: "the one thing standing between a free-tier key and a real
bill"). `_resolve_plan_rate_limit` takes an injected Session rather than
opening a real one, purely so this doesn't need Postgres — same in-memory
SQLite + JSONB-as-JSON compiler shim convention as test_accounts.py, since
`ApiKey.scopes` is a Postgres JSONB column.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.types import JSON

from wardline.api.routers.query import _resolve_plan_rate_limit
from wardline.common.plans import get_plan
from wardline.common.security import generate_api_key, lookup_key_for_index
from wardline.storage.models.base import Base
from wardline.storage.models.billing import STATUS_ACTIVE, Subscription
from wardline.storage.models.governance import ApiKey, User


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json_on_sqlite(element, compiler, **kw):  # pragma: no cover - DDL glue
    return compiler.visit_JSON(JSON(), **kw)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[User.__table__, ApiKey.__table__, Subscription.__table__]
    )
    with Session(engine) as session:
        yield session


def _make_user_with_key(db, *, plan: str | None = None, revoked: bool = False) -> str:
    user = User(email=f"{plan or 'free'}@example.com", role="viewer")
    db.add(user)
    db.flush()
    if plan is not None:
        db.add(Subscription(user_id=user.id, plan=plan, status=STATUS_ACTIVE))
    plaintext, key_hash = generate_api_key()
    db.add(
        ApiKey(
            user_id=user.id,
            key_hash=key_hash,
            lookup_hash=lookup_key_for_index(plaintext),
            scopes=["*"],
            revoked=revoked,
        )
    )
    db.flush()
    return plaintext


def test_resolves_the_free_default_for_a_user_with_no_subscription(db):
    key = _make_user_with_key(db, plan=None)
    assert _resolve_plan_rate_limit(db, key) == f"{get_plan('free').query_rate_limit_per_minute}/minute"


def test_resolves_a_higher_limit_for_a_paid_plan(db):
    key = _make_user_with_key(db, plan="enterprise")
    assert _resolve_plan_rate_limit(db, key) == "120/minute"


def test_returns_none_for_an_unknown_key():
    # No db row backs this plaintext at all -- distinct from "wrong hash".
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, ApiKey.__table__, Subscription.__table__])
    with Session(engine) as db:
        assert _resolve_plan_rate_limit(db, "wl_not-a-real-key") is None


def test_returns_none_for_a_revoked_key(db):
    key = _make_user_with_key(db, plan="pro", revoked=True)
    assert _resolve_plan_rate_limit(db, key) is None
