/**
 * Which sign-in desk the user came through, and which tenant context they
 * picked. Both survive the MSAL redirect (the SPA is torn down and rebooted
 * mid-flow, so this cannot live in React state alone).
 *
 * SECURITY: neither of these is a grant. The audience only decides which
 * authority to redirect to; the tenant context is only ever sent as a *hint*
 * that the backend validates against the user's own memberships. Tampering
 * with either can narrow what you see, never widen it.
 */
import type { Audience } from "../config";

const AUDIENCE_KEY = "ctaa.audience";
const CONTEXT_KEY = "ctaa.context";

export interface TenantSelection {
  firmId: string;
  clientId?: string | null;
}

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    // Storage can be unavailable (some incognito / embedded webviews).
    return null;
  }
}

export function readAudience(): Audience {
  const v = storage()?.getItem(AUDIENCE_KEY);
  return v === "client" ? "client" : "firm";
}

export function writeAudience(a: Audience): void {
  try {
    storage()?.setItem(AUDIENCE_KEY, a);
  } catch {
    /* ignore */
  }
}

export function readSelection(): TenantSelection | null {
  const raw = storage()?.getItem(CONTEXT_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as TenantSelection;
    return parsed && typeof parsed.firmId === "string" ? parsed : null;
  } catch {
    return null;
  }
}

export function writeSelection(sel: TenantSelection | null): void {
  try {
    if (sel === null) storage()?.removeItem(CONTEXT_KEY);
    else storage()?.setItem(CONTEXT_KEY, JSON.stringify(sel));
  } catch {
    /* ignore */
  }
}

export function clearSignInState(): void {
  try {
    storage()?.removeItem(CONTEXT_KEY);
    storage()?.removeItem(AUDIENCE_KEY);
  } catch {
    /* ignore */
  }
}
