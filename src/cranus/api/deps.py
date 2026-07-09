"""Shared FastAPI dependencies. Real auth/RBAC/kill-switch enforcement lands
in Phase 6 (governance/pep.py); until then `get_current_user` returns None
(anonymous), which the query pipeline already treats as a valid, if
unauthenticated, caller.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from cranus.storage.db import sync_session


def get_db() -> Iterator[Session]:
    with sync_session() as db:
        yield db


def get_current_user_id() -> str | None:
    return None
