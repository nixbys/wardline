"""Billing endpoints (commercialization roadmap Pillar 5). Plan browsing is
public; checkout/portal/subscription-status need a logged-in user; the
webhook is Stripe calling *us*, authenticated by signature (`Stripe-
Signature` header + `STRIPE_WEBHOOK_SECRET`) rather than a bearer token —
Stripe has no API key of ours to send.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from wardline.api.deps import get_current_user, get_db
from wardline.common.errors import AccessDeniedError
from wardline.common.plans import public_plan_list
from wardline.governance import billing
from wardline.storage.models.governance import User

router = APIRouter(prefix="/v1/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan_id: str


@router.get("/plans")
def list_plans() -> list[dict]:
    return public_plan_list()


@router.get("/subscription")
def get_subscription(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    sub = billing.get_subscription(db, user)
    if sub is None:
        return {"plan": "free", "status": "active", "current_period_end": None}
    return {
        "plan": sub.plan,
        "status": sub.status,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
    }


@router.post("/checkout")
def checkout(
    body: CheckoutRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    try:
        url = billing.create_checkout_session(db, user, plan_id=body.plan_id)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"checkout_url": url}


@router.post("/portal")
def portal(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    try:
        url = billing.create_portal_session(db, user)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"portal_url": url}


@router.post("/webhook")
async def webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    payload = await request.body()
    try:
        event = billing.verify_webhook_signature(payload, stripe_signature or "")
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    billing.handle_webhook_event(db, event)
    return {"received": True}
