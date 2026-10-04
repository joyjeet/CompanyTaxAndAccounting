# CTAA — Customer Demo Guide

Welcome, and thank you for taking the time to evaluate **CTAA — Company Tax
and Accounting**. This guide walks you through everything you need to log in
to the hosted demo, click through the product end-to-end, and tell us what
works and what doesn't.

You do **not** need to install anything. Everything runs in your browser.

---

## 1. Quick facts

| | |
|---|---|
| **Demo URL** | https://ca-ctax-demo-cus-ui.thankfulmushroom-8b2bd8cf.centralus.azurecontainerapps.io |
| **Available until** | **2026-06-22 03:58 UTC** (24 hours from deploy) |
| **Login** | Paste a UUID — no password required (see §3) |
| **Supported browsers** | Latest Chrome, Edge, Firefox, or Safari on desktop |
| **What's pre-loaded** | One firm, one client, one accounting period, a starter chart of accounts |
| **What's mocked** | OCR / document extraction (see §6.4) |

> **24-hour expiry.** The environment is automatically torn down at the
> time above to control cost. If you need more time, let us know and we
> will redeploy a fresh instance.

---

## 2. What CTAA does

CTAA is a multi-tenant tax and accounting platform built for small-to-mid
sized accounting firms and their clients. In this demo you can play two
roles:

* **Firm staff** — the accountant view. Create clients, set up accounting
  periods, build a chart of accounts, upload source documents, post journal
  entries, generate financial statements (P&L, Balance Sheet, Cash Flow),
  and prepare tax worksheets.
* **Client portal user** — the end-customer view. Upload your own source
  documents, see only your own data, and download finalized reports your
  accountant has shared with you.

You can switch between the two roles at any time using **Sign out** in the
top bar.

---

## 3. How to log in

1. Open the demo URL: **https://ca-ctax-demo-cus-ui.thankfulmushroom-8b2bd8cf.centralus.azurecontainerapps.io**
2. You land on the **Sign in** page.
3. Fill in the form:

   | Field | Value |
   |---|---|
   | **Subject** | Anything you like, e.g. `tester@example.com`. It is recorded in the audit log so we can trace your actions. |
   | **Role** | Pick **`firm_staff`** for your first session. |
   | **Firm ID** | The `firm_id` we sent you with your demo invite. |
   | **Client ID** | Leave blank for `firm_staff`. |

4. Click **Sign in**. You will land on the **Dashboard**.

To try the customer-facing portal later, sign out and sign back in with:

| Field | Value |
|---|---|
| **Role** | `client_portal` |
| **Firm ID** | The same `firm_id` as above. |
| **Client ID** | The `client_id` we sent you with your demo invite. |

> Each demo stack is rebuilt from scratch, so the firm and client IDs are new
> every time. Operators: the current values are in the deploy receipt at
> `results/azure-demo-<timestamp>/deploy.json`. Do not commit them here.

There is no password — this demo uses a short-lived test token so you can
get straight to clicking through the product.

---

## 4. The pre-loaded sample data

To save you time, the demo is seeded with:

* **One firm** (the accounting firm you are logged into).
* **One client** — your sample customer to work with.
* **One accounting period** — open, ready to receive journal entries.
* **A starter chart of accounts** — a handful of standard accounts
  (Cash, Accounts Receivable, Revenue, etc.) so you can post entries
  without setting them up from scratch.

You can freely add more clients, periods, accounts, documents, and journal
entries — the whole environment is yours for the next 24 hours.

---

## 5. Suggested tour (firm staff)

The left navigation rail is grouped into five sections. We recommend
walking through them in this order — it follows the natural workflow of
onboarding a client and producing their financials.

### 5.1 Dashboard

Four KPI tiles (Clients, Pending drafts, Documents, Artifacts) plus four
list tiles showing your clients, recent documents, pending drafts, and
latest generated reports. Everything here is scoped to your firm.

### 5.2 Clients

Lists every client in your firm. Click **+ New client** to add one — try
"Acme Coffee Co." or whatever you like. Click a client name to open their
detail page.

