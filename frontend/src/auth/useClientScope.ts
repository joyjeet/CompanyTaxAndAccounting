/**
 * Reads the `?client=<uuid>` filter that firm-wide pages honour.
 *
 * Firm staff legitimately see every client in the firm, but once they open a
 * client they are working inside that client's books — showing 200 clients'
 * drafts on one screen is noise. The client workspace nav links here with
 * `?client=`, and these pages narrow themselves accordingly.
 */
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { useApi } from "../api/useApi";

export interface ClientScope {
  /** The client to filter to, or null when viewing the whole firm. */
  clientId: string | null;
  /** Display name once loaded; null while loading or when unscoped. */
  clientName: string | null;
}

export function useClientScope(): ClientScope {
  const api = useApi();
  const [params] = useSearchParams();
  const clientId = params.get("client");

  const client = useQuery({
    queryKey: ["client", clientId],
    queryFn: () => api.getClient(clientId as string),
    enabled: Boolean(clientId),
    staleTime: 60_000,
  });

  return { clientId, clientName: client.data?.name ?? null };
}
