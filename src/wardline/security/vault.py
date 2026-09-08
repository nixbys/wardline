"""Encrypted conversation-history vault primitives (commercialization
roadmap Phase 2 / Pillar 2): derive/wrap/unwrap a per-user data-encryption
key (DEK), and encrypt/decrypt individual text fields with it.

Threat model, precisely: this protects a Pro-tier solo user's stored
conversation history from LATER, offline browsing -- a DB dump, a backup,
an insider with only database access -- not from the live, currently
authenticated request that's already answering the user's question (the
plaintext question necessarily passes through this process in-flight, same
as it would for Lumo or any other RAG product; see the roadmap's Pillar 2
section for why that's unavoidable). "Session bridge" functions here
(governance/accounts.py's login/logout) bound that live-process exposure to
"an active, unrevoked session," not indefinitely.

Two distinct key-derivation uses, both via Argon2id, both deliberately NOT
common/security.py's `PasswordHasher`: that hasher embeds a fresh random
salt on every `.hash()` call and is verify-only (there's no way to get the
same output twice), which is exactly wrong for a KEK that must be
re-derived identically at write time and read time from the same secret.
`derive_kek` here is a real, deterministic KDF -- the caller supplies a
salt it already has stored, not one generated per call.
"""

from __future__ import annotations

import base64
import secrets

from argon2 import Type, low_level
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.orm import Session

from wardline.common.config import get_settings
from wardline.common.plans import PRO
from wardline.storage.models.governance import User

_DEK_LEN = 32  # AES-256
_NONCE_LEN = 12  # AESGCM's standard nonce size
_FIELD_PREFIX = "enc:v1:"


class VaultError(Exception):
    """Raised on a failed unwrap/decrypt (wrong key, tampered ciphertext,
    or mismatched AAD) -- always fail closed, never return garbage."""


def generate_dek() -> bytes:
    """A fresh, random per-user data-encryption key. Never stored or
    transmitted in the clear -- always passed through `wrap`/`unwrap`
    first."""
    return secrets.token_bytes(_DEK_LEN)


def generate_salt() -> bytes:
    return secrets.token_bytes(16)


def derive_kek(secret: str, *, salt: bytes) -> bytes:
    """Deterministic Argon2id derivation of a key-encryption key from a
    secret the user (re-)supplies -- their password, or one recovery
    code's plaintext. Same secret + same salt always yields the same KEK,
    which is the whole point: this is how a KEK gets re-derived at read
    time without ever having been stored anywhere."""
    settings = get_settings()
    peppered = (settings.vault_pepper + secret).encode("utf-8")
    return low_level.hash_secret_raw(
        peppered,
        salt,
        time_cost=settings.vault_kdf_time_cost,
        memory_cost=settings.vault_kdf_memory_cost_kib,
        parallelism=settings.vault_kdf_parallelism,
        hash_len=_DEK_LEN,
        type=Type.ID,
    )


def wrap(key: bytes, plaintext: bytes, *, aad: str) -> tuple[bytes, bytes]:
    """Returns (nonce, ciphertext). `aad` binds the ciphertext to the row
    it's stored on (e.g. a user id or recovery-code id) so a wrapped blob
    can't be silently copied onto a different row and still verify."""
    nonce = secrets.token_bytes(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad.encode("utf-8"))
    return nonce, ciphertext


def unwrap(key: bytes, nonce: bytes, ciphertext: bytes, *, aad: str) -> bytes:
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad.encode("utf-8"))
    except InvalidTag as exc:
        raise VaultError("wrong key, tampered ciphertext, or mismatched aad") from exc


def encrypt_field(dek: bytes, plaintext: str) -> str:
    """For embedding an encrypted value inside a JSONB payload (a plain
    string column, alongside other never-encrypted keys in the same
    dict) -- not for a dedicated binary column, which should just call
    `wrap` directly and store nonce/ciphertext in their own columns
    (see VaultKey/RecoveryCode/ApiKey)."""
    nonce, ciphertext = wrap(dek, plaintext.encode("utf-8"), aad="field")
    return _FIELD_PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_field(dek: bytes, blob: str) -> str:
    if not blob.startswith(_FIELD_PREFIX):
        raise VaultError(f"not an encrypted field (missing {_FIELD_PREFIX!r} prefix)")
    raw = base64.urlsafe_b64decode(blob[len(_FIELD_PREFIX) :])
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    return unwrap(dek, nonce, ciphertext, aad="field").decode("utf-8")


def _session_wrap_key() -> bytes:
    """Fast-derived (HKDF-SHA256, not Argon2id) 32-byte AES key from
    settings.vault_session_secret. Deliberately not Argon2id: that secret
    is already high-entropy, server-held config, not a human-chosen one —
    slow-hashing it on every login/logout/request would be pure overhead
    with no security benefit. Used only for the "session bridge"
    (governance/accounts.py): re-wrapping a DEK so an active session can
    reuse it without the plaintext password, which only ever existed for
    the instant of the login call."""
    secret = get_settings().vault_session_secret.encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(), length=_DEK_LEN, salt=None, info=b"wardline-vault-session"
    ).derive(secret)


def wrap_for_session(dek: bytes, *, aad: str) -> tuple[bytes, bytes]:
    return wrap(_session_wrap_key(), dek, aad=aad)


def unwrap_for_session(nonce: bytes, ciphertext: bytes, *, aad: str) -> bytes:
    return unwrap(_session_wrap_key(), nonce, ciphertext, aad=aad)


def should_encrypt_history(db: Session, user: User) -> bool:
    """Solo Pro accounts only, matching the roadmap's Pillar 5 tier table
    literally: "encrypted private history" is listed under Pro, while
    Team is "shared corpus + shared audit log *within the org*" -- org
    membership means shared/plaintext audit visibility is the point
    being paid for, not a bug to work around here."""
    if not get_settings().vault_enabled or user.org_id is not None:
        return False
    from wardline.governance.billing import current_plan_id

    return current_plan_id(db, user) == PRO
