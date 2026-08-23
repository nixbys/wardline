"""Self-serve account lifecycle (commercialization roadmap Pillar 1):
signup, email verification, login (with optional TOTP MFA + recovery-code
fallback), logout, password reset, MFA enrollment, and admin-issued
invites. `api/routers/auth.py` is a thin wrapper around this module,
matching this codebase's existing router/business-logic split (compare
`query/pipeline.py` behind `api/routers/query.py`, or
`governance/engagements.py` behind `api/routers/admin_engagements.py`).

Deliberately layered on top of the *existing* auth primitives rather than
inventing a parallel session system: a successful login mints a normal
`ApiKey` row (`common/security.generate_api_key`, the exact helper
`api/routers/admin_users.py` already uses for admin-minted keys) tagged
`scopes=["session"]`. Every other piece of this app — `get_current_user`,
RBAC, the kill switch, the audit log — keeps working completely unchanged,
because as far as they're concerned this is just another API key. Logout
and password-reset only ever revoke *session*-scoped keys, never a
long-lived key a user minted separately for CLI/API use — those have their
own lifecycle and shouldn't die because someone logged out of the web app.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from wardline.common.config import get_settings
from wardline.common.email import send_email
from wardline.common.errors import AccessDeniedError
from wardline.common.security import (
    generate_api_key,
    generate_token,
    hash_password,
    hash_token,
    lookup_key_for_index,
    verify_api_key,
    verify_password,
)
from wardline.governance import mfa
from wardline.storage.models.base import utcnow
from wardline.storage.models.governance import ROLE_VIEWER, ApiKey, AuthToken, RecoveryCode, User

SESSION_SCOPE = "session"
MIN_PASSWORD_LENGTH = 10


def _require_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccessDeniedError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")


def _issue_token_and_link(db: Session, user: User, *, purpose: str, path: str) -> str:
    settings = get_settings()
    plaintext, token_hash = generate_token()
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=token_hash,
            expires_at=utcnow() + timedelta(minutes=settings.auth_token_ttl_minutes),
        )
    )
    db.flush()
    return f"{settings.app_base_url}{path}?token={plaintext}"


def _consume_token(db: Session, *, plaintext: str, purpose: str) -> AuthToken:
    token = (
        db.query(AuthToken)
        .filter(AuthToken.token_hash == hash_token(plaintext), AuthToken.purpose == purpose)
        .first()
    )
    if token is None or token.used_at is not None or _as_aware(token.expires_at) < utcnow():
        raise AccessDeniedError("invalid or expired token")
    token.used_at = utcnow()
    db.flush()
    return token


def _as_aware(value: datetime) -> datetime:
    """Normalize a possibly-naive datetime to UTC-aware before comparing
    against `utcnow()`. `DateTime(timezone=True)` columns round-trip
    tz-aware through Postgres, but defending against a naive value here
    (a different driver, a hand-inserted row, a test database) is cheap
    insurance against a TypeError crashing every token check instead of
    just correctly rejecting a malformed row."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _normalize_recovery_code(code: str) -> str:
    return code.strip().lower().replace("-", "")


def _hash_recovery_code(code: str) -> str:
    return hash_token(_normalize_recovery_code(code))


def _redeem_recovery_code(db: Session, user: User, code: str) -> None:
    target_hash = _hash_recovery_code(code)
    match = (
        db.query(RecoveryCode)
        .filter(
            RecoveryCode.user_id == user.id,
            RecoveryCode.used_at.is_(None),
            RecoveryCode.code_hash == target_hash,
        )
        .first()
    )
    if match is None:
        raise AccessDeniedError("invalid or already-used recovery code")
    match.used_at = utcnow()
    db.flush()


def _revoke_session_keys(db: Session, user_id: str) -> None:
    for key in db.query(ApiKey).filter(ApiKey.user_id == user_id):
        if key.scopes == [SESSION_SCOPE]:
            key.revoked = True
    db.flush()


# --- Signup / verification --------------------------------------------------


