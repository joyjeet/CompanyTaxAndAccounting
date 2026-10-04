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

import config, { type Audience } from "../config";
import type { AuthClient } from "./AuthClient";
import { DevAuthClient } from "./DevAuthClient";
import { MsalAuthClient } from "./MsalAuthClient";
import { clearSignInState, readAudience, writeAudience } from "./signInState";
import type { Identity } from "./types";

interface AuthContextValue {
  client: AuthClient;
  identity: Identity | null;
  isAuthenticated: boolean;
  /** Which desk the user came through. Routing hint only, never a grant. */
  audience: Audience;
  /** Start an interactive sign-in against the authority for `audience`. */
  signIn: (audience: Audience) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function buildClient(audience: Audience): AuthClient {
  if (config.authMode === "msal") {
    const msal = config.msal[audience];
    if (!msal.clientId || !msal.authority || !msal.apiScope) {
      throw new Error(
        `VITE_AUTH_MODE=msal but the ${audience} authority is not configured ` +
          "(VITE_MSAL_CLIENT_ID / AUTHORITY / API_SCOPE)"
      );
    }
    return new MsalAuthClient(msal);
  }
  return new DevAuthClient(config.apiBase);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Seeded from storage so that returning from an MSAL redirect rebuilds the
  // same authority the user originally chose.
  const [audience, setAudience] = useState<Audience>(readAudience);
  const client = useMemo(() => buildClient(audience), [audience]);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    return client.onChange(() => setVersion((v) => v + 1));
  }, [client]);

  const value = useMemo<AuthContextValue>(
    () => ({
      client,
      identity: client.getIdentity(),
      isAuthenticated: client.isAuthenticated(),
      audience,
      signIn: async (next: Audience) => {
        writeAudience(next);
        setAudience(next);
        // In msal mode this navigates away, so the state update above only
        // matters for the dev client. Build the target client directly rather
        // than waiting for the re-render.
        if (config.authMode === "msal") await buildClient(next).login();
      },
      signOut: async () => {
        clearSignInState();
        await client.logout();
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, version, audience]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() outside AuthProvider");
  return ctx;
}
