/**
 * Shared types mirroring backend Pydantic models. The frontend never trusts
 * these for security decisions — the backend re-validates the JWT on every
 * request — but uses them to render the right UI per role.
 */

export type Role = "firm_staff" | "client_portal";

export interface Identity {
  sub: string;
  firmId: string;
  clientId: string | null;
  role: Role;
  /** Epoch seconds. */
  expiresAt: number;
}

// --------------------------------------------------------------------- //
// Drafts
// --------------------------------------------------------------------- //
export interface DraftOut {
  id: string;
  source_document_id: string;
  kind: string;
  status: string;
  confidence: string;
  high_confidence: boolean;
  needs_review: boolean;
  model: string;
  prompt_version: string;
  payload: Record<string, unknown>;
}

// --------------------------------------------------------------------- //
// Documents
// --------------------------------------------------------------------- //
export interface DocumentOut {
  id: string;
  client_id: string;
  kind: string;
  filename: string | null;
  content_type: string | null;
  sha256: string;
  ocr_status: string;
  ocr_completed_at: string | null;
  ocr_error: string | null;
  received_at: string;
}

export interface UploadOut {
  source_document_id: string;
  storage_uri: string;
  sha256: string;
  deduped: boolean;
  job_id: string | null;
  auto_promoted_count?: number;
}

export interface ExtractedField {
  name: string;
  value: string;
  confidence?: number;
}

export interface DocumentDetailOut {
  id: string;
  client_id: string;
  kind: string;
  filename: string | null;
  content_type: string | null;
  sha256: string;
  storage_uri: string;
  size_bytes: number | null;
  ocr_status: string;
  ocr_completed_at: string | null;
  ocr_error: string | null;
  received_at: string;
  uploaded_by: string | null;
  extracted: {
    text?: string;
    fields?: ExtractedField[];
    model?: string;
    model_version?: string;
    page_count?: number;
    warnings?: string[];
    [k: string]: unknown;
  } | null;
  drafts: Array<{
    id: string;
    kind: string;
    status: string;
    confidence: string;
    promoted_journal_entry_id: string | null;
  }>;
  journal_entries: Array<{
    id: string;
    entry_date: string;
    memo: string | null;
    status: string;
  }>;
}

export interface SeedOut {
  client_id: string;
  accounts_created: string[];
  accounts_existing: string[];
  period_id: string;
  period_created: boolean;
  sample_entries_posted: number;
  notes: string[];
}

export interface ResetOut {
  client_id: string;
  deleted: Record<string, number>;
  notes: string[];
}

// --------------------------------------------------------------------- //
// Clients / Periods / COA
// --------------------------------------------------------------------- //
export interface ClientOut {
  id: string;
  firm_id: string;
  name: string;
  external_code: string | null;
}

export interface PeriodOut {
  id: string;
  client_id: string;
  name: string;
  start_date: string; // ISO date
  end_date: string;   // ISO date
  is_locked: boolean;
}

export type AccountType = "asset" | "liability" | "equity" | "revenue" | "expense";
export type NormalBalance = "debit" | "credit";

export interface CoaOut {
  id: string;
  client_id: string;
  code: string;
  name: string;
  account_type: AccountType;
  normal_balance: NormalBalance;
  is_active: boolean;
}

// --------------------------------------------------------------------- //
// Journal Entries
// --------------------------------------------------------------------- //
export interface JournalLineOut {
  id: string;
  line_no: number;
  account_id: string;
  debit: string;   // Decimal as string
  credit: string;
  description: string | null;
}

export interface JournalEntryOut {
  id: string;
  client_id: string;
  period_id: string;
  entry_date: string;
  memo: string | null;
  status: string;
  source_document_id: string | null;
  lines: JournalLineOut[];
}

export interface JournalLineIn {
  account_id: string;
  debit: string;
  credit: string;
  description?: string | null;
}

export interface JournalEntryCreateIn {
  client_id: string;
  period_id: string;
  entry_date: string;
  memo?: string | null;
  lines: JournalLineIn[];
}

// --------------------------------------------------------------------- //
// Statements (inline preview)
// --------------------------------------------------------------------- //
export interface AccountBalanceOut {
  account_id: string;
  code: string;
  name: string;
  account_type: AccountType;
  debit_total: string;
  credit_total: string;
  signed_balance: string;
}

export interface ProfitAndLossOut {
  kind: "profit_and_loss";
  period_start: string;
  period_end: string;
  revenue: AccountBalanceOut[];
  expenses: AccountBalanceOut[];
  total_revenue: string;
  total_expenses: string;
  net_income: string;
}

export interface BalanceSheetOut {
  kind: "balance_sheet";
  as_of: string;
  assets: AccountBalanceOut[];
  liabilities: AccountBalanceOut[];
  equity: AccountBalanceOut[];
  total_assets: string;
  total_liabilities: string;
  total_equity: string;
  retained_earnings_to_date: string;
  balances: boolean;
}

export interface CashFlowOut {
  kind: "cash_flow";
  period_start: string;
  period_end: string;
  cash_account_codes: string[];
  opening_cash: string;
  closing_cash: string;
  net_change: string;
  inflows: string;
  outflows: string;
}

export interface TrialBalanceOut {
  kind: "trial_balance";
  as_of: string;
  rows: AccountBalanceOut[];
  total_debits: string;
  total_credits: string;
  balances: boolean;
}

// --------------------------------------------------------------------- //
// Reports / Artifacts
// --------------------------------------------------------------------- //
export type ArtifactKind =
  | "profit_and_loss"
  | "balance_sheet"
  | "cash_flow"
  | "tax_worksheet"
  | "audit_package"
  | "narrative";

export type ArtifactFormat = "pdf" | "json" | "csv" | "xlsx" | "zip" | "md";

export interface ArtifactOut {
  id: string;
  firm_id: string;
  client_id: string;
  period_id: string | null;
  tax_worksheet_id: string | null;
  kind: string;
  format: string;
  status: string;
  title: string;
  plaintext_sha256: string;
  size_bytes: number;
  generated_by: string;
  finalized_by: string | null;
  parameters: Record<string, unknown>;
}

// --------------------------------------------------------------------- //
// Tax
// --------------------------------------------------------------------- //
export interface TaxFormOut {
  id: string;
  code: string;
  label: string;
  jurisdiction: string;
  catalog_version: string;
  is_active: boolean;
}

export interface TaxFormLineOut {
  id: string;
  code: string;
  label: string;
  section: string;
  sequence: number;
  description: string | null;
}

export interface TaxFormDetailOut extends TaxFormOut {
  lines: TaxFormLineOut[];
}

export interface MappingOut {
  id: string;
  form_id: string;
  account_id: string;
  line_id: string;
  sign: string;
  status: string;
  notes: string | null;
  proposed_by: string;
  reviewed_by: string | null;
}

export interface WorksheetOut {
  id: string;
  period_id: string;
  form_id: string;
  status: string;
  catalog_version: string;
  total_income: string;
  total_cogs: string;
  total_deductions: string;
  taxable_income: string;
  sha256: string;
  generated_by: string;
  approved_by: string | null;
}

export interface WorksheetLineOut {
  line_code: string;
  line_label: string;
  section: string;
  sequence: number;
  amount: string;
  contributing_accounts: Array<Record<string, unknown>>;
}

export interface WorksheetDetailOut extends WorksheetOut {
  lines: WorksheetLineOut[];
}
