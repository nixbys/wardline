"""Donation endpoints. `/donate` is public; the webhook is Stripe calling
us, authenticated by the `Stripe-Signature` header and
`STRIPE_WEBHOOK_SECRET` rather than a bearer token. The paths keep their
`/v1/billing/` prefix so existing Stripe webhook settings keep working.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from wardline.api.deps import get_db
from wardline.common.config import get_settings
from wardline.common.errors import AccessDeniedError
from wardline.governance import donations
from wardline.governance.rate_limit import limiter

router = APIRouter(prefix="/v1/billing", tags=["donations"])


class DonateRequest(BaseModel):
    amount_usd: float = Field(gt=0)
    message: str | None = Field(default=None, max_length=500)


@router.post("/donate")
@limiter.limit(f"{get_settings().rate_limit_donate_per_minute}/minute")
def donate(request: Request, body: DonateRequest, db: Session = Depends(get_db)) -> dict:
    try:
        url = donations.create_donation_checkout_session(db, amount_usd=body.amount_usd, message=body.message)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"checkout_url": url}


@router.post("/webhook")
async def webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    payload = await request.body()
    try:
        event = donations.verify_webhook_signature(payload, stripe_signature or "")
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    donations.handle_webhook_event(db, event)
    return {"received": True}
