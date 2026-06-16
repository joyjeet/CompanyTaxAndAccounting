/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUTH_MODE?: "dev" | "msal";
  readonly VITE_API_BASE?: string;
  readonly VITE_MSAL_CLIENT_ID?: string;
  readonly VITE_MSAL_AUTHORITY?: string;
  readonly VITE_MSAL_API_SCOPE?: string;
  readonly VITE_MSAL_REDIRECT_URI?: string;
  readonly VITE_DEV_DEFAULT_FIRM_ID?: string;
  readonly VITE_DEV_DEFAULT_CLIENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
