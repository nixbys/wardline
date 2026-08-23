"""Unit coverage for governance/accounts.py + governance/mfa.py.

Runs against a real (in-memory SQLite) database rather than a hand-rolled
fake session — `ApiKey.scopes` is a Postgres `JSONB` column, so a small
compiler shim below teaches SQLite to render it as its native `JSON` type
for DDL purposes only; the ORM round-trips a plain Python list either way.
This is strictly a test-time shim: production always runs against real
Postgres (see docker-compose.yml), this just lets the *business logic* in
accounts.py — not the Postgres-specific bits elsewhere in the schema — run
against a fast, disposable database per test.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.types import JSON

from wardline.common.errors import AccessDeniedError
from wardline.governance import accounts, mfa
from wardline.storage.models.base import Base
from wardline.storage.models.governance import ApiKey, AuthToken, RecoveryCode, User


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json_on_sqlite(element, compiler, **kw):  # pragma: no cover - DDL glue
    return compiler.visit_JSON(JSON(), **kw)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[User.__table__, ApiKey.__table__, AuthToken.__table__, RecoveryCode.__table__]
    )
    with Session(engine) as session:
        yield session


# --- signup / email verification ----------------------------------------


def test_signup_creates_unverified_user_with_hashed_password(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    assert user.email == "a@example.com"
    assert user.email_verified_at is None
    assert user.password_hash != "correct-horse-battery"


def test_signup_rejects_weak_password(db):
    with pytest.raises(AccessDeniedError, match="at least"):
        accounts.signup(db, email="a@example.com", password="short")


def test_signup_does_not_create_a_duplicate_for_an_existing_email(db):
    first = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    second = accounts.signup(db, email="a@example.com", password="a-totally-different-password")
    assert first.id == second.id


def test_verify_email_activates_the_account(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    token = db.query(AuthToken).filter(AuthToken.user_id == user.id).first()
    # accounts.signup only returns the User, not the plaintext link, so pull
    # the plaintext the same way the emailed link would carry it: we don't
    # have it (only the hash is stored) -- so exercise the private issuance
    # helper directly to get a token whose plaintext we actually hold.
    plaintext = accounts._issue_token_and_link(db, user, purpose="email_verify", path="/verify-email")
    plaintext = plaintext.rsplit("token=", 1)[1]
    verified = accounts.verify_email(db, token=plaintext)
    assert verified.email_verified_at is not None
    assert token is not None  # the original signup token still exists, just unused


def test_verify_email_rejects_reused_token(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    link = accounts._issue_token_and_link(db, user, purpose="email_verify", path="/verify-email")
    token = link.rsplit("token=", 1)[1]
    accounts.verify_email(db, token=token)
    with pytest.raises(AccessDeniedError, match="invalid or expired"):
        accounts.verify_email(db, token=token)


def test_verify_email_rejects_unknown_token(db):
    with pytest.raises(AccessDeniedError, match="invalid or expired"):
        accounts.verify_email(db, token="not-a-real-token")


# --- login / logout ------------------------------------------------------


def test_login_succeeds_with_correct_password_and_mints_a_session_key(db):
    accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    user = accounts.authenticate(db, email="a@example.com", password="correct-horse-battery")
    api_key = accounts.mint_session_key(db, user)
    assert api_key.startswith("crn_")
    row = db.query(ApiKey).filter(ApiKey.user_id == user.id).first()
    assert row.scopes == ["session"]


def test_login_fails_with_wrong_password(db):
    accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    with pytest.raises(AccessDeniedError, match="invalid email or password"):
        accounts.authenticate(db, email="a@example.com", password="wrong-password-entirely")


def test_login_fails_identically_for_unknown_email(db):
    with pytest.raises(AccessDeniedError, match="invalid email or password"):
        accounts.authenticate(db, email="nobody@example.com", password="whatever-it-is")


def test_login_fails_for_revoked_user(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    user.revoked = True
    db.flush()
    with pytest.raises(AccessDeniedError):
        accounts.authenticate(db, email="a@example.com", password="correct-horse-battery")


def test_login_requires_mfa_code_once_enabled(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    uri = accounts.enroll_mfa(db, user)
    secret = user.mfa_secret
    assert secret in uri
    code = mfa.pyotp.TOTP(secret).now()
    accounts.confirm_mfa(db, user, code=code)

    with pytest.raises(AccessDeniedError, match="mfa_required"):
        accounts.authenticate(db, email="a@example.com", password="correct-horse-battery")

    fresh_code = mfa.pyotp.TOTP(secret).now()
    logged_in = accounts.authenticate(
        db, email="a@example.com", password="correct-horse-battery", mfa_code=fresh_code
    )
    assert logged_in.id == user.id


def test_login_accepts_a_recovery_code_and_consumes_it(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    accounts.enroll_mfa(db, user)
    codes = accounts.confirm_mfa(db, user, code=mfa.pyotp.TOTP(user.mfa_secret).now())

    accounts.authenticate(
        db, email="a@example.com", password="correct-horse-battery", recovery_code=codes[0]
    )
    # Same code again must fail -- recovery codes are single-use. This gets
    # a more specific error than the generic "mfa_required" signal, since
    # the caller did supply a recovery code and it specifically didn't work.
    with pytest.raises(AccessDeniedError, match="invalid or already-used recovery code"):
        accounts.authenticate(
            db, email="a@example.com", password="correct-horse-battery", recovery_code=codes[0]
        )


def test_logout_revokes_only_the_session_key_used(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    session_key = accounts.mint_session_key(db, user)
    from wardline.common.security import generate_api_key, lookup_key_for_index

    permanent_plaintext, permanent_hash = generate_api_key()
    db.add(
        ApiKey(
            user_id=user.id,
            key_hash=permanent_hash,
            lookup_hash=lookup_key_for_index(permanent_plaintext),
            scopes=["*"],
        )
    )
    db.flush()

    accounts.logout(db, token=session_key)

    session_row = (
        db.query(ApiKey).filter(ApiKey.lookup_hash == lookup_key_for_index(session_key)).first()
    )
    permanent_row = (
        db.query(ApiKey).filter(ApiKey.lookup_hash == lookup_key_for_index(permanent_plaintext)).first()
    )
    assert session_row.revoked is True
    assert permanent_row.revoked is False


# --- password reset --------------------------------------------------


def test_reset_password_updates_hash_and_revokes_session_keys_only(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    session_key = accounts.mint_session_key(db, user)
    from wardline.common.security import generate_api_key, lookup_key_for_index

    permanent_plaintext, permanent_hash = generate_api_key()
    db.add(
        ApiKey(
            user_id=user.id,
            key_hash=permanent_hash,
            lookup_hash=lookup_key_for_index(permanent_plaintext),
            scopes=["*"],
        )
    )
    db.flush()

    link = accounts._issue_token_and_link(db, user, purpose="password_reset", path="/reset-password")
    token = link.rsplit("token=", 1)[1]
    accounts.reset_password(db, token=token, new_password="a-brand-new-strong-password")

    accounts.authenticate(db, email="a@example.com", password="a-brand-new-strong-password")
    with pytest.raises(AccessDeniedError):
        accounts.authenticate(db, email="a@example.com", password="correct-horse-battery")

    session_row = (
        db.query(ApiKey).filter(ApiKey.lookup_hash == lookup_key_for_index(session_key)).first()
    )
    permanent_row = (
        db.query(ApiKey).filter(ApiKey.lookup_hash == lookup_key_for_index(permanent_plaintext)).first()
    )
    assert session_row.revoked is True
    assert permanent_row.revoked is False


def test_request_password_reset_does_not_raise_for_unknown_email(db):
    accounts.request_password_reset(db, email="nobody@example.com")  # must not raise


# --- MFA enroll/confirm/disable -----------------------------------------


def test_confirm_mfa_rejects_wrong_code(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    accounts.enroll_mfa(db, user)
    with pytest.raises(AccessDeniedError, match="invalid verification code"):
        accounts.confirm_mfa(db, user, code="000000")


def test_confirm_mfa_issues_the_configured_number_of_recovery_codes(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    accounts.enroll_mfa(db, user)
    codes = accounts.confirm_mfa(db, user, code=mfa.pyotp.TOTP(user.mfa_secret).now())
    from wardline.common.config import get_settings

    assert len(codes) == get_settings().recovery_code_count
    assert len(set(codes)) == len(codes)


def test_disable_mfa_requires_a_valid_code_or_recovery_code(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    accounts.enroll_mfa(db, user)
    accounts.confirm_mfa(db, user, code=mfa.pyotp.TOTP(user.mfa_secret).now())

    with pytest.raises(AccessDeniedError, match="a current MFA code"):
        accounts.disable_mfa(db, user, code="000000", recovery_code=None)

    accounts.disable_mfa(db, user, code=mfa.pyotp.TOTP(user.mfa_secret).now(), recovery_code=None)
    assert user.mfa_enabled is False
    assert user.mfa_secret is None


def test_disable_mfa_via_recovery_code_and_clears_unused_codes(db):
    user = accounts.signup(db, email="a@example.com", password="correct-horse-battery")
    accounts.enroll_mfa(db, user)
    codes = accounts.confirm_mfa(db, user, code=mfa.pyotp.TOTP(user.mfa_secret).now())

    accounts.disable_mfa(db, user, code=None, recovery_code=codes[0])
    assert user.mfa_enabled is False
    # The just-redeemed code (codes[0]) is deliberately left in place as a
    # used record, not deleted -- disable_mfa only purges the ones that
    # never got used and are now moot. So the right assertion is "no
    # *unused* codes remain", not "no rows remain".
    remaining_unused = (
        db.query(RecoveryCode)
        .filter(RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None))
        .count()
    )
    assert remaining_unused == 0


# --- invites ------------------------------------------------------------


def test_invite_and_accept_invite_activates_the_account(db):
    link = accounts.create_invite(db, email="teammate@example.com", role="analyst")
    token = link.rsplit("token=", 1)[1]
    user = accounts.accept_invite(db, token=token, password="a-strong-invited-password")
    assert user.role == "analyst"
    assert user.email_verified_at is not None
    accounts.authenticate(db, email="teammate@example.com", password="a-strong-invited-password")


def test_accept_invite_rejects_reused_token(db):
    link = accounts.create_invite(db, email="teammate@example.com", role="viewer")
    token = link.rsplit("token=", 1)[1]
    accounts.accept_invite(db, token=token, password="a-strong-invited-password")
    with pytest.raises(AccessDeniedError):
        accounts.accept_invite(db, token=token, password="yet-another-strong-password")


# --- mfa.py pure functions -----------------------------------------------


def test_mfa_generate_and_verify_round_trip():
    secret = mfa.generate_secret()
    code = mfa.pyotp.TOTP(secret).now()
    assert mfa.verify_code(secret, code)


def test_mfa_verify_rejects_wrong_code():
    secret = mfa.generate_secret()
    assert not mfa.verify_code(secret, "000000")


def test_mfa_provisioning_uri_embeds_secret_and_issuer():
    secret = mfa.generate_secret()
    uri = mfa.provisioning_uri(secret, "a@example.com")
    assert secret in uri
    assert "a%40example.com" in uri or "a@example.com" in uri


def test_generate_recovery_code_is_readable_and_unique():
    codes = {mfa.generate_recovery_code() for _ in range(50)}
    assert len(codes) == 50
    assert all(len(c) == 11 and c[5] == "-" for c in codes)
