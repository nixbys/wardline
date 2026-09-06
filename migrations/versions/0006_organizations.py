"""Add organizations table and users.org_id (commercialization roadmap
Pillar 1: the "one org, several seats" grouping entity invites need).
Deliberately narrow: subscriptions stay keyed to user_id unchanged --
org-scoped billing is separate follow-on work.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-06

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "owner_user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column(
        "users",
        sa.Column(
            "org_id", sa.String(64), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_column("users", "org_id")
    op.drop_table("organizations")