def signup(db: Session, *, email: str, password: str) -> User:
    """Create a new self-serve account and email a verification link.
    Always returns as if it succeeded (even if the email is already
    registered) — the caller gets the same "check your email" response
    either way, so this can't be used to enumerate registered addresses.
    """
    _require_password_strength(password)
    existing = db.query(User).filter(User.email == email).first()
    if existing is not None:
        return existing

    user = User(email=email, role=ROLE_VIEWER, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    link = _issue_token_and_link(db, user, purpose="email_verify", path="/verify-email")
    send_email(email, "Verify your Wardline account", f"Confirm your email to finish signing up: {link}")
    return user


def verify_email(db: Session, *, token: str) -> User:
    auth_token = _consume_token(db, plaintext=token, purpose="email_verify")
    user = db.get(User, auth_token.user_id)
    if user is None:
        raise AccessDeniedError("invalid or expired token")
    user.email_verified_at = utcnow()
    db.flush()
    return user


# --- Login / logout ----------------------------------------------------


def authenticate(
    db: Session,
    *,
    email: str,
    password: str,
    mfa_code: str | None = None,
    recovery_code: str | None = None,
) -> User:
    """Verifies email+password (+ MFA, if enabled). Raises AccessDeniedError
    either way a caller shouldn't be able to distinguish — "no such user"
    and "wrong password" get the identical message, on purpose."""
    user = db.query(User).filter(User.email == email).first()
    if (
        user is None
        or user.revoked
        or not user.password_hash
        or not verify_password(password, user.password_hash)
    ):
        raise AccessDeniedError("invalid email or password")

    if user.mfa_enabled:
        if recovery_code:
            _redeem_recovery_code(db, user, recovery_code)
        elif mfa_code and mfa.verify_code(user.mfa_secret or "", mfa_code):
            pass
        else:
            # Deliberately distinct from the generic failure above: the
            # frontend needs to tell "wrong password" (retry the form) apart
            # from "password was right, now prompt for a 2FA code" — the
            # exact string is part of this function's contract, checked in
            # tests, not just an incidental message.
            raise AccessDeniedError("mfa_required")

    return user


def mint_session_key(db: Session, user: User) -> str:
    plaintext, key_hash = generate_api_key()
    db.add(
        ApiKey(
            user_id=user.id,
            key_hash=key_hash,
            lookup_hash=lookup_key_for_index(plaintext),
            scopes=[SESSION_SCOPE],
        )
    )
    db.flush()
    return plaintext


def logout(db: Session, *, token: str) -> None:
    api_key = db.query(ApiKey).filter(ApiKey.lookup_hash == lookup_key_for_index(token)).first()
    if api_key is None or api_key.scopes != [SESSION_SCOPE]:
        return
    if not verify_api_key(token, api_key.key_hash):
        return
    api_key.revoked = True
    db.flush()


# --- Password reset ----------------------------------------------------


def request_password_reset(db: Session, *, email: str) -> None:
    user = db.query(User).filter(User.email == email).first()
    if user is None or user.revoked:
        return  # don't reveal whether the email is registered
    link = _issue_token_and_link(db, user, purpose="password_reset", path="/reset-password")
    send_email(email, "Reset your Wardline password", f"Reset your password: {link}")


def reset_password(db: Session, *, token: str, new_password: str) -> None:
    _require_password_strength(new_password)
    auth_token = _consume_token(db, plaintext=token, purpose="password_reset")
    user = db.get(User, auth_token.user_id)
    if user is None:
        raise AccessDeniedError("invalid or expired token")
    user.password_hash = hash_password(new_password)
    db.flush()
    # A password reset is exactly the moment to force re-login everywhere
    # else too — a session key minted before an account takeover (the whole
    # reason someone resets a password) shouldn't keep working after.
    _revoke_session_keys(db, user.id)


# --- MFA -----------------------------------------------------------------


def enroll_mfa(db: Session, user: User) -> str:
    """Generates and stores a *pending* TOTP secret — mfa_enabled stays
    False until confirm_mfa verifies the user actually has it set up in
    their authenticator app. Returns the otpauth:// provisioning URI."""
    secret = mfa.generate_secret()
    user.mfa_secret = secret
    db.flush()
    return mfa.provisioning_uri(secret, user.email)


def confirm_mfa(db: Session, user: User, *, code: str) -> list[str]:
    """Verifies the pending secret with a real code, flips mfa_enabled on,
    and returns a fresh batch of recovery codes — shown once; only each
    one's hash is retained."""
    if not user.mfa_secret or not mfa.verify_code(user.mfa_secret, code):
        raise AccessDeniedError("invalid verification code")
    user.mfa_enabled = True
    db.flush()

    codes = [mfa.generate_recovery_code() for _ in range(get_settings().recovery_code_count)]
    for plaintext in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=_hash_recovery_code(plaintext)))
    db.flush()
    return codes


def disable_mfa(db: Session, user: User, *, code: str | None, recovery_code: str | None) -> None:
    valid = bool(code and user.mfa_secret and mfa.verify_code(user.mfa_secret, code))
    if not valid and recovery_code:
        try:
            _redeem_recovery_code(db, user, recovery_code)
            valid = True
        except AccessDeniedError:
            valid = False
    if not valid:
        raise AccessDeniedError("a current MFA code or an unused recovery code is required to disable MFA")

    user.mfa_enabled = False
    user.mfa_secret = None
    db.flush()
    db.query(RecoveryCode).filter(
        RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
    ).delete()
    db.flush()


# --- Admin invites ------------------------------------------------------


def create_invite(db: Session, *, email: str, role: str) -> str:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, role=role)
        db.add(user)
        db.flush()
    link = _issue_token_and_link(db, user, purpose="invite", path="/accept-invite")
    send_email(email, "You've been invited to Wardline", f"Set up your account: {link}")
    return link


def accept_invite(db: Session, *, token: str, password: str) -> User:
    _require_password_strength(password)
    auth_token = _consume_token(db, plaintext=token, purpose="invite")
    user = db.get(User, auth_token.user_id)
    if user is None:
        raise AccessDeniedError("invalid or expired token")
    user.password_hash = hash_password(password)
    user.email_verified_at = utcnow()
    db.flush()
    return user
