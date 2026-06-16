import { useMemo } from "react";

import { useAuth } from "../auth/AuthContext";
import { ApiClient } from "./ApiClient";

export function useApi(): ApiClient {
  const { client } = useAuth();
  return useMemo(() => new ApiClient(client), [client]);
}
