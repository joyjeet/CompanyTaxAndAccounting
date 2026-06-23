"""Form template registry domain service (Phase 8b).

Three CPA-driven transitions:

* ``register_template`` — INSERT a new row as DRAFT/unverified. The CPA
  supplies the form_code/tax_year/revision/path; the service computes
  sha256 from the file at path (or accepts a placeholder).

* ``verify_template`` — flip ``verified=True`` after the CPA has mapped
  every AcroForm field for this form_code in ``irs_form_fields.py``.
  Verification cannot be undone via API; if a field-map regresses, the
  CPA must SUPERSEDE the row and register a fresh one.

* ``activate_template`` — flip DRAFT → ACTIVE, superseding any prior
  ACTIVE row for the same (form_code, tax_year). Refuses if
  ``verified=False``. Activation is the only gate that lets a tax PDF
  become a FINALIZED artifact.

All transitions are firm-level (AccessScope.FIRM only); audit is written
against the firm with NIL client_id, matching the COA-template pattern.

``get_active_verified(sess, form_code, tax_year)`` is the public lookup
used by ``app.domain.artifact_service.finalize_artifact`` — returns the
single ACTIVE+verified row, or raises ``FormTemplateNotActiveError`` if
the form has no active+verified template.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tenant import AccessScope
from app.domain.audit import write_audit
from app.models.enums import AuditAction, FormTemplateStatus, TaxFormCode
from app.models.form_template import FormTemplate


class FormTemplateError(Exception):
    """Base for form-template domain errors."""


class FormTemplateForbiddenError(FormTemplateError):
    """Caller's scope/role is not allowed to perform the operation."""


class FormTemplateNotFoundError(FormTemplateError):
    """The requested form-template row does not exist."""


class FormTemplateNotActiveError(FormTemplateError):
    """No ACTIVE+verified template exists for the requested form_code+year.

    Raised by ``get_active_verified``. The finalize path catches this to
    refuse FINALIZING a tax-worksheet PDF for a form whose template the
    CPA has not yet activated.
    """


class FormTemplateStateError(FormTemplateError):
    """Requested transition is not legal from the current row's state."""


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #
def get_active_verified(
    sess: Session, *, form_code: TaxFormCode, tax_year: int,
) -> FormTemplate:
    """Return the single ACTIVE+verified template for (form_code, tax_year).

    Raises ``FormTemplateNotActiveError`` if none exists. Activation
    invariant guarantees at most one ACTIVE row per (form_code, tax_year);
    if more than one is found we treat that as a corrupted invariant and
    raise a state error.
    """
    rows = sess.execute(
        select(FormTemplate).where(
            FormTemplate.form_code == form_code,
            FormTemplate.tax_year == tax_year,
            FormTemplate.status == FormTemplateStatus.ACTIVE,
        )
    ).scalars().all()
    verified = [r for r in rows if r.verified]
    if not verified:
        raise FormTemplateNotActiveError(
            f"No ACTIVE+verified form template for {form_code.value} "
            f"tax_year={tax_year}; CPA must activate one before "
            "finalizing tax PDFs for this form."
        )
    if len(verified) > 1:
        # Defensive — activation should supersede priors. Surface loudly.
        raise FormTemplateStateError(
            f"Multiple ACTIVE+verified templates for {form_code.value} "
            f"tax_year={tax_year}; registry invariant violated."
        )
    return verified[0]


