/**
 * React context wrapping an `AuthClient`. Selected at boot from app config.
 */
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import config from "../config";
import type { AuthClient } from "./AuthClient";
import { DevAuthClient } from "./DevAuthClient";
import { MsalAuthClient } from "./MsalAuthClient";
import type { Identity } from "./types";

interface AuthContextValue {
  client: AuthClient;
  identity: Identity | null;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function buildClient(): AuthClient {
  if (config.authMode === "msal") {
    if (!config.msal.clientId || !config.msal.authority || !config.msal.apiScope) {
      throw new Error(
        "VITE_AUTH_MODE=msal but VITE_MSAL_CLIENT_ID / AUTHORITY / API_SCOPE are not set"
      );
    }
    return new MsalAuthClient(config.msal);
  }
  return new DevAuthClient(config.apiBase);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useMemo(buildClient, []);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    return client.onChange(() => setVersion((v) => v + 1));
  }, [client]);

  // Recompute identity whenever the client emits a change.
  const value = useMemo<AuthContextValue>(
    () => ({
      client,
      identity: client.getIdentity(),
      isAuthenticated: client.isAuthenticated(),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, version]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() outside AuthProvider");
  return ctx;
}
