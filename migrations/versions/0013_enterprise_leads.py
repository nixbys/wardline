"""Add enterprise_leads table -- "Talk to sales" submissions from
pricing.html's Enterprise card. See storage/models/billing.py's
EnterpriseLead docstring: contract-billed outside Subscription/Stripe,
tracked by an admin/analyst through to a provisioned instance.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-13

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_table("enterprise_leads")
