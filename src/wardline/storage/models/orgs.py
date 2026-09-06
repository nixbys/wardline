"""Org/workspace plane (commercialization roadmap Pillar 1: "one org,
several seats" as the unit customers actually get billed for). Deliberately
narrow for now: this table is the grouping entity invites need, no more.
`Subscription` stays keyed to `user_id` (see storage/models/billing.py) --
org-scoped/seat-counted billing is real follow-on work once this entity
exists to hang it off of, not bundled in here.
"""

from __future__ import annotations

from functools import partial

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from wardline.storage.models.base import Base, TimestampMixin, new_id


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "org"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
