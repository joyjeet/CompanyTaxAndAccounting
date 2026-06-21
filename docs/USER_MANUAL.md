# CTAA — Tester / QA User Manual

This manual covers **how to spin up the app and click through it as a tester**.
It is written for someone with access to the repository and a Mac/Linux box.
No knowledge of the codebase internals is assumed.

> **Status note.** As of this writing the platform has the **full
> Fluent UI v9** front-end wired against every backend endpoint — Dashboard,
> Clients, Periods, Chart of Accounts, Documents, Journal Entries, Statements
> (P&L / Balance Sheet / Cash Flow), Tax (Forms, Mappings, Worksheets),
> Artifacts, Review Queue, and a separate Client Portal with its own
> Dashboard / My Documents / My Reports. The deterministic accounting engine,
> multi-tenant data model, RLS isolation, dev/test auth, and 170+ automated
> tests are all green. **What is still mocked out in dev:** OCR ingestion
> uses a fake extractor, LLM draft classification uses a mock classifier,
> Entra ID is wired in code but the dev login path mints HS256 tokens via
> `POST /auth/dev-token`. PDF artifacts are real; e-sign is not.

---

## TL;DR — Test the UI locally in five commands

```bash
git clone <repo-url> CompanyTaxAndAccounting
cd CompanyTaxAndAccounting
cp .env.example .env
cp frontend/.env.example frontend/.env

make up                # Postgres + Redis + API   (http://localhost:8000)
make migrate           # apply DB schema + RLS policies
make seed-demo         # creates one firm + one client; prints the IDs
make frontend-install
make frontend-dev      # Vite dev server          (http://localhost:5173)
```

Paste the `firm_id` (and `client_id` if you pick `client_portal`) from
`make seed-demo` into the **Dev sign-in** form at
`http://localhost:5173/login` — or, easier, put them in `frontend/.env` as
`VITE_DEV_DEFAULT_FIRM_ID` / `VITE_DEV_DEFAULT_CLIENT_ID` so the form is
pre-populated. Click **Sign in** and you are in.

---

## 1. Where do I log in?

| Environment | UI URL | API URL | Notes |
|---|---|---|---|
| **Local dev** (recommended for QA) | `http://localhost:5173` | `http://localhost:8000` | Dev login form. Use this for end-to-end testing. |
| **Azure dev deployment** | _redeploying_ | _redeploying_ | The previous `rg-ctax-dev-cus` smoke deployment is being torn down and replaced with a full UI+DB stack. See `docs/deployment-runbook.md`. |

---

## 2. Prerequisites

* macOS or Linux with **Docker** and **Docker Compose v2**.
* **Node.js 20+** and **npm** for the Vite dev server.
* Ports `5173` (UI), `8000` (API), `5432` (Postgres), `6379` (Redis) free.

```bash
docker --version && docker compose version && node --version && npm --version
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
`VITE_AUTH_MODE=dev`.

---

## 4. Start the backend stack

```bash
make up         # builds API image, starts db + redis + app
make migrate    # creates schema, RLS policies, owner + app DB roles
```

Sanity-check the API:

```bash
curl http://localhost:8000/livez     # -> {"status":"alive"}
curl http://localhost:8000/healthz   # -> {"status":"ok"}
curl http://localhost:8000/readyz    # -> {"status":"ready","checks":{"db":"ok"}}
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
```

**Copy `firm_id` and `client_id`.** Either:

1. Paste them into the **Dev sign-in** form every time, **or**
2. Add to `frontend/.env` so the form is pre-filled:

   ```
   VITE_DEV_DEFAULT_FIRM_ID=<firm_id from seed-demo>
   VITE_DEV_DEFAULT_CLIENT_ID=<client_id from seed-demo>
   ```

   Restart `make frontend-dev` to pick them up.

To wipe everything and re-seed:

```bash
make down && make up && make migrate && make seed-demo
```

---

## 6. Start the frontend

In a new terminal tab:

```bash
make frontend-install      # once per checkout
make frontend-dev          # leave running
```

```
  VITE v5.x  ready in 612 ms
  ➜  Local:   http://localhost:5173/
