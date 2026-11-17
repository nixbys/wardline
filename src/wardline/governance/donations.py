"""Donations through Stripe Checkout.

`settings.billing_mode` follows the project's mock/live convention
(`LLM_CLIENT_MODE`, `EMAIL_MODE`): "mock" (the default) never calls Stripe
and records the donation immediately, so the flow works in dev and CI;
"stripe" creates a real one-time Checkout payment, and the `Donation` row is
written from the webhook once Stripe confirms the payment.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from wardline.common.config import get_settings
from wardline.common.errors import AccessDeniedError
from wardline.storage.models.donations import Donation

_MIN_DONATION_CENTS = 100  # $1 -- Stripe itself rejects most currencies below this
_MAX_DONATION_CENTS = 100_000_00  # $100,000 -- a sanity ceiling


def create_donation_checkout_session(db: Session, *, amount_usd: float, message: str | None = None) -> str:
    """A one-time payment (`mode="payment"`). The donor picks the amount,
    so the line item is built inline with `price_data`; no account needed.
    """
    amount_cents = round(amount_usd * 100)
    if not (_MIN_DONATION_CENTS <= amount_cents <= _MAX_DONATION_CENTS):
        raise AccessDeniedError(
            f"donation amount must be between ${_MIN_DONATION_CENTS / 100:.2f} "
            f"and ${_MAX_DONATION_CENTS / 100:,.2f}"
        )

    settings = get_settings()
    if settings.billing_mode != "stripe":
        db.add(Donation(amount_cents=amount_cents, message=message))
        db.flush()
        return f"{settings.billing_success_url}&mock=true&donation=true"

    import stripe

    stripe.api_key = settings.stripe_api_key
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Support Wardline"},
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }
        ],
        success_url=settings.billing_success_url,
        cancel_url=settings.billing_cancel_url,
        metadata={"kind": "donation", "message": message or ""},
    )
    # The Donation row is written by the webhook once Stripe confirms the
    # payment, not here for a payment that might not complete.
    return session.url


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
    """Records a completed donation from an already-verified Stripe event;
    every other event type is ignored. Takes a plain dict so it can be
    tested without a real Stripe signature."""
    data = event.get("data", {}).get("object", {})
    metadata = data.get("metadata", {})
    if event.get("type") != "checkout.session.completed" or metadata.get("kind") != "donation":
        return
    # amount_total (what Stripe actually charged) is authoritative, not the
    # amount the client originally requested.
    amount_cents = data.get("amount_total")
    if amount_cents is None:
        return
    db.add(
        Donation(
            amount_cents=amount_cents,
            currency=data.get("currency", "usd"),
            message=metadata.get("message") or None,
            stripe_checkout_session_id=data.get("id"),
        )
    )
    db.flush()
