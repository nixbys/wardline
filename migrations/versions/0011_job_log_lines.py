"""Add job_log_lines table -- per-step progress lines for one IngestionJob,
the Ops Console's live "terminal" tail. See storage/models/ingestion.py's
JobLogLine docstring for why this table uses a plain auto-incrementing
integer id instead of this codebase's usual new_id()-prefixed string ids.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-13

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_log_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id", sa.String(64), sa.ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_log_lines_job_id", "job_log_lines", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_log_lines_job_id", table_name="job_log_lines")
    op.drop_table("job_log_lines")
