import type {
  ClientProfileOut,
  CoaOut,
  DocumentOut,
  EntityType,
  MappingOut,
  WorksheetOut,
} from "../auth/types";

export type ReadinessCheckStatus = "complete" | "attention" | "not_started";

export interface ReadinessCheck {
  id: "profile" | "period" | "documents" | "mappings" | "worksheet";
  label: string;
  detail: string;
  status: ReadinessCheckStatus;
  target: "profile" | "documents" | "mappings" | "worksheets";
}

export interface TaxReadiness {
  score: number;
  completeCount: number;
  checks: ReadinessCheck[];
  blockers: string[];
  eligibleAccountCount: number;
  approvedMappingCount: number;
  pendingMappingCount: number;
  unmappedAccounts: CoaOut[];
  documentCounts: {
    complete: number;
    processing: number;
    failed: number;
  };
  worksheetStatus: string | null;
}

const FORM_BY_ENTITY: Record<EntityType, string> = {
  c_corp: "F1120",
  s_corp: "F1120S",
  partnership: "F1065",
  single_member_llc: "F1040SC",
  sole_prop: "F1040SC",
};

export function recommendedFormCode(
  profile: ClientProfileOut | null | undefined,
): string | null {
  return profile?.entity_type ? FORM_BY_ENTITY[profile.entity_type] : null;
}

export function deriveTaxReadiness({
  profile,
  hasPeriod,
  formCode,
  accounts,
  mappings,
  documents,
  worksheets,
}: {
  profile: ClientProfileOut | null | undefined;
  hasPeriod: boolean;
  formCode: string;
  accounts: CoaOut[];
  mappings: MappingOut[];
  documents: DocumentOut[];
  worksheets: WorksheetOut[];
}): TaxReadiness {
  const eligibleAccounts = accounts.filter(
    (account) =>
      account.is_active &&
      account.is_leaf &&
      (account.account_type === "revenue" || account.account_type === "expense"),
  );
  const approvedMappings = mappings.filter((mapping) => mapping.status === "approved");
  const pendingMappings = mappings.filter(
    (mapping) => mapping.status === "draft" || mapping.status === "proposed",
  );
  const coveredAccountIds = new Set(approvedMappings.map((mapping) => mapping.account_id));
  const unmappedAccounts = eligibleAccounts.filter(
    (account) => !coveredAccountIds.has(account.id),
  );

  const documentCounts = documents.reduce(
    (counts, document) => {
      if (document.ocr_status === "complete") counts.complete += 1;
      else if (document.ocr_status === "failed") counts.failed += 1;
      else counts.processing += 1;
      return counts;
    },
    { complete: 0, processing: 0, failed: 0 },
  );

  const approvedWorksheet = worksheets.find((worksheet) => worksheet.status === "approved");
  const currentWorksheet = approvedWorksheet ?? worksheets[0];
  const profileReady = Boolean(profile?.entity_type && profile.tax_year);
  const documentsReady =
    documentCounts.complete > 0 &&
    documentCounts.processing === 0 &&
    documentCounts.failed === 0;
  const mappingsReady =
    eligibleAccounts.length > 0 &&
    approvedMappings.length > 0 &&
    pendingMappings.length === 0 &&
    unmappedAccounts.length === 0;
  const worksheetReady = Boolean(approvedWorksheet);

  const checks: ReadinessCheck[] = [
    {
      id: "profile",
      label: "Client tax profile",
      detail: profileReady
        ? `${profile!.entity_type!.replaceAll("_", " ")} · tax year ${profile!.tax_year}`
        : "Entity type and tax year are required.",
      status: profileReady ? "complete" : "not_started",
      target: "profile",
    },
    {
      id: "period",
      label: "Filing period",
      detail: hasPeriod ? "A filing period is selected." : "Create and select a filing period.",
      status: hasPeriod ? "complete" : "not_started",
      target: "worksheets",
    },
    {
      id: "documents",
      label: "Source documents",
      detail:
        documentCounts.complete === 0
          ? "No completed source documents."
          : `${documentCounts.complete} complete · ${documentCounts.processing} processing · ${documentCounts.failed} failed`,
      status: documentsReady
        ? "complete"
        : documentCounts.processing > 0 || documentCounts.failed > 0
          ? "attention"
          : "not_started",
      target: "documents",
    },
    {
      id: "mappings",
      label: `${formCode || "Form"} account mappings`,
      detail:
        eligibleAccounts.length === 0
          ? "No active revenue or expense posting accounts."
          : `${approvedMappings.length} approved · ${pendingMappings.length} awaiting review · ${unmappedAccounts.length} unmapped`,
      status: mappingsReady
        ? "complete"
        : pendingMappings.length > 0 || approvedMappings.length > 0
          ? "attention"
          : "not_started",
      target: "mappings",
    },
    {
      id: "worksheet",
      label: "Tax worksheet",
      detail: currentWorksheet
        ? `${currentWorksheet.status} · taxable income ${currentWorksheet.taxable_income}`
        : "No worksheet has been generated for this period and form.",
      status: worksheetReady
        ? "complete"
        : currentWorksheet
          ? "attention"
          : "not_started",
      target: "worksheets",
    },
  ];

  const completeCount = checks.filter((check) => check.status === "complete").length;
  const blockers = checks
    .filter((check) => check.status !== "complete")
    .map((check) => check.detail);

  return {
    score: Math.round((completeCount / checks.length) * 100),
    completeCount,
    checks,
    blockers,
    eligibleAccountCount: eligibleAccounts.length,
    approvedMappingCount: approvedMappings.length,
    pendingMappingCount: pendingMappings.length,
    unmappedAccounts,
    documentCounts,
    worksheetStatus: currentWorksheet?.status ?? null,
  };
}
