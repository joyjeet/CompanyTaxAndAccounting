/**
 * Resolves *which* firm/client the signed-in user is acting as.
 *
 * With membership-based authorization the token no longer says. We ask the
 * backend (`GET /auth/context`) which contexts this person holds and then:
 *
 *   0 contexts  -> "none"   : authenticated but not onboarded. Signing in
 *                             again cannot fix this, so we must NOT bounce
 *                             them back to the identity provider.
 *   1 context   -> "ready"  : select it silently. Most users, always.
 *   2+ contexts -> "choose" : ask. A CPA who is also a client of another firm,
 *                             or staff at two practices, is a real case.
 */
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { useAuth } from "./AuthContext";
import config from "../config";
import { readSelection, writeSelection } from "./signInState";
import type { Identity } from "./types";

export interface ContextOption {
  firm_id: string;
  firm_name: string;
  role: string;
  scope: "firm" | "client";
  client_id: string | null;
  client_name: string | null;
}

export type TenantStatus = "loading" | "ready" | "choose" | "none" | "error";

interface TenantContextValue {
  status: TenantStatus;
  options: ContextOption[];
  selected: ContextOption | null;
  error: string | null;
  select: (option: ContextOption) => void;
  /** Return to the picker (only meaningful when more than one is available). */
  clear: () => void;
}

const TenantCtx = createContext<TenantContextValue | null>(null);

function matches(option: ContextOption, firmId: string, clientId?: string | null) {
  return (
    option.firm_id === firmId && (option.client_id ?? null) === (clientId ?? null)
  );
}

export function TenantProvider({ children }: { children: ReactNode }) {
  const { client, isAuthenticated } = useAuth();
  const [status, setStatus] = useState<TenantStatus>("loading");
  const [options, setOptions] = useState<ContextOption[]>([]);
  const [selected, setSelected] = useState<ContextOption | null>(null);
  const [error, setError] = useState<string | null>(null);

  const select = useCallback((option: ContextOption) => {
    writeSelection({ firmId: option.firm_id, clientId: option.client_id });
    setSelected(option);
    setStatus("ready");
  }, []);

  const clear = useCallback(() => {
    writeSelection(null);
    setSelected(null);
    setStatus("choose");
  }, []);

  useEffect(() => {
    // Claims mode: the token already carries the context, so there is nothing
    // to resolve and no picker to show.
    if (config.authzSource !== "membership") {
      setStatus("ready");
      return;
    }
    if (!isAuthenticated) {
      setStatus("loading");
      return;
    }

    let cancelled = false;
    (async () => {
      setStatus("loading");
      try {
        const token = await client.getAccessToken();
        const resp = await fetch(`${config.apiBase}/auth/context`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!resp.ok) throw new Error(`Sign-in context failed (${resp.status})`);
        const body = (await resp.json()) as { options: ContextOption[] };
        if (cancelled) return;

        const opts = body.options ?? [];
        setOptions(opts);

        if (opts.length === 0) {
          writeSelection(null);
          setStatus("none");
          return;
        }
        if (opts.length === 1) {
          select(opts[0]);
          return;
        }
        // Re-use a previous choice if it is still one of theirs. Access is
        // re-checked server-side on every request, so a stale entry here is a
        // UX detail, not a security hole.
        const prior = readSelection();
        const match = prior
          ? opts.find((o) => matches(o, prior.firmId, prior.clientId))
          : undefined;
        if (match) select(match);
        else {
          writeSelection(null);
          setStatus("choose");
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [client, isAuthenticated, select]);

  const value = useMemo<TenantContextValue>(
    () => ({ status, options, selected, error, select, clear }),
    [status, options, selected, error, select, clear]
  );

  return <TenantCtx.Provider value={value}>{children}</TenantCtx.Provider>;
}

export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantCtx);
  if (!ctx) throw new Error("useTenant() outside TenantProvider");
  return ctx;
}

/**
 * The identity the UI should render against.
 *
 * In membership mode the token carries no firm/client/role claims, so the
 * token-derived identity has nothing useful in it — the resolved context is
 * the only source. In claims mode we keep using the token so nothing about
 * the existing dev flow changes.
 *
 * Either way this drives presentation only; the backend re-authorizes every
 * request.
 */
export function useEffectiveIdentity(): Identity | null {
  const { identity } = useAuth();
  // Read the context directly rather than via useTenant(): this hook is used
  // in leaf components and tests that render without a TenantProvider, and in
  // claims mode it has nothing to contribute anyway.
  const tenant = useContext(TenantCtx);

  if (config.authzSource !== "membership") return identity;
  const selected = tenant?.selected ?? null;
  if (!selected) return null;
  return {
    sub: identity?.sub ?? "",
    firmId: selected.firm_id,
    clientId: selected.client_id,
    role: selected.scope === "client" ? "client_portal" : "firm_staff",
    expiresAt: identity?.expiresAt ?? 0,
  };
}
