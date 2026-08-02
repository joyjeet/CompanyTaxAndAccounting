/**
 * Application config sourced from import.meta.env. All Vite env vars are
 * prefixed VITE_ and inlined at build time. Secrets MUST NOT be placed
 * here — only public config like client IDs and authority URLs.
 */

export type AuthMode = "dev" | "msal";

export interface AppConfig {
  authMode: AuthMode;
  apiBase: string;
  msal: {
    clientId: string;
    authority: string;
    apiScope: string;
    redirectUri: string;
  };
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

const cfg: AppConfig = {
  authMode: (read("VITE_AUTH_MODE", "dev") as AuthMode),
  apiBase: read("VITE_API_BASE", "/api"),
  msal: {
    clientId: read("VITE_MSAL_CLIENT_ID"),
    authority: read("VITE_MSAL_AUTHORITY"),
    apiScope: read("VITE_MSAL_API_SCOPE"),
    redirectUri: read("VITE_MSAL_REDIRECT_URI", window.location.origin),
  },
  dev: {
    defaultFirmId: read("VITE_DEV_DEFAULT_FIRM_ID"),
    defaultClientId: read("VITE_DEV_DEFAULT_CLIENT_ID"),
  },
};

export default cfg;
