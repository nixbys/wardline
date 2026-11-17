"""Org/workspace plane: the grouping entity team invites and the shared
org audit log hang off. Deliberately narrow: this table is that grouping,
no more.
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
