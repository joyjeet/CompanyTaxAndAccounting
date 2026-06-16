/**
 * Typed fetch wrapper. Pulls the bearer from the active `AuthClient` and
 * surfaces non-2xx responses as `ApiError` with a parsed message.
 */
import config from "../config";
import type { AuthClient } from "../auth/AuthClient";
import type {
  ClientOut,
  DocumentOut,
  DraftOut,
  UploadOut,
} from "../auth/types";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

export class ApiClient {
  constructor(private auth: AuthClient, private base = config.apiBase) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const token = await this.auth.getAccessToken();
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    const resp = await fetch(`${this.base}${path}`, { ...init, headers });
    if (resp.status === 204) return undefined as T;
    const text = await resp.text();
    let body: unknown = text;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      // leave body as text.
    }
    if (!resp.ok) {
      const detail =
        (typeof body === "object" && body && "detail" in body
          ? String((body as Record<string, unknown>).detail)
          : null) ?? text ?? `HTTP ${resp.status}`;
      throw new ApiError(resp.status, detail, body);
    }
    return body as T;
  }

  // ----- Documents -------------------------------------------------- //
  listDocuments(): Promise<DocumentOut[]> {
    return this.request<DocumentOut[]>("/documents");
  }

  uploadDocument(file: File, kindHint = "generic"): Promise<UploadOut> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind_hint", kindHint);
    return this.request<UploadOut>("/documents/upload", {
      method: "POST",
      body: fd,
    });
  }

  // ----- Drafts ----------------------------------------------------- //
  listDrafts(pendingOnly = true): Promise<DraftOut[]> {
    const q = pendingOnly ? "?pending_only=true" : "?pending_only=false";
    return this.request<DraftOut[]>(`/drafts${q}`);
  }

  promoteDraft(
    draftId: string,
    body: {
      period_id: string;
      entry_date: string;
      memo?: string;
      lines: Array<{
        account_id: string;
        debit: string;
        credit: string;
        description?: string;
      }>;
    }
  ): Promise<{ journal_entry_id: string }> {
    return this.request(`/drafts/${draftId}/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  rejectDraft(draftId: string, reason?: string): Promise<void> {
    return this.request(`/drafts/${draftId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? null }),
    });
  }

  // ----- Clients --------------------------------------------------- //
  listClients(): Promise<ClientOut[]> {
    return this.request<ClientOut[]>("/clients");
  }
}
