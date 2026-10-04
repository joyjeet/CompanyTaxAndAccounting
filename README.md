# CTAA — Foundation

AI-assisted financial statement and tax preparation platform for a CPA firm
serving multiple client businesses. **This commit delivers the foundation
only**: the deterministic accounting engine, the multi-tenant data model, and
PostgreSQL Row-Level Security (RLS) for tenant isolation. AI / OCR / UI layers
are explicitly NOT in this phase.

## Core principle

> AI reads and classifies; deterministic CODE does all accounting math.

Every figure on every statement traces back to `journal_line` rows through
code in `app/domain`. The LLM and OCR layers will sit *outside* this engine
and propose drafts — they cannot post.

## Layout

```
app/
  api/           FastAPI app, auth stub, tenant-scoped session dependency
  core/          config (env-only), logging
  db/            engine, session, RLS context manager
  domain/        deterministic services: ledger, statements, reconciliation, audit
  models/        SQLAlchemy ORM
  workers/       Redis-backed JobQueue stub (no real jobs yet)
  integrations/  STUB interfaces for OCR / LLM / blob storage
migrations/      Alembic; the initial revision creates schema + RLS policies
tests/
  unit/          invariants, statement math, reconciliation
  isolation/     CRITICAL: cross-tenant negative tests (RLS contract)
docker/          Dockerfile + initdb (creates owner + app DB roles)
```

## Tenant isolation model

Production target is **one database per firm**. Within a firm, RLS provides
client-to-client isolation. The schema is keyed on both `firm_id` and
`client_id`, so a firm's tenant can be sharded out to its own DB later
without code changes.

Every tenant-scoped table has:

* `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`
* one isolation policy `p_isolation` with both `USING` and `WITH CHECK`
* a predicate that reads three transaction-local GUCs:
  * `app.current_firm`
  * `app.current_client`
  * `app.access_scope` — `'firm'` (CPA staff sees all clients in firm) or
    `'client'` (portal user sees only own client)

The GUCs are read with `current_setting(..., true)` so a missing setting
becomes `NULL`, the predicate evaluates false, and the query returns zero
rows / refuses the insert. **Fail closed by construction.**

The runtime app role (`app_user`) is explicitly `NOSUPERUSER NOBYPASSRLS`.
Migrations run as a separate `ctaa_owner` role.

The FastAPI dependency in [`app/api/deps.py`](app/api/deps.py) opens a
transaction and issues `SET LOCAL` for each GUC, derived ONLY from the
authenticated identity (a stub for now — real OIDC arrives later). Because
`SET LOCAL` is transaction-scoped, the GUC values are dropped when the
connection returns to the pool — no cross-request leakage. There is an
explicit test for this in [`tests/isolation/test_rls_isolation.py`](tests/isolation/test_rls_isolation.py).

## Deterministic accounting engine

[`app/domain/ledger.py`](app/domain/ledger.py)
: `LedgerService.post(...)` validates `SUM(debits) == SUM(credits)` before
emitting any SQL, then re-aggregates from the DB after flush as a belt-and-
suspenders check. Negative amounts and lines with both sides set are
rejected; the DB also has CHECK constraints as a third defense layer.

[`app/domain/statements.py`](app/domain/statements.py)
: P&L, Balance Sheet, and Cash Flow generators. Each is a pure aggregation
of `journal_line` over an `accounting_period`. The Balance Sheet asserts
`assets == liabilities + equity (incl. retained earnings)` and raises if
the books don't balance.

[`app/domain/reconciliation.py`](app/domain/reconciliation.py)
: `reconcile_account(...)` compares the ledger balance against a provided
statement balance and persists a `reconciliation` row.

[`app/domain/audit.py`](app/domain/audit.py)
: All state changes call `write_audit(...)` which appends an immutable
`audit_event` row.

## Quickstart

```bash
cp .env.example .env
make up                 # start postgres + redis + app
make migrate            # apply alembic migrations (runs as owner role)
make test               # full suite (in Docker)
make test-db            # one-time: create the disposable ctaa_test database
make test-local         # full suite on the host against ctaa_test
make test-isolation     # ONLY the cross-tenant negative tests
```

The API is at `http://localhost:8000`; OpenAPI at `/docs`. **Authentication
is real**: every protected route requires a `Authorization: Bearer <jwt>`
header. In `APP_AUTH_MODE=test` the token is HS256-signed with
`APP_TEST_JWT_SECRET` (helper: `app.security.auth.mint_test_token`). In
`APP_AUTH_MODE=jwt` the token is validated against the configured OIDC JWKS
(Entra ID), with `iss`, `aud`, `exp`, and signature checked. Failure returns
`401`; there is no anonymous mode.

## Authentication and encryption (Phase 3)

* **JWT validation** — `app/security/auth.py` exposes `IdentityProvider` with
  `JwtIdentityProvider` (production, JWKS-backed RS256) and
  `TestTokenIdentityProvider` (HS256). `app/api/auth.py` extracts the bearer
  token and calls the active provider. Tenant context (`firm_id`, `client_id`,
  `scope`) is derived ONLY from validated claims.
* **Envelope encryption** — `app/security/envelope.py` implements AES-256-GCM
  body encryption with a fresh per-item DEK that is wrapped by a per-firm KEK.
  `firm_id` is bound into the AAD, so a wrapped DEK from firm A cannot decrypt
  a ciphertext authored against firm B.
