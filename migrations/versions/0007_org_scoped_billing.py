"""Add subscriptions.org_id (commercialization roadmap Pillar 5: a per-seat
plan bought once by an org's owner covers every member of that org).
Nullable and unique when set -- an org has at most one subscription;
existing per-user subscriptions are untouched (org_id stays NULL for them).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-07

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "org_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_unique_constraint("uq_subscriptions_org_id", "subscriptions", ["org_id"])


def downgrade() -> None:
    op.drop_constraint("uq_subscriptions_org_id", "subscriptions", type_="unique")
    op.drop_column("subscriptions", "org_id")