# --------------------------------------------------------------------------- #
# Register
# --------------------------------------------------------------------------- #
def register_template(
    sess: Session,
    *,
    firm_id: UUID,
    actor: str,
    scope: AccessScope,
    form_code: TaxFormCode,
    tax_year: int,
    revision: str,
    local_template_path: str,
    sha256: str | None = None,
) -> FormTemplate:
    """Create a new DRAFT/unverified form-template row.

    If ``sha256`` is None and the file at ``local_template_path`` exists,
    the service computes the digest from the file bytes. If neither is
    available we record a placeholder (64 zeros) so the row can exist and
    the CPA can fill in the real digest at verify time.
    """
    if scope is not AccessScope.FIRM:
        raise FormTemplateForbiddenError(
            "Only firm staff may register form templates."
        )

    # Reject duplicate (form_code, tax_year, revision).
    existing = sess.execute(
        select(FormTemplate).where(
            FormTemplate.form_code == form_code,
            FormTemplate.tax_year == tax_year,
            FormTemplate.revision == revision,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise FormTemplateStateError(
            f"FormTemplate already registered for {form_code.value} "
            f"tax_year={tax_year} revision={revision}."
        )

    digest = sha256
    if digest is None:
        p = Path(local_template_path)
        digest = (
            hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "0" * 64
        )

    row = FormTemplate(
        form_code=form_code,
        tax_year=tax_year,
        revision=revision,
        status=FormTemplateStatus.DRAFT,
        verified=False,
        local_template_path=local_template_path,
        sha256=digest,
    )
    sess.add(row)
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=UUID(int=0),
        actor=actor,
        action=AuditAction.FORM_TEMPLATE_REGISTER,
        entity_type="form_template",
        entity_id=row.id,
        details={
            "form_code": form_code.value,
            "tax_year": tax_year,
            "revision": revision,
            "sha256": digest,
        },
    )
    return row


# --------------------------------------------------------------------------- #
# Verify
# --------------------------------------------------------------------------- #
def verify_template(
    sess: Session,
    *,
    firm_id: UUID,
    actor: str,
    scope: AccessScope,
    template_id: UUID,
) -> FormTemplate:
    """Flip ``verified=True`` on a DRAFT row.

    Re-verification of an ACTIVE row is allowed (no-op) so the CPA can
    safely re-run the verify endpoint. SUPERSEDED rows cannot be
    re-verified — the CPA must register a new revision.
    """
    if scope is not AccessScope.FIRM:
        raise FormTemplateForbiddenError(
            "Only firm staff may verify form templates."
        )
    row = sess.get(FormTemplate, template_id)
    if row is None:
        raise FormTemplateNotFoundError("Form template not found.")
    if row.status is FormTemplateStatus.SUPERSEDED:
        raise FormTemplateStateError(
            "Cannot verify a SUPERSEDED form template; register a new revision."
        )
    if row.verified:
        return row  # idempotent

    row.verified = True
    row.verified_at = datetime.now(tz=UTC)
    row.verified_by = actor
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=UUID(int=0),
        actor=actor,
        action=AuditAction.FORM_TEMPLATE_VERIFY,
        entity_type="form_template",
        entity_id=row.id,
        details={
            "form_code": row.form_code.value,
            "tax_year": row.tax_year,
            "revision": row.revision,
        },
    )
    return row


# --------------------------------------------------------------------------- #
# Activate
# --------------------------------------------------------------------------- #
def activate_template(
    sess: Session,
    *,
    firm_id: UUID,
    actor: str,
    scope: AccessScope,
    template_id: UUID,
) -> FormTemplate:
    """Flip DRAFT → ACTIVE; supersede any prior ACTIVE for (form_code, year).

    Requires ``verified=True``. Idempotent if already ACTIVE+verified.
    """
    if scope is not AccessScope.FIRM:
        raise FormTemplateForbiddenError(
            "Only firm staff may activate form templates."
        )
    row = sess.get(FormTemplate, template_id)
    if row is None:
        raise FormTemplateNotFoundError("Form template not found.")
    if row.status is FormTemplateStatus.ACTIVE and row.verified:
        return row
    if row.status is FormTemplateStatus.SUPERSEDED:
        raise FormTemplateStateError(
            "Cannot activate a SUPERSEDED form template."
        )
    if not row.verified:
        raise FormTemplateStateError(
            "Form template must be verified before activation."
        )

    # Supersede prior ACTIVE rows with same (form_code, tax_year).
    prior = sess.execute(
        select(FormTemplate).where(
            FormTemplate.form_code == row.form_code,
            FormTemplate.tax_year == row.tax_year,
            FormTemplate.status == FormTemplateStatus.ACTIVE,
            FormTemplate.id != row.id,
        )
    ).scalars().all()
    for p in prior:
        p.status = FormTemplateStatus.SUPERSEDED
    if prior:
        sess.flush()

    row.status = FormTemplateStatus.ACTIVE
    row.activated_at = datetime.now(tz=UTC)
    row.activated_by = actor
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=UUID(int=0),
        actor=actor,
        action=AuditAction.FORM_TEMPLATE_ACTIVATE,
        entity_type="form_template",
        entity_id=row.id,
        details={
            "form_code": row.form_code.value,
            "tax_year": row.tax_year,
            "revision": row.revision,
            "superseded_ids": [str(p.id) for p in prior],
        },
    )
    return row


__all__ = [
    "FormTemplateError",
    "FormTemplateForbiddenError",
    "FormTemplateNotActiveError",
    "FormTemplateNotFoundError",
    "FormTemplateStateError",
    "activate_template",
    "get_active_verified",
    "register_template",
    "verify_template",
]