### 5.3 Client detail — eight tabs

This is the heart of the app. Each tab is a different aspect of one
client's books.

| Tab | What to try |
|---|---|
| **Overview** | Stat cards summarizing periods, accounts, documents, and artifacts. |
| **Periods** | Create a new accounting period (e.g. "FY2026", start `2026-01-01`, end `2026-12-31`). Inverted dates are rejected. Locking a period prevents further journal entries. |
| **Chart of accounts** | Add a new account. Pick its type (asset / liability / equity / revenue / expense) and normal balance (debit / credit). |
| **Documents** | Upload any file. See §6.4 for what the system does with it. |
| **Journal entries** | Click **+ Post entry**, pick a date, add at least two lines. The **Post** button only enables when total debits = total credits — try unbalancing it on purpose. Posting to a locked period is blocked. |
| **Statements** | Pick a period and switch between **Profit & Loss**, **Balance Sheet**, and **Cash Flow**. The numbers are computed live from your journal entries. Click **Generate PDF artifact** to produce a downloadable report. |
| **Tax** | Three sub-tabs: **Forms** (catalog of US tax forms), **Mappings** (proposed account → tax-line mappings you approve / reject), **Worksheets** (generated from approved mappings). |
| **Artifacts** | Every generated report. **Finalize** locks an artifact, **Download** streams it. |

### 5.4 Review queue

Lists documents that the system has classified but a human still needs to
turn into a journal entry. (Empty on a fresh deployment until you upload
and process documents.)

### 5.5 Artifacts

Firm-wide library of every generated report across all clients.

---

## 6. Suggested tour (client portal)

Sign out, sign back in as `client_portal` (see §3).

| Page | What to try |
|---|---|
| **Overview** (`/portal`) | KPI cards showing your documents and reports. Confirm you only see your own client's data. |
| **My documents** (`/portal/documents`) | Upload a file. Same behavior as the firm-staff Documents tab, scoped to you. |
| **My reports** (`/portal/reports`) | Lists only **finalized** reports your accountant has shared with you. Download streams the file. |

Try pasting another client's UUID into a portal URL — the system enforces
strict tenant isolation and will return no rows.

---

## 7. Things to try (and what should happen)

This is a quick checklist of behaviors we'd love you to verify.

1. **Create a client.** It appears in the Clients list immediately.
2. **Create a period** with start date *after* end date → rejected.
3. **Create a chart of accounts entry** for each of the five account types.
4. **Post a balanced journal entry** (e.g. debit Cash $100, credit Revenue $100) → succeeds and appears on the Journal entries list.
5. **Try to post an unbalanced entry** (debit $100, credit $50) → the **Post** button stays disabled.
6. **Lock a period**, then try to post a new entry to it → rejected with a 409 Conflict.
7. **Open the Statements tab**, generate a Profit & Loss → numbers reflect your journal entries; Balance Sheet shows `Assets = Liabilities + Equity`.
8. **Click "Generate PDF artifact"** on a statement → a row appears in the Artifacts tab; **Finalize** then **Download** produces a real PDF.
9. **Upload a document** on the Documents tab → it appears in the list with a status badge (note the mock-OCR caveat in §6.4).
10. **Sign out**, sign back in as `client_portal` → you only see your own client's data, no firm-wide views.

### 6.4 About document uploads (important)

The Documents tab accepts **any file type** — PDF, PNG, JPG, CSV, XLSX,
DOCX, plain text, anything your browser will let you select. There is no
file size limit you will hit in normal testing.

**However:** in this demo the document extraction (OCR) is a **mock
service**. That means:

