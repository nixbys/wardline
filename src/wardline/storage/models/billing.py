"""Billing plane (commercialization roadmap Pillar 5): one `Subscription`
row per user, mirroring Stripe's own customer/subscription objects rather
than reinventing billing state — this table is a local cache of what
Stripe already knows, kept in sync by `governance/billing.py`'s webhook
handler, not a second source of truth Stripe has to agree with.

Every user implicitly has the free plan until a `Subscription` row exists
and is `active` — there's no separate "free" row to create or maintain.

`org_id` (nullable, unique when set): a per-seat plan (Team) is bought
once by an org's owner and covers every member of that org, not just the
buyer -- `governance/billing.get_subscription` checks for an org-scoped
row before falling back to the caller's own personal one. `user_id` still
means "who's on file with Stripe as the payer" even for an org-scoped row;
it doesn't become every member's row.
"""

from __future__ import annotations

from datetime import datetime
from functools import partial

from sqlalchemy import DateTime, ForeignKey, Integer, String
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
    org_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, unique=True
    )


class Donation(Base, TimestampMixin):
    """A one-time Stripe Checkout payment (`mode="payment"`, not
    `"subscription"`) -- deliberately unrelated to `Subscription`/plan
    entitlements. Wardline stays free to use; this just records that
    someone chose to support the project, for a future thank-you/supporter
    display. No `user_id` -- donating never requires an account (see
    `POST /v1/billing/donate`), so this only ever has whatever the donor
    typed into the optional `message` field.
    """

    __tablename__ = "donations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "don"))
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="usd")
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


LEAD_STATUS_NEW = "new"
LEAD_STATUS_CONTACTED = "contacted"
LEAD_STATUS_PROVISIONED = "provisioned"
LEAD_STATUS_CLOSED = "closed"
LEAD_STATUSES = (LEAD_STATUS_NEW, LEAD_STATUS_CONTACTED, LEAD_STATUS_PROVISIONED, LEAD_STATUS_CLOSED)


class EnterpriseLead(Base, TimestampMixin):
    """A "Talk to sales" submission from pricing.html's Enterprise card.
    Enterprise is deliberately not self-serve checkout (`plans.py`'s
    `self_serve_checkout=False`, "dedicated instance / contract") -- this
    is the entry point into that path instead: capture the inquiry, notify
    whoever's on point for sales (`governance.billing.submit_enterprise_lead`),
    and let an admin/analyst track it to a provisioned instance
    (`scripts/provision_customer.sh`) from the Ops Console.

    No relation to `Subscription`/Stripe -- Enterprise is contract-billed
    outside that plumbing, same reason `Donation` is deliberately
    unrelated to it. `status` is a plain operator-tracked pipeline stage,
    not a state machine anything else in this codebase reacts to.
    """

    __tablename__ = "enterprise_leads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=partial(new_id, "lead"))
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False)
    seats_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=LEAD_STATUS_NEW)
