"""Unit coverage for security/vault.py's crypto primitives (commercialization
roadmap Phase 2 / Pillar 2). governance/accounts.py's lifecycle integration
(signup provisioning a vault, the login/logout session bridge, recovery-code
escrow) is covered in test_accounts.py instead — this file is just the
primitives themselves.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.types import JSON

from wardline.common.plans import FREE, PRO
from wardline.governance import billing, orgs
from wardline.security import vault
from wardline.storage.models.base import Base
from wardline.storage.models.billing import Subscription
from wardline.storage.models.governance import User
from wardline.storage.models.orgs import Organization


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json_on_sqlite(element, compiler, **kw):  # pragma: no cover - DDL glue
    return compiler.visit_JSON(JSON(), **kw)


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


# --- derive_kek -------------------------------------------------------


def test_derive_kek_is_deterministic_for_the_same_password_and_salt():
    salt = vault.generate_salt()
    assert vault.derive_kek("correct-horse-battery", salt=salt) == vault.derive_kek(
        "correct-horse-battery", salt=salt
    )


def test_derive_kek_differs_for_a_different_password():
    salt = vault.generate_salt()
    assert vault.derive_kek("correct-horse-battery", salt=salt) != vault.derive_kek(
        "a-totally-different-password", salt=salt
    )


def test_derive_kek_differs_for_a_different_salt():
    kek1 = vault.derive_kek("correct-horse-battery", salt=vault.generate_salt())
    kek2 = vault.derive_kek("correct-horse-battery", salt=vault.generate_salt())
    assert kek1 != kek2


# --- wrap / unwrap ------------------------------------------------------


def test_wrap_unwrap_round_trips():
    key = vault.generate_dek()
    dek = vault.generate_dek()
    nonce, ciphertext = vault.wrap(key, dek, aad="user_1")
    assert vault.unwrap(key, nonce, ciphertext, aad="user_1") == dek


def test_unwrap_fails_closed_on_wrong_key():
    dek = vault.generate_dek()
    nonce, ciphertext = vault.wrap(vault.generate_dek(), dek, aad="user_1")
    with pytest.raises(vault.VaultError):
        vault.unwrap(vault.generate_dek(), nonce, ciphertext, aad="user_1")


def test_unwrap_fails_closed_on_tampered_ciphertext():
    key = vault.generate_dek()
    dek = vault.generate_dek()
    nonce, ciphertext = vault.wrap(key, dek, aad="user_1")
    tampered = bytes([ciphertext[0] ^ 0xFF]) + ciphertext[1:]
    with pytest.raises(vault.VaultError):
        vault.unwrap(key, nonce, tampered, aad="user_1")


def test_unwrap_fails_closed_on_mismatched_aad():
    key = vault.generate_dek()
    dek = vault.generate_dek()
    nonce, ciphertext = vault.wrap(key, dek, aad="user_1")
    with pytest.raises(vault.VaultError):
        vault.unwrap(key, nonce, ciphertext, aad="user_2")


# --- encrypt_field / decrypt_field --------------------------------------


def test_encrypt_field_round_trips_and_is_prefixed():
    dek = vault.generate_dek()
    blob = vault.encrypt_field(dek, "what's the blast radius of CVE-2024-1234?")
    assert blob.startswith("enc:v1:")
    assert vault.decrypt_field(dek, blob) == "what's the blast radius of CVE-2024-1234?"


def test_decrypt_field_rejects_a_plaintext_blob():
    with pytest.raises(vault.VaultError, match="enc:v1:"):
        vault.decrypt_field(vault.generate_dek(), "just a plain question, never encrypted")


# --- session bridge ------------------------------------------------------


def test_wrap_unwrap_for_session_round_trips():
    dek = vault.generate_dek()
    nonce, ciphertext = vault.wrap_for_session(dek, aad="key_1")
    assert vault.unwrap_for_session(nonce, ciphertext, aad="key_1") == dek


# --- should_encrypt_history ----------------------------------------------


def test_should_encrypt_history_true_for_a_solo_pro_user(db, user):
    billing.create_checkout_session(db, user, plan_id=PRO)
    assert vault.should_encrypt_history(db, user) is True


def test_should_encrypt_history_false_for_a_solo_free_user(db, user):
    assert billing.current_plan_id(db, user) == FREE
    assert vault.should_encrypt_history(db, user) is False


def test_should_encrypt_history_false_for_an_org_member_even_on_pro(db, user):
    org = orgs.create_organization(db, owner=user, name="Acme Inc")
    member = User(email="member@example.com", role="viewer", org_id=org.id)
    db.add(member)
    db.flush()
    billing.create_checkout_session(db, member, plan_id=PRO)
    assert vault.should_encrypt_history(db, member) is False
