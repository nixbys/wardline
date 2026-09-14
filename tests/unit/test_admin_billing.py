"""Unit coverage for api/routers/admin_billing.py. Real (in-memory
SQLite) database, same convention as test_billing.py -- EnterpriseLead is
plain-typed, no Postgres-specific JSONB. Router functions are called
directly (bypassing the require_role dependency, `_user=None`), matching
test_admin_graph.py's convention.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from wardline.api.routers import admin_billing
from wardline.governance import billing
from wardline.storage.models.base import Base
from wardline.storage.models.billing import LEAD_STATUS_CONTACTED, EnterpriseLead


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[EnterpriseLead.__table__])
    with Session(engine) as session:
        yield session


def test_list_enterprise_leads_serializes_every_field(db):
    billing.submit_enterprise_lead(
        db, company="Acme Inc", contact_email="ceo@acme.example", contact_name="Jane", seats_estimate=50
    )
    result = admin_billing.list_enterprise_leads(status=None, db=db, _user=None)
    assert len(result) == 1
    assert result[0]["company"] == "Acme Inc"
    assert result[0]["contact_name"] == "Jane"
    assert result[0]["seats_estimate"] == 50
    assert result[0]["status"] == "new"
    assert "created_at" in result[0]


def test_list_enterprise_leads_filters_by_status(db):
    billing.submit_enterprise_lead(db, company="Old Co", contact_email="a@old.example")
    lead = billing.submit_enterprise_lead(db, company="New Co", contact_email="a@new.example")
    billing.update_enterprise_lead_status(db, lead.id, status=LEAD_STATUS_CONTACTED)

    result = admin_billing.list_enterprise_leads(status=LEAD_STATUS_CONTACTED, db=db, _user=None)
    assert [row["company"] for row in result] == ["New Co"]


def test_update_enterprise_lead_status_returns_the_updated_row(db):
    lead = billing.submit_enterprise_lead(db, company="Acme Inc", contact_email="ceo@acme.example")
    body = admin_billing.UpdateLeadStatusRequest(status=LEAD_STATUS_CONTACTED)
    result = admin_billing.update_enterprise_lead_status(lead.id, body, db=db, _user=None)
    assert result["status"] == LEAD_STATUS_CONTACTED


def test_update_enterprise_lead_status_404s_on_unknown_lead(db):
    body = admin_billing.UpdateLeadStatusRequest(status=LEAD_STATUS_CONTACTED)
    with pytest.raises(HTTPException) as exc_info:
        admin_billing.update_enterprise_lead_status("lead_doesnotexist", body, db=db, _user=None)
    assert exc_info.value.status_code == 404


def test_update_enterprise_lead_status_400s_on_bad_status(db):
    lead = billing.submit_enterprise_lead(db, company="Acme Inc", contact_email="ceo@acme.example")
    body = admin_billing.UpdateLeadStatusRequest(status="not-a-real-status")
    with pytest.raises(HTTPException) as exc_info:
        admin_billing.update_enterprise_lead_status(lead.id, body, db=db, _user=None)
    assert exc_info.value.status_code == 400
