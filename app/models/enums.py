from __future__ import annotations

import enum


class AccountType(enum.StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class NormalBalance(enum.StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


# Canonical mapping. Used by the engine to validate COA rows on insert.
NORMAL_BALANCE_FOR: dict[AccountType, NormalBalance] = {
    AccountType.ASSET: NormalBalance.DEBIT,
    AccountType.EXPENSE: NormalBalance.DEBIT,
    AccountType.LIABILITY: NormalBalance.CREDIT,
    AccountType.EQUITY: NormalBalance.CREDIT,
    AccountType.REVENUE: NormalBalance.CREDIT,
}


class JournalEntryStatus(enum.StrEnum):
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"


class ReconciliationStatus(enum.StrEnum):
    OPEN = "open"
    COMPLETE = "complete"
    DISCREPANCY = "discrepancy"


class AssetStatus(enum.StrEnum):
    ACTIVE = "active"
    DISPOSED = "disposed"


class AuditAction(enum.StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    POST = "post"
    REVERSE = "reverse"
    LOCK_PERIOD = "lock_period"
    UNLOCK_PERIOD = "unlock_period"
    RECONCILE = "reconcile"
    INGEST = "ingest"
    EXTRACT = "extract"
    CLASSIFY = "classify"
    PROMOTE = "promote"
    REJECT = "reject"
    TAX_MAP_PROPOSE = "tax_map_propose"
    TAX_MAP_APPROVE = "tax_map_approve"
    TAX_MAP_REJECT = "tax_map_reject"
    TAX_WORKSHEET_GENERATE = "tax_worksheet_generate"
    TAX_WORKSHEET_APPROVE = "tax_worksheet_approve"
    ARTIFACT_GENERATE = "artifact_generate"
    ARTIFACT_FINALIZE = "artifact_finalize"
    AUDIT_PACKAGE_GENERATE = "audit_package_generate"
    ARTIFACT_DOWNLOAD = "artifact_download"
    # Phase 7 — administrative / compliance actions.
    TENANT_KEYS_DESTROY = "tenant_keys_destroy"
    AUDIT_EXPORT = "audit_export"
    # Phase 8 — COA templates + onboarding.
    COA_TEMPLATE_ACTIVATE = "coa_template_activate"
    COA_TEMPLATE_INSTANTIATE = "coa_template_instantiate"
    COA_ACCOUNT_RENAME = "coa_account_rename"
    COA_ACCOUNT_DEACTIVATE = "coa_account_deactivate"
    # Phase 8b — Form template registry, client profile, entity-form ruleset.
    FORM_TEMPLATE_REGISTER = "form_template_register"
    FORM_TEMPLATE_VERIFY = "form_template_verify"
    FORM_TEMPLATE_ACTIVATE = "form_template_activate"
    CLIENT_PROFILE_UPSERT = "client_profile_upsert"
    ENTITY_FORM_RULESET_ACTIVATE = "entity_form_ruleset_activate"
    TAX_WORKSHEET_REJECT = "tax_worksheet_reject"
    TAX_WORKSHEET_SUPERSEDE = "tax_worksheet_supersede"
    USER_INVITE_CREATE = "user_invite_create"
    USER_INVITE_CANCEL = "user_invite_cancel"
    USER_INVITE_ACCEPT = "user_invite_accept"
    USER_ROLE_UPDATE = "user_role_update"
    USER_STATUS_UPDATE = "user_status_update"


class StaffRole(enum.StrEnum):
    FIRM_OWNER = "firm_owner"
    FIRM_ADMIN = "firm_admin"
    MANAGER = "manager"
    STAFF = "staff"
    READ_ONLY = "read_only"
    CLIENT_PORTAL = "client_portal"


class MembershipStatus(enum.StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class InviteStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CANCELED = "canceled"
    EXPIRED = "expired"


class OcrStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


class DraftKind(enum.StrEnum):
    BANK_TRANSACTION = "bank_transaction"
    TAX_FORM = "tax_form"
    INVOICE = "invoice"
    RECEIPT = "receipt"
    GENERIC = "generic"


class DraftStatus(enum.StrEnum):
    PENDING_REVIEW = "pending_review"
    PROMOTED = "promoted"
    REJECTED = "rejected"


# --------------------------------------------------------------------------- #
# Tax module (Phase 5)
# --------------------------------------------------------------------------- #
class TaxFormCode(enum.StrEnum):
    """Supported US federal income-tax forms.

    v1 supports the major business return types. Each form is modeled with
    its income-statement-relevant lines (Sched L / M-1 / M-2 deferred).
    """

    F1120 = "F1120"       # US C-Corporation Income Tax Return
    F1120S = "F1120S"     # US S-Corporation Income Tax Return
    F1065 = "F1065"       # US Return of Partnership Income
    F1040SC = "F1040SC"   # US Sole Proprietor (Form 1040, Schedule C)


class TaxFormSection(enum.StrEnum):
    """Coarse sections we expose on every form. Maps to a worksheet block."""

    INCOME = "income"
    COGS = "cogs"
    DEDUCTIONS = "deductions"
    OTHER = "other"


class TaxLineSign(enum.StrEnum):
    """How an account's signed ledger balance contributes to a tax line.

    Tax lines are reported as positive numbers regardless of the ledger
    debit/credit posture. The signed_balance of an account (already at its
    natural normal balance — see app/domain/statements.py) is passed through
    one of these:

      * POSITIVE: signed_balance contributes as-is (revenue accounts on an
        income line; expense accounts on a deduction line — both yield a
        positive line amount).
      * NEGATIVE: signed_balance is negated (returns/allowances, contra
        revenue, etc.).
    """

    POSITIVE = "positive"
    NEGATIVE = "negative"


class TaxMappingStatus(enum.StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class TaxWorksheetStatus(enum.StrEnum):
    COMPUTED = "computed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


# --------------------------------------------------------------------------- #
# Output / Reporting (Phase 6)
# --------------------------------------------------------------------------- #
class ArtifactKind(enum.StrEnum):
    """What kind of report a `generated_artifact` row represents."""

    PROFIT_AND_LOSS = "profit_and_loss"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    TAX_WORKSHEET = "tax_worksheet"
    NARRATIVE = "narrative"
    AUDIT_PACKAGE = "audit_package"


class ArtifactFormat(enum.StrEnum):
    """Wire / on-disk format of the artifact body."""

    PDF = "pdf"
    XLSX = "xlsx"
    ZIP = "zip"
    JSON = "json"
    MARKDOWN = "markdown"


class ArtifactStatus(enum.StrEnum):
    """Reviewer lifecycle for a generated artifact.

    Only FINALIZED artifacts are visible to client-portal users and are
    eligible to be bundled into an audit-ready package. DRAFT artifacts may
    be regenerated; FINALIZED artifacts are immutable (a new artifact must be
    generated to replace one).
    """

    DRAFT = "draft"
    FINALIZED = "finalized"
    SUPERSEDED = "superseded"


# --------------------------------------------------------------------------- #
# Phase 8 — Granular COA templates + entity/industry-driven onboarding
# ---------------------------------------------------------------------------
# All template content is DATA, seeded by migrations as DRAFT. A CPA on the
# firm must ACTIVATE a template version before it can be instantiated for a
# client. Activation is the only audit-bearing transition.
#
# Industry and EntityType are exposed as enums for type-safety in the seed
# code paths, but the on-disk representation is a string — adding a new
# industry (e.g. "manufacturing") only requires a seed file + adding the
# value to the enum, not a migration of existing data.
# --------------------------------------------------------------------------- #
class CoaTemplateKind(enum.StrEnum):
    """Whether a COA template stands alone or layers onto another."""

    GENERAL = "general"               # The full base tree.
    INDUSTRY_OVERLAY = "industry_overlay"  # Adds nodes onto the general base.


class CoaTemplateStatus(enum.StrEnum):
    """Activation lifecycle for a versioned COA template.

    Only an ACTIVE template version is offered to new clients during
    onboarding. Editing a template means publishing a new version (DRAFT)
    and explicitly activating it (which supersedes the prior ACTIVE).
    """

    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class CoaNodeOrigin(enum.StrEnum):
    """Where a `chart_of_accounts` row came from.

    Track lineage so per-client customizations are clearly distinguishable
    from template-derived nodes. CPA workflows can warn before deactivating
    a template node that the client renamed locally.
    """

    GENERAL = "general"
    INDUSTRY_OVERLAY = "industry_overlay"
    CUSTOM = "custom"


class Industry(enum.StrEnum):
    """Industry overlays the firm currently supports.

    Treat values as strings on the wire; the enum exists for type-safety in
    seed code. New industries are added by (a) appending a value here and
    (b) adding a seed file under `app/data/coa_templates/<industry>.py`.
    """

    GENERIC = "generic"
    CONSTRUCTION = "construction"
    RETAIL_ECOMMERCE = "retail_ecommerce"
    PROFESSIONAL_SERVICES = "professional_services"


class EntityType(enum.StrEnum):
    """US business entity types currently supported by the form-set engine.

    Same extensibility note as `Industry`: add a value here and supply the
    entity → form-set mapping in PART B's data file. Phase-8a only uses
    this for client profile capture; the form-set wiring lands in Part B.
    """

    C_CORP = "c_corp"
    S_CORP = "s_corp"
    PARTNERSHIP = "partnership"
    SINGLE_MEMBER_LLC = "single_member_llc"
    SOLE_PROP = "sole_prop"


# --------------------------------------------------------------------------- #
# Phase 8b — Form template registry + entity-form ruleset.
# --------------------------------------------------------------------------- #
# A FormTemplate row exists per (form_code, tax_year, revision). It tracks
# the local PDF path + sha256 of bytes, and a `verified` flag the CPA flips
# only after they have mapped/verified every AcroForm field in
# `irs_form_fields.py`. A tax PDF may only be FINALIZED when an ACTIVE +
# verified template exists for its (form_code, tax_year). DRAFT templates
# may be test-rendered into `results/` for review but never finalized.
class FormTemplateStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


# An EntityFormRuleset row exists per (entity_type, tax_year, version) and
# carries the JSON list of required tax forms for that entity type. CPA
# activates a version; the system fails-closed for a client whose
# entity_type+tax_year has no ACTIVE ruleset.
class EntityFormRulesetStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"

