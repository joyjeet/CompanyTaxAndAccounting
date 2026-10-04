import { describe, expect, it } from "vitest";

import { capabilitiesForRole, roleDisplayName } from "../auth/firmRole";

describe("firm role capabilities", () => {
  it("grants admin capabilities to owner/admin", () => {
    expect(capabilitiesForRole("firm_owner").canManageTeam).toBe(true);
    expect(capabilitiesForRole("firm_admin").canEditRulesEngine).toBe(true);
  });

  it("grants operational but not admin capabilities to manager/staff", () => {
    expect(capabilitiesForRole("manager").canCreateClient).toBe(true);
    expect(capabilitiesForRole("manager").canManageTeam).toBe(false);
    expect(capabilitiesForRole("staff").canPromoteDrafts).toBe(true);
  });

  it("keeps read-only locked down", () => {
    const caps = capabilitiesForRole("read_only");
    expect(caps.canCreateClient).toBe(false);
    expect(caps.canEditRulesEngine).toBe(false);
    expect(caps.canPromoteDrafts).toBe(false);
  });

  it("formats role labels", () => {
    expect(roleDisplayName("firm_admin")).toBe("firm admin");
  });
});
