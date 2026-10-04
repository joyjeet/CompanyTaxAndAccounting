/**
 * Dev-only auth client. Calls the backend's /auth/dev-token to mint an
 * HS256 JWT for a chosen role+firm. Token is held in memory ONLY (not in
 * localStorage) — refreshing the page logs you out, which is the right
 * behaviour for a dev shim.
 */
import type { AuthClient, DevLoginRequest } from "./AuthClient";
import { tokenIsExpired, tokenToIdentity } from "./jwt";
import type { Identity } from "./types";

const STORAGE_KEY = "ctaa.dev.token";

export class DevAuthClient implements AuthClient {
  private token: string | null = null;
  private identity: Identity | null = null;
  private listeners = new Set<() => void>();

  constructor(private apiBase: string) {
    // Persist across reloads in dev only — not security-sensitive because
    // dev mode is gated server-side. Real prod uses MSAL.
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (stored && !tokenIsExpired(stored)) {
      this.token = stored;
      this.identity = tokenToIdentity(stored);
    } else if (stored) {
      sessionStorage.removeItem(STORAGE_KEY);
    }
  }

  isAuthenticated(): boolean {
    return this.token !== null && !tokenIsExpired(this.token);
  }

  getIdentity(): Identity | null {
    return this.identity;
  }

  async getAccessToken(): Promise<string | null> {
    if (!this.token) return null;
    if (tokenIsExpired(this.token)) {
      this.token = null;
      this.identity = null;
      sessionStorage.removeItem(STORAGE_KEY);
      this.notify();
      return null;
    }
    return this.token;
  }

  async login(req?: DevLoginRequest): Promise<void> {
    if (!req) throw new Error("DevAuthClient.login requires a request body");
    const body = {
      sub: req.sub,
      role: req.role,
      firm_id: req.firmId ?? null,
      client_id: req.clientId ?? null,
    };
    const resp = await fetch(`${this.apiBase}/auth/dev-token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const detail = await resp.text();
      throw new Error(`dev-token failed (${resp.status}): ${detail}`);
    }
    const data = (await resp.json()) as { access_token: string };
    this.token = data.access_token;
    this.identity = tokenToIdentity(this.token);
    if (!this.identity) {
      this.token = null;
      throw new Error("dev-token returned a malformed token");
    }
    sessionStorage.setItem(STORAGE_KEY, this.token);
    this.notify();
  }

  async logout(): Promise<void> {
    this.token = null;
    this.identity = null;
    sessionStorage.removeItem(STORAGE_KEY);
    this.notify();
  }

  onChange(cb: () => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  private notify(): void {
    for (const l of this.listeners) l();
  }
}
