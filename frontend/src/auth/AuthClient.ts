/**
 * Auth provider abstraction.
 *
 * Two implementations sit behind the `AuthClient` interface:
 *   - `MsalAuthClient`  : Entra ID auth-code/PKCE via @azure/msal-browser.
 *   - `DevAuthClient`   : calls the backend's /auth/dev-token to mint an
 *                         HS256 JWT. Used in local dev and CI only.
 *
 * Both produce a bearer token + a parsed identity (firm_id, client_id, role).
 * The rest of the app talks to this interface; nothing else imports msal.
 */
import type { Identity } from "./types";

export interface DevLoginRequest {
  sub: string;
  role: "firm_staff" | "client_portal";
  firmId: string;
  clientId?: string;
}

export interface AuthClient {
  /** Returns the current bearer token (refreshing if necessary), or null. */
  getAccessToken(): Promise<string | null>;
  /** Cached identity derived from the latest token. */
  getIdentity(): Identity | null;
  /** True if a usable token is currently held. */
  isAuthenticated(): boolean;
  /** Mode-specific entry point. Dev: pass the role; msal: redirect to AAD. */
  login(req?: DevLoginRequest): Promise<void>;
  logout(): Promise<void>;
  /** Subscribe to identity changes. Returns an unsubscribe fn. */
  onChange(cb: () => void): () => void;
}
