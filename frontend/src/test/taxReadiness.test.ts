import { describe, expect, it } from "vitest";

import type {
  ClientProfileOut,
  CoaOut,
  DocumentOut,
  MappingOut,
  WorksheetOut,
} from "../auth/types";
import { deriveTaxReadiness, recommendedFormCode } from "../lib/taxReadiness";

const profile = {
  entity_type: "s_corp",
  tax_year: 2026,
} as ClientProfileOut;

const account = {
  id: "account-1",
  account_type: "revenue",
  is_active: true,
  is_leaf: true,
} as CoaOut;

const mapping = {
  account_id: account.id,
  status: "approved",
} as MappingOut;

const document = {
  ocr_status: "complete",
} as DocumentOut;

const worksheet = {
  status: "approved",
  taxable_income: "12500.00",
} as WorksheetOut;

describe("tax readiness", () => {
  it("recommends the federal form from the entity type", () => {
    expect(recommendedFormCode(profile)).toBe("F1120S");
  });

  it("reports a fully ready return only when every gate is complete", () => {
    const result = deriveTaxReadiness({
      profile,
      hasPeriod: true,
      formCode: "F1120S",
      accounts: [account],
      mappings: [mapping],
      documents: [document],
      worksheets: [worksheet],
    });

    expect(result.score).toBe(100);
    expect(result.blockers).toEqual([]);
    expect(result.unmappedAccounts).toEqual([]);
  });

  it("surfaces processing documents, draft mappings, and an unapproved worksheet", () => {
    const result = deriveTaxReadiness({
      profile,
      hasPeriod: true,
      formCode: "F1120S",
      accounts: [account],
      mappings: [{ ...mapping, status: "draft" }],
      documents: [{ ...document, ocr_status: "in_progress" }],
      worksheets: [{ ...worksheet, status: "draft" }],
    });

    expect(result.score).toBe(40);
    expect(result.pendingMappingCount).toBe(1);
    expect(result.unmappedAccounts).toEqual([account]);
    expect(result.checks.find((check) => check.id === "documents")?.status).toBe("attention");
    expect(result.checks.find((check) => check.id === "worksheet")?.status).toBe("attention");
  });
});
