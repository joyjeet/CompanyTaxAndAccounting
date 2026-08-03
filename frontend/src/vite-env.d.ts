/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUTH_MODE?: "dev" | "msal";
  readonly VITE_AUTHZ_SOURCE?: "claims" | "membership";
  readonly VITE_API_BASE?: string;
  readonly VITE_MSAL_CLIENT_ID?: string;
  readonly VITE_MSAL_AUTHORITY?: string;
  readonly VITE_MSAL_API_SCOPE?: string;
  readonly VITE_MSAL_REDIRECT_URI?: string;
  // Client portal authority (Entra External ID). Falls back to the values
  // above when unset, for single-authority deployments.
  readonly VITE_MSAL_CLIENT_CLIENT_ID?: string;
  readonly VITE_MSAL_CLIENT_AUTHORITY?: string;
  readonly VITE_MSAL_CLIENT_API_SCOPE?: string;
  readonly VITE_DEV_DEFAULT_FIRM_ID?: string;
  readonly VITE_DEV_DEFAULT_CLIENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
