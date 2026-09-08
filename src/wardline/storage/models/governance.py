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

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, LargeBinary, String
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

    # --- Org/workspace membership (commercialization roadmap Pillar 1) ---
    # Nullable: a solo signup or an admin-minted CLI/OIDC user belongs to no
    # org until one is created (storage/models/orgs.py) and they join it.
    org_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (Index("ix_users_org_id", "org_id"),)


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

    # --- Encrypted conversation vault (commercialization roadmap Pillar 2) ---
    # The vault DEK, re-wrapped under settings.vault_session_secret for this
    # session's lifetime (security/vault.py) -- the "session bridge" that lets
    # a request decrypt/encrypt without the plaintext password, which only
    # ever existed for the instant of the login call. Both null for any
    # session that never resolved a vault (no VaultKey, OIDC user, vault
    # disabled) and cleared on logout/revocation so a revoked session can't
    # still be unwrapped.
    vault_dek_wrapped: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    vault_dek_nonce: Mapped[bytes | None] = mapped_column(LargeBinary(12), nullable=True)

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

    # --- Encrypted conversation vault escrow (commercialization roadmap Pillar 2) ---
    # Null for a user with no vault (Free tier, org member -- see
    # security/vault.should_encrypt_history) or a code issued before this
    # existed. Populated whenever a live vault DEK is available at issuance
    # time (signup, confirm_mfa, or a password reset that re-wraps every
    # still-unused code) so ANY unredeemed code can later unwrap the vault
    # during account recovery, not just disable MFA.
    vault_wrapped_dek: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    vault_wrapped_dek_nonce: Mapped[bytes | None] = mapped_column(LargeBinary(12), nullable=True)

    __table_args__ = (Index("ix_recovery_codes_user_id", "user_id"),)


class VaultKey(Base, TimestampMixin):
    """One row per user with an encrypted conversation-history vault
    (commercialization roadmap Pillar 2, security/vault.py). Holds the
    user's data-encryption key (DEK), wrapped under a key derived from
    their password -- never the DEK itself in the clear. `kdf_salt` is a
    dedicated, deterministic-KDF salt (unlike password_hash's own argon2
    salt, which is verify-only and can't be used to re-derive the same
    key twice)."""

    __tablename__ = "vault_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "vlt"))
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    kdf_salt: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    wrapped_dek_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)


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
