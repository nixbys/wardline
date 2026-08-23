"""Credential hashing helpers: API keys, self-serve account passwords, and
the single-use tokens (email verification, password reset, invites,
recovery codes) accounts.py issues.

API keys and passwords are low-entropy-adjacent secrets a human or this
process picks/derives, so both go through argon2 with a server-side pepper
mixed in — never stored in plaintext, matching the "no plaintext credentials
at rest" rule in the report's security plane (4.7). The two use *separate*
pepper settings (api_key_pepper vs. password_pepper) so a leak of one
doesn't automatically compromise the other credential class.

Single-use tokens are different: they're high-entropy random values this
process generates, not secrets a human chooses, so a fast collision-resistant
hash (SHA-256) is the right tool for at-rest storage — the same reasoning
`lookup_key_for_index` below already uses for API keys' non-secret lookup
index.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from wardline.common.config import get_settings

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


def hash_password(plaintext: str) -> str:
    peppered = get_settings().password_pepper + plaintext
    return _hasher.hash(peppered)


def verify_password(plaintext: str, stored_hash: str) -> bool:
    peppered = get_settings().password_pepper + plaintext
    try:
        return _hasher.verify(stored_hash, peppered)
    except VerifyMismatchError:
        return False


def generate_token() -> tuple[str, str]:
    """Return (plaintext_token_to_send_once, sha256_hash_to_store) for
    single-use links (email verification, password reset, invites)."""
    plaintext = secrets.token_urlsafe(32)
    return plaintext, hash_token(plaintext)


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
