"""Environment-based configuration. No secrets in code; values come from env."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["local", "test", "staging", "prod"] = "local"
    app_log_level: str = "INFO"

    # ------------------------------------------------------------------ #
    # Authentication
    # ------------------------------------------------------------------ #
    # 'jwt'  : production. Validate Bearer JWT against an OIDC issuer (Entra ID).
    # 'test' : local/CI. Validate HS256 tokens signed by the test secret below.
    #          The application also accepts a small set of test-only tokens.
    app_auth_mode: Literal["jwt", "test"] = "test"

    # OIDC parameters (used when app_auth_mode == 'jwt'). For Entra ID these
    # come from the App Registration in the directory. NEVER commit secrets.
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_jwks_cache_seconds: int = 3600

    # Claim names. Defaults match the recommended custom-claim names in the
    # Entra ID App Registration. Override per environment if your directory
    # uses different names.
    oidc_claim_firm_id: str = "firm_id"
    oidc_claim_client_id: str = "client_id"
    oidc_claim_roles: str = "roles"  # array. e.g. ["firm_staff"] or ["client_portal"]

    # Role values used to bucket users into FIRM vs CLIENT scope. The list is
    # checked in order; the first match wins. CSV in env so ops can extend
    # without code changes.
    oidc_role_firm: str = "firm_staff"
    oidc_role_client: str = "client_portal"

    # Test-mode HS256 secret. Used for tests + local dev only. The app refuses
    # to start in app_env='prod' if app_auth_mode=='test'.
    app_test_jwt_secret: str = "test-only-do-not-use-in-prod-please-do-not"
    app_test_jwt_issuer: str = "ctaa-test"
    app_test_jwt_audience: str = "ctaa-api"

    # ------------------------------------------------------------------ #
    # Encryption / KEK
    # ------------------------------------------------------------------ #
    # 'local'    : per-firm KEK derived from a master secret + firm_id (HKDF).
    #              Suitable for tests and dev. Crypto-shred is implemented by
    #              recording the firm_id in a destroyed-keys table; unwrap
    #              refuses for destroyed firms.
    # 'keyvault' : per-firm KEK in Azure Key Vault. wrap/unwrap go through
    #              the Key Vault Crypto API; destroy issues delete-key.
    app_kek_provider: Literal["local", "keyvault"] = "local"

    # Master secret for `local` provider. Must be set in non-test environments.
    app_local_kek_master: str = "test-only-master-do-not-use-in-prod"

    # Azure Key Vault config (used when app_kek_provider == 'keyvault').
    azure_keyvault_url: str | None = None
    # Per-firm key naming template. {firm_id} is replaced.
    azure_keyvault_key_name_template: str = "ctaa-firm-{firm_id}"

    # ------------------------------------------------------------------ #
    # Database / Redis
    # ------------------------------------------------------------------ #
    database_url: str = Field(
        default="postgresql+psycopg://app_user:app_password@localhost:5432/ctaa",
    )
    database_owner_url: str = Field(
        default="postgresql+psycopg://ctaa_owner:owner_password@localhost:5432/ctaa",
    )
    redis_url: str = "redis://localhost:6379/0"

    # ------------------------------------------------------------------ #
    # Frontend / CORS
    # ------------------------------------------------------------------ #
    # Comma-separated list of allowed CORS origins. The Vite dev server
    # defaults to :5173. In prod, set this to the deployed frontend URL only.
    app_cors_origins: str = "http://localhost:5173"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
