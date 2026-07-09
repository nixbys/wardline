"""Add engagements table (authorization-scoping for dual-use connectors).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "engagements",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("target", sa.String(512), nullable=False),
        sa.Column("scope_note", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.String(512), nullable=False),
        sa.Column(
            "authorized_by_user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_engagements_target", "engagements", ["target"])


def downgrade() -> None:
    op.drop_index("ix_engagements_target", table_name="engagements")
    op.drop_table("engagements")
