"""LLM classification stage.

Reads the extracted JSON from `source_document.extracted`, calls the
configured classifier, and writes a `DraftClassification` row with
`status=PENDING_REVIEW`. NEVER writes to journal_entry/journal_line.

Confidence handling:
  * If `confidence >= HIGH_CONFIDENCE_THRESHOLD`, the draft is flagged
    `high_confidence=True` for fast-path UI surfacing. It is STILL pending
    review — humans approve everything before posting.
  * If `confidence < LOW_CONFIDENCE_THRESHOLD`, the draft is flagged
    `needs_review=True` (which it always is at this stage) and surfaced for
    triage.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.audit import write_audit
from app.integrations.llm import LLMClassifier
from app.integrations.ocr import ExtractionResult
from app.models.accounting import ChartOfAccounts, DraftClassification, SourceDocument
from app.models.enums import AuditAction, DraftKind, DraftStatus

HIGH_CONFIDENCE_THRESHOLD = Decimal("0.85")
LOW_CONFIDENCE_THRESHOLD = Decimal("0.60")


_KIND_TO_ENUM = {
    "bank_transaction": DraftKind.BANK_TRANSACTION,
    "tax_form": DraftKind.TAX_FORM,
    "invoice": DraftKind.INVOICE,
    "receipt": DraftKind.RECEIPT,
    "generic": DraftKind.GENERIC,
}


def run_classification(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    source_document_id: UUID,
    kind_hint: str,
    classifier: LLMClassifier,
) -> UUID | None:
    """Classify the extracted document and write a DraftClassification row.

    Returns the new draft id, or None if the source doc has no extraction
    (which would be a programming error).
    """
    doc = sess.get(SourceDocument, source_document_id)
    if doc is None:
        return None
    if not doc.extracted:
        # Extraction must run first.
        return None

    extraction = _extraction_from_dict(doc.extracted)

    # Fetch the client's active chart of accounts so the classifier can map
    # vendors to the codes that actually exist for this firm/client. The
    # classifier signature is the public contract — anything richer (e.g.,
    # tax mappings) belongs in a higher-level enrichment step.
    coa_rows = (
        sess.execute(
            select(ChartOfAccounts)
            .where(
                ChartOfAccounts.client_id == client_id,
                ChartOfAccounts.is_active.is_(True),
            )
            .order_by(ChartOfAccounts.code)
        )
        .scalars()
        .all()
    )
    coa_payload = [
        {
            "code": a.code,
            "name": a.name,
            "account_type": a.account_type.value,
        }
        for a in coa_rows
    ]

    classification = classifier.classify(
        kind_hint=kind_hint,
        extraction=extraction,
        chart_of_accounts=coa_payload or None,
    )

    # Confidence is clamped into [0, 1] defensively.
    conf = max(Decimal("0"), min(Decimal("1"), Decimal(classification.confidence)))

    # Translate the classifier's `kind` string into our enum, falling back to
    # GENERIC if the classifier returned something unexpected.
    kind_enum = _KIND_TO_ENUM.get(classification.kind, DraftKind.GENERIC)

    high_conf = conf >= HIGH_CONFIDENCE_THRESHOLD
    needs_review = True  # ALWAYS true; humans approve everything

    draft = DraftClassification(
        firm_id=firm_id,
        client_id=client_id,
        source_document_id=source_document_id,
        kind=kind_enum,
        status=DraftStatus.PENDING_REVIEW,
        needs_review=needs_review,
        high_confidence=high_conf,
        confidence=conf,
        model=classification.model,
        prompt_version=classification.prompt_version,
        payload=classification.payload,
    )
    sess.add(draft)
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.CLASSIFY,
        entity_type="draft_classification",
        entity_id=draft.id,
        details={
            "source_document_id": str(source_document_id),
            "kind": kind_enum.value,
            "confidence": str(conf),
            "model": classification.model,
            "prompt_version": classification.prompt_version,
            "high_confidence": high_conf,
            "warnings": classification.warnings,
        },
    )

    return draft.id


def _extraction_from_dict(extracted: dict) -> ExtractionResult:
    """Round-trip the persisted JSON back into an ExtractionResult."""
    return ExtractionResult(
        text=extracted.get("text"),
        fields=list(extracted.get("fields", []) or []),
        model=extracted.get("model", ""),
        model_version=extracted.get("model_version"),
        page_count=int(extracted.get("page_count", 0) or 0),
        warnings=list(extracted.get("warnings", []) or []),
    )


__all__ = [
    "HIGH_CONFIDENCE_THRESHOLD",
    "LOW_CONFIDENCE_THRESHOLD",
    "run_classification",
]
