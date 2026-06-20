# Compliance Control Mapping

This table maps each in-scope control to the **code, configuration, or
process** that implements it. Use it as the master index for any
auditor walkthrough.

| Status | Meaning |
|---|---|
| **Implemented** | Fully realised in code/IaC, verifiable by reading the file. |
| **Partial** | Code exists but depends on organisational input or a configuration toggle. |
| **Requires-Process** | This is a human or organisational control. The platform supports it but does not produce evidence on its own. |

> This document **does not certify** compliance with any framework. SOC 2
> Type II requires an independent CPA audit; FTC Safeguards, IRS Pub 4557
> and GLBA require firm-level governance. Use this as the evidence
> starting-point for those engagements.

---

## FTC Safeguards Rule (16 CFR §314)

| § | Requirement | Status | Location / Evidence |
|---|---|---|---|
| 314.4(a) | Designate a qualified individual to oversee the security program | Requires-Process | Named in `wisp_template.md` §1 (firm to complete) |
| 314.4(b)(1) | Risk assessment, written | Requires-Process | `wisp_template.md` §2 — firm completes annually |
| 314.4(c)(1) | Access controls (least privilege) | Implemented | Per-firm UAMI in `infra/modules/identity.bicep`; KV roles in `infra/modules/keyvault.bicep`; DB role split (owner vs `app_user_test`/`app_user`) in `migrations/versions/0001_initial.py`, `0002_audit_append_only.py` |
| 314.4(c)(2) | Inventory of customer data | Partial | Data model encoded in `app/models/accounting.py`; firm maintains its own client data inventory |
| 314.4(c)(3) | Encryption in transit and at rest | Implemented | TLS enforced: `infra/modules/postgres.bicep` (`require_secure_transport=ON`), HSTS via `app/api/middleware.py`. At-rest: envelope encryption in `app/integrations/encryption.py` + per-firm KEK in `app/integrations/keys.py` |
| 314.4(c)(4) | Secure software development | Implemented | CI in `.github/workflows/ci.yml` (ruff, tests, Trivy, pip-audit); IaC validation in `.github/workflows/iac-validate.yml`; isolation-gate proof in `.github/workflows/isolation-gate-proof.yml` |
| 314.4(c)(5) | Authentication (MFA where appropriate) | Partial | OIDC-based auth in `app/security/auth.py`; MFA enforcement is the firm's Entra ID tenant config (Requires-Process) |
| 314.4(c)(6) | Disposal of customer information | Implemented | Crypto-shred endpoint in `app/api/routes/admin.py`; runbook in `docs/runbooks/destroy_tenant_keys.md` |
| 314.4(c)(7) | Change management | Implemented | All changes via PR + CI; protected `prod` environment in `.github/workflows/cd.yml` |
| 314.4(c)(8) | Monitoring and logging | Implemented | Structured logs in `app/core/logging.py`; alerts in `infra/modules/alerts.bicep`; diagnostic settings on every PaaS resource |
| 314.4(d)(1) | Continuous monitoring / penetration testing | Partial | Continuous monitoring: implemented (alerts). Annual pen test: Requires-Process — see `pen_test_brief.md` |
| 314.4(e) | Training | Requires-Process | `wisp_template.md` §5 — firm tracks employee training |
| 314.4(f) | Service-provider oversight | Partial | Microsoft Azure is the sole infrastructure provider (subprocessor list in firm's contract); third-party model providers (OpenAI etc.) require firm-level vendor DD if used |
| 314.4(g) | Periodic evaluation and adjustment | Requires-Process | Annual review of this document + WISP |
| 314.4(h) | Incident response plan | Partial | Runbooks in `docs/runbooks/` give technical playbooks; firm-side IR roles, comms, notification timing in `wisp_template.md` §7 |
| 314.4(i) | Annual written report to board | Requires-Process | Designated qualified individual produces report |

## IRS Pub 4557 — Safeguarding Taxpayer Data

| Topic | Status | Location |
|---|---|---|
| Written Information Security Plan (WISP) | Partial | Template in `wisp_template.md` |
| Anti-malware and patching | Requires-Process | Endpoint MDM is firm's IT scope; the platform runs in container images rebuilt per release (CI in `.github/workflows/ci.yml`) |
| Strong passwords / MFA | Partial | OIDC integration enforces firm's tenant policies (Requires-Process) |
| Encryption of taxpayer data | Implemented | Envelope encryption (`app/integrations/encryption.py`) for stored docs; TLS in transit |
| Backup procedures | Implemented | Postgres backups in `infra/modules/postgres.bicep` (35 days, geo-redundant prod); restore drill in `docs/runbooks/restore_drill.md` |
| Disposal of paper / hardware | Requires-Process | Firm-side physical process |
| Incident reporting (FTC, IRS, states) | Requires-Process | Notification thresholds + counsel coordination in `wisp_template.md` §7 |

## GLBA Safeguards (15 U.S.C. §6801) — supplements FTC Safeguards Rule

Substantially overlaps with the FTC Safeguards Rule controls above. The
firm's customer-notification obligations for NPI events (15 USC §6809)
are Requires-Process; the platform's `AUDIT_EXPORT` action plus structured
logs supply the technical evidence trail for notification timing.

## SOC 2 Type II — Common Criteria (illustrative subset)

| CC | Description | Status | Location |
|---|---|---|---|
| CC1 | Control Environment | Requires-Process | Firm's governance (WISP §1, §5) |
| CC2 | Communication & Information | Requires-Process | Firm's policies, training |
| CC3 | Risk Assessment | Requires-Process | WISP §2 (annual) |
| CC4 | Monitoring Activities | Implemented | App Insights + Log Analytics + alert rules in `infra/modules/alerts.bicep`; restore-drill evidence per `docs/runbooks/restore_drill.md` |
| CC5 | Control Activities | Implemented | Code-level controls (RLS, encryption, append-only audit) listed above |
| CC6.1 | Logical access | Implemented | OIDC + tenant-scoped DB session (`app/db/session.py`); RLS in `migrations/versions/0001_initial.py` |
| CC6.2 | New/modified access reviewed | Requires-Process | Firm's joiner-mover-leaver workflow in Entra ID |
| CC6.3 | Removal of access | Implemented | OIDC token expiry; crypto-shred for terminated firm (`docs/runbooks/destroy_tenant_keys.md`) |
| CC6.6 | Logical access to system credentials | Implemented | No secrets in code — KV references throughout `infra/`; Managed Identity for runtime access |
| CC6.7 | Restriction of physical access | Implemented (inherited) | Azure data centres (Microsoft's SOC 2) |
| CC6.8 | Detection of unauthorised software | Implemented | Trivy + pip-audit in CI; WAF + Defender for Cloud (Requires-Process to enable Defender Standard tier in customer subscription) |
| CC7.1 | Detection / vulnerability mgmt | Implemented | Trivy scans in `ci.yml`; pip-audit; WAF Microsoft_DefaultRuleSet 2.1 in `infra/modules/frontdoor.bicep` |
| CC7.2 | Incident detection and response | Implemented | Alerts in `infra/modules/alerts.bicep` (auth failure spike, RLS error, DLQ depth, backup failure); runbooks in `docs/runbooks/` |
| CC7.4 | Incident communication | Requires-Process | WISP §7 |
| CC7.5 | Recovery | Implemented | Backups + restore drill (`docs/runbooks/restore_drill.md`); ZoneRedundant HA in prod (`infra/params/prod.bicepparam`) |
| CC8.1 | Change management | Implemented | PR-only changes, required CI checks, protected `prod` environment with approvals in `.github/workflows/cd.yml` |
| CC9.1 | Risk mitigation — system | Implemented | Defence in depth: WAF + Front Door + private endpoints + RLS + envelope encryption + crypto-shred |
| CC9.2 | Risk mitigation — vendor | Partial | Microsoft Azure subprocessor relationship documented in firm's contract; any LLM provider is firm-side vendor DD |

---

## Tenancy-isolation controls (cross-cutting)

| Control | Location |
|---|---|
| RLS ENABLE + FORCE on every tenant table | `migrations/versions/0001_initial.py` and subsequent migrations |
| Per-request transaction-scoped GUCs | `app/db/session.py::tenant_session` |
| Token-derived tenant context (no body/query override) | `app/api/auth.py`, `app/api/deps.py` |
| App role is NOT BYPASSRLS / not superuser | `migrations/versions/0001_initial.py`; verified by isolation tests |
| Append-only audit (REVOKE UPDATE/DELETE on `audit_event`) | `migrations/versions/0002_audit_append_only.py` |
| Crypto-shred destroys per-firm KEK | `app/integrations/keys.py::KeyProvider.destroy_tenant_keys`; admin endpoint in `app/api/routes/admin.py` |
| Tenant-scoped audit export with hash chain | `app/api/routes/audit_export.py` |
| Isolation-gate proof workflow | `.github/workflows/isolation-gate-proof.yml` |

## Data-residency controls

| Control | Location |
|---|---|
| US-only allowed-list on `location` parameter | `infra/main.bicep` (`@allowed([…]) param location`) |
| GRS storage in US paired regions | `infra/modules/storage.bicep` (`Standard_GRS`) |
| Geo-redundant Postgres backup in prod | `infra/modules/postgres.bicep` (`geoRedundantBackup=Enabled`) |
