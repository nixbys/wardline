"""Add donations table -- a one-time Stripe Checkout payment, deliberately
unrelated to subscriptions/plan entitlements. See
storage/models/billing.py's Donation docstring.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-13

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "donations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="usd"),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column("stripe_checkout_session_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("donations")
