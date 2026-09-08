"""Stripe billing integration (commercialization roadmap Pillar 5).

`settings.billing_mode` selects the implementation, matching this
project's existing mock/live convention (`LLM_CLIENT_MODE`, `EMAIL_MODE`):
"mock" (default) never calls Stripe — checkout "completes" immediately and
activates the plan locally, so the whole billing flow (plan gating,
webhook-shaped state transitions) is exercisable in dev/CI without a real
Stripe account. "stripe" calls the real API.

`Subscription` rows are a local *cache* of what Stripe already knows, kept
in sync by `handle_webhook_event` — nothing here writes speculative billing
state outside that path (mock mode's immediate-activation shortcut stands
in for the webhook Stripe would otherwise send, not a second source of
truth competing with it).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from wardline.common.config import get_settings
from wardline.common.errors import AccessDeniedError
from wardline.common.plans import PRO, TEAM, get_plan
from wardline.storage.models.billing import (
    STATUS_ACTIVE,
    STATUS_CANCELED,
    STATUS_INCOMPLETE,
    STATUS_PAST_DUE,
    Subscription,
)
from wardline.storage.models.governance import User
from wardline.storage.models.orgs import Organization

# Which settings field holds a plan's real Stripe Price id, once one
# exists — deliberately not in common/plans.py, which stays free of
# env/settings reads (see that module's docstring).
_PRICE_ID_SETTING = {
    PRO: "stripe_price_id_pro",
    TEAM: "stripe_price_id_team",
}

_STRIPE_STATUS_MAP = {
    "active": STATUS_ACTIVE,
    "trialing": STATUS_ACTIVE,
    "past_due": STATUS_PAST_DUE,
    "unpaid": STATUS_PAST_DUE,
    "canceled": STATUS_CANCELED,
    "incomplete": STATUS_INCOMPLETE,
    "incomplete_expired": STATUS_CANCELED,
}


def _price_id_for(plan_id: str) -> str:
    settings = get_settings()
    attr = _PRICE_ID_SETTING.get(plan_id)
    price_id = getattr(settings, attr, None) if attr else None
    if not price_id:
        raise AccessDeniedError(
            f"no Stripe Price configured for plan {plan_id!r} — "
            f"set STRIPE_PRICE_ID_{plan_id.upper()} once one exists in the Stripe dashboard"
        )
    return price_id


def get_subscription(db: Session, user: User) -> Subscription | None:
    """An org-scoped subscription (bought once by the org's owner) covers
    every member of that org, checked first; a member with no org
    subscription still falls back to their own personal one, unchanged
    from before org-scoped billing existed."""
    if user.org_id is not None:
        org_sub = db.query(Subscription).filter(Subscription.org_id == user.org_id).first()
        if org_sub is not None:
            return org_sub
    return db.query(Subscription).filter(Subscription.user_id == user.id).first()


def current_plan_id(db: Session, user: User) -> str:
    sub = get_subscription(db, user)
    if sub is None or sub.status != STATUS_ACTIVE:
        return "free"
    return sub.plan


def _get_or_create_subscription(db: Session, user: User) -> Subscription:
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if sub is None:
        sub = Subscription(user_id=user.id)
        db.add(sub)
        db.flush()
    return sub


def _get_or_create_org_subscription(db: Session, org: Organization) -> Subscription:
    sub = db.query(Subscription).filter(Subscription.org_id == org.id).first()
    if sub is None:
        # user_id is unique, so if the owner already has a personal
        # Subscription row (e.g. they were on Pro individually before
        # buying Team for the org), reuse that row rather than inserting
        # a second one for the same user_id -- that would violate the
        # unique constraint. Their personal plan is superseded by the
        # org's from here on; get_subscription() checks org first anyway.
        sub = db.query(Subscription).filter(Subscription.user_id == org.owner_user_id).first()
        if sub is None:
            sub = Subscription(user_id=org.owner_user_id)
            db.add(sub)
        # user_id still records who's on file with Stripe as the payer
        # (the org's owner) -- org_id is what makes every member's
        # get_subscription() resolve to this same row.
        sub.org_id = org.id
        db.flush()
    return sub


def _seat_count(db: Session, org: Organization) -> int:
    from wardline.governance.orgs import list_org_members

    return max(len(list_org_members(db, org)), 1)


def create_checkout_session(db: Session, user: User, *, plan_id: str) -> str:
    plan = get_plan(plan_id)
    if not plan.self_serve_checkout:
        raise AccessDeniedError(f"{plan.label} isn't a self-serve plan — contact sales instead")

    org = None
    if plan.per_seat:
        # A per-seat plan is an org's plan, not an individual's -- billing
        # every member separately would defeat the point of "one org,
        # several seats" as the unit being sold.
        if user.org_id is None:
            raise AccessDeniedError(
                f"{plan.label} is a per-seat plan for an organization — "
                f"create one first (POST /v1/orgs) before subscribing"
            )
        org = db.get(Organization, user.org_id)
        if org is None or user.id != org.owner_user_id:
            raise AccessDeniedError(f"only your organization's owner can subscribe it to {plan.label}")

    settings = get_settings()
    if settings.billing_mode != "stripe":
        sub = _get_or_create_org_subscription(db, org) if org else _get_or_create_subscription(db, user)
        sub.plan = plan.id
        sub.status = STATUS_ACTIVE
        sub.current_period_end = datetime.now(UTC) + timedelta(days=30)
        db.flush()
        return f"{settings.billing_success_url}&mock=true"

    import stripe

    stripe.api_key = settings.stripe_api_key
    sub = _get_or_create_org_subscription(db, org) if org else _get_or_create_subscription(db, user)
    if not sub.stripe_customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            metadata={"user_id": user.id, "org_id": org.id} if org else {"user_id": user.id},
        )
        sub.stripe_customer_id = customer.id
        db.flush()

    quantity = _seat_count(db, org) if org else 1
    metadata = {"user_id": user.id, "plan": plan.id}
    if org:
        metadata["org_id"] = org.id

    session = stripe.checkout.Session.create(
        customer=sub.stripe_customer_id,
        mode="subscription",
        line_items=[{"price": _price_id_for(plan.id), "quantity": quantity}],
        success_url=settings.billing_success_url,
        cancel_url=settings.billing_cancel_url,
        metadata=metadata,
    )
    return session.url


def create_portal_session(db: Session, user: User) -> str:
    sub = get_subscription(db, user)
    if sub is not None and sub.org_id is not None:
        org = db.get(Organization, sub.org_id)
        if org is not None and user.id != org.owner_user_id:
            # get_subscription() resolves every member to the org's one
            # shared row -- without this check, any member (not just the
            # owner) could open the Stripe portal for the whole org's
            # billing and cancel/change it.
            raise AccessDeniedError("only your organization's owner can manage its billing")

    settings = get_settings()
    if settings.billing_mode != "stripe":
        return f"{settings.billing_success_url}&mock_portal=true"

    if sub is None or not sub.stripe_customer_id:
        raise AccessDeniedError("no billing account yet — subscribe to a plan first")

    import stripe

    stripe.api_key = settings.stripe_api_key
    portal = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id, return_url=settings.billing_success_url
    )
    return portal.url


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise AccessDeniedError("STRIPE_WEBHOOK_SECRET is not configured")

    import stripe

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise AccessDeniedError(f"invalid Stripe webhook signature: {exc}") from exc
    return event


def handle_webhook_event(db: Session, event: dict) -> None:
    """Applies an already-verified Stripe event to local `Subscription`
    state. Deliberately takes a plain dict, not a `stripe.Event` object —
    signature verification (`verify_webhook_signature`) is the caller's job,
    kept separate so this function, the actual state machine, is testable
    with a hand-built event dict and no real Stripe signature."""
    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        metadata = data.get("metadata", {})
        user_id, plan_id, org_id = (
            metadata.get("user_id"),
            metadata.get("plan"),
            metadata.get("org_id"),
        )
        if not user_id or not plan_id:
            return
        if org_id:
            sub = db.query(Subscription).filter(Subscription.org_id == org_id).first()
            if sub is None:
                # Same user_id-uniqueness hazard as _get_or_create_org_subscription:
                # the payer (org owner) may already have a personal row.
                sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
                if sub is None:
                    sub = Subscription(user_id=user_id)
                    db.add(sub)
                sub.org_id = org_id
        else:
            sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
            if sub is None:
                sub = Subscription(user_id=user_id)
                db.add(sub)
        sub.plan = plan_id
        sub.status = STATUS_ACTIVE
        sub.stripe_customer_id = data.get("customer") or sub.stripe_customer_id
        sub.stripe_subscription_id = data.get("subscription")
        db.flush()

    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        sub = (
            db.query(Subscription)
            .filter(Subscription.stripe_customer_id == data.get("customer"))
            .first()
        )
        if sub is None:
            return
        sub.status = _STRIPE_STATUS_MAP.get(data.get("status", ""), STATUS_INCOMPLETE)
        period_end = data.get("current_period_end")
        if period_end:
            sub.current_period_end = datetime.fromtimestamp(period_end, tz=UTC)
        db.flush()

    elif event_type == "customer.subscription.deleted":
        sub = (
            db.query(Subscription)
            .filter(Subscription.stripe_customer_id == data.get("customer"))
            .first()
        )
        if sub is None:
            return
        sub.status = STATUS_CANCELED
        sub.plan = "free"
        db.flush()
