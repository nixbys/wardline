"""Governance & access plane (report 4.6): identity, RBAC role, the admin
kill switch, and the immutable public audit log.

`AuditEvent` is deliberately append-only: migrations/versions/0001 installs a
BEFORE UPDATE OR DELETE trigger that unconditionally raises, so immutability
is enforced by Postgres itself for every role (including the table owner —
plain REVOKE doesn't bind owners), not just by never calling `.update()` in
application code.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cranus.storage.models.base import Base, TimestampMixin, new_id, utcnow

ROLE_ADMIN = "admin"
ROLE_ANALYST = "analyst"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "user"))
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_VIEWER)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "key"))
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, default=list)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_api_keys_lookup_hash", "lookup_hash"),)


class AuditEvent(Base):
    """Append-only. No TimestampMixin (no updated_at — nothing about this row
    is ever mutated after insert)."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "aud"))
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_audit_events_session_id", "session_id"),
        Index("ix_audit_events_created_at", "created_at"),
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


KILL_SWITCH_KEY = "kill_switch_enabled"
