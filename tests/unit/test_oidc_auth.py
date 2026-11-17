"""OIDC token validation against a local RSA key and a mocked JWKS endpoint.

tests/integration/test_oidc_live.py covers a real Keycloak; these cases run
everywhere and pin down the failure modes.
"""

from __future__ import annotations

import json
import time

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa

from wardline.api import oidc_auth
from wardline.api.oidc_auth import OidcAuthError, validate_token
from wardline.common.config import Settings

ISSUER = "https://idp.example.test/realms/wardline"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
AUDIENCE = "wardline-api"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings():
    return Settings(
        oidc_issuer=ISSUER,
        oidc_jwks_url=JWKS_URL,
        oidc_audience=AUDIENCE,
        oidc_role_claim="realm_access.roles",
        oidc_role_map={"wardline-analyst": "analyst"},
    )


@pytest.fixture(autouse=True)
def jwks(signing_key):
    oidc_auth._jwks_cache.clear()
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    jwk.update(kid="key-1", use="sig", alg="RS256")
    with respx.mock:
        respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": [jwk]}))
        yield


def make_token(key, kid="key-1", **overrides):
    now = int(time.time())
    claims = {
        "sub": "user-123",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        "email": "analyst@example.test",
        "realm_access": {"roles": ["wardline-analyst"]},
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def test_valid_token_maps_role(signing_key, settings):
    subject, role, email = validate_token(make_token(signing_key), settings)
    assert (subject, role, email) == ("user-123", "analyst", "analyst@example.test")


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://other-idp.example.test"},
        {"aud": "another-app"},
        {"exp": int(time.time()) - 60},
    ],
    ids=["wrong-issuer", "wrong-audience", "expired"],
)
def test_rejects_bad_claims(signing_key, settings, overrides):
    with pytest.raises(OidcAuthError):
        validate_token(make_token(signing_key, **overrides), settings)


def test_rejects_unknown_key_id(signing_key, settings):
    with pytest.raises(OidcAuthError, match="key id"):
        validate_token(make_token(signing_key, kid="rotated-away"), settings)


def test_rejects_token_signed_by_another_key(settings):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(OidcAuthError):
        validate_token(make_token(other), settings)


def test_rejects_malformed_token(settings):
    with pytest.raises(OidcAuthError):
        validate_token("not-a-jwt", settings)
