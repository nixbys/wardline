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

from wardline.storage.models.base import Base, TimestampMixin, new_id, utcnow

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

    # --- Self-serve accounts (commercialization roadmap Pillar 1) ---
    # All nullable: an admin-minted (CLI) or OIDC-authenticated user has
    # neither a local password nor local MFA — an admin or an external IdP
    # asserts their identity instead, not this table.
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


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


class AuthToken(Base, TimestampMixin):
    """Single-use links for email verification, password reset, and admin
    invites (governance/accounts.py). One table, a `purpose` column,
    rather than three near-identical tables — the shape (a hash, an
    expiry, a used-once flag) is identical across all three."""

    __tablename__ = "auth_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "tok"))
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_auth_tokens_token_hash", "token_hash"),)


class RecoveryCode(Base, TimestampMixin):
    """MFA backup codes (governance/accounts.py + governance/mfa.py) — a
    batch is issued once when MFA is confirmed, each usable exactly once."""

    __tablename__ = "recovery_codes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "rec"))
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_recovery_codes_user_id", "user_id"),)


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
