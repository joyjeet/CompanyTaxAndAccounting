"""JWT authentication tests.

We don't stand up a real JWKS — we exercise the `TestTokenIdentityProvider`
(HS256) for happy/sad paths, and we exercise the FastAPI dep wrapper to
confirm fail-closed behaviour at the HTTP boundary.
"""
from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_identity
from app.core.config import get_settings
from app.main import create_app
from app.security.auth import (
    InvalidTokenError,
    TestTokenIdentityProvider,
    mint_test_token,
    reset_identity_provider,
)


@pytest.fixture(autouse=True)
def _ensure_test_mode():
    settings = get_settings()
    assert settings.app_auth_mode == "test"
    reset_identity_provider()
    yield
    reset_identity_provider()


@pytest.fixture
def provider() -> TestTokenIdentityProvider:
    return TestTokenIdentityProvider()


# --------------------------------------------------------------------------- #
# Provider-level tests
# --------------------------------------------------------------------------- #
def test_valid_firm_token(provider: TestTokenIdentityProvider) -> None:
    firm = uuid4()
    token = mint_test_token(sub="alice", firm_id=firm, role="firm_staff")
    ident = provider.validate(token=token)
    assert ident.subject == "alice"
    assert ident.firm_id == firm
    assert ident.scope.value == "firm"
    assert ident.client_id is None


def test_valid_client_token(provider: TestTokenIdentityProvider) -> None:
    firm, client = uuid4(), uuid4()
    token = mint_test_token(
        sub="bob", firm_id=firm, role="client_portal", client_id=client
    )
    ident = provider.validate(token=token)
    assert ident.scope.value == "client"
    assert ident.client_id == client


def test_client_role_without_client_id_rejected(provider: TestTokenIdentityProvider) -> None:
    token = mint_test_token(sub="bob", firm_id=uuid4(), role="client_portal")
    with pytest.raises(InvalidTokenError):
        provider.validate(token=token)


def test_unknown_role_rejected(provider: TestTokenIdentityProvider) -> None:
    token = mint_test_token(sub="x", firm_id=uuid4(), role="janitor")
    with pytest.raises(InvalidTokenError):
        provider.validate(token=token)


def test_expired_token_rejected(provider: TestTokenIdentityProvider) -> None:
    token = mint_test_token(
        sub="alice", firm_id=uuid4(), role="firm_staff", expires_in=-10
    )
    with pytest.raises(InvalidTokenError):
        provider.validate(token=token)


def test_wrong_audience_rejected(provider: TestTokenIdentityProvider) -> None:
    token = mint_test_token(
        sub="alice", firm_id=uuid4(), role="firm_staff", audience="wrong-audience"
    )
    with pytest.raises(InvalidTokenError):
        provider.validate(token=token)


def test_wrong_issuer_rejected(provider: TestTokenIdentityProvider) -> None:
    token = mint_test_token(
        sub="alice", firm_id=uuid4(), role="firm_staff", issuer="wrong-issuer"
    )
    with pytest.raises(InvalidTokenError):
        provider.validate(token=token)


def test_tampered_signature_rejected(provider: TestTokenIdentityProvider) -> None:
    token = mint_test_token(sub="alice", firm_id=uuid4(), role="firm_staff")
    # Flip the FIRST char of the signature segment. The last base64 char
    # of an HS256 signature carries only 4 significant bits — the trailing
    # bits are padding and a 1-bit flip there decodes to the same bytes and
    # verifies successfully. Mutating the first char avoids this.
    head, payload, sig = token.split(".")
    bad = ("A" if sig[0] != "A" else "B") + sig[1:]
    tampered = ".".join([head, payload, bad])
    with pytest.raises(InvalidTokenError):
        provider.validate(token=tampered)


def test_alg_none_rejected(provider: TestTokenIdentityProvider) -> None:
    """A token signed with `alg=none` (or any non-HS256 alg) must be refused."""
    settings = get_settings()
    payload = {
        "sub": "alice",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "iss": settings.app_test_jwt_issuer,
        "aud": settings.app_test_jwt_audience,
        settings.oidc_claim_roles: ["firm_staff"],
        settings.oidc_claim_firm_id: str(uuid4()),
    }
    # Mint without signature using PyJWT's `none` algorithm.
    bad = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(InvalidTokenError):
        provider.validate(token=bad)


def test_missing_firm_id_rejected(provider: TestTokenIdentityProvider) -> None:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": "alice",
        "iat": now,
        "exp": now + 3600,
        "iss": settings.app_test_jwt_issuer,
        "aud": settings.app_test_jwt_audience,
        settings.oidc_claim_roles: ["firm_staff"],
        # firm_id intentionally absent
    }
    token = jwt.encode(payload, settings.app_test_jwt_secret, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        provider.validate(token=token)


# --------------------------------------------------------------------------- #
# FastAPI dependency / HTTP boundary
# --------------------------------------------------------------------------- #
def _client() -> TestClient:
    app = create_app()
    return TestClient(app)


def test_healthz_does_not_require_auth() -> None:
    """Sanity: /healthz is unauthenticated."""
    resp = _client().get("/healthz")
    assert resp.status_code == 200


def test_protected_route_without_token_returns_401() -> None:
    resp = _client().get("/drafts")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate", "").lower().startswith("bearer")


def test_protected_route_with_malformed_header_returns_401() -> None:
    resp = _client().get("/drafts", headers={"Authorization": "Token abc"})
    assert resp.status_code == 401


def test_protected_route_with_invalid_token_returns_401() -> None:
    resp = _client().get(
        "/drafts", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert resp.status_code == 401


def test_protected_route_with_expired_token_returns_401() -> None:
    token = mint_test_token(
        sub="alice", firm_id=uuid4(), role="firm_staff", expires_in=-1
    )
    resp = _client().get(
        "/drafts", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


def test_protected_route_with_valid_firm_token_succeeds(world) -> None:
    """A valid token gets through auth and the route returns 200 with [] of drafts."""
    token = mint_test_token(
        sub="alice", firm_id=world.firm_a, role="firm_staff"
    )
    resp = _client().get(
        "/drafts", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_get_identity_callable_directly_with_request(monkeypatch) -> None:
    """Direct call signature still returns AuthIdentity for a real bearer."""
    from starlette.requests import Request

    firm = uuid4()
    token = mint_test_token(sub="x", firm_id=firm, role="firm_staff")
    scope = {
        "type": "http",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    }
    ident = get_identity(Request(scope))
    assert ident.firm_id == firm
