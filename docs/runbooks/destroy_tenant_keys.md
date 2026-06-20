# Crypto-Shred Runbook (Destroy Tenant Keys)

**Purpose:** Permanently render all of a firm's encrypted data
unrecoverable by destroying the per-firm KEK (Key Encryption Key).

**When to use:**
* The firm offboards from the platform and a "right to be forgotten" /
  contractual data-destruction obligation applies.
* Required by a regulatory data-destruction order.

**Reversibility:** **NONE.** Once the KEK is destroyed, every artifact
whose DEK was wrapped with that KEK becomes ciphertext-only and
mathematically unrecoverable. There is no break-glass.

---

## Prerequisites

* You have a firm-scope authentication token for the **target firm itself**
  (cross-firm admin actions are forbidden by `/admin/tenants/{firm_id}/destroy-keys`).
* You have written change-management approval (ticket id captured below).
* You have notified the firm via the documented offboarding workflow.
* You have a current audit-log export (see `audit_export.md`) — the act of
  destruction will append an `AuditAction.TENANT_KEYS_DESTROY` event but
  capturing the *pre-destruction* state is required for evidence.

## Procedure

### 1. Capture pre-destruction evidence

```bash
TOKEN="<firm-admin-bearer-token>"
FIRM_ID="<target-firm-uuid>"

# Export the firm's audit trail
curl -sSf -H "Authorization: Bearer $TOKEN" \
  "https://api.ctaa.example.com/audit/export?period_start=2000-01-01T00:00:00Z&period_end=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -o "evidence/${FIRM_ID}-pre-destruction-audit.json"

sha256sum "evidence/${FIRM_ID}-pre-destruction-audit.json"
```

Store the SHA-256 in the change-management ticket.

### 2. Issue destruction

```bash
curl -sSf -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm":"DESTROY","reason":"<ticket-id> offboarding per signed contract clause X.Y"}' \
  "https://api.ctaa.example.com/admin/tenants/${FIRM_ID}/destroy-keys"
```

Expected response (HTTP 200):

```json
{"firm_id": "<firm-uuid>", "status": "destroyed"}
```

The audit row is written **before** the key destruction call so the trail
survives partial-failure scenarios.

### 3. Verify

```bash
# Subsequent decrypt attempts MUST fail. Confirm by attempting any
# artifact download for this firm — should return 5xx with a
# KeyDestroyedError in the structured logs.

# DB-level: tenant_encryption_key.status for this firm should be 'destroyed'
# and destroyed_at should be set.
psql "$ADMIN_DATABASE_URL" -c \
  "SELECT firm_id, status, destroyed_at FROM tenant_encryption_key WHERE firm_id='${FIRM_ID}';"
```

### 4. Document

Attach to the change-management ticket:

* The destruction `AuditAction.TENANT_KEYS_DESTROY` row (timestamp + actor).
* SHA-256 of the pre-destruction audit export.
* The verification screenshot showing decrypt failure.

## What this does and does not destroy

| Item | Effect of crypto-shred |
|---|---|
| Encrypted source documents in blob storage | Permanently unreadable |
| Encrypted generated artifacts (PDFs, XLSXs) | Permanently unreadable |
| Database rows (journal_entry, journal_line, …) | **NOT destroyed.** RLS continues to scope them to the firm. To physically delete the rows, follow `data_purge.md` (separate runbook). |
| Audit log | **NOT destroyed.** Audit history is preserved by design (append-only). |
| Tenant_encryption_key row | Status → `destroyed`, KEK material erased from KMS, `destroyed_at` set. |

If full row deletion is also required, run that as a separate, also-audited
step after this runbook completes.
