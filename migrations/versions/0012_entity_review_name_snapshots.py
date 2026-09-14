"""Add entity_a_name/entity_b_name/entity_type snapshot columns to
entity_resolution_review. See storage/models/entity_resolution.py's
EntityResolutionReview docstring for why: entity_b_id (and its name)
disappears via ON DELETE SET NULL the moment a "merged" decision actually
runs, so without a snapshot taken at queue_for_review() time, a resolved
review row remembers a decision was made but not what it was about.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-13

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("entity_resolution_review", sa.Column("entity_a_name", sa.String(512), nullable=True))
    op.add_column("entity_resolution_review", sa.Column("entity_b_name", sa.String(512), nullable=True))
    op.add_column("entity_resolution_review", sa.Column("entity_type", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("entity_resolution_review", "entity_type")
    op.drop_column("entity_resolution_review", "entity_b_name")
    op.drop_column("entity_resolution_review", "entity_a_name")
