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
  client_id: string;
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

export interface StatementPromoteOut {
  journal_entry_ids: string[];
  skipped: Array<{ index: string; reason: string }>;
  posted_indexes: number[];
  excluded_indexes: number[];
  pending_indexes: number[];
  review_complete: boolean;
  learned_rule_count: number;
}

export interface LearnRuleOut {
  learned_rule_count: number;
}

// --------------------------------------------------------------------- //
// Documents
// --------------------------------------------------------------------- //
export type DocumentKind =
  | "generic"
  | "bank_transaction"
  | "invoice"
  | "receipt"
  | "tax_form"
  | "tax_form_w2"
  | "tax_form_1099_nec"
  | "tax_form_1099_int"
  | "tax_form_1098";

export interface DocumentOut {
  id: string;
  client_id: string;
  kind: DocumentKind;
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
  kind: DocumentKind;
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
  /** Archived clients are hidden by default and refuse new postings. */
  is_active: boolean;
  archived_at: string | null;
  /** Only returned by the create call — null elsewhere. */
  coa_seeded?: boolean | null;
  coa_seed_error?: string | null;
}

/** Whether a client can be hard-deleted, and what is blocking it. */
export interface ClientDeletabilityOut {
  client_id: string;
  can_delete: boolean;
  /** Label -> count, e.g. `{ "journal entry": 12 }`. Empty when deletable. */
  blocking_counts: Record<string, number>;
}

/**
 * Onboarding payload. Everything past `external_code` is optional profile
 * detail; supplying it up front means the client is ready to use without a
 * second setup step. `industry` also picks the chart-of-accounts overlay.
 */
