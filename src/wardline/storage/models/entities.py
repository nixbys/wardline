"""Knowledge-graph nodes, canonical in Postgres (report 5.3 Entity).

These rows are the system of record for entity resolution's human-review
workflow; graph/sync.py mirrors them into Neo4j for traversal.
"""

from __future__ import annotations

from functools import partial

from sqlalchemy import Float, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from wardline.storage.models.base import Base, TimestampMixin, new_id


class Entity(Base, TimestampMixin):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "ent"))
    type: Mapped[str] = mapped_column(String(64), nullable=False)  # Person | Organization | ...
    canonical_name: Mapped[str] = mapped_column(String(512), nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    __table_args__ = (
        Index("ix_entities_type", "type"),
        Index("ix_entities_canonical_name", "canonical_name"),
    )
