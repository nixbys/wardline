"""TOTP-based multi-factor auth (commercialization roadmap Pillar 1):
secret generation, provisioning-URI construction for an authenticator app,
code verification, and recovery-code generation for when the device is
lost. `governance/accounts.py` is the only caller — this module stays
free of DB/session concerns so it's trivially unit-testable on its own.

Passkeys/WebAuthn are the natural next step here but are a materially
bigger client-side lift (the browser credential API, not just an HTTP
call) — TOTP is the standard first cut and what every mainstream MFA flow
(GitHub, Google, Proton included) still offers as a baseline alongside
whatever else they support.
"""

from __future__ import annotations

import secrets

import pyotp

from wardline.common.config import get_settings

# One 30-second step of clock drift tolerance on each side — the standard
# compromise between rejecting a slightly-out-of-sync authenticator app and
# widening the window enough to matter for brute-force resistance (a 6-digit
# code already has 1e6 possibilities; +/-1 step just triples the guesses
# that count as valid, not meaningfully weaker).
_VALID_WINDOW = 1


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str) -> str:
    """otpauth:// URI for a QR code / manual-entry string in an authenticator app."""
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=get_settings().mfa_issuer)


def verify_code(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=_VALID_WINDOW)


def generate_recovery_code() -> str:
    """A human-typeable backup code, shown once. Formatted for readability
    (xxxxx-xxxxx) — normalization for hashing/matching happens in
    governance/accounts.py, not here, since that's a storage concern."""
    raw = secrets.token_hex(5)
    return f"{raw[:5]}-{raw[5:]}"
