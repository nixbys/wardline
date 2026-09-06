"""Unit coverage for governance/orgs.py.

Same in-memory-SQLite convention as test_accounts.py -- Organization has
no JSONB column, so no compiler shim is needed here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from wardline.common.errors import AccessDeniedError
from wardline.governance import accounts, orgs
from wardline.storage.models.base import Base
from wardline.storage.models.governance import AuthToken, User
from wardline.storage.models.orgs import Organization


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, Organization.__table__, AuthToken.__table__])
    with Session(engine) as session:
        yield session


def _make_user(db, email="owner@example.com", role="viewer"):
    user = User(email=email, role=role)
    db.add(user)
    db.flush()
    return user


def test_create_organization_sets_owners_org_id(db):
    owner = _make_user(db)
    org = orgs.create_organization(db, owner=owner, name="Acme Inc")
    assert org.owner_user_id == owner.id
    assert owner.org_id == org.id


def test_create_organization_rejects_a_user_already_in_one(db):
    owner = _make_user(db)
    orgs.create_organization(db, owner=owner, name="Acme Inc")
    with pytest.raises(AccessDeniedError, match="already belong"):
        orgs.create_organization(db, owner=owner, name="A Second Org")


def test_invite_to_org_sets_org_id_on_the_invited_user(db):
    owner = _make_user(db)
    org = orgs.create_organization(db, owner=owner, name="Acme Inc")
    link = orgs.invite_to_org(db, org=org, inviter=owner, email="teammate@example.com", role="analyst")

    token = link.rsplit("token=", 1)[1]
    invited = accounts.accept_invite(db, token=token, password="a-strong-invited-password")
    assert invited.org_id == org.id
    assert invited.role == "analyst"


def test_invite_to_org_rejects_a_non_owner(db):
    owner = _make_user(db)
    org = orgs.create_organization(db, owner=owner, name="Acme Inc")
    someone_else = _make_user(db, email="someone-else@example.com")
    with pytest.raises(AccessDeniedError, match="owner"):
        orgs.invite_to_org(db, org=org, inviter=someone_else, email="teammate@example.com", role="viewer")


def test_list_org_members_scopes_to_the_org(db):
    owner = _make_user(db)
    org = orgs.create_organization(db, owner=owner, name="Acme Inc")
    outsider = _make_user(db, email="outsider@example.com")

    link = orgs.invite_to_org(db, org=org, inviter=owner, email="teammate@example.com", role="viewer")
    token = link.rsplit("token=", 1)[1]
    accounts.accept_invite(db, token=token, password="a-strong-invited-password")

    members = orgs.list_org_members(db, org)
    member_emails = {m.email for m in members}
    assert member_emails == {owner.email, "teammate@example.com"}
    assert outsider.email not in member_emails
