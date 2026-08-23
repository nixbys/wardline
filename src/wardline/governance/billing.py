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
    return db.query(Subscription).filter(Subscription.user_id == user.id).first()


def current_plan_id(db: Session, user: User) -> str:
    sub = get_subscription(db, user)
    if sub is None or sub.status != STATUS_ACTIVE:
        return "free"
    return sub.plan


def _get_or_create_subscription(db: Session, user: User) -> Subscription:
    sub = get_subscription(db, user)
    if sub is None:
        sub = Subscription(user_id=user.id)
        db.add(sub)
        db.flush()
    return sub


def create_checkout_session(db: Session, user: User, *, plan_id: str) -> str:
    plan = get_plan(plan_id)
    if not plan.self_serve_checkout:
        raise AccessDeniedError(f"{plan.label} isn't a self-serve plan — contact sales instead")

    settings = get_settings()
    if settings.billing_mode != "stripe":
        sub = _get_or_create_subscription(db, user)
        sub.plan = plan.id
        sub.status = STATUS_ACTIVE
        sub.current_period_end = datetime.now(UTC) + timedelta(days=30)
        db.flush()
        return f"{settings.billing_success_url}&mock=true"

    import stripe

    stripe.api_key = settings.stripe_api_key
    sub = _get_or_create_subscription(db, user)
    if not sub.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email, metadata={"user_id": user.id})
        sub.stripe_customer_id = customer.id
        db.flush()

    session = stripe.checkout.Session.create(
        customer=sub.stripe_customer_id,
        mode="subscription",
        line_items=[{"price": _price_id_for(plan.id), "quantity": 1}],
        success_url=settings.billing_success_url,
        cancel_url=settings.billing_cancel_url,
        metadata={"user_id": user.id, "plan": plan.id},
    )
    return session.url


def create_portal_session(db: Session, user: User) -> str:
    settings = get_settings()
    if settings.billing_mode != "stripe":
        return f"{settings.billing_success_url}&mock_portal=true"

    sub = get_subscription(db, user)
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
        user_id, plan_id = metadata.get("user_id"), metadata.get("plan")
        if not user_id or not plan_id:
            return
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
