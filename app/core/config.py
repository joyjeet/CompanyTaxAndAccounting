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
    # Object storage (uploaded source documents + generated artifacts)
    # ------------------------------------------------------------------ #
    # 'local'      : LocalFilesystemStorage rooted at ./data/blob/.
    #                Suitable for tests/local dev ONLY — bytes do not survive
    #                a container restart.
    # 'azure_blob' : AzureBlobStorage backed by a private Storage Account
    #                container. AAD auth via DefaultAzureCredential (Managed
    #                Identity in Azure, az login locally). Per-tenant prefix
    #                isolation is enforced by tenant_path() + _check_prefix()
    #                exactly as in the local backend.
    app_storage_backend: Literal["local", "azure_blob"] = "local"
    # Base URL of the Storage Account, e.g. https://ctaxdemodocs.blob.core.windows.net
    azure_storage_account_url: str | None = None
    # Container name. Created out-of-band by infra (not by the app).
    azure_storage_container: str = "documents"

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

    # 'redis'  : RedisJobQueue against `redis_url`. Use in production where a
    #            durable worker process consumes the stream.
    # 'memory' : InMemoryJobQueue. Suitable for demo/test deployments that
    #            don't yet run a separate worker — uploads still succeed and
    #            the job is recorded in-process, but no extraction runs until
    #            you add a worker. Pairs with `app_storage_backend=azure_blob`.
    app_queue_backend: Literal["redis", "memory"] = "redis"

    # ------------------------------------------------------------------ #
    # Frontend / CORS
    # ------------------------------------------------------------------ #
    # Comma-separated list of allowed CORS origins. The Vite dev server
    # defaults to :5173. In prod, set this to the deployed frontend URL only.
    app_cors_origins: str = "http://localhost:5173"

    # ------------------------------------------------------------------ #
    # AI integrations (Azure OpenAI, Document Intelligence)
    # ------------------------------------------------------------------ #
    # Categorizer backend used by the bank-statement pipeline to map
    # transactions onto the client's chart of accounts.
    #   'dictionary'  : deterministic vendor-keyword dict only (default;
    #                   no network calls). Suitable for tests and demos
    #                   that don't want Azure OpenAI dependencies.
    #   'azure_openai': re-categorize weak rows with Azure OpenAI Chat
    #                   Completions, using the client's actual COA. The
    #                   dictionary still runs first; the LLM only sees
    #                   rows that landed on 9999 (Suspense) etc.
    app_categorizer_backend: Literal["dictionary", "azure_openai"] = "dictionary"
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-08-01-preview"
    azure_openai_deployment: str = "gpt-4o-mini"

    # Document extraction backend used by /documents upload + classify.
    #   'mock'                       : MockDocumentExtractor (pypdf-based;
    #                                  no network). Default — keeps tests
    #                                  and demos self-contained.
    #   'azure_document_intelligence': real Azure AI Document Intelligence.
    #                                  Routes by kind_hint to prebuilt
    #                                  models (bank-statement.us, tax.us.W2,
    #                                  tax.us.1099*, invoice, receipt) for
    #                                  high-fidelity structured output.
    app_extractor_backend: Literal[
        "mock", "azure_document_intelligence"
    ] = "mock"
    azure_document_intelligence_endpoint: str | None = None
    # When supplied, auth uses AzureKeyCredential. When None, the extractor
    # falls back to DefaultAzureCredential (Managed Identity in Azure,
    # `az login` locally). Prefer Managed Identity in prod.
    azure_document_intelligence_api_key: str | None = None

    # ------------------------------------------------------------------ #
    # Output / Branding (Phase 6)
    # ------------------------------------------------------------------ #
    # Branding rendered on every PDF/XLSX header. The "firm" here is the
    # operating firm (MMFC LLC by default); per-client branding overrides
    # are intentionally NOT supported in v1 — every report carries the
    # operating firm's letterhead so the source of work is unambiguous.
    branding_firm_name: str = "MMFC LLC"
    branding_firm_tagline: str = "Certified Public Accountants"
    branding_firm_address: str = ""
    # Path to an optional logo image (PNG / JPG). Empty = no logo.
    branding_firm_logo_path: str = ""
    # ISO 4217 currency code displayed alongside money figures.
    branding_currency: str = "USD"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
