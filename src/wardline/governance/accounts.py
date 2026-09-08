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
from wardline.security import vault
from wardline.storage.models.base import new_id, utcnow
from wardline.storage.models.governance import (
    ROLE_VIEWER,
    ApiKey,
    AuthToken,
    RecoveryCode,
    User,
    VaultKey,
)

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


def _redeem_recovery_code(db: Session, user: User, code: str) -> RecoveryCode:
    """Returns the matched row (not just a bool) so a vault-recovery caller
    (reset_password) can read its vault_wrapped_dek before/after marking it
    used — the other two callers (authenticate's MFA fallback, disable_mfa)
    just discard it, exactly as before."""
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
    return match


def _issue_recovery_codes(db: Session, user: User, dek: bytes | None) -> list[str]:
    """Generates a fresh batch of recovery codes — shown once, only each
    one's hash is retained. When `dek` is available (a freshly generated
    vault key at signup/invite-acceptance, or one resolved via the session
    bridge when a batch is re-issued later at MFA confirm), also wraps it
    into each code — keyed by that code's own row id as the Argon2id salt
    (unique per row, already stored as the primary key; no separate salt
    column needed since it doesn't need to be secret, just fixed) — so any
    one of them can later unwrap the vault during account recovery
    (reset_password below), not just disable MFA."""
    codes = []
    for _ in range(get_settings().recovery_code_count):
        plaintext = mfa.generate_recovery_code()
        code_id = new_id("rec")
        record = RecoveryCode(id=code_id, user_id=user.id, code_hash=_hash_recovery_code(plaintext))
        if dek is not None:
            kek = vault.derive_kek(plaintext, salt=code_id.encode("utf-8"))
            nonce, wrapped = vault.wrap(kek, dek, aad=code_id)
            record.vault_wrapped_dek = wrapped
            record.vault_wrapped_dek_nonce = nonce
        db.add(record)
        codes.append(plaintext)
    db.flush()
    return codes


def _provision_vault(db: Session, user: User, *, password: str) -> list[str]:
    """Creates this user's encrypted-history vault (security/vault.py) and
    a batch of escrow recovery codes wrapping its key. Called once, right
    after a user's first password is set (signup or invite acceptance) —
    the plaintext password is still in scope at that moment and is never
    stored. Unconditional regardless of plan or org membership —
    `vault.should_encrypt_history` only gates whether the vault is
    actually *used* on the query path, not whether one exists, so
    upgrading to Pro later needs no backfill."""
    dek = vault.generate_dek()
    salt = vault.generate_salt()
    kek = vault.derive_kek(password, salt=salt)
    nonce, wrapped = vault.wrap(kek, dek, aad=user.id)
    db.add(VaultKey(user_id=user.id, kdf_salt=salt, wrapped_dek=wrapped, wrapped_dek_nonce=nonce))
    db.flush()
    return _issue_recovery_codes(db, user, dek)


def _revoke_session_keys(db: Session, user_id: str) -> None:
    for key in db.query(ApiKey).filter(ApiKey.user_id == user_id):
        if key.scopes == [SESSION_SCOPE]:
            key.revoked = True
            key.vault_dek_wrapped = None
            key.vault_dek_nonce = None
    db.flush()


# --- Signup / verification --------------------------------------------------


