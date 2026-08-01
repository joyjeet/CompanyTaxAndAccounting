import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { useApi } from "../api/useApi";
import { capabilitiesForRole, type FirmRoleCapabilities } from "./firmRole";
import { useAuth } from "./AuthContext";
import type { StaffRole } from "./types";

interface UseFirmRoleOut {
  role: StaffRole | null;
  isAdmin: boolean;
  capabilities: FirmRoleCapabilities;
  isLoading: boolean;
}

export function useFirmRole(): UseFirmRoleOut {
  const api = useApi();
  const { identity } = useAuth();
  const isFirm = identity?.role === "firm_staff";

  const team = useQuery({
    queryKey: ["team", "summary", "firm-role"],
    queryFn: () => api.listTeamMembers(),
    enabled: Boolean(isFirm && identity),
    staleTime: 60_000,
  });

  const role = useMemo(() => {
    if (!isFirm || !identity || !team.data) return null;
    return team.data.members.find((m) => m.subject === identity.sub)?.role ?? null;
  }, [identity, isFirm, team.data]);

  const capabilities = capabilitiesForRole(role);
  return {
    role,
    isAdmin: capabilities.canManageTeam,
    capabilities,
    isLoading: Boolean(isFirm) && team.isLoading,
  };
}
