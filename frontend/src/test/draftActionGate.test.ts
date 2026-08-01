import { describe, expect, it } from "vitest";

import {
  promoteAllDisabledReason,
  promoteDisabledReason,
  rejectDisabledReason,
} from "../pages/draftActionGate";

describe("draft action gating", () => {
  it("blocks all posting actions for read-only role", () => {
    const base = {
      canPromoteDrafts: false,
      role: "read_only" as const,
      clientId: "c1",
      periodId: "p1",
    };
    expect(promoteAllDisabledReason(base)).toContain("read only");
    expect(promoteDisabledReason({ ...base, balanced: true })).toContain("read only");
    expect(rejectDisabledReason(base)).toContain("read only");
  });

  it("requires client and period before posting", () => {
    const base = {
      canPromoteDrafts: true,
      role: "staff" as const,
      clientId: "",
      periodId: "",
    };
    expect(promoteAllDisabledReason(base)).toBe("Select a client first.");
    expect(promoteDisabledReason({ ...base, balanced: true })).toBe("Select a client first.");
    expect(promoteDisabledReason({ ...base, clientId: "c1", balanced: true })).toBe(
      "Select an open period first.",
    );
  });

  it("requires balanced totals for single-entry promote", () => {
    const base = {
      canPromoteDrafts: true,
      role: "staff" as const,
      clientId: "c1",
      periodId: "p1",
    };
    expect(promoteDisabledReason({ ...base, balanced: false })).toBe(
      "Debits and credits must be balanced to promote.",
    );
    expect(promoteDisabledReason({ ...base, balanced: true })).toBe("");
  });
});
