"""Engine/session management. The API uses the async engine; the worker and
CLI use the sync engine — both point at the same Postgres instance and share
the same declarative models.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from wardline.common.config import get_settings

_async_engine: AsyncEngine | None = None
_async_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_sync_engine = None
_sync_sessionmaker: sessionmaker[Session] | None = None


def get_async_engine() -> AsyncEngine:
    global _async_engine
    if _async_engine is None:
        _async_engine = create_async_engine(get_settings().database_url_async, pool_pre_ping=True)
    return _async_engine


def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _async_sessionmaker
    if _async_sessionmaker is None:
        _async_sessionmaker = async_sessionmaker(get_async_engine(), expire_on_commit=False)
    return _async_sessionmaker


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with get_async_sessionmaker()() as session:
        yield session


def get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _sync_engine


def get_sync_sessionmaker() -> sessionmaker[Session]:
    global _sync_sessionmaker
    if _sync_sessionmaker is None:
        _sync_sessionmaker = sessionmaker(get_sync_engine(), expire_on_commit=False)
    return _sync_sessionmaker


@contextmanager
def sync_session() -> Iterator[Session]:
    """Worker/CLI usage: `with sync_session() as db: ...`."""
    session = get_sync_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
