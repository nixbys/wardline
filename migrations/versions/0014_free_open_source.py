"""Wardline is free and open source: drop paid-plan subscriptions and
enterprise sales leads. Donations (the `donations` table) stay.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-16

"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("enterprise_leads")
    op.drop_table("subscriptions")


def downgrade() -> None:
    # Recreates the empty tables as 0005, 0007 and 0013 left them; the rows
    # dropped by upgrade() are not restored.
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("stripe_customer_id", sa.String(128), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(128), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "org_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("org_id", name="uq_subscriptions_org_id"),
    )
    op.create_table(
        "enterprise_leads",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_email", sa.String(320), nullable=False),
        sa.Column("seats_estimate", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(2000), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