def signup(db: Session, *, email: str, password: str) -> tuple[User, list[str]]:
    """Create a new self-serve account, provision its encrypted-history
    vault, and email a verification link. Always returns as if it
    succeeded (even if the email is already registered) — the caller gets
    the same "check your email" response either way, so this can't be
    used to enumerate registered addresses; the recovery-code list is
    empty in that case too, for the same reason (minting a second batch
    for someone else's account would both leak that the email exists and
    hand out live escrow codes to whoever made the request).
    """
    _require_password_strength(password)
    existing = db.query(User).filter(User.email == email).first()
    if existing is not None:
        return existing, []

    user = User(email=email, role=ROLE_VIEWER, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    recovery_codes = _provision_vault(db, user, password=password)
    link = _issue_token_and_link(db, user, purpose="email_verify", path="/verify-email")
    send_email(
        email, "Verify your Wardline account", f"Confirm your email to finish signing up: {link}"
    )
    return user, recovery_codes


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


def mint_session_key(db: Session, user: User, *, password: str | None = None) -> str:
    """`password`, when given, bridges this session to the user's vault
    (security/vault.py): unwraps the DEK with a KEK re-derived from the
    just-verified plaintext password, then re-wraps it under
    settings.vault_session_secret and stores that on the new ApiKey row —
    the only place a session can read it back from for the rest of this
    session's lifetime, since the plaintext password itself is never
    retained past this call. Silently skipped (no vault bridge, session
    still minted) if the user has no VaultKey or the unwrap fails — the
    latter shouldn't happen in practice, since authenticate() already
    verified this exact password against password_hash before this is
    ever called, but a login must never be blocked by a vault-bridge
    failure."""
    plaintext, key_hash = generate_api_key()
    api_key = ApiKey(
        id=new_id("key"),
        user_id=user.id,
        key_hash=key_hash,
        lookup_hash=lookup_key_for_index(plaintext),
        scopes=[SESSION_SCOPE],
    )
    if password is not None:
        vault_key = db.query(VaultKey).filter(VaultKey.user_id == user.id).first()
        if vault_key is not None:
            kek = vault.derive_kek(password, salt=vault_key.kdf_salt)
            try:
                dek = vault.unwrap(
                    kek, vault_key.wrapped_dek_nonce, vault_key.wrapped_dek, aad=user.id
                )
            except vault.VaultError:
                pass
            else:
                api_key.vault_dek_nonce, api_key.vault_dek_wrapped = vault.wrap_for_session(
                    dek, aad=api_key.id
                )
    db.add(api_key)
    db.flush()
    return plaintext


def logout(db: Session, *, token: str) -> None:
    api_key = db.query(ApiKey).filter(ApiKey.lookup_hash == lookup_key_for_index(token)).first()
    if api_key is None or api_key.scopes != [SESSION_SCOPE]:
        return
    if not verify_api_key(token, api_key.key_hash):
        return
    api_key.revoked = True
    api_key.vault_dek_wrapped = None
    api_key.vault_dek_nonce = None
    db.flush()


# --- Password reset ----------------------------------------------------


def request_password_reset(db: Session, *, email: str) -> None:
    user = db.query(User).filter(User.email == email).first()
    if user is None or user.revoked:
        return  # don't reveal whether the email is registered
    link = _issue_token_and_link(db, user, purpose="password_reset", path="/reset-password")
    send_email(email, "Reset your Wardline password", f"Reset your password: {link}")


def reset_password(
    db: Session, *, token: str, new_password: str, recovery_code: str | None = None
) -> list[str]:
    """Resets the password and, if this account has a vault, re-establishes
    access to it. Returns a fresh batch of recovery codes when (and only
    when) the vault's DEK had to be replaced — see the no-code branch
    below — since every other still-unused code's escrow wrap goes stale
    the moment that happens and there's no way to repair it (the server
    never retains a code's plaintext to re-wrap anything under it later).
    Empty list otherwise (no vault, or a valid code kept the same DEK)."""
    _require_password_strength(new_password)
    auth_token = _consume_token(db, plaintext=token, purpose="password_reset")
    user = db.get(User, auth_token.user_id)
    if user is None:
        raise AccessDeniedError("invalid or expired token")

    fresh_codes: list[str] = []
    vault_key = db.query(VaultKey).filter(VaultKey.user_id == user.id).first()
    if vault_key is not None:
        dek: bytes | None = None
        if recovery_code:
            record = _redeem_recovery_code(db, user, recovery_code)
            if record.vault_wrapped_dek is not None and record.vault_wrapped_dek_nonce is not None:
                kek = vault.derive_kek(recovery_code, salt=record.id.encode("utf-8"))
                try:
                    dek = vault.unwrap(
                        kek, record.vault_wrapped_dek_nonce, record.vault_wrapped_dek, aad=record.id
                    )
                except vault.VaultError:
                    dek = None  # corrupt/tampered row -- fall through to minting a fresh DEK
                    # rather than surfacing an opaque crypto error on a legitimate reset

        if dek is None:
            # No code given, or the code given predates vault escrow /
            # failed to unwrap: mint a fresh DEK. Old history stays
            # encrypted under the now-orphaned key, permanently unreadable
            # -- crypto-shredded, consistent with Pillar 4's
            # right-to-erasure framing -- but the account and everything
            # going forward keep working. Every other still-unused
            # recovery code now wraps a DEK nothing can ever derive again,
            # so void them (they're still perfectly good for their other
            # purpose, disabling MFA, right up until they're used — this
            # only retires their vault-escrow use) and hand back a fresh
            # batch instead of leaving silently-stale codes lying around.
            db.query(RecoveryCode).filter(
                RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)
            ).update({"used_at": utcnow()})
            dek = vault.generate_dek()
            fresh_codes = _issue_recovery_codes(db, user, dek)

        new_salt = vault.generate_salt()
        new_kek = vault.derive_kek(new_password, salt=new_salt)
        nonce, wrapped = vault.wrap(new_kek, dek, aad=user.id)
        vault_key.kdf_salt = new_salt
        vault_key.wrapped_dek = wrapped
        vault_key.wrapped_dek_nonce = nonce

    user.password_hash = hash_password(new_password)
    db.flush()
    # A password reset is exactly the moment to force re-login everywhere
    # else too — a session key minted before an account takeover (the whole
    # reason someone resets a password) shouldn't keep working after.
    _revoke_session_keys(db, user.id)
    return fresh_codes


