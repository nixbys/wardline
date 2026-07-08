"""API-key generation/hashing helpers.

Keys are never stored in plaintext: we hash `pepper + secret` with argon2 and
store only the hash, matching the "no plaintext credentials at rest" rule in
the report's security plane (4.7).
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from cranus.common.config import get_settings

_hasher = PasswordHasher()

API_KEY_PREFIX = "crn"


def generate_api_key() -> tuple[str, str]:
    """Return (plaintext_key_to_show_once, hash_to_store)."""
    secret = secrets.token_urlsafe(32)
    plaintext = f"{API_KEY_PREFIX}_{secret}"
    return plaintext, hash_api_key(plaintext)


def hash_api_key(plaintext: str) -> str:
    peppered = get_settings().api_key_pepper + plaintext
    return _hasher.hash(peppered)


def verify_api_key(plaintext: str, stored_hash: str) -> bool:
    peppered = get_settings().api_key_pepper + plaintext
    try:
        return _hasher.verify(stored_hash, peppered)
    except VerifyMismatchError:
        return False


def lookup_key_for_index(plaintext: str) -> str:
    """Deterministic, non-secret index to find the candidate row before argon2-verifying it.

    Argon2 hashes aren't lookup-able by design, so api_keys carries this alongside
    the argon2 hash purely as a DB index — never used for authentication itself.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
