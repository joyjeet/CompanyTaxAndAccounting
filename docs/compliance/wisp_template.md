# Written Information Security Plan (WISP) — Template

> This is a **template**. Sections marked **[FIRM TO COMPLETE]** must be
> filled in by the firm before the WISP is considered active. The
> technical-controls inventory is pre-filled from the platform's
> implementation; everything else is firm-governance scope.

---

## 1. Designation of a Qualified Individual

**[FIRM TO COMPLETE]**

* Name:
* Title:
* Contact:
* Date appointed:
* Reporting line to firm leadership:

Reviews this WISP at least annually and signs off on the annual report to
firm leadership.

## 2. Risk Assessment

**[FIRM TO COMPLETE]** — at least annually, in writing.

* Inventory of personal information (PII) the firm collects, processes,
  and stores
* Threat scenarios (insider, external attacker, vendor compromise,
  natural disaster)
* Likelihood × impact for each
* Treatment plan for each material risk

## 3. Information Security Program — Technical Controls (pre-filled)

The platform implements the following technical controls. Each is
verifiable by reading the cited source files.

| Domain | Control | Implementation |
|---|---|---|
| Tenant isolation | Postgres RLS ENABLE + FORCE on all client-data tables; per-request GUCs (`app.current_firm`, `app.current_client`, `app.access_scope`); `app_user` is **not** superuser and **not** BYPASSRLS | `migrations/versions/0001_initial.py`, `app/db/session.py` |
| Identity | OIDC bearer-token auth; tenant context derived **only** from validated token, never from body/query | `app/api/auth.py`, `app/api/deps.py` |
| Encryption at rest | Envelope encryption (AES-GCM DEK wrapped with per-firm KEK); KEKs in Azure Key Vault in prod, with purge protection enabled | `app/integrations/encryption.py`, `app/integrations/keys.py`, `infra/modules/keyvault.bicep` |
| Encryption in transit | TLS 1.2 enforced on every PaaS resource; HSTS preload-eligible headers on every response | `infra/modules/postgres.bicep`, `infra/modules/storage.bicep`, `app/api/middleware.py` |
| Audit logging | Application-layer `write_audit()` for every state change; DB-level REVOKE UPDATE/DELETE on `audit_event` for the runtime app role; tamper-evident hash-chain export | `app/domain/audit.py`, `migrations/versions/0002_audit_append_only.py`, `app/api/routes/audit_export.py` |
| Logging hygiene | Structured JSON logs with SSN/EIN redaction and forbidden-field allowlist | `app/core/logging.py` |
| Network | All data-plane services on private endpoints in a VNet; public ingress only via Front Door + WAF | `infra/modules/network.bicep`, `infra/modules/frontdoor.bicep` |
| Application security | OWASP DRS 2.1 + Bot Manager 1.0 in WAF; route-level rate-limit fallback in app middleware | `infra/modules/frontdoor.bicep`, `app/api/middleware.py` |
| Vulnerability management | Trivy + pip-audit on every PR; container images rebuilt per release | `.github/workflows/ci.yml` |
| Backup | Postgres PITR (35-day window, geo-redundant in prod); quarterly restore drill | `infra/modules/postgres.bicep`, `docs/runbooks/restore_drill.md` |
| Data disposal | Crypto-shred renders all per-firm encrypted material unrecoverable | `app/api/routes/admin.py`, `docs/runbooks/destroy_tenant_keys.md` |
| Change management | All changes via PR + protected branches + required CI; protected `prod` environment with reviewer approval | `.github/workflows/cd.yml` |

## 4. Information Security Program — Administrative Controls

**[FIRM TO COMPLETE]**

* 4.1 Access provisioning — who can grant firm-staff access, joiner /
  mover / leaver workflow
* 4.2 MFA policy — required for all firm-staff and admin accounts
* 4.3 Acceptable Use Policy — reference to firm's existing AUP
* 4.4 Bring-your-own-device — policy and controls
* 4.5 Vendor management — list of in-scope vendors and review cadence
* 4.6 Background checks — for staff with access to client tax data

## 5. Employee Training

**[FIRM TO COMPLETE]**

* Mandatory security-awareness training on hire and annually thereafter
* Phishing simulation cadence
* Tax-specific security training (IRS Pub 4557 awareness)
* Training completion tracked in (system name)

## 6. Service Providers

**[FIRM TO COMPLETE]**

* Microsoft Azure — primary infrastructure provider. See subprocessor
  list in (firm's MSA reference).
* (LLM provider, if used) — vendor DD, DPA in place, data-handling
  reviewed annually.
* Any third-party document-extraction service must be reviewed before
  enablement.

## 7. Incident Response

### 7.1 Detection

Technical detection is provided by the platform alerts (auth failure
spike, RLS error, backup failure, DLQ depth, failure-anomaly smart
detector) routed to the action-group email defined in
`infra/params/prod.bicepparam`.

**[FIRM TO COMPLETE]**

* 7.1.1 Who monitors the action-group inbox during/outside business hours
* 7.1.2 Escalation path

### 7.2 Containment

* 7.2.1 Suspend affected user — disable in Entra ID
* 7.2.2 Suspend affected firm tenant — set Front Door to maintenance
  mode (`docs/runbooks/maintenance_mode.md`, to be added)
* 7.2.3 If credential compromise — rotate KV secrets, restart Container Apps

### 7.3 Eradication & Recovery

* 7.3.1 If data integrity in doubt — restore from PITR per
  `docs/runbooks/restore_drill.md`
* 7.3.2 If suspected KEK compromise — generate new KEK version, re-wrap
  DEKs in next maintenance window (TBD runbook)

### 7.4 Notification

**[FIRM TO COMPLETE]**

* 7.4.1 Counsel notified within (hours)
* 7.4.2 Affected clients notified per state breach-notification law (track
  state-by-state deadlines)
* 7.4.3 FTC notified per FTC Safeguards Rule (if applicable)
* 7.4.4 IRS notified per Pub 4557 (Stakeholder Liaison contact)

### 7.5 Lessons Learned

* Post-incident review within 30 days
* WISP, runbooks, and controls updated as needed

## 8. Periodic Evaluation

**[FIRM TO COMPLETE]**

* This WISP reviewed at least annually
* Risk assessment refreshed at least annually
* Pen test conducted at least every 12 months (see
  `pen_test_brief.md`)
* Restore drill conducted at least quarterly

## 9. Annual Report

**[FIRM TO COMPLETE]**

The qualified individual (§1) produces an annual written report to firm
leadership covering: control effectiveness, risks identified, incidents,
remediation status, and material changes.
