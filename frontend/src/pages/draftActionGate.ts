import { roleDisplayName } from "../auth/firmRole";
import type { StaffRole } from "../auth/types";

interface BaseGateInput {
  canPromoteDrafts: boolean;
  role: StaffRole | null;
  clientId: string;
  periodId: string;
}

function blockedReason(role: StaffRole | null): string {
  return `Your role (${role ? roleDisplayName(role) : "unknown"}) is read-only for draft posting actions.`;
}

export function promoteAllDisabledReason(input: BaseGateInput): string {
  if (!input.canPromoteDrafts) return blockedReason(input.role);
  if (!input.clientId) return "Select a client first.";
  if (!input.periodId) return "Select an open period first.";
  return "";
}

export function promoteDisabledReason(
  input: BaseGateInput & { balanced: boolean },
): string {
  if (!input.canPromoteDrafts) return blockedReason(input.role);
  if (!input.clientId) return "Select a client first.";
  if (!input.periodId) return "Select an open period first.";
  if (!input.balanced) return "Debits and credits must be balanced to promote.";
  return "";
}

export function rejectDisabledReason(input: Pick<BaseGateInput, "canPromoteDrafts" | "role">): string {
  if (!input.canPromoteDrafts) return blockedReason(input.role);
  return "";
}
