/**
 * Typed fetch wrapper. Pulls the bearer from the active `AuthClient` and
 * surfaces non-2xx responses as `ApiError` with a parsed message.
 */
import config from "../config";
import type { AuthClient } from "../auth/AuthClient";
import type {
  ArtifactOut,
  BalanceSheetOut,
  CashFlowOut,
  ClientOut,
  CoaOut,
  DocumentOut,
  DocumentDetailOut,
  DraftOut,
  JournalEntryCreateIn,
  JournalEntryOut,
  MappingOut,
  PeriodOut,
  ProfitAndLossOut,
  ResetOut,
  SeedOut,
  TaxFormDetailOut,
  TaxFormOut,
  TrialBalanceOut,
  UploadOut,
  WorksheetDetailOut,
  WorksheetOut,
  AutoProposeOut,
  AutoFillOut,
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
          ? typeof (body as Record<string, unknown>).detail === "string"
            ? String((body as Record<string, unknown>).detail)
            : JSON.stringify((body as Record<string, unknown>).detail)
          : null) ?? text ?? `HTTP ${resp.status}`;
      throw new ApiError(resp.status, detail, body);
    }
    return body as T;
  }

  private json<T>(path: string, method: string, body: unknown): Promise<T> {
    return this.request<T>(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  // ----- Clients -------------------------------------------------- //
  listClients(): Promise<ClientOut[]> {
    return this.request<ClientOut[]>("/clients");
  }

  getClient(id: string): Promise<ClientOut> {
    return this.request<ClientOut>(`/clients/${id}`);
  }

  createClient(body: { name: string; external_code?: string | null }): Promise<ClientOut> {
    return this.json<ClientOut>("/clients", "POST", body);
  }

  // ----- Periods -------------------------------------------------- //
  listPeriods(clientId: string): Promise<PeriodOut[]> {
    return this.request<PeriodOut[]>(`/clients/${clientId}/periods`);
  }

  createPeriod(
    clientId: string,
    body: { name: string; start_date: string; end_date: string },
  ): Promise<PeriodOut> {
    return this.json<PeriodOut>(`/clients/${clientId}/periods`, "POST", body);
  }

  // ----- Chart of accounts --------------------------------------- //
  listAccounts(clientId: string): Promise<CoaOut[]> {
    return this.request<CoaOut[]>(`/clients/${clientId}/chart-of-accounts`);
  }

  createAccount(
    clientId: string,
    body: {
      code: string;
      name: string;
      account_type: string;
      normal_balance: string;
    },
  ): Promise<CoaOut> {
    return this.json<CoaOut>(`/clients/${clientId}/chart-of-accounts`, "POST", body);
  }

  // ----- Documents ----------------------------------------------- //
  listDocuments(): Promise<DocumentOut[]> {
    return this.request<DocumentOut[]>("/documents");
  }

  /** Full detail for a single uploaded document, including OCR text/fields
   * and the drafts/journal entries derived from it. */
  getDocument(id: string): Promise<DocumentDetailOut> {
    return this.request<DocumentDetailOut>(`/documents/${id}`);
  }

  /** Returns a function that fetches the original file bytes for inline
   * preview. Includes the bearer token so it works against the deployed
   * API. Use `URL.createObjectURL(blob)` on the result. */
  async downloadDocumentBlob(id: string): Promise<Blob> {
    const token = await this.auth.getAccessToken();
    const headers = new Headers();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const resp = await fetch(`${this.base}/documents/${id}/download`, {
      headers,
    });
    if (!resp.ok) {
      throw new ApiError(resp.status, `HTTP ${resp.status} downloading document`);
    }
    return resp.blob();
  }

  uploadDocument(
    file: File,
    kindHint = "generic",
    clientId?: string,
  ): Promise<UploadOut> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind_hint", kindHint);
    // Firm-staff sessions don't carry a client_id on the token; the active
    // client is known from the URL on /clients/:id/* pages and must be sent
    // explicitly so the upload lands against the right tenant.
    if (clientId) fd.append("client_id", clientId);
    return this.request<UploadOut>("/documents/upload", {
      method: "POST",
      body: fd,
    });
  }

  // ----- Drafts -------------------------------------------------- //
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
    },
  ): Promise<{ journal_entry_id: string }> {
    return this.json(`/drafts/${draftId}/promote`, "POST", body);
  }

  rejectDraft(draftId: string, reason?: string): Promise<void> {
    return this.json(`/drafts/${draftId}/reject`, "POST", { reason: reason ?? null });
  }

  promoteStatementDraft(
    draftId: string,
    body: {
      period_id: string;
      cash_account_code?: string;
      account_overrides?: Record<string, string>;
    },
  ): Promise<{ journal_entry_ids: string[]; skipped: Array<{ index: string; reason: string }> }> {
    return this.json(`/drafts/${draftId}/promote-all`, "POST", body);
  }

  // ----- Journal entries ----------------------------------------- //
  listJournalEntries(clientId: string, periodId?: string): Promise<JournalEntryOut[]> {
    const params = new URLSearchParams({ client_id: clientId });
    if (periodId) params.set("period_id", periodId);
    return this.request<JournalEntryOut[]>(`/journal-entries?${params.toString()}`);
  }

  getJournalEntry(entryId: string): Promise<JournalEntryOut> {
    return this.request<JournalEntryOut>(`/journal-entries/${entryId}`);
  }

  postJournalEntry(body: JournalEntryCreateIn): Promise<JournalEntryOut> {
    return this.json<JournalEntryOut>("/journal-entries", "POST", body);
  }

  // ----- Statements (inline preview) ----------------------------- //
  getProfitAndLoss(clientId: string, periodId: string): Promise<ProfitAndLossOut> {
    const q = new URLSearchParams({ client_id: clientId, period_id: periodId });
    return this.request<ProfitAndLossOut>(`/statements/profit-and-loss?${q}`);
  }

  getBalanceSheet(clientId: string, periodId: string): Promise<BalanceSheetOut> {
    const q = new URLSearchParams({ client_id: clientId, period_id: periodId });
    return this.request<BalanceSheetOut>(`/statements/balance-sheet?${q}`);
  }

  getCashFlow(
    clientId: string,
    periodId: string,
    cashAccountCodes?: string[],
  ): Promise<CashFlowOut> {
    const q = new URLSearchParams({ client_id: clientId, period_id: periodId });
    if (cashAccountCodes && cashAccountCodes.length > 0) {
      q.set("cash_account_codes", cashAccountCodes.join(","));
    }
    return this.request<CashFlowOut>(`/statements/cash-flow?${q}`);
  }

  getTrialBalance(clientId: string, periodId: string): Promise<TrialBalanceOut> {
    const q = new URLSearchParams({ client_id: clientId, period_id: periodId });
    return this.request<TrialBalanceOut>(`/statements/trial-balance?${q}`);
  }

  // ----- Demo / seed helpers ------------------------------------- //
  /**
   * Idempotently seed a starter chart of accounts and an open period for
   * the client. Returns counts of what was created vs already present.
   * Only mounted on non-prod envs (dev / staging); 404 in production.
   */
  seedDefaults(clientId: string, postSamples = true): Promise<SeedOut> {
    const q = new URLSearchParams({
      client_id: clientId,
      post_samples: String(postSamples),
    });
    return this.json<SeedOut>(`/dev/seed-defaults?${q}`, "POST", {});
  }

  /**
   * Wipe transactional data for a client (drafts, journal entries, source
   * documents, artifacts) so the demo can start fresh. Preserves the chart
   * of accounts and accounting periods. Non-prod only.
   */
  resetClient(clientId: string, keepAudit = true): Promise<ResetOut> {
    const q = new URLSearchParams({
      client_id: clientId,
      keep_audit: String(keepAudit),
    });
    return this.json<ResetOut>(`/dev/reset-client?${q}`, "POST", {});
  }

  // ----- Reports / artifacts ------------------------------------- //
  generateStatementArtifact(body: {
    period_id: string;
    kind: string;
    format: string;
    cash_account_codes?: string[];
    prior_period_id?: string;
  }): Promise<ArtifactOut> {
    return this.json<ArtifactOut>("/reports/statements/generate", "POST", body);
  }

  listArtifacts(opts?: { period_id?: string; kind?: string }): Promise<ArtifactOut[]> {
    const q = new URLSearchParams();
    if (opts?.period_id) q.set("period_id", opts.period_id);
    if (opts?.kind) q.set("kind", opts.kind);
    const tail = q.toString() ? `?${q}` : "";
    return this.request<ArtifactOut[]>(`/reports/artifacts${tail}`);
  }

  finalizeArtifact(id: string): Promise<ArtifactOut> {
    return this.json<ArtifactOut>(`/reports/artifacts/${id}/finalize`, "POST", {});
  }

  async downloadArtifact(id: string): Promise<{ blob: Blob; filename: string }> {
    const token = await this.auth.getAccessToken();
    const headers = new Headers();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const resp = await fetch(`${this.base}/reports/artifacts/${id}/download`, { headers });
    if (!resp.ok) {
      throw new ApiError(resp.status, `download failed: HTTP ${resp.status}`);
    }
    const disp = resp.headers.get("Content-Disposition") ?? "";
    const m = /filename="?([^";]+)"?/.exec(disp);
    const filename = m ? m[1] : `artifact-${id}`;
    const blob = await resp.blob();
    return { blob, filename };
  }

  // ----- Tax ----------------------------------------------------- //
  listTaxForms(): Promise<TaxFormOut[]> {
    return this.request<TaxFormOut[]>("/tax/forms");
  }

  getTaxForm(code: string): Promise<TaxFormDetailOut> {
    return this.request<TaxFormDetailOut>(`/tax/forms/${code}`);
  }

  listMappings(formCode?: string): Promise<MappingOut[]> {
    const q = formCode ? `?form_code=${formCode}` : "";
    return this.request<MappingOut[]>(`/tax/mappings${q}`);
  }

  proposeMapping(body: {
    form_id: string;
    account_id: string;
    line_id: string;
    sign?: string;
    notes?: string;
  }): Promise<MappingOut> {
    return this.json<MappingOut>("/tax/mappings", "POST", body);
  }

  approveMapping(id: string): Promise<MappingOut> {
    return this.json<MappingOut>(`/tax/mappings/${id}/approve`, "POST", {});
  }

  rejectMapping(id: string, reason?: string): Promise<MappingOut> {
    return this.json<MappingOut>(`/tax/mappings/${id}/reject`, "POST", {
      reason: reason ?? null,
    });
  }

  listWorksheets(periodId?: string, formCode?: string): Promise<WorksheetOut[]> {
    const q = new URLSearchParams();
    if (periodId) q.set("period_id", periodId);
    if (formCode) q.set("form_code", formCode);
    const tail = q.toString() ? `?${q}` : "";
    return this.request<WorksheetOut[]>(`/tax/worksheets${tail}`);
  }

  getWorksheet(id: string): Promise<WorksheetDetailOut> {
    return this.request<WorksheetDetailOut>(`/tax/worksheets/${id}`);
  }

  generateWorksheet(body: { period_id: string; form_code: string }): Promise<WorksheetDetailOut> {
    return this.json<WorksheetDetailOut>("/tax/worksheets", "POST", body);
  }

  approveWorksheet(id: string): Promise<WorksheetDetailOut> {
    return this.json<WorksheetDetailOut>(`/tax/worksheets/${id}/approve`, "POST", {});
  }

  /**
   * Render an approved tax worksheet into an encrypted Artifact (PDF or
   * JSON). The result lands in the Artifacts library where it can be
   * finalized and downloaded.
   */
  renderTaxWorksheet(id: string, format: "pdf" | "json" = "pdf"): Promise<ArtifactOut> {
    const q = new URLSearchParams({ format });
    return this.json<ArtifactOut>(
      `/reports/tax-worksheets/${id}/render?${q}`,
      "POST",
      {},
    );
  }

  autoProposeMappings(body: { form_code: string }): Promise<AutoProposeOut> {
    return this.json<AutoProposeOut>("/tax/mappings/auto-propose", "POST", body);
  }

  approveAllMappings(body: { form_code: string }): Promise<string[]> {
    return this.json<string[]>("/tax/mappings/approve-all", "POST", body);
  }

  autoFillWorksheet(body: { period_id: string; form_code: string }): Promise<AutoFillOut> {
    return this.json<AutoFillOut>("/tax/auto-fill", "POST", body);
  }
}
