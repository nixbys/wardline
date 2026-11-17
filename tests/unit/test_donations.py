"""Unit coverage for governance/donations.py: one-time, account-free
donations in mock mode, and the Stripe webhook that records a completed one.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from wardline.common.errors import AccessDeniedError
from wardline.governance import donations
from wardline.storage.models.base import Base
from wardline.storage.models.donations import Donation


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Donation.__table__])
    with Session(engine) as session:
        yield session


def _event(event_type: str, obj: dict) -> dict:
    return {"type": event_type, "data": {"object": obj}}


def test_mock_donation_records_a_donation_row_immediately(db):
    url = donations.create_donation_checkout_session(db, amount_usd=25, message="keep it free")
    assert "donation=true" in url
    donation = db.query(Donation).one()
    assert donation.amount_cents == 2500
    assert donation.message == "keep it free"


def test_donation_rejects_amounts_outside_the_allowed_range(db):
    with pytest.raises(AccessDeniedError, match="must be between"):
        donations.create_donation_checkout_session(db, amount_usd=0.50)
    with pytest.raises(AccessDeniedError, match="must be between"):
        donations.create_donation_checkout_session(db, amount_usd=1_000_000)


def test_webhook_donation_completed_records_a_donation_row(db):
    event = _event(
        "checkout.session.completed",
        {
            "id": "cs_test_123",
            "amount_total": 500,
            "currency": "usd",
            "metadata": {"kind": "donation", "message": "thanks!"},
        },
    )
    donations.handle_webhook_event(db, event)
    donation = db.query(Donation).one()
    assert donation.amount_cents == 500
    assert donation.message == "thanks!"
    assert donation.stripe_checkout_session_id == "cs_test_123"


def test_webhook_donation_completed_without_amount_is_a_no_op(db):
    donations.handle_webhook_event(db, _event("checkout.session.completed", {"metadata": {"kind": "donation"}}))
    assert db.query(Donation).count() == 0


@pytest.mark.parametrize(
    "event",
    [
        _event("checkout.session.completed", {"amount_total": 500, "metadata": {}}),
        _event("customer.subscription.updated", {"customer": "cus_1", "status": "active"}),
    ],
    ids=["checkout-without-donation-kind", "subscription-event"],
)
def test_webhook_ignores_everything_but_completed_donations(db, event):
    donations.handle_webhook_event(db, event)
    assert db.query(Donation).count() == 0