export interface ClientCreateIn {
  name: string;
  external_code?: string | null;
  industry?: Industry;
  entity_type?: EntityType | null;
  tax_year?: number | null;
  home_state?: string | null;
  fiscal_year_end_month?: number | null;
  business_legal_name?: string | null;
  dba_name?: string | null;
  ein?: string | null;
  email?: string | null;
  phone?: string | null;
  address_line1?: string | null;
  address_line2?: string | null;
  city?: string | null;
  address_state?: string | null;
  postal_code?: string | null;
  /** Defaults to true — seed the default chart of accounts on create. */
  seed_coa?: boolean;
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

/**
 * Reporting bucket within an `AccountType`. This — not the account code —
 * decides where a line lands on the P&L and balance sheet.
 */
export type AccountSubType =
  | "current_asset"
  | "fixed_asset"
  | "intangible_asset"
  | "other_asset"
  | "current_liability"
  | "long_term_liability"
  | "equity"
  | "operating_revenue"
  | "other_income"
  | "cogs"
  | "operating_expense"
  | "other_expense"
  | "income_tax";

export interface CoaOut {
  id: string;
  client_id: string;
  code: string;
  name: string;
  account_type: AccountType;
  /** Always populated; inferred from the code when not explicitly set. */
  sub_type: AccountSubType;
  /** Derived from `account_type` by the backend — never sent on write. */
  normal_balance: NormalBalance;
  is_active: boolean;
  parent_account_id: string | null;
  /** 0 for top-level accounts, +1 per ancestor. Drives row indentation. */
  depth: number;
  is_leaf: boolean;
  /** >0 means the account cannot be removed, only deactivated. */
  journal_line_count: number;
  child_count: number;
}

export interface CoaCreateIn {
  code: string;
  name: string;
  account_type: AccountType;
  /** Omit to derive from the account code. */
  sub_type?: AccountSubType | null;
  /** Omit or null for a top-level account. Must match the parent's type. */
  parent_account_id?: string | null;
}

/**
 * Partial update — only the supplied keys change. Omitting
 * `parent_account_id` leaves the parent alone; sending `null` promotes the
 * account to top level.
 */
export interface CoaUpdateIn {
  code?: string;
  name?: string;
  account_type?: AccountType;
  sub_type?: AccountSubType | null;
  parent_account_id?: string | null;
  is_active?: boolean;
}

export interface RuleConditionOut {
  field: string;
  operator: string;
  value: string;
}

export interface RuleOut {
  name: string;
  target_code: string;
  match: string;
  conditions: RuleConditionOut[];
}

export interface RulesEngineOut {
  backend: string;
  rules_file: string;
  format: string;
  content: string;
  rule_count: number;
  rules: RuleOut[];
}

// --------------------------------------------------------------------- //
// Client profile (Phase 8c — entity + contact, editable by firm OR client)
// --------------------------------------------------------------------- //
/** Mirrors backend ``EntityType`` enum. Drives which tax forms get filed. */
export type EntityType =
  | "c_corp"
  | "s_corp"
  | "partnership"
  | "single_member_llc"
  | "sole_prop";

/** Mirrors backend ``Industry`` enum (used for default account templates). */
export type Industry =
  | "generic"
  | "construction"
  | "retail_ecommerce"
  | "professional_services"
  | "agriculture"
  | "automotive"
  | "childcare"
  | "education"
  | "energy_utilities"
  | "financial_services"
  | "fitness_wellness"
  | "healthcare"
  | "hospitality"
  | "insurance"
  | "legal_services"
  | "manufacturing"
  | "media_entertainment"
  | "nonprofit"
  | "personal_services"
  | "property_management"
  | "real_estate"
  | "restaurant_food_service"
  | "software_saas"
  | "transportation_logistics"
  | "veterinary"
  | "wholesale_distribution";

/** Mirrors backend ``CoaTemplateOut``. */
export interface CoaTemplateOut {
  id: string;
  key: string;
  display_name: string;
  kind: "general" | "industry_overlay" | "custom";
  industry: string | null;
  version: string;
  status: "draft" | "active" | "superseded";
  node_count: number;
}

export interface ClientProfileOut {
  client_id: string;
  entity_type: EntityType | null;
  industry: Industry;
  tax_year: number | null;
  home_state: string | null;
  additional_states: string[];
  fiscal_year_end_month: number | null;
  entity_attributes: Record<string, unknown>;
  business_legal_name: string | null;
  dba_name: string | null;
  ein: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  address_state: string | null;
  postal_code: string | null;
  country: string;
  created_at: string;
  updated_at: string;
}

/** PATCH-style: every field optional. Omitting a key leaves the existing
 * value untouched; passing ``null`` clears it. */
export interface ClientProfileUpsertIn {
  entity_type?: EntityType | null;
  industry?: Industry | null;
  tax_year?: number | null;
  home_state?: string | null;
  additional_states?: string[] | null;
  fiscal_year_end_month?: number | null;
  entity_attributes?: Record<string, unknown> | null;
  business_legal_name?: string | null;
  dba_name?: string | null;
  ein?: string | null;
  phone?: string | null;
  email?: string | null;
  website?: string | null;
  address_line1?: string | null;
  address_line2?: string | null;
  city?: string | null;
  address_state?: string | null;
  postal_code?: string | null;
  country?: string | null;
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
  entry_date: string;
  /** Optional — the server derives the bucket from `entry_date`. */
  period_id?: string;
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
// PART C client-facing reports
// --------------------------------------------------------------------- //
export interface LedgerEntryOut {
  entry_id: string;
  line_id: string;
  entry_date: string;
  memo: string | null;
  line_description: string | null;
  debit: string;
  credit: string;
  running_balance: string;
}

export interface GeneralLedgerOut {
  kind: "general_ledger";
  account_id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  period_start: string;
  period_end: string;
  opening_balance: string;
  closing_balance: string;
  rows: LedgerEntryOut[];
}

export interface AgingBucketOut {
  label: string;
  min_days: number;
  max_days: number | null;
  amount: string;
}

export interface AgingAccountRowOut {
  account_id: string;
  account_code: string;
  account_name: string;
  total: string;
  buckets: AgingBucketOut[];
}

export interface AgingReportOut {
  kind: "ar_aging" | "ap_aging";
  as_of: string;
  account_codes: string[];
  rows: AgingAccountRowOut[];
  totals_by_bucket: AgingBucketOut[];
  grand_total: string;
}

export interface DrillDownLineOut {
  entry_id: string;
  line_id: string;
  entry_date: string;
  account_id: string;
  account_code: string;
  account_name: string;
  memo: string | null;
  line_description: string | null;
  debit: string;
  credit: string;
  source_document_id: string | null;
}

export interface DrillDownOut {
  kind: "account_activity";
  account_id: string;
  account_code: string;
  account_name: string;
  is_rollup: boolean;
  leaf_account_ids: string[];
  period_start: string;
  period_end: string;
  total_debit: string;
  total_credit: string;
  signed_total: string;
  lines: DrillDownLineOut[];
}

export interface RollupNodeOut {
  account_id: string;
  code: string;
  name: string;
  account_type: string;
  depth: number;
  is_leaf: boolean;
  debit_total: string;
  credit_total: string;
  signed_balance: string;
  children: RollupNodeOut[];
}

export interface RollupTreeOut {
  kind: "account_rollup";
  scope: "balance_sheet" | "profit_and_loss" | "trial_balance";
  period_start: string | null;
  period_end: string;
  roots: RollupNodeOut[];
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
  generated_at: string;
  finalized_by: string | null;
  finalized_at: string | null;
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

export interface AutoProposeSkipped {
  code: string;
  name: string;
  reason: string;
}

export interface AutoProposeAlreadyExisted {
  code: string;
  name: string;
  status: string;
}

export interface AutoProposeOut {
  form_code: string;
  proposed_mapping_ids: string[];
  skipped: AutoProposeSkipped[];
  already_existed: AutoProposeAlreadyExisted[];
}

export interface AutoFillOut {
  proposed_mapping_ids: string[];
  approved_mapping_ids: string[];
  skipped: AutoProposeSkipped[];
  already_existed: AutoProposeAlreadyExisted[];
  worksheet: WorksheetDetailOut;
}

export interface RulesetOut {
  id: string;
  entity_type: string;
  tax_year: number;
  version: string;
  status: string;
  required_forms: string[];
}

// --------------------------------------------------------------------- //
// Team management (Sprint 3)
// --------------------------------------------------------------------- //
export type StaffRole =
  | "firm_owner"
  | "firm_admin"
  | "manager"
  | "staff"
  | "read_only"
  | "client_portal";

export type MembershipStatus = "active" | "disabled";
export type InviteStatus = "pending" | "accepted" | "canceled" | "expired";

export interface TeamMemberOut {
  id: string;
  user_id: string;
  subject: string;
  email: string | null;
  role: StaffRole;
  status: MembershipStatus;
  created_at: string;
  updated_at: string;
}

export interface TeamInviteOut {
  id: string;
  email: string;
  role: StaffRole;
  status: InviteStatus;
  expires_at: string;
  created_at: string;
}

export interface TeamInviteCreateOut extends TeamInviteOut {
  invite_token: string;
}

export interface TeamSummaryOut {
  members: TeamMemberOut[];
  invites: TeamInviteOut[];
}
