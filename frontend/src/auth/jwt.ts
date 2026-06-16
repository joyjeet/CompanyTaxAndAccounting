/**
 * Decode a JWT *without* verifying — we only use this to extract claims for
 * UI hints. The backend re-validates the token on every API call, so trust
 * here is bounded: the worst case from a tampered/expired token is a UI
 * that asks for the wrong page; the API will still 401.
 */

import type { Identity, Role } from "./types";

interface RawClaims {
  sub?: string;
  exp?: number;
  firm_id?: string;
  client_id?: string;
  roles?: string[] | string;
}

function base64UrlDecode(input: string): string {
  const pad = input.length % 4 === 2 ? "==" : input.length % 4 === 3 ? "=" : "";
  const base64 = (input + pad).replace(/-/g, "+").replace(/_/g, "/");
  return atob(base64);
}

export function parseJwtUnsafe(token: string): RawClaims | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const json = decodeURIComponent(
      base64UrlDecode(parts[1])
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(json) as RawClaims;
  } catch {
    return null;
  }
}

export function tokenToIdentity(token: string): Identity | null {
  const c = parseJwtUnsafe(token);
  if (!c?.sub || !c.firm_id || !c.exp) return null;
  const rolesArr = Array.isArray(c.roles) ? c.roles : c.roles ? [c.roles] : [];
  let role: Role | null = null;
  if (rolesArr.includes("firm_staff")) role = "firm_staff";
  else if (rolesArr.includes("client_portal")) role = "client_portal";
  if (!role) return null;
  return {
    sub: c.sub,
    firmId: c.firm_id,
    clientId: c.client_id ?? null,
    role,
    expiresAt: c.exp,
  };
}

export function tokenIsExpired(token: string, skewSeconds = 30): boolean {
  const id = tokenToIdentity(token);
  if (!id) return true;
  const now = Math.floor(Date.now() / 1000);
  return id.expiresAt - skewSeconds <= now;
}