```

Open **http://localhost:5173**.

---

## 7. Log in (dev mode)

You land on **Dev sign-in**. Fill in:

| Field | Value |
|---|---|
| **Subject** | any string, e.g. `qa-alice@example.com`. Recorded in audit logs. |
| **Role** | `firm_staff` for the firm reviewer experience; `client_portal` for the customer portal experience. |
| **Firm ID** | UUID from `make seed-demo`. Pre-filled if you set `VITE_DEV_DEFAULT_FIRM_ID`. |
| **Client ID** | required only when Role = `client_portal`. Pre-filled if you set `VITE_DEV_DEFAULT_CLIENT_ID`. |

Click **Sign in**. You land on:

* `/` (**Dashboard**) when Role = `firm_staff`.
* `/portal` (**Client Portal Home**) when Role = `client_portal`.

To switch personas: click **Sign out** in the top bar.

---

## 8. The Firm Staff app (Role = `firm_staff`)

The left rail has five sections. Walk through them in order:

### 8.1 Dashboard (`/`)

Four KPI cards (Clients, Pending drafts, Documents, Artifacts) plus four
list cards (Your clients, Recent documents, Pending drafts, Latest
artifacts). All counts and rows are scoped to your firm by RLS.

### 8.2 Clients (`/clients`)

Table of every client in your firm. Click **+ New client** to create one
(only firm-scope users can; portal users get 403). Click any client name to
open its detail page.

### 8.3 Client Detail (`/clients/{id}`) — eight tabs

| Tab | What to test |
|---|---|
| **Overview** | 4 stat cards (periods, accounts, documents, artifacts) + the most recent period. Confirm numbers match what you seed. |
| **Periods** | Lists accounting periods. **+ New period** creates one (start ≤ end is enforced — try inverted dates → 400). A locked period blocks new journal entries. |
| **Chart of accounts** | Lists all accounts ordered by code. **+ New account** lets you pick type (asset/liability/equity/revenue/expense) and normal balance (debit/credit). |
| **Documents** | Drag/drop or pick a source document. Backend currently uses a mock OCR/classifier, so uploads complete instantly. Document kind badges show classifier output. |
| **Journal entries** | Filter by period. **+ Post entry** opens a line editor that totals debits/credits live. **The Post button stays disabled until books balance.** Try an unbalanced entry → button disabled; force one in Swagger → 400. Posting to a locked period → 409. |
| **Statements** | Pick a period, then tab between **Profit & loss**, **Balance sheet**, and **Cash flow**. Numbers are computed live by `StatementsService`. **Generate PDF artifact** creates a finalizable encrypted artifact in the Artifacts tab. |
| **Tax** | Sub-tabs: **Forms** (read-only catalog), **Mappings** (account → tax line proposals; approve/reject), **Worksheets** (generate from approved mappings, then approve). |
| **Artifacts** | Per-client list of generated artifacts (statements, worksheets, audit packages). **Finalize** locks the artifact; **Download** streams the encrypted bytes. |

### 8.4 Review queue (`/review`)

Lists all pending `draft_classification` rows across the firm. Click one to
open `/drafts/{id}` where you can pick a client + period + accounts and
**Promote** to a posted journal entry, or **Reject** with a reason. (Drafts
only appear after the ingest pipeline runs — see `make seed-drafts` if
available, or POST to `/documents` then trigger the classifier.)

### 8.5 Artifacts (`/artifacts`)

Firm-wide artifact library. Filter by kind (P&L, BS, CF, tax worksheet,
audit package). Finalize / Download work identically to the per-client tab.

### 8.6 Tax forms (`/tax/forms`)

Read-only catalog of every tax form registered in `tax_form` /
`tax_form_line`. Used as the source of truth for mappings.

---

## 9. The Client Portal (Role = `client_portal`)

A separate three-page experience for end-customer users:

| Page | Path | What to test |
|---|---|---|
| **Overview** | `/portal` | KPI cards (documents, artifacts, period status) + recent activity. Confirm you see only your own client's data. |
| **My documents** | `/portal/documents` | Drag-drop or pick. Upload completes instantly via mock OCR. The table shows kind + status badges. |
| **My reports** | `/portal/reports` | Lists only **finalized** artifacts for your client. Download streams the encrypted bytes. |

Try cross-tenant: paste another client's UUID into a portal URL (e.g.
`/portal/documents?client_id=<other>`) — the API still RLS-filters and you
get no rows.

---

## 10. What to look for / acceptance criteria

The properties to focus QA on:

1. **Tenant isolation (RLS).** A `firm_staff` token for Firm A can never see
   any row belonging to Firm B. Seed two firms (re-run `make seed-demo`
   noting both firm IDs) and confirm Firm A → 0 Firm B rows on every list.
2. **Portal scoping.** A `client_portal` token scoped to Client 1 sees only
   their own client.
3. **Books must balance.** Posting a journal entry where
   `SUM(debits) != SUM(credits)` returns 400 and produces no rows.
4. **Period lock.** Posting to a locked period returns 409.
5. **Statements balance.** On the Balance Sheet tab, `Total assets ==
   Total liabilities + Total equity` and the `balances` flag is `true`.
6. **Audit trail.** Every state change writes an `audit_event` row. Check
   with `make psql` → `SELECT count(*) FROM audit_event;` before and after.
7. **Health endpoints** stay green during normal operation:
   - `/livez` → 200 always (no deps).
   - `/healthz` → 200 always (no deps).
   - `/readyz` → 200 when DB reachable, 503 when DB unreachable.

---

## 11. Power-user: hit the API directly

Mint a token without the UI:

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

Then any endpoint:

```bash
TOKEN=eyJ...
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/clients
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/statements/profit-and-loss?client_id=<id>&period_id=<id>"
```

Full reference at `http://localhost:8000/docs` (Swagger UI).

---

## 12. Reset / teardown

```bash
make down       # stops containers and DROPS the local Postgres volume
```

Destructive — re-run `make migrate && make seed-demo` afterwards. To stop
without losing data:

```bash
docker compose stop
```

---

## 13. Reporting bugs

Please include:

* Output of `git rev-parse --short HEAD` (commit you tested).
* `firm_id` / `client_id` / role you were signed in as.
* The HTTP request that misbehaved (Swagger has a "Try it out" + copy curl
  button on every endpoint, or grab the request from the browser DevTools
  Network panel).
* The relevant slice of `docker compose logs app` around the time of the
  error — API logs are JSON-structured and include `firm_id`, `client_id`,
  `request_id` on every line.