* **Per-tenant KEK** — `app/integrations/keys.py`. `LocalKeyProvider`
  derives a per-firm KEK from a master secret with HKDF-SHA256 and wraps DEKs
  with AES Key Wrap (RFC 3394). `AzureKeyVaultKeyProvider` uses a per-firm RSA
  key in Azure Key Vault. Both implement `destroy_tenant_keys(firm_id)` —
  **crypto-shred**: destroying the KEK renders all of that tenant's
  ciphertext unrecoverable.
* **Encrypted blob storage** — `app/security/encrypted_storage.py` wraps any
  `StorageService` and transparently encrypts blobs at rest. Migration
  `0004_tenant_encryption_keys` adds the admin-only `tenant_encryption_key`
  registry that records destroyed firms; `unwrap_data_key` checks this on
  every call.

### Required environment for production

```
APP_AUTH_MODE=jwt
OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
OIDC_AUDIENCE=<app-registration-client-id-or-app-uri>
OIDC_JWKS_URL=https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys
OIDC_CLAIM_FIRM_ID=firm_id            # custom claim
OIDC_CLAIM_CLIENT_ID=client_id        # custom claim
OIDC_ROLE_FIRM=firm_staff             # value in 'roles' claim
OIDC_ROLE_CLIENT=client_portal

APP_KEK_PROVIDER=keyvault
AZURE_KEYVAULT_URL=https://<vault>.vault.azure.net/
AZURE_KEYVAULT_KEY_NAME_TEMPLATE=ctaa-firm-{firm_id}
```

Use a User-Assigned Managed Identity for the Key Vault credential — never put
secrets in env. The `app_user` DB role remains non-superuser /
non-`BYPASSRLS`, and the `tenant_encryption_key` table is admin-only (revoked
from `app_user*`).

### Claim-mapping assumption (CONFIRM AGAINST DIRECTORY)

The current implementation assumes Entra ID issues:
* a `roles` claim (string array) containing exactly one of
  `firm_staff` (→ `AccessScope.FIRM`) or `client_portal` (→ `AccessScope.CLIENT`),
* a `firm_id` claim (UUID string) for both roles,
* a `client_id` claim (UUID string) — required for `client_portal`, optional
  for `firm_staff` (when present, scopes the firm-staff session to a single
  client).

If your App Registration uses different custom-claim names or different role
values, override `OIDC_CLAIM_*` and `OIDC_ROLE_*` in env. Confirm against the
real directory before going to prod.

## Frontend (Phase 4)

A React + TypeScript SPA lives under [frontend/](frontend/). Two surfaces:

* **Reviewer dashboard** (`firm_staff` role) — pending-draft queue, draft
  detail with the AI's classification payload, promote-to-journal-entry form
  (every line is debit-or-credit; the backend enforces the balance), and
  reject.
* **Client portal** (`client_portal` role) — upload a document, see your
  uploads with their OCR status, and a read-only view of the AI drafts the
  firm will review.

The auth layer sits behind an `AuthClient` interface with two
implementations:

* `MsalAuthClient` — Entra ID auth-code/PKCE via `@azure/msal-browser`.
* `DevAuthClient` — calls the backend's dev-only `POST /auth/dev-token` to
  mint a test JWT. The endpoint is mounted ONLY when `APP_AUTH_MODE=test`
  AND `APP_ENV != prod`; it cannot be enabled in production.

Quickstart:

```bash
make frontend-install   # one-time
make frontend-dev       # Vite at http://localhost:5173, proxies /api -> :8000
make frontend-build     # production build to frontend/dist/
make frontend-test      # vitest suite
```

The backend's CORS allow-list is `APP_CORS_ORIGINS` (comma-separated). Default
is `http://localhost:5173`; in prod set this to the deployed SPA URL only.

### MSAL configuration (for production deploys)

Set on the frontend (`frontend/.env`):

```
VITE_AUTH_MODE=msal
VITE_MSAL_CLIENT_ID=<spa app registration client id>
VITE_MSAL_AUTHORITY=https://login.microsoftonline.com/<tenant id>
VITE_MSAL_API_SCOPE=api://<api app id>/access
VITE_MSAL_REDIRECT_URI=https://<deployed-spa-host>
VITE_API_BASE=https://<api-host>
```

The `VITE_MSAL_API_SCOPE` MUST be the API's app-id-uri scope (an
access-token scope), not the SPA's own client id. If you request the SPA's
own scope you'll get an id-token back and the backend's RS256 validator
will reject it.

## What is NOT built (next phases)

* OCR / document extraction (Azure AI Document Intelligence)
* LLM classification (Azure OpenAI)
* Tax-document classification and form mapping

## Flagged design decisions / assumptions

1. **Single DB now, per-firm DB later.** Schema preserves `firm_id` so
   per-firm shard-out is mechanical.
2. **`FORCE` RLS on all tenant tables** — even the schema owner is subject
   to RLS at runtime. Test fixtures honor this by setting tenant context
   before seeding data through the runtime role.
3. **Authentication.** Real JWT validation against an OIDC JWKS (Entra ID)
   in `APP_AUTH_MODE=jwt`; HS256 with a shared secret in `APP_AUTH_MODE=test`.
   Tenant context derives ONLY from validated claims. See the
   *Authentication and encryption* section above and the claim-mapping
   assumption block.
4. **Audit append-only by convention.** I did not yet `REVOKE UPDATE,
   DELETE` on `audit_event` from `app_user`; this is a hardening follow-up.
5. **Money** is `Numeric(20, 4)` / Python `Decimal` end to end. No floats.
6. **Cash Flow statement** currently returns the change-in-cash core
   (opening, closing, in/out, net change). The operating/investing/
   financing breakdown is a follow-up that depends on classification rules
   we'll define alongside the AI layer.
