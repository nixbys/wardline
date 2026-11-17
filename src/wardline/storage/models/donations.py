"""Donations: one-time Stripe Checkout payments that support the project.
Wardline is free to use; a donation unlocks nothing.
"""

from __future__ import annotations

from functools import partial

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from wardline.storage.models.base import Base, TimestampMixin, new_id


class Donation(Base, TimestampMixin):
    """No `user_id`: donating never requires an account (see
    `POST /v1/billing/donate`), so this only holds the amount and whatever
    the donor typed into the optional message.
    """

    __tablename__ = "donations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "don"))
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="usd")
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
