"""Unit coverage for common/plans.py, governance/entitlements.py, and
governance/billing.py. Runs against a real (in-memory SQLite) database for
the DB-touching parts of billing.py — `User`/`Subscription` are both
plain-typed (no Postgres-specific JSONB, unlike `ApiKey`), so no dialect
compiler shim is needed here, unlike test_accounts.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from wardline.common.errors import AccessDeniedError
from wardline.common.plans import ENTERPRISE, FREE, PRO, TEAM, get_plan, public_plan_list
from wardline.governance import billing, entitlements
from wardline.storage.models.base import Base
from wardline.storage.models.billing import STATUS_ACTIVE, STATUS_CANCELED, Subscription
from wardline.storage.models.governance import User


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, Subscription.__table__])
    with Session(engine) as session:
        yield session


@pytest.fixture()
def user(db):
    u = User(email="a@example.com", role="viewer")
    db.add(u)
    db.flush()
    return u


# --- common/plans.py ------------------------------------------------


def test_get_plan_falls_back_to_free_for_unknown_id():
    assert get_plan("not-a-real-plan").id == FREE


def test_public_plan_list_never_leaks_internal_fields():
    for plan in public_plan_list():
        assert set(plan.keys()) == {
            "id",
            "label",
            "monthly_price_usd",
            "per_seat",
            "modes",
            "max_sources_cap",
            "self_serve_checkout",
        }


def test_enterprise_and_free_are_not_self_serve():
    assert not get_plan(FREE).self_serve_checkout
    assert not get_plan(ENTERPRISE).self_serve_checkout
    assert get_plan(PRO).self_serve_checkout
    assert get_plan(TEAM).self_serve_checkout


# --- governance/entitlements.py ------------------------------------


def test_free_plan_allows_fast_and_auto_not_research():
    entitlements.enforce_mode_allowed(FREE, "fast")
    entitlements.enforce_mode_allowed(FREE, "auto")
    with pytest.raises(AccessDeniedError, match="doesn't include"):
        entitlements.enforce_mode_allowed(FREE, "research")


def test_pro_plan_allows_research():
    entitlements.enforce_mode_allowed(PRO, "research")  # does not raise


def test_capped_max_sources_never_exceeds_the_plan_cap():
    assert entitlements.capped_max_sources(FREE, 100) == get_plan(FREE).max_sources_cap
    assert entitlements.capped_max_sources(PRO, 3) == 3  # never raises a request that's already under cap


# --- governance/billing.py (mock mode) ------------------------------


def test_current_plan_id_defaults_to_free_with_no_subscription_row(db, user):
    assert billing.current_plan_id(db, user) == FREE


def test_mock_checkout_activates_the_plan_immediately(db, user):
    url = billing.create_checkout_session(db, user, plan_id=PRO)
    assert "billing=success" in url
    assert billing.current_plan_id(db, user) == PRO
    sub = billing.get_subscription(db, user)
    assert sub.status == STATUS_ACTIVE
    assert sub.current_period_end is not None


def test_checkout_rejects_a_non_self_serve_plan(db, user):
    with pytest.raises(AccessDeniedError, match="isn't a self-serve plan"):
        billing.create_checkout_session(db, user, plan_id=ENTERPRISE)


def test_mock_portal_session_does_not_require_stripe(db, user):
    url = billing.create_portal_session(db, user)
    assert url  # just needs to not raise / not need a real Stripe customer


# --- governance/billing.py webhook state machine ------------------

def _event(event_type: str, obj: dict) -> dict:
    return {"type": event_type, "data": {"object": obj}}


def test_webhook_checkout_completed_activates_subscription(db, user):
    event = _event(
        "checkout.session.completed",
        {
            "metadata": {"user_id": user.id, "plan": PRO},
            "customer": "cus_123",
            "subscription": "sub_123",
        },
    )
    billing.handle_webhook_event(db, event)
    sub = billing.get_subscription(db, user)
    assert sub.plan == PRO
    assert sub.status == STATUS_ACTIVE
    assert sub.stripe_customer_id == "cus_123"


def test_webhook_ignores_checkout_completed_without_metadata(db, user):
    billing.handle_webhook_event(db, _event("checkout.session.completed", {}))
    assert billing.get_subscription(db, user) is None


def test_webhook_subscription_updated_maps_stripe_status(db, user):
    db.add(Subscription(user_id=user.id, plan=PRO, stripe_customer_id="cus_123"))
    db.flush()
    event = _event(
        "customer.subscription.updated",
        {"customer": "cus_123", "status": "past_due", "current_period_end": 1735689600},
    )
    billing.handle_webhook_event(db, event)
    sub = billing.get_subscription(db, user)
    assert sub.status == "past_due"
    assert sub.current_period_end is not None


def test_webhook_subscription_deleted_reverts_to_free(db, user):
    db.add(Subscription(user_id=user.id, plan=PRO, status=STATUS_ACTIVE, stripe_customer_id="cus_123"))
    db.flush()
    billing.handle_webhook_event(db, _event("customer.subscription.deleted", {"customer": "cus_123"}))
    sub = billing.get_subscription(db, user)
    assert sub.status == STATUS_CANCELED
    assert sub.plan == FREE


def test_webhook_for_unknown_customer_is_a_no_op(db, user):
    # Must not raise even though no Subscription row matches -- an event
    # for a customer this deployment doesn't recognize is just ignored.
    billing.handle_webhook_event(
        db, _event("customer.subscription.updated", {"customer": "cus_unknown", "status": "active"})
    )
