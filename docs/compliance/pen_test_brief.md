# External Penetration Test — Scope Brief

**Status:** Template. The actual engagement must be performed by an
independent third-party firm; this document defines scope, ground rules,
and reporting expectations.

---

## 1. Objective

Independently verify the production deployment of CTAA does not expose
client tax data through any reachable vulnerability, and that the
tenant-isolation controls cannot be bypassed by an authenticated user
acting in bad faith.

The test must explicitly cover:

* **Authentication & authorisation** — token validation, scope checks,
  cross-tenant access attempts.
* **Tenant isolation** — RLS enforcement, GUC manipulation, JWT claim
  tampering, IDOR.
* **Input handling** — file upload, document parsing, prompt injection
  into the AI extraction layer.
* **Network exposure** — what is reachable from the public Internet via
  Front Door vs. what should only be reachable from inside the VNet.
* **Web application security** — OWASP Top 10 against both the API and
  the React frontend.

## 2. Tester profile

* US-based firm with CREST / OSCP / equivalent certified testers.
* Background-checked staff.
* Signed MSA + NDA + SOW with the firm before kickoff.
* Cyber-liability insurance ≥ $2M.

## 3. Scope (in-scope)

| Asset | URL / Identifier | Notes |
|---|---|---|
| Production API | `https://api.ctaa.example.com` (Front Door endpoint) | Primary target |
| Production portal frontend | `https://app.ctaa.example.com` | Client-portal flows |
| Authentication flows | Entra ID OIDC | Test from outside; tenant config is the firm's |
| File upload endpoints | `POST /documents/upload` | Malicious file fuzzing |
| AI extraction pipeline | `POST /documents/{id}/extract` | Prompt injection, oversized inputs |
| Admin endpoints | `POST /admin/tenants/{firm_id}/destroy-keys` | Authorisation testing only — do **NOT** actually destroy any keys |
| Audit export | `GET /audit/export` | Authorisation testing, integrity of hash chain |

## 4. Out-of-scope (do NOT test)

* Microsoft Azure infrastructure itself (Microsoft's responsibility).
* DoS / volumetric attacks. Rate-limit can be probed with low-volume
  positive tests only.
* Physical security of Azure data centres.
* Firm employees' personal devices.
* Social engineering of firm staff (unless explicitly added to a
  separate red-team engagement).
* The Entra ID directory configuration (firm-side; separate audit).
* Any pre-production environment containing real client data (none
  exists by policy; if found, stop and report).

## 5. Provided accounts

The firm provisions, for the duration of the engagement only:

| Account | Scope | Purpose |
|---|---|---|
| `pentester-firm-a-staff@…` | Firm A, FIRM scope | Test legitimate firm-staff actions |
| `pentester-firm-a-client@…` | Firm A, CLIENT scope, Client X | Test legitimate client-portal actions |
| `pentester-firm-b-staff@…` | Firm B, FIRM scope | Cross-tenant isolation probe (must NOT see any of Firm A's data) |
| `pentester-firm-b-client@…` | Firm B, CLIENT scope, Client Y | Cross-tenant isolation probe |

Tenant-isolation success criterion: from any Firm B credential, **zero**
Firm A data is reachable through any combination of legitimate API
calls, claim manipulation, or response analysis.

## 6. Ground rules

* No data exfiltration beyond what is necessary to demonstrate a finding.
  Any sample client data accidentally accessed must be deleted by the
  tester within 24 hours and reported.
* All testing from a registered IP allowlist (the WAF will throttle
  unknown sources, which is the desired production behaviour).
* No automated scanning that triggers >100 req/s without coordination.
* Findings disclosed only to the firm's qualified individual and the
  platform team. Public disclosure requires written approval.
* Critical findings (RCE, cross-tenant data exposure, auth bypass)
  reported within 24 hours of discovery.

## 7. Deliverables

1. **Executive summary** — non-technical, suitable for firm leadership.
2. **Technical findings** — each with: severity (CVSS 3.1), reproduction
   steps, affected component, recommended remediation.
3. **Evidence package** — request/response captures, screenshots, scripts.
4. **Remediation tracking table** — see `pen_test_remediation_template.md`.

## 8. Remediation timelines

| Severity | SLA |
|---|---|
| Critical | Hotfix within 7 days |
| High | Within 30 days |
| Medium | Within 90 days |
| Low | Tracked, addressed in next quarterly hardening cycle |

## 9. Retest

Within 60 days of the initial report, the same firm retests all Critical
and High findings to confirm remediation. Retest scope is limited to
those findings; full-scope retest is the next annual engagement.

## 10. Cadence

Annual, plus on any of the following:

* Material change to the authentication system.
* New external-facing surface (e.g. partner API).
* After remediating a Critical finding from monitoring (live incident).

---

## Findings tracking template

Copy into `pen_test_remediation_<YYYY>.md` after each engagement:

| Id | Title | Severity | Status | Owner | Found | Fixed | Verified |
|----|-------|----------|--------|-------|-------|-------|----------|
| F-001 | (example) | Critical | Fixed | platform | 2026-01-15 | 2026-01-18 | 2026-02-02 |
