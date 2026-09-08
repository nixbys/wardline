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
from wardline.governance import billing, entitlements, orgs
from wardline.storage.models.base import Base
from wardline.storage.models.billing import STATUS_ACTIVE, STATUS_CANCELED, Subscription
from wardline.storage.models.governance import User
from wardline.storage.models.orgs import Organization


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[User.__table__, Subscription.__table__, Organization.__table__]
    )
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


# --- org-scoped billing (Pillar 5's Team/Enterprise "one org, several
# seats" model, hung off the org/workspace entity) --------------------


def test_checkout_for_a_per_seat_plan_requires_an_org(db, user):
    with pytest.raises(AccessDeniedError, match="create one first"):
        billing.create_checkout_session(db, user, plan_id=TEAM)


def test_checkout_for_a_per_seat_plan_requires_the_org_owner(db, user):
    org = orgs.create_organization(db, owner=user, name="Acme Inc")
    member = User(email="member@example.com", role="viewer", org_id=org.id)
    db.add(member)
    db.flush()
    with pytest.raises(AccessDeniedError, match="only your organization's owner"):
        billing.create_checkout_session(db, member, plan_id=TEAM)


def test_owner_checkout_for_team_plan_activates_an_org_scoped_subscription(db, user):
    org = orgs.create_organization(db, owner=user, name="Acme Inc")
    billing.create_checkout_session(db, user, plan_id=TEAM)
    sub = billing.get_subscription(db, user)
    assert sub.org_id == org.id
    assert sub.plan == TEAM


def test_org_members_share_the_owners_subscription(db, user):
    org = orgs.create_organization(db, owner=user, name="Acme Inc")
    billing.create_checkout_session(db, user, plan_id=TEAM)

    member = User(email="member@example.com", role="viewer", org_id=org.id)
    db.add(member)
    db.flush()

    assert billing.current_plan_id(db, member) == TEAM
    # Same row, not a second one -- "one org, several seats" is one
    # Subscription, not one per member.
    assert billing.get_subscription(db, member).id == billing.get_subscription(db, user).id


def test_a_member_without_an_org_subscription_keeps_their_own_personal_plan(db, user):
    org = orgs.create_organization(db, owner=user, name="Acme Inc")
    # Owner never checks out a Team plan for the org -- member's own
    # personal subscription (if any) must still apply, not "free" by
    # virtue of the org existing.
    member = User(email="member@example.com", role="viewer", org_id=org.id)
    db.add(member)
    db.flush()
    billing.create_checkout_session(db, member, plan_id=PRO)
    assert billing.current_plan_id(db, member) == PRO


def test_only_the_org_owner_can_manage_the_shared_subscription_portal(db, user):
    org = orgs.create_organization(db, owner=user, name="Acme Inc")
    billing.create_checkout_session(db, user, plan_id=TEAM)
    member = User(email="member@example.com", role="viewer", org_id=org.id)
    db.add(member)
    db.flush()

    billing.create_portal_session(db, user)  # owner: does not raise
    with pytest.raises(AccessDeniedError, match="only your organization's owner"):
        billing.create_portal_session(db, member)


def test_owner_with_an_existing_personal_subscription_can_still_buy_team(db, user):
    # Owner was already on Pro individually before creating an org and
    # buying Team for it -- subscriptions.user_id is unique, so this must
    # reuse/repurpose that row (org_id set on it) rather than trying to
    # insert a second row for the same user_id, which would raise
    # IntegrityError.
    billing.create_checkout_session(db, user, plan_id=PRO)
    org = orgs.create_organization(db, owner=user, name="Acme Inc")
    billing.create_checkout_session(db, user, plan_id=TEAM)

    sub = billing.get_subscription(db, user)
    assert sub.org_id == org.id
    assert sub.plan == TEAM
    assert db.query(Subscription).filter(Subscription.user_id == user.id).count() == 1


def test_webhook_checkout_completed_with_org_id_activates_the_org_subscription(db, user):
    org = orgs.create_organization(db, owner=user, name="Acme Inc")
    event = _event(
        "checkout.session.completed",
        {
            "metadata": {"user_id": user.id, "plan": TEAM, "org_id": org.id},
            "customer": "cus_org_1",
            "subscription": "sub_org_1",
        },
    )
    billing.handle_webhook_event(db, event)
    sub = db.query(Subscription).filter(Subscription.org_id == org.id).first()
    assert sub is not None
    assert sub.plan == TEAM
    assert sub.status == STATUS_ACTIVE


def test_webhook_checkout_completed_with_org_id_reuses_owners_existing_row(db, user):
    # Same unique-user_id hazard as the checkout-session path, but via the
    # webhook: the payer already has a personal Subscription row when the
    # org's first checkout.session.completed event arrives.
    db.add(Subscription(user_id=user.id, plan=PRO, status=STATUS_ACTIVE, stripe_customer_id="cus_personal"))
    db.flush()
    org = orgs.create_organization(db, owner=user, name="Acme Inc")
    event = _event(
        "checkout.session.completed",
        {
            "metadata": {"user_id": user.id, "plan": TEAM, "org_id": org.id},
            "customer": "cus_org_1",
            "subscription": "sub_org_1",
        },
    )
    billing.handle_webhook_event(db, event)  # must not raise IntegrityError
    sub = db.query(Subscription).filter(Subscription.org_id == org.id).first()
    assert sub is not None
    assert sub.plan == TEAM
    assert db.query(Subscription).filter(Subscription.user_id == user.id).count() == 1