* Uploads always succeed (assuming the file isn't empty or virus-flagged).
* The system stores your file securely, computes its hash for deduplication,
  records the audit trail, and walks the document through the full status
  pipeline.
* But the **extracted fields** you see (vendor name, amount, date, etc.)
  are deterministic placeholder values based on the **"Kind hint"**
  dropdown — not on the actual contents of your file.

The Kind hint values the system recognises are:

| Kind hint | Mock extraction returns |
|---|---|
| `generic` (default) | A generic placeholder string. |
| `bank_transaction` | A fake merchant, amount, and date. |
| `tax_form_w2` | Fake employer EIN, wages, federal withholding. |
| `tax_form_1099_nec`, `tax_form_1099_int`, `tax_form_1098` | Fake tax form fields. |
| `invoice` | A fake vendor, total, and invoice date. |
| `receipt` | A fake receipt. |

So: **upload anything you like to validate the workflow** (drag and drop,
deduplication, status badges, audit trail, encrypted storage), but please
don't expect real OCR on the document contents in this demo. In production
this same pipeline is wired to Azure AI Document Intelligence and produces
real field extraction from PDFs, images, and Office files.

### 6.5 Where your uploaded files actually live

Uploads are stored in a dedicated, hardened **Azure Storage Account**
provisioned just for this demo. Every file lands at a tenant-isolated key:

```
firm-{your-firm-id}/client-{your-client-id}/{year}/{kind}/{uuid}.{ext}
```

What the platform does on your behalf, *for every upload*:

| Property | What it gives you |
|---|---|
| **Per-tenant prefix** computed server-side from your auth identity | A session bound to firm A cannot read, write, or list under firm B's prefix — enforced in code (`tenant_path()`, `_check_prefix()`) regardless of what path you try to send. |
| **AAD (managed-identity) auth between API and Storage** | No connection strings, no SAS keys; the API authenticates with Entra ID. Shared-key access on the account is **disabled**. |
| **TLS 1.2 minimum, HTTPS-only** | All traffic to the account is encrypted in transit. |
| **Microsoft-managed double encryption at rest (infrastructure encryption)** | Two independent cryptographic layers underneath the storage service. |
| **App-level envelope encryption** | The application also wraps each blob in a per-tenant DEK (data encryption key) before handing the bytes to Storage — defense in depth. |
| **Blob soft-delete: 30 days** | Accidental deletes are recoverable. |
| **Versioning + change feed** | Every overwrite produces a new version; the change feed gives a tamper-evident audit log of writes. |
| **Geo-zone-redundant storage (GZRS)** | Six replicas across three zones in-region plus an async paired region copy. |
| **Container has no anonymous access** | Public reads are blocked at the container and at the account. |

So when the customer tester uploads a real document, the bytes are written
directly into a private, AAD-only Storage Account container with a path
that is mechanically impossible to share across tenants. Restarting the
API does not affect persistence; the files remain durably stored.

---

## 8. What's intentionally limited in this demo

* **Document OCR** is mocked (see §6.4 above).
* **Email notifications** are not sent.
* **E-signature** flows are not enabled (PDF artifacts are real and
  downloadable; signing them is out of scope).
* **SSO / Entra ID login** is wired in the codebase but disabled for the
  demo so you can log in by pasting a UUID instead of provisioning users.
* The demo runs on a small database tier — it's sized for one or two
  testers clicking through, not for load testing.

Everything else — multi-tenant isolation, balanced-books enforcement,
period locks, statement computation, tax-line mapping, PDF generation,
encrypted storage, full audit trail — is the real production code path.

---

## 9. Giving us feedback

We'd love to hear:

* **What worked well** and felt natural.
* **What surprised you** — a button you expected to do something else, a
  field that didn't make sense, a number that looked wrong.
* **Any errors** you hit. If you see an error toast or a blank page,
  please note:
  * Which page you were on (the URL in the address bar).
  * Whether you were signed in as `firm_staff` or `client_portal`.
  * Roughly what you clicked just before the error.
  * A screenshot if you have time.

Send your feedback to **gaurav.malhotra@mmfcllc.com** — we'll fold it
directly into the next iteration.

---

## 10. After the demo

The environment automatically tears itself down at the time shown in §1.
Your test data is destroyed at that point — nothing you upload here is
preserved. If you'd like a fresh environment or a longer-lived demo with
your own sample data, just ask.

Thank you for taking the time to try CTAA.
