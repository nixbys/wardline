"""Optional OIDC JWT bearer-token auth (`settings.auth_mode == "oidc"`), an
alternative to this project's own API-key system for onboarding through a
real IdP (Okta/Auth0/Keycloak/Entra ID, anything OIDC-compliant) instead.

Validates the token's signature against the IdP's published JWKS, checks
issuer/audience/expiry, and maps a configured role claim onto this app's
internal roles (admin/analyst/viewer) so the rest of the app (RBAC/ABAC/
audit) doesn't need to know which auth mode produced the `User`.

Known limitation: JWKS keys are cached for `_JWKS_TTL_SECONDS` rather than
re-fetched per request (fetching on every request would defeat the point of
a fast local check) — a key rotated at the IdP takes up to that long to be
picked up here. Short enough to be a non-issue in practice, long enough to
avoid hammering the IdP's JWKS endpoint.
"""

from __future__ import annotations

import time

import httpx
from jose import jwt
from jose.exceptions import JOSEError

from cranus.common.config import Settings
from cranus.storage.models.governance import ROLE_VIEWER, ROLES

_JWKS_TTL_SECONDS = 600
_jwks_cache: dict[str, tuple[float, dict]] = {}


class OidcAuthError(Exception):
    """Token missing, malformed, expired, or fails signature/claim checks."""


def _get_jwks(jwks_url: str) -> dict:
    cached = _jwks_cache.get(jwks_url)
    now = time.monotonic()
    if cached and now - cached[0] < _JWKS_TTL_SECONDS:
        return cached[1]
    resp = httpx.get(jwks_url, timeout=10)
    resp.raise_for_status()
    jwks = resp.json()
    _jwks_cache[jwks_url] = (now, jwks)
    return jwks


def _resolve_role(claims: dict, settings: Settings) -> str:
    raw_roles = claims.get(settings.oidc_role_claim, [])
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    for raw in raw_roles:
        mapped = settings.oidc_role_map.get(str(raw).lower())
        if mapped in ROLES:
            return mapped
    return ROLE_VIEWER


def validate_token(token: str, settings: Settings) -> tuple[str, str, str | None]:
    """Returns (subject, resolved_role, email_claim_if_present). Raises
    OidcAuthError on any failure — signature, issuer, audience, or expiry.
    """
    if not settings.oidc_jwks_url or not settings.oidc_issuer:
        raise OidcAuthError(
            "AUTH_MODE=oidc but oidc_issuer/oidc_jwks_url aren't configured"
        )
    try:
        jwks = _get_jwks(settings.oidc_jwks_url)
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256", "ES256"],
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            options={"verify_aud": settings.oidc_audience is not None},
        )
    except JOSEError as exc:
        raise OidcAuthError(f"invalid token: {exc}") from exc
    except httpx.HTTPError as exc:
        raise OidcAuthError(f"could not fetch JWKS: {exc}") from exc

    subject = claims.get("sub")
    if not subject:
        raise OidcAuthError("token has no 'sub' claim")
    return subject, _resolve_role(claims, settings), claims.get("email")
