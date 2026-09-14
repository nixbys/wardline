"""Enterprise-lead tracking for the Ops Console. Enterprise inquiries
land via the public POST /v1/billing/enterprise-inquiry (api/routers/
billing.py) with no admin visibility beyond a best-effort email
notification -- this gives an admin/analyst a real way to see the queue
and move a lead through to a provisioned instance (scripts/
provision_customer.sh) without direct DB access. Same admin/analyst gate
as admin_graph.py's queue-adjacent endpoints: operational visibility, not
a public surface.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from wardline.api.deps import get_db, require_role
from wardline.common.errors import AccessDeniedError, NotFoundError
from wardline.governance import billing
from wardline.storage.models.governance import ROLE_ADMIN, ROLE_ANALYST, User

router = APIRouter(prefix="/v1/admin/billing", tags=["admin-billing"])
_operator_role = require_role(ROLE_ADMIN, ROLE_ANALYST)


class UpdateLeadStatusRequest(BaseModel):
    status: str


def _serialize(lead) -> dict:
    return {
        "id": lead.id,
        "company": lead.company,
        "contact_name": lead.contact_name,
        "contact_email": lead.contact_email,
        "seats_estimate": lead.seats_estimate,
        "message": lead.message,
        "status": lead.status,
        "created_at": lead.created_at.isoformat(),
    }


@router.get("/enterprise-leads")
def list_enterprise_leads(
    status: str | None = None, db: Session = Depends(get_db), _user: User = Depends(_operator_role)
) -> list[dict]:
    return [_serialize(lead) for lead in billing.list_enterprise_leads(db, status=status)]


@router.post("/enterprise-leads/{lead_id}/status")
def update_enterprise_lead_status(
    lead_id: str,
    body: UpdateLeadStatusRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(_operator_role),
) -> dict:
    try:
        lead = billing.update_enterprise_lead_status(db, lead_id, status=body.status)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize(lead)
