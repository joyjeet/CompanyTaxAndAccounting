"""JWT-based identity providers.

Two implementations sit behind the `IdentityProvider` ABC:

* `JwtIdentityProvider`     — production. Validates RS256-signed JWTs against
                              an OIDC JWKS (Entra ID), checks issuer +
                              audience + expiry, then maps claims to a tenant
                              `AuthIdentity`.
* `TestTokenIdentityProvider` — local/dev/CI. Validates HS256-signed tokens
                              minted with a shared secret. Same `AuthIdentity`
                              shape; same fail-closed semantics on any failure.

The active provider is selected by `Settings.app_auth_mode`. There is NO third
"trust the client" mode: a missing/invalid token always raises
`InvalidTokenError`, which the FastAPI dependency translates into 401.

Claim contract
--------------
The directory administrator MUST issue tokens with these claims:

    sub        — principal id (oid for Entra ID).
    iss        — issuer URL (matched against `oidc_issuer`).
    aud        — audience (matched against `oidc_audience`).
    exp / iat  — standard JWT lifetime claims.
    roles      — string[] containing exactly one of:
                   `firm_staff` -> AccessScope.FIRM
                   `client_portal` -> AccessScope.CLIENT
    firm_id    — UUID of the firm. Required for both roles.
    client_id  — UUID of the client.
                   Required when role is `client_portal`.
                   Optional for `firm_staff` (when present, it scopes the
                   session to a single client).

Claim names are configurable via `oidc_claim_*` settings so the same code
works against directories that use different custom-claim names.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient

from app.api.auth import AuthIdentity
from app.core.config import Settings, get_settings
from app.db.tenant import AccessScope


class InvalidTokenError(Exception):
    """Raised for ANY token validation failure. Caller maps to 401.

    Intentionally a single exception type — we do not want to leak whether
    the failure was 'bad signature' vs 'expired' vs 'wrong audience' to the
    network, beyond what a generic 401 conveys.
    """


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    """*Authentication* result: who the caller is, before any authorization.

    Deliberately carries no firm/client/scope. When
    `Settings.app_authz_source == 'membership'` those are resolved from our own
    tables (`app.domain.identity_resolution`) rather than trusted from claims.
    """

    subject: str
    email: str | None = None


# --------------------------------------------------------------------------- #
# Provider interface
# --------------------------------------------------------------------------- #
class IdentityProvider(ABC):
    @abstractmethod
    def decode(self, *, token: str) -> dict[str, Any]:
        """Return verified claims, or raise `InvalidTokenError`.

        Implementations must fully verify signature, issuer, audience and
        expiry before returning. Callers may trust the result.
        """

    def validate(self, *, token: str) -> AuthIdentity:
        """Claims-derived identity. Used when authz comes from the token."""
        return _claims_to_identity(self.decode(token=token), get_settings())

    def validate_principal(self, *, token: str) -> AuthPrincipal:
        """Identity only. Used when authz comes from membership rows."""
        claims = self.decode(token=token)
        sub = claims.get("sub")
        if not sub:
            raise InvalidTokenError("missing sub claim")
        email = claims.get("email") or claims.get("preferred_username")
        return AuthPrincipal(
            subject=str(sub), email=str(email) if email else None
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _claims_to_identity(claims: dict[str, Any], settings: Settings) -> AuthIdentity:
    """Map a validated claims dict to an `AuthIdentity`.

    Validates that role + firm_id + client_id are present and consistent. ANY
    inconsistency raises `InvalidTokenError`: the token might be technically
    valid but logically unusable, and we fail closed.
    """
    sub = claims.get("sub")
    if not sub:
        raise InvalidTokenError("missing sub claim")

    roles = claims.get(settings.oidc_claim_roles) or []
    if isinstance(roles, str):
        roles = [roles]
    if not isinstance(roles, list):
        raise InvalidTokenError("roles claim must be a list")

    if settings.oidc_role_firm in roles:
        scope = AccessScope.FIRM
    elif settings.oidc_role_client in roles:
        scope = AccessScope.CLIENT
    else:
        raise InvalidTokenError(
            "no recognised role; expected one of "
            f"[{settings.oidc_role_firm!r}, {settings.oidc_role_client!r}]"
        )

    firm_raw = claims.get(settings.oidc_claim_firm_id)
    if not firm_raw:
        raise InvalidTokenError("missing firm_id claim")
    try:
        firm_id = UUID(str(firm_raw))
    except ValueError as e:
        raise InvalidTokenError(f"firm_id is not a UUID: {e}") from e

    client_raw = claims.get(settings.oidc_claim_client_id)
    client_id: UUID | None = None
    if client_raw:
        try:
            client_id = UUID(str(client_raw))
        except ValueError as e:
            raise InvalidTokenError(f"client_id is not a UUID: {e}") from e

    if scope is AccessScope.CLIENT and client_id is None:
        raise InvalidTokenError("client_portal role requires client_id claim")

    return AuthIdentity(
        subject=str(sub),
        firm_id=firm_id,
        scope=scope,
        client_id=client_id,
    )


# --------------------------------------------------------------------------- #
# JWKS-backed RS256 validation (Entra ID, generic OIDC)
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class _JwksCache:
    client: PyJWKClient
    fetched_at: float


class JwtIdentityProvider(IdentityProvider):
    """RS256 / RS384 / RS512 JWT validation against a JWKS endpoint.

    Verifies (in this order):
      1. Header `alg` is in the expected RS-family allowlist.
      2. Signature against the JWKS key whose `kid` matches the header.
      3. `exp` not in the past, `nbf`/`iat` sanity (standard PyJWT checks).
      4. `iss` matches the configured issuer.
      5. `aud` matches the configured audience.
      6. Claims map cleanly to an `AuthIdentity`.

    Failure at any step raises `InvalidTokenError`.
    """

    _ALLOWED_ALGS = ("RS256", "RS384", "RS512")

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        for required in ("oidc_issuer", "oidc_audience", "oidc_jwks_url"):
            if not getattr(self._settings, required):
                raise RuntimeError(
                    f"app_auth_mode='jwt' requires {required}; not configured"
                )
        self._jwks: _JwksCache | None = None

    def _jwks_client(self) -> PyJWKClient:
        now = time.monotonic()
        ttl = self._settings.oidc_jwks_cache_seconds
        if self._jwks is None or (now - self._jwks.fetched_at) > ttl:
            assert self._settings.oidc_jwks_url is not None
            self._jwks = _JwksCache(
                client=PyJWKClient(self._settings.oidc_jwks_url, cache_keys=True),
                fetched_at=now,
            )
        return self._jwks.client

    def decode(self, *, token: str) -> dict[str, Any]:
        settings = self._settings
        try:
            signing_key = self._jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=list(self._ALLOWED_ALGS),
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except jwt.PyJWTError as e:
            raise InvalidTokenError(f"jwt validation failed: {type(e).__name__}") from e
        except Exception as e:  # JWKS fetch / network problems
            raise InvalidTokenError(f"jwt validation failed: {type(e).__name__}") from e
        return claims


# --------------------------------------------------------------------------- #
# HS256 test provider — tests + local dev only.
# --------------------------------------------------------------------------- #
class TestTokenIdentityProvider(IdentityProvider):
    """HS256 validation using a shared secret. Used by tests and local dev.

    Refuses to be used in `app_env='prod'`.
    """

    __test__ = False  # tell pytest this is not a test class

    _ALG = "HS256"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if self._settings.app_env == "prod":
            raise RuntimeError(
                "TestTokenIdentityProvider must not be used in production "
                "(app_env='prod' with app_auth_mode='test' is forbidden)"
            )

    def decode(self, *, token: str) -> dict[str, Any]:
        settings = self._settings
        try:
            claims = jwt.decode(
                token,
                settings.app_test_jwt_secret,
                algorithms=[self._ALG],
                audience=settings.app_test_jwt_audience,
                issuer=settings.app_test_jwt_issuer,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except jwt.PyJWTError as e:
            raise InvalidTokenError(f"jwt validation failed: {type(e).__name__}") from e
        return claims


# --------------------------------------------------------------------------- #
# Test helper: mint HS256 tokens. Lives in app code (not tests/) so it can be
# imported from API e2e tests without circular imports. NOT usable in prod
# because the secret is only set in non-prod envs.
# --------------------------------------------------------------------------- #
def mint_test_token(
    *,
    sub: str,
    firm_id: UUID,
    role: str,
    client_id: UUID | None = None,
    expires_in: int = 3600,
    issuer: str | None = None,
    audience: str | None = None,
    secret: str | None = None,
    extra_claims: dict[str, Any] | None = None,
    not_before: int | None = None,
    issued_at: int | None = None,
) -> str:
    """Mint an HS256 token suitable for `TestTokenIdentityProvider`.

    `expires_in` is seconds from now; pass a negative value to mint an
    already-expired token for tests.
    """
    settings = get_settings()
    now = int(time.time())
    iat = issued_at if issued_at is not None else now
    payload: dict[str, Any] = {
        "sub": sub,
        "iat": iat,
        "nbf": not_before if not_before is not None else iat,
        "exp": now + expires_in,
        "iss": issuer if issuer is not None else settings.app_test_jwt_issuer,
        "aud": audience if audience is not None else settings.app_test_jwt_audience,
        settings.oidc_claim_roles: [role],
        settings.oidc_claim_firm_id: str(firm_id),
    }
    if client_id is not None:
        payload[settings.oidc_claim_client_id] = str(client_id)
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        secret if secret is not None else settings.app_test_jwt_secret,
        algorithm="HS256",
    )


# --------------------------------------------------------------------------- #
# Process-wide selection
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def get_identity_provider() -> IdentityProvider:
    settings = get_settings()
    if settings.app_auth_mode == "jwt":
        return JwtIdentityProvider(settings)
    return TestTokenIdentityProvider(settings)


def reset_identity_provider() -> None:
    """Test helper: drop the cached provider so a new one is built next call."""
    get_identity_provider.cache_clear()


__all__ = [
    "IdentityProvider",
    "InvalidTokenError",
    "JwtIdentityProvider",
    "TestTokenIdentityProvider",
    "get_identity_provider",
    "mint_test_token",
    "reset_identity_provider",
]
