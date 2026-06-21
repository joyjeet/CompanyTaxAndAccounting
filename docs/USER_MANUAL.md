# CTAA — Tester / QA User Manual

This manual covers **how to spin up the app and log in to test it**. It is
written for someone who has access to the repository and a Mac/Linux machine
with Docker installed. It assumes no knowledge of the codebase internals.

> **Status note** — as of this writing the platform is in **early phase 7**.
> The deterministic accounting engine, multi-tenant data model, RLS isolation,
> backend API, dev/test auth, and a thin React UI are working. **Production
> features that are NOT in this build yet:** OCR ingestion, LLM-assisted
> draft classification, real PDF report generation, e-sign, real Entra ID
> integration (only the dev-token path is wired). Anything you exercise here
> is the foundation, not the finished product.

---

## TL;DR — Test the UI locally in five commands

```bash
git clone <repo-url> CompanyTaxAndAccounting
cd CompanyTaxAndAccounting
cp .env.example .env
cp frontend/.env.example frontend/.env

make up               # Postgres + Redis + API   (http://localhost:8000)
make migrate          # apply DB schema + RLS policies
make seed-demo        # creates one firm + one client; prints the IDs
make frontend-install
make frontend-dev     # Vite dev server          (http://localhost:5173)
```

Then open **http://localhost:5173** in your browser, paste the **firm_id**
(and **client_id**, only if you pick `client_portal`) printed by
`make seed-demo` into the dev login form, click **Sign in**, and you are
authenticated.

---

## 1. What URL do I log in to?

| Environment | UI URL | API URL | Notes |
|---|---|---|---|
| **Local dev** (recommended for QA today) | `http://localhost:5173` | `http://localhost:8000` | Dev login form. Use this for end-to-end testing. |
| **Azure smoke deployment** | _none deployed_ | `https://ca-ctax-dev-cus-api.grayisland-1d1659e2.centralus.azurecontainerapps.io` | API-only smoke. `GET /livez` and `GET /healthz` return 200. No UI, no DB wired, no login wired. For platform/IaC validation only. |

A full Azure deployment with the React UI, real DB wiring, and Entra ID login
is the next phase of work (Phase 7.5b). It is **not** in the current build.

---

## 2. Prerequisites

* macOS or Linux with **Docker** and **Docker Compose v2**.
* **Node.js 20+** and **npm** on the host (for the Vite dev server).
* Ports `5173` (UI), `8000` (API), `5432` (Postgres), `6379` (Redis) free.

Verify:

```bash
docker --version
docker compose version
node --version
npm --version
```

---

## 3. First-time setup

```bash
git clone <repo-url> CompanyTaxAndAccounting
cd CompanyTaxAndAccounting
cp .env.example .env
cp frontend/.env.example frontend/.env
```

The `.env` defaults are safe for local dev: `APP_AUTH_MODE=test` enables the
dev login form, no real secrets needed. The frontend `.env` defaults to
`VITE_AUTH_MODE=dev` which matches.

---

## 4. Start the backend stack

```bash
make up         # builds the API image, starts db + redis + app
make migrate    # creates schema, RLS policies, owner + app DB roles
```

Sanity-check the API is up:

```bash
curl http://localhost:8000/livez
# -> {"status":"alive"}
curl http://localhost:8000/healthz
# -> {"status":"ok"}
curl http://localhost:8000/readyz
# -> {"status":"ready","checks":{"db":"ok"}}      # 200 once migrations done
```

OpenAPI / Swagger explorer:

```
http://localhost:8000/docs
```

---

## 5. Seed a demo firm and client

```bash
make seed-demo
```

Sample output:

```
Seeded demo data.
  firm_id   = 4f1a2c8d-...-9b
  client_id = c3e6f0aa-...-1f
  period_id = 8a2bd91e-...-44

Use these in the frontend dev login form:
  Firm ID:   4f1a2c8d-...-9b
  Client ID: c3e6f0aa-...-1f  (only required for role=client_portal)
```

**Copy these UUIDs.** You will paste them into the login form in step 7.

To wipe everything and re-seed, run:

```bash
make down       # destroys containers + volumes (DB data gone)
make up
make migrate
make seed-demo
```

---

## 6. Start the frontend

In a new terminal tab:

```bash
make frontend-install      # once per checkout
make frontend-dev          # leave running
```

Vite will print:

```
  VITE v5.x  ready in 612 ms
  ➜  Local:   http://localhost:5173/
```

Open **http://localhost:5173** in your browser.

