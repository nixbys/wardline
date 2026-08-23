"""Self-serve account endpoints (commercialization roadmap Pillar 1):
signup, email verification, login (+ MFA), logout, password reset, MFA
enrollment, and invite acceptance. All the actual logic lives in
`governance/accounts.py` — this router is deliberately thin, matching the
rest of this codebase's router/business-logic split.

Unauthenticated endpoints here (signup, login, forgot-password) are rate
limited per caller IP — the same `slowapi` limiter every other public
surface uses, at a tighter default (`rate_limit_auth_per_minute`, 10/min)
since credential-guessing is exactly the abuse shape these endpoints
attract.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from wardline.api.deps import get_current_user, get_db
from wardline.common.config import get_settings
from wardline.common.errors import AccessDeniedError
from wardline.governance import accounts
from wardline.governance.rate_limit import limiter
from wardline.storage.models.governance import User

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str
    mfa_code: str | None = None
    recovery_code: str | None = None


class VerifyEmailRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class MfaConfirmRequest(BaseModel):
    code: str


class MfaDisableRequest(BaseModel):
    code: str | None = None
    recovery_code: str | None = None


class AcceptInviteRequest(BaseModel):
    token: str
    password: str


@router.get("/me")
def whoami(user: User = Depends(get_current_user)) -> dict:
    return {
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
        "email_verified": user.email_verified_at is not None,
        "mfa_enabled": user.mfa_enabled,
    }


@router.post("/signup")
@limiter.limit(f"{get_settings().rate_limit_auth_per_minute}/minute")
def signup(request: Request, body: SignupRequest, db: Session = Depends(get_db)) -> dict:
    try:
        accounts.signup(db, email=body.email, password=body.password)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "check your email to verify your account"}


@router.post("/verify-email")
def verify_email_route(body: VerifyEmailRequest, db: Session = Depends(get_db)) -> dict:
    try:
        user = accounts.verify_email(db, token=body.token)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"email": user.email, "verified": True}


@router.post("/login")
@limiter.limit(f"{get_settings().rate_limit_auth_per_minute}/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    try:
        user = accounts.authenticate(
            db,
            email=body.email,
            password=body.password,
            mfa_code=body.mfa_code,
            recovery_code=body.recovery_code,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    api_key = accounts.mint_session_key(db, user)
    return {"api_key": api_key, "user_id": user.id, "role": user.role}


@router.post("/logout")
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict:
    if authorization and authorization.startswith("Bearer "):
        accounts.logout(db, token=authorization[len("Bearer ") :])
    return {"message": "logged out"}


@router.post("/password/forgot")
@limiter.limit(f"{get_settings().rate_limit_auth_per_minute}/minute")
def forgot_password(request: Request, body: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    accounts.request_password_reset(db, email=body.email)
    return {"message": "if that email is registered, a reset link has been sent"}


@router.post("/password/reset")
def reset_password_route(body: ResetPasswordRequest, db: Session = Depends(get_db)) -> dict:
    try:
        accounts.reset_password(db, token=body.token, new_password=body.new_password)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "password updated"}


@router.post("/mfa/enroll")
def enroll_mfa(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    uri = accounts.enroll_mfa(db, user)
    return {"provisioning_uri": uri}


@router.post("/mfa/confirm")
def confirm_mfa(
    body: MfaConfirmRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    try:
        codes = accounts.confirm_mfa(db, user, code=body.code)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"recovery_codes": codes}


@router.post("/mfa/disable")
def disable_mfa(
    body: MfaDisableRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    try:
        accounts.disable_mfa(db, user, code=body.code, recovery_code=body.recovery_code)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "mfa disabled"}


@router.post("/accept-invite")
def accept_invite(body: AcceptInviteRequest, db: Session = Depends(get_db)) -> dict:
    try:
        user = accounts.accept_invite(db, token=body.token, password=body.password)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    api_key = accounts.mint_session_key(db, user)
    return {"api_key": api_key, "user_id": user.id, "role": user.role}
