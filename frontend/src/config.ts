/**
 * Application config sourced from import.meta.env. All Vite env vars are
 * prefixed VITE_ and inlined at build time. Secrets MUST NOT be placed
 * here — only public config like client IDs and authority URLs.
 */

export type AuthMode = "dev" | "msal";

/**
 * Where the firm/client/scope come from once the token is verified. Mirrors
 * the backend's APP_AUTHZ_SOURCE and must be set to match it.
 *
 *   claims     — the token carries firm_id/client_id/roles.
 *   membership — the backend resolves them from firm_membership, so the SPA
 *                asks GET /auth/context and may need the user to pick one.
 */
export type AuthzSource = "claims" | "membership";

/** Which sign-in desk the user came through. NOT a permission grant. */
export type Audience = "firm" | "client";

export interface MsalAudienceConfig {
  clientId: string;
  authority: string;
  apiScope: string;
  redirectUri: string;
}

export interface AppConfig {
  authMode: AuthMode;
  authzSource: AuthzSource;
  apiBase: string;
  msal: Record<Audience, MsalAudienceConfig>;
  dev: {
    defaultFirmId: string;
    defaultClientId: string;
  };
}

function read(name: string, fallback = ""): string {
  const v = (import.meta.env as Record<string, string | undefined>)[name];
  if (v == null) return fallback;
  const trimmed = v.trim();
  return trimmed === "" ? fallback : trimmed;
}

const redirectUri = read("VITE_MSAL_REDIRECT_URI", window.location.origin);

// Staff sign in against the workforce tenant.
const firmMsal: MsalAudienceConfig = {
  clientId: read("VITE_MSAL_CLIENT_ID"),
  authority: read("VITE_MSAL_AUTHORITY"),
  apiScope: read("VITE_MSAL_API_SCOPE"),
  redirectUri,
};

// Clients sign in against Entra External ID — a separate authority, and often
// a separate app registration. Each value falls back to the firm setting so a
// single-authority deployment keeps working with no extra configuration.
const clientMsal: MsalAudienceConfig = {
  clientId: read("VITE_MSAL_CLIENT_CLIENT_ID", firmMsal.clientId),
  authority: read("VITE_MSAL_CLIENT_AUTHORITY", firmMsal.authority),
  apiScope: read("VITE_MSAL_CLIENT_API_SCOPE", firmMsal.apiScope),
  redirectUri,
};

const cfg: AppConfig = {
  authMode: read("VITE_AUTH_MODE", "dev") as AuthMode,
  authzSource: read("VITE_AUTHZ_SOURCE", "claims") as AuthzSource,
  apiBase: read("VITE_API_BASE", ""),
  msal: { firm: firmMsal, client: clientMsal },
  dev: {
    defaultFirmId: read("VITE_DEV_DEFAULT_FIRM_ID"),
    defaultClientId: read("VITE_DEV_DEFAULT_CLIENT_ID"),
  },
};

export default cfg;