The Vite dev server proxies `/api/*` to `http://localhost:8000`, so you do
not need to configure CORS or change any base URL.

---

## 7. Log in (dev mode)

You will land on the **Dev sign-in** screen. Fill in:

| Field | What to type |
|---|---|
| **Subject** | any string, e.g. `qa-alice@example.com`. This is the user's identity for audit logs. |
| **Role** | `firm_staff` for the firm reviewer experience, `client_portal` for the customer portal experience. |
| **Firm ID** | the UUID printed by `make seed-demo`. |
| **Client ID** | only needed if Role = `client_portal`. Paste the UUID from `make seed-demo`. |

Click **Sign in**. You should land on:

* `/review` (Review Queue) when role = **firm_staff**
* `/portal` (Client Portal) when role = **client_portal**

If you want to switch personas, click **Sign out** on the top bar and fill
the form again with the other role.

---

## 8. What you can do once logged in

The UI is thin in this build. Functional paths:

### As `firm_staff`

* **Review Queue** at `/review` — lists draft classifications waiting for
  review. Empty after a fresh seed (no drafts yet — see "creating drafts"
  below).
* **Draft Detail** at `/drafts/<id>` — approve / reject a single draft
  classification.

### As `client_portal`

* **Client Portal** at `/portal` — currently scoped read-only views of the
  signed-in client's own data. RLS guarantees they cannot see anything from
  another client or firm.

### Things you must do via API / Swagger, not the UI (yet)

* List clients in the firm: `GET /clients` (firm_staff token only).
* Upload a source document, draft a journal entry, post to the ledger,
  generate a P&L / Balance Sheet — all live under `/docs` with examples.
  Use the Bearer token shown in the browser's `localStorage` (key
  `ctaa.auth.token`) or mint a fresh one with `POST /auth/dev-token`.

To get an API token without the UI:

```bash
curl -X POST http://localhost:8000/auth/dev-token \
  -H "Content-Type: application/json" \
  -d '{
        "sub": "qa-alice@example.com",
        "role": "firm_staff",
        "firm_id": "<paste firm_id from seed-demo>"
      }'
# -> {"access_token":"eyJ...","token_type":"Bearer","expires_in":3600}
```

Then:

```bash
TOKEN=eyJ...
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/clients
```

---

## 9. What to look for / acceptance criteria

The properties the build is supposed to enforce — these are what to focus QA on:

1. **Tenant isolation (RLS).** A `firm_staff` token for Firm A can never see
   any row belonging to Firm B. Seed two firms (run `make seed-demo` twice,
   note both firm IDs) and confirm a token for firm A returns 0 firm-B rows
   from any list endpoint.
2. **Portal scoping.** A `client_portal` token scoped to Client 1 sees only
   their own client, never the firm's other clients.
3. **Books must balance.** Posting a journal entry where
   `SUM(debits) != SUM(credits)` must be rejected with a 400-class error.
4. **Audit trail.** Every state change should produce an `audit_event` row.
   Verify with `make psql` and `SELECT count(*) FROM audit_event;`.
5. **Health endpoints** stay green during normal operation:
   - `/livez` → 200 always (no deps).
   - `/healthz` → 200 always (no deps).
   - `/readyz` → 200 when DB reachable, 503 when DB unreachable.

---

## 10. Reset / teardown

```bash
make down       # stops containers and DROPS the local Postgres volume
```

That is destructive — you will lose all seeded data and need to re-run
`make migrate && make seed-demo`. To stop without losing data:

```bash
docker compose stop
```

---

## 11. Reporting bugs

Please include:

* Output of `git rev-parse --short HEAD` (which commit you tested).
* The `firm_id` / `client_id` / role you were signed in as.
* The HTTP request that misbehaved (Swagger has a "Try it out" + copy
  curl button on every endpoint).
* The relevant slice of `docker compose logs app` around the time of the
  error — the API logs are JSON-structured and include `firm_id`,
  `client_id`, `request_id` on every line.

---

## 12. Azure deployment URL (for IaC validation only)

The thin smoke deployment is up at:

```
https://ca-ctax-dev-cus-api.grayisland-1d1659e2.centralus.azurecontainerapps.io
```

Only `/livez` and `/healthz` are useful there. `/readyz` will return 503 by
design — the DB is intentionally un-wired in the cost-thin profile. This URL
exists to prove the IaC stack stands up cleanly, **not** to log in or
exercise features. Use the local stack (sections 3–10) for everything else.
