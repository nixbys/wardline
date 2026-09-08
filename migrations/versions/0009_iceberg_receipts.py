"""Add iceberg_export_receipts (commercialization roadmap Phase 2 / Pillar
3.3): a small, ML-DSA-signed receipt per Iceberg audit-log export run --
snapshot id, row count, time range, a SHA-256 hash over what was exported,
plus the signature and the exact public key that produced it (denormalized
per row so a receipt stays independently verifiable even after the signing
key later rotates).

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-08

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "iceberg_export_receipts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("time_range_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_range_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("batch_sha256", sa.String(64), nullable=False),
        sa.Column("algorithm", sa.String(32), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_iceberg_export_receipts_snapshot_id", "iceberg_export_receipts", ["snapshot_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_iceberg_export_receipts_snapshot_id", table_name="iceberg_export_receipts")
    op.drop_table("iceberg_export_receipts")
