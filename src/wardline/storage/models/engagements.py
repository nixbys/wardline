"""Engagement scope (governance plane): the missing primitive for dual-use
connectors (Shodan/Censys-style asset-exposure lookups, breach-check APIs,
SpiderFoot-style aggregators). RBAC answers "who are you", ABAC answers
"what license does this document carry" — neither answers "who authorized
looking at *this specific target* with a tool built for reconnaissance."

An Engagement records that authorization explicitly: a target, the scope of
what's authorized, a reference to the evidence for that authorization (a
signed SOW, a ticket, a contract number), and a validity window. Connectors
that set `requires_engagement = True` (see connectors/base.py) cannot run
without one — see governance/pep.py:enforce_engagement_scope.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from wardline.storage.models.base import Base, TimestampMixin, new_id


class Engagement(Base, TimestampMixin):
    __tablename__ = "engagements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "eng"))
    target: Mapped[str] = mapped_column(String(512), nullable=False)
    scope_note: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    authorized_by_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_engagements_target", "target"),)
