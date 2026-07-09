"""entity_resolution_review.entity_{a,b}_id: CASCADE -> SET NULL

A merge decision deletes the "drop" entity; the review row is the audit
record of that decision, and CASCADE was deleting it in the same instant
the merge happened. Nullable + SET NULL preserves the historical record.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-09

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("entity_resolution_review", "entity_a_id", nullable=True)
    op.alter_column("entity_resolution_review", "entity_b_id", nullable=True)

    op.drop_constraint(
        "entity_resolution_review_entity_a_id_fkey", "entity_resolution_review", type_="foreignkey"
    )
    op.create_foreign_key(
        "entity_resolution_review_entity_a_id_fkey",
        "entity_resolution_review",
        "entities",
        ["entity_a_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint(
        "entity_resolution_review_entity_b_id_fkey", "entity_resolution_review", type_="foreignkey"
    )
    op.create_foreign_key(
        "entity_resolution_review_entity_b_id_fkey",
        "entity_resolution_review",
        "entities",
        ["entity_b_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "entity_resolution_review_entity_a_id_fkey", "entity_resolution_review", type_="foreignkey"
    )
    op.create_foreign_key(
        "entity_resolution_review_entity_a_id_fkey",
        "entity_resolution_review",
        "entities",
        ["entity_a_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "entity_resolution_review_entity_b_id_fkey", "entity_resolution_review", type_="foreignkey"
    )
    op.create_foreign_key(
        "entity_resolution_review_entity_b_id_fkey",
        "entity_resolution_review",
        "entities",
        ["entity_b_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.alter_column("entity_resolution_review", "entity_a_id", nullable=False)
    op.alter_column("entity_resolution_review", "entity_b_id", nullable=False)
