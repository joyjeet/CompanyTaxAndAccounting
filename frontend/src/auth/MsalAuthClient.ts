/**
 * Entra ID auth-code/PKCE via @azure/msal-browser.
 *
 * Notes:
 *   - We use `acquireTokenSilent` for the API scope and fall back to
 *     `acquireTokenRedirect` if the cache is empty/expired.
 *   - We do NOT store tokens in localStorage by default; MSAL's session
 *     storage is preferred so they're cleared on tab close. (Configurable.)
 *   - The configured `apiScope` MUST be the API's app-id-uri scope (e.g.
 *     `api://<api-client-id>/access`) — NOT the SPA's own client id.
 *     Requesting the SPA's own scope returns an id-token, not an
 *     access-token, and the backend's RS256 validator will reject it.
 */
import {
  type AccountInfo,
  type AuthenticationResult,
  EventType,
  PublicClientApplication,
} from "@azure/msal-browser";

import type { AuthClient } from "./AuthClient";
import { tokenToIdentity } from "./jwt";
import type { Identity } from "./types";

export interface MsalConfig {
  clientId: string;
  authority: string;
  apiScope: string;
  redirectUri: string;
}

export class MsalAuthClient implements AuthClient {
  private app: PublicClientApplication;
  private identity: Identity | null = null;
  private currentToken: string | null = null;
  private listeners = new Set<() => void>();
  private initPromise: Promise<void>;

  constructor(private config: MsalConfig) {
    this.app = new PublicClientApplication({
      auth: {
        clientId: config.clientId,
        authority: config.authority,
        redirectUri: config.redirectUri,
        navigateToLoginRequestUrl: true,
      },
      cache: {
        cacheLocation: "sessionStorage",
        storeAuthStateInCookie: false,
      },
    });

    this.app.addEventCallback((evt) => {
      if (
        evt.eventType === EventType.LOGIN_SUCCESS ||
        evt.eventType === EventType.ACQUIRE_TOKEN_SUCCESS
      ) {
        const result = evt.payload as AuthenticationResult | null;
        if (result?.accessToken) this.applyToken(result.accessToken);
      }
      if (evt.eventType === EventType.LOGOUT_SUCCESS) {
        this.currentToken = null;
        this.identity = null;
        this.notify();
      }
    });

    this.initPromise = this.app.initialize().then(async () => {
      // Complete a redirect-flow login if we are returning from one.
      const result = await this.app.handleRedirectPromise();
      if (result?.accessToken) this.applyToken(result.accessToken);
    });
  }

  isAuthenticated(): boolean {
    return this.currentToken !== null;
  }

  getIdentity(): Identity | null {
    return this.identity;
  }

  async getAccessToken(): Promise<string | null> {
    await this.initPromise;
    const account = this.activeAccount();
    if (!account) return null;
    try {
      const result = await this.app.acquireTokenSilent({
        account,
        scopes: [this.config.apiScope],
      });
      this.applyToken(result.accessToken);
      return result.accessToken;
    } catch {
      // Silent failed — caller should trigger an interactive login.
      return null;
    }
  }

  async login(): Promise<void> {
    await this.initPromise;
    await this.app.loginRedirect({
      scopes: [this.config.apiScope],
      redirectUri: this.config.redirectUri,
    });
  }

  async logout(): Promise<void> {
    await this.initPromise;
    await this.app.logoutRedirect({ postLogoutRedirectUri: this.config.redirectUri });
  }

  onChange(cb: () => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  private activeAccount(): AccountInfo | null {
    return this.app.getActiveAccount() ?? this.app.getAllAccounts()[0] ?? null;
  }

  private applyToken(token: string): void {
    this.currentToken = token;
    this.identity = tokenToIdentity(token);
    this.notify();
  }

  private notify(): void {
    for (const l of this.listeners) l();
  }
}
