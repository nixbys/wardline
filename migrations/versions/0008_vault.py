"""Add the encrypted conversation-history vault (commercialization roadmap
Phase 2 / Pillar 2): vault_keys (one row per user with a vault -- their
data-encryption key, wrapped under a password-derived key-encryption key),
plus vault-escrow columns on recovery_codes (so an unredeemed MFA recovery
code can also unwrap the vault) and a session-bridge pair on api_keys (the
vault key re-wrapped under a server-held secret for an active session's
lifetime, cleared on logout).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-08

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vault_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("kdf_salt", sa.LargeBinary(16), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek_nonce", sa.LargeBinary(12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("recovery_codes", sa.Column("vault_wrapped_dek", sa.LargeBinary(), nullable=True))
    op.add_column(
        "recovery_codes", sa.Column("vault_wrapped_dek_nonce", sa.LargeBinary(12), nullable=True)
    )

    op.add_column("api_keys", sa.Column("vault_dek_wrapped", sa.LargeBinary(), nullable=True))
    op.add_column("api_keys", sa.Column("vault_dek_nonce", sa.LargeBinary(12), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "vault_dek_nonce")
    op.drop_column("api_keys", "vault_dek_wrapped")

    op.drop_column("recovery_codes", "vault_wrapped_dek_nonce")
    op.drop_column("recovery_codes", "vault_wrapped_dek")

    op.drop_table("vault_keys")
