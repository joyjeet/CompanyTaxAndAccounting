# Tax Readiness Workspace

## Summary

The client Tax area now opens with a **Readiness** workspace that turns the
existing profile, document, account-mapping, and worksheet data into an
evidence-based return status.

The workspace answers three questions for firm staff:

1. What is complete?
2. What is blocking the return?
3. Where should the preparer go to resolve each blocker?

The implementation was introduced in commit `59f6b2f`.

## User workflow

Open a client and select **Tax → Readiness**.

The workspace automatically:

- selects the latest accounting period;
- recommends the federal form from the client's entity type;
- calculates a readiness percentage;
- reports account-mapping and document-processing coverage;
- identifies unresolved readiness gates;
- links each gate to the profile, documents, mappings, or worksheets workflow;
- lists active revenue and expense posting accounts without an approved
  mapping for the selected form.

Firm staff can still switch to the existing **Forms**, **Account mappings**,
and **Worksheets** sub-tabs.

## Form recommendations

| Entity type | Recommended form |
|---|---|
| C corporation | `F1120` |
| S corporation | `F1120S` |
| Partnership | `F1065` |
| Single-member LLC | `F1040SC` |
| Sole proprietor | `F1040SC` |

The recommendation is a default selection, not a replacement for the active
entity-form ruleset enforced by the backend.

## Readiness gates

The score is derived from five gates. Users cannot manually mark a gate
complete.

| Gate | Completion rule |
|---|---|
| Client tax profile | The client has both an entity type and tax year. |
| Filing period | An accounting period is selected. |
| Source documents | At least one document completed extraction, with no documents processing or failed. |
| Account mappings | Every active leaf revenue and expense account has an approved mapping for the selected form, with no draft mappings awaiting review. |
| Tax worksheet | An approved worksheet exists for the selected period and form. |

Each complete gate contributes equally to the displayed percentage:

```text
readiness percentage = completed gates / 5 × 100
```

Incomplete gates are classified as either **Not started** or **Needs
attention**. The latter indicates that work exists but still requires review,
such as draft mappings, a processing or failed document, or an unapproved
worksheet.

## API changes

### Chart of accounts

Chart-of-accounts responses now include:

```json
{
  "is_leaf": true
}
```

The readiness calculation uses this field to evaluate posting accounts only.
Parent and grouping nodes do not count as unmapped accounts.

### Tax mappings

`GET /tax/mappings` now accepts an optional `client_id` query parameter:

```http
GET /tax/mappings?form_code=F1120S&client_id=<client-uuid>
```

This ensures a firm-level session receives mappings only for the client being
evaluated. PostgreSQL RLS continues to enforce firm and client isolation
independently of this filter.

## Implementation

| File | Change |
|---|---|
| `app/api/routes/clients.py` | Exposes `is_leaf` in chart-of-accounts responses. |
| `app/api/routes/tax.py` | Adds client filtering to the mappings endpoint. |
| `frontend/src/api/ApiClient.ts` | Sends form and client mapping filters. |
| `frontend/src/auth/types.ts` | Adds `is_leaf` to the chart-of-accounts type. |
| `frontend/src/lib/taxReadiness.ts` | Contains form recommendation and deterministic readiness derivation. |
| `frontend/src/pages/client/TaxTab.tsx` | Adds the Readiness UI, selectors, scorecards, checklist, blockers, and unmapped-account table. |
| `frontend/src/pages/client/ClientDetail.tsx` | Allows readiness actions to navigate to Profile and Documents. |
| `frontend/src/test/taxReadiness.test.ts` | Tests readiness rules and entity-specific recommendations. |
| `frontend/src/test/ApiClient.test.ts` | Verifies client- and form-scoped mapping requests. |

## Validation

The completed implementation was validated with:

- the full backend suite: **392 tests passed**;
- focused frontend tests: **7 tests passed**;
- TypeScript type checking;
- the frontend production build;
- Ruff on the modified backend routes;
- live browser verification against the seeded S-corporation demo client.

The live verification confirmed that `F1120S` is selected for an S
corporation, blockers match current client data, unmapped accounts are
reported, and **Resolve** actions open the corresponding workflow.

## Current limitations

- Each readiness gate has equal weight.
- Document readiness checks extraction state, not a form-specific document
  checklist.
- The form recommendation covers the currently supported federal entity
  forms only.
- Readiness is calculated in the frontend from existing APIs; there is not
  yet a dedicated readiness endpoint or persisted readiness snapshot.
- Assignment, comments, due dates, and preparer/reviewer sign-off are not yet
  part of this workspace.