# --- MFA -----------------------------------------------------------------


def enroll_mfa(db: Session, user: User) -> str:
    """Generates and stores a *pending* TOTP secret — mfa_enabled stays
    False until confirm_mfa verifies the user actually has it set up in
    their authenticator app. Returns the otpauth:// provisioning URI."""
    secret = mfa.generate_secret()
    user.mfa_secret = secret
    db.flush()
    return mfa.provisioning_uri(secret, user.email)


def confirm_mfa(db: Session, user: User, *, code: str, dek: bytes | None = None) -> list[str]:
    """Verifies the pending secret with a real code, flips mfa_enabled on,
    and returns a fresh batch of recovery codes — shown once; only each
    one's hash is retained. `dek` (resolved by the caller via the session
    bridge, api/deps.get_vault_dek — this only runs inside an authenticated
    request) is wrapped into each new code too when available, same as the
    batch already issued at signup/invite-acceptance."""
    if not user.mfa_secret or not mfa.verify_code(user.mfa_secret, code):
        raise AccessDeniedError("invalid verification code")
    user.mfa_enabled = True
    db.flush()
    return _issue_recovery_codes(db, user, dek)


def disable_mfa(db: Session, user: User, *, code: str | None, recovery_code: str | None) -> None:
    valid = bool(code and user.mfa_secret and mfa.verify_code(user.mfa_secret, code))
    if not valid and recovery_code:
        try:
            _redeem_recovery_code(db, user, recovery_code)
            valid = True
        except AccessDeniedError:
            valid = False
    if not valid:
        raise AccessDeniedError(
            "a current MFA code or an unused recovery code is required to disable MFA"
        )

    user.mfa_enabled = False
    user.mfa_secret = None
    # Recovery codes used to get deleted here (they existed only for MFA
    # recovery). Now that they're also generated independently at signup
    # as this account's vault-escrow secret (commercialization roadmap
    # Phase 2), deleting every unused one just because MFA turned off
    # would strand that escrow path for no reason — leave them alone.
    db.flush()


# --- Admin invites ------------------------------------------------------


def create_invite(db: Session, *, email: str, role: str, org_id: str | None = None) -> str:
    """`org_id` is optional and defaults to None, preserving the original
    global-invite behavior (`api/routers/admin_users.py`) -- an org invite
    (`governance/orgs.invite_to_org`) passes it through so the invited user
    joins that org once they accept."""
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, role=role, org_id=org_id)
        db.add(user)
        db.flush()
    elif org_id is not None and user.org_id is None:
        user.org_id = org_id
        db.flush()
    link = _issue_token_and_link(db, user, purpose="invite", path="/accept-invite")
    send_email(email, "You've been invited to Wardline", f"Set up your account: {link}")
    return link


def accept_invite(db: Session, *, token: str, password: str) -> tuple[User, list[str]]:
    _require_password_strength(password)
    auth_token = _consume_token(db, plaintext=token, purpose="invite")
    user = db.get(User, auth_token.user_id)
    if user is None:
        raise AccessDeniedError("invalid or expired token")
    user.password_hash = hash_password(password)
    user.email_verified_at = utcnow()
    db.flush()
    recovery_codes = _provision_vault(db, user, password=password)
    return user, recovery_codes
