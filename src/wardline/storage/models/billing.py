"""Billing plane (commercialization roadmap Pillar 5): one `Subscription`
row per user, mirroring Stripe's own customer/subscription objects rather
than reinventing billing state — this table is a local cache of what
Stripe already knows, kept in sync by `governance/billing.py`'s webhook
handler, not a second source of truth Stripe has to agree with.

Every user implicitly has the free plan until a `Subscription` row exists
and is `active` — there's no separate "free" row to create or maintain.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from wardline.common.plans import DEFAULT_PLAN
from wardline.storage.models.base import Base, TimestampMixin, new_id

STATUS_ACTIVE = "active"
STATUS_PAST_DUE = "past_due"
STATUS_CANCELED = "canceled"
STATUS_INCOMPLETE = "incomplete"


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "sub"))
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan: Mapped[str] = mapped_column(String(32), default=DEFAULT_PLAN)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
