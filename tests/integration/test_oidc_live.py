"""Live test of the OIDC auth path (api/oidc_auth.py) against a real
Keycloak instance -- the README's own "Production readiness" section
flagged this as "not yet live-tested against a real IdP... validated by
code review and the JWT/JWKS-handling logic only". This closes that gap.

Requires a real Keycloak reachable at KEYCLOAK_BASE_URL (CI starts one via
`docker run` in the workflow -- Keycloak's official image needs a
`start-dev` command argument that GitHub Actions' `services:` block has no
way to pass, so it isn't a service container like Postgres/Neo4j). Skips
itself when that env var isn't set, so `pytest tests/integration` still
runs everywhere else without requiring every contributor to stand up a
Keycloak locally.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from wardline.api.oidc_auth import OidcAuthError, validate_token
from wardline.common.config import Settings

KEYCLOAK_BASE_URL = os.environ.get("KEYCLOAK_BASE_URL")
pytestmark = pytest.mark.skipif(
    not KEYCLOAK_BASE_URL, reason="KEYCLOAK_BASE_URL not set -- no live Keycloak to test against"
)


@pytest.fixture(scope="module")
def keycloak_client_credentials():
    """Provisions a throwaway realm/client/role/service-account against the
    real Keycloak via its admin REST API, and returns a real signed access
    token plus the settings needed to validate it -- the same shape
    `oidc_auth.validate_token` sees from any real IdP.
    """
    base = KEYCLOAK_BASE_URL
    realm = f"wardline-test-{uuid.uuid4().hex[:8]}"
    client_id = "wardline-svc-client"
    client_secret = "svc-secret"

    # The master realm's own sslRequired policy (unrelated to the throwaway
    # realm created below) rejects plain HTTP unless the request looks like
    # it arrived via a TLS-terminating proxy -- true of most container
    # network setups fronting a bare `docker run`. Real deployments sit
    # behind real TLS; this header only stands in for that on this one
    # bootstrap call.
    admin_token = httpx.post(
        f"{base}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": "admin",
        },
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "localhost"},
        timeout=10,
    ).raise_for_status().json()["access_token"]
    # Same TLS-proxy stand-in as above -- the admin REST API is served
    # under the same sslRequired policy as the token endpoint.
    h = {
        "Authorization": f"Bearer {admin_token}",
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "localhost",
    }

    # sslRequired="none": this realm is only ever reached over plain HTTP in
    # CI/local testing, and oidc_auth.py's own JWKS fetch doesn't send any
    # X-Forwarded-Proto override (a real deployment sits behind real TLS).
    httpx.post(
        f"{base}/admin/realms",
        json={"realm": realm, "enabled": True, "sslRequired": "none"},
        headers=h, timeout=10,
    ).raise_for_status()
    try:
        httpx.post(
            f"{base}/admin/realms/{realm}/clients",
            json={
                "clientId": client_id,
                "enabled": True,
                "publicClient": False,
                "serviceAccountsEnabled": True,
                "standardFlowEnabled": False,
                "directAccessGrantsEnabled": False,
                "clientAuthenticatorType": "client-secret",
                "secret": client_secret,
            },
            headers=h, timeout=10,
        ).raise_for_status()
        client_uuid = httpx.get(
            f"{base}/admin/realms/{realm}/clients", params={"clientId": client_id},
            headers=h, timeout=10,
        ).json()[0]["id"]
        svc_user_id = httpx.get(
            f"{base}/admin/realms/{realm}/clients/{client_uuid}/service-account-user",
            headers=h, timeout=10,
        ).json()["id"]

        httpx.post(
            f"{base}/admin/realms/{realm}/roles", json={"name": "admin"}, headers=h, timeout=10
        ).raise_for_status()
        role = httpx.get(f"{base}/admin/realms/{realm}/roles/admin", headers=h, timeout=10).json()
        httpx.post(
            f"{base}/admin/realms/{realm}/users/{svc_user_id}/role-mappings/realm",
            json=[role], headers=h, timeout=10,
        ).raise_for_status()

        token = httpx.post(
            f"{base}/realms/{realm}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=10,
        ).raise_for_status().json()["access_token"]

        settings = Settings(
            oidc_issuer=f"{base}/realms/{realm}",
            oidc_jwks_url=f"{base}/realms/{realm}/protocol/openid-connect/certs",
            oidc_audience="account",
        )
        yield token, settings
    finally:
        httpx.delete(f"{base}/admin/realms/{realm}", headers=h, timeout=10)


def test_validate_token_accepts_real_signed_token_and_maps_realm_role(keycloak_client_credentials):
    token, settings = keycloak_client_credentials
    subject, role, _email = validate_token(token, settings)
    assert subject  # the service account's Keycloak-assigned UUID
    assert role == "admin"  # from realm_access.roles, per the role mapping above


def test_validate_token_rejects_tampered_signature(keycloak_client_credentials):
    token, settings = keycloak_client_credentials
    with pytest.raises(OidcAuthError):
        validate_token(token + "tampered", settings)


def test_validate_token_rejects_wrong_issuer(keycloak_client_credentials):
    token, settings = keycloak_client_credentials
    wrong = Settings(
        oidc_issuer=f"{KEYCLOAK_BASE_URL}/realms/not-the-real-realm",
        oidc_jwks_url=settings.oidc_jwks_url,
        oidc_audience=settings.oidc_audience,
    )
    with pytest.raises(OidcAuthError):
        validate_token(token, wrong)
