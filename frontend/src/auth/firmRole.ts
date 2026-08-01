import type { StaffRole } from "./types";

export interface FirmRoleCapabilities {
  canManageTeam: boolean;
  canCreateClient: boolean;
  canEditRulesEngine: boolean;
  canPromoteDrafts: boolean;
}

export function capabilitiesForRole(role: StaffRole | null): FirmRoleCapabilities {
  if (role === "firm_owner" || role === "firm_admin") {
    return {
      canManageTeam: true,
      canCreateClient: true,
      canEditRulesEngine: true,
      canPromoteDrafts: true,
    };
  }
  if (role === "manager" || role === "staff") {
    return {
      canManageTeam: false,
      canCreateClient: true,
      canEditRulesEngine: false,
      canPromoteDrafts: true,
    };
  }
  if (role === "read_only") {
    return {
      canManageTeam: false,
      canCreateClient: false,
      canEditRulesEngine: false,
      canPromoteDrafts: false,
    };
  }
  return {
    canManageTeam: false,
    canCreateClient: false,
    canEditRulesEngine: false,
    canPromoteDrafts: false,
  };
}

export function roleDisplayName(role: StaffRole): string {
  return role.replaceAll("_", " ");
}
