"""Entity-form ruleset domain service (Phase 8b).

Versioned, CPA-activated mapping from (entity_type, tax_year) →
required tax forms. The system **fails closed** if a client's
(entity_type, tax_year) has no ACTIVE ruleset; no worksheet, artifact,
or downstream tax computation may be produced.

Public surface:

* ``activate_ruleset`` — flip DRAFT → ACTIVE; supersede prior ACTIVE
  for the same (entity_type, tax_year). Firm-scope only.

* ``get_form_set_for_client`` — public lookup used by the worksheet /
  artifact flows. Raises ``NeedsRulesetError`` if the client has no
  profile (so the system cannot determine their entity_type/tax_year),
  and ``NeedsRulesetError`` if no ACTIVE ruleset exists for that pair.

The ``required_forms`` column is a JSON list of ``TaxFormCode`` string
values; we coerce back to typed enum members on read so callers can
intersect with the catalog without parsing surprises.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tenant import AccessScope
from app.domain.audit import write_audit
from app.domain.client_profile import get_profile_for_client
from app.models.entity_form_ruleset import EntityFormRuleset
from app.models.enums import (
    AuditAction,
    EntityFormRulesetStatus,
    EntityType,
    TaxFormCode,
)


class EntityFormRulesetError(Exception):
    """Base for entity-form-ruleset domain errors."""


class EntityFormRulesetForbiddenError(EntityFormRulesetError):
    """Caller's scope/role is not allowed to perform the operation."""


class EntityFormRulesetNotFoundError(EntityFormRulesetError):
    """Requested ruleset row does not exist."""


class EntityFormRulesetStateError(EntityFormRulesetError):
    """Requested transition is not legal from the current row's state."""


class NeedsRulesetError(EntityFormRulesetError):
    """Fail-closed: no ACTIVE ruleset exists for the client's situation.

    Raised by ``get_form_set_for_client`` when the client either has no
    profile or their (entity_type, tax_year) has no ACTIVE ruleset.
    Callers should surface this to the firm with a clear "CPA must
    activate a ruleset before tax forms can be generated" message.
    """


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def _coerce_required_forms(raw: list[str]) -> list[TaxFormCode]:
    """Coerce stored JSON strings back to TaxFormCode enum members.

    Unknown codes are silently dropped — we never want to crash the
    form-set lookup because a future TaxFormCode value isn't yet in the
    enum. The CPA review doc surfaces orphaned codes.
    """
    out: list[TaxFormCode] = []
    for code in raw or []:
        try:
            out.append(TaxFormCode(code))
        except ValueError:
            continue
    return out


def get_active_ruleset(
    sess: Session, *, entity_type: EntityType | str, tax_year: int,
) -> EntityFormRuleset | None:
    """Return the ACTIVE ruleset for (entity_type, tax_year), or None."""
    et_value = (
        entity_type.value if isinstance(entity_type, EntityType) else entity_type
    )
    return sess.execute(
        select(EntityFormRuleset).where(
            EntityFormRuleset.entity_type == et_value,
            EntityFormRuleset.tax_year == tax_year,
            EntityFormRuleset.status == EntityFormRulesetStatus.ACTIVE,
        )
    ).scalar_one_or_none()


def get_form_set_for_client(
    sess: Session, *, client_id: UUID,
) -> list[TaxFormCode]:
    """Return the list of TaxFormCodes a client may generate worksheets for.

    Fails closed with ``NeedsRulesetError`` if:
      * The client has no ``client_profile`` row, OR
      * No ACTIVE ``entity_form_ruleset`` exists for the client's
        (entity_type, tax_year).
    """
    profile = get_profile_for_client(sess, client_id=client_id)
    if profile is None:
        raise NeedsRulesetError(
            f"Client {client_id} has no profile; the firm must capture "
            "entity_type + tax_year before tax forms can be generated."
        )
    ruleset = get_active_ruleset(
        sess, entity_type=profile.entity_type, tax_year=profile.tax_year,
    )
    if ruleset is None:
        raise NeedsRulesetError(
            f"No ACTIVE entity-form ruleset for entity_type="
            f"{profile.entity_type} tax_year={profile.tax_year}; "
            "CPA must activate one before tax forms can be generated."
        )
    return _coerce_required_forms(ruleset.required_forms)


# --------------------------------------------------------------------------- #
# Activation
# --------------------------------------------------------------------------- #
def activate_ruleset(
    sess: Session,
    *,
    firm_id: UUID,
    actor: str,
    scope: AccessScope,
    ruleset_id: UUID,
) -> EntityFormRuleset:
    """Flip DRAFT → ACTIVE; supersede priors for same (entity_type, tax_year).

    Reference-data activation — firm-scope only; audit row written with
    NIL client_id (matches COA template activation pattern).
    """
    if scope is not AccessScope.FIRM:
        raise EntityFormRulesetForbiddenError(
            "Only firm staff may activate entity-form rulesets."
        )
    row = sess.get(EntityFormRuleset, ruleset_id)
    if row is None:
        raise EntityFormRulesetNotFoundError("Ruleset not found.")
    if row.status is EntityFormRulesetStatus.ACTIVE:
        return row  # idempotent
    if row.status is EntityFormRulesetStatus.SUPERSEDED:
        raise EntityFormRulesetStateError(
            "Cannot activate a SUPERSEDED ruleset; register a new version."
        )

    prior = sess.execute(
        select(EntityFormRuleset).where(
            EntityFormRuleset.entity_type == row.entity_type,
            EntityFormRuleset.tax_year == row.tax_year,
            EntityFormRuleset.status == EntityFormRulesetStatus.ACTIVE,
            EntityFormRuleset.id != row.id,
        )
    ).scalars().all()
    for p in prior:
        p.status = EntityFormRulesetStatus.SUPERSEDED
    if prior:
        sess.flush()

    row.status = EntityFormRulesetStatus.ACTIVE
    row.activated_at = datetime.now(tz=UTC)
    row.activated_by = actor
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=UUID(int=0),
        actor=actor,
        action=AuditAction.ENTITY_FORM_RULESET_ACTIVATE,
        entity_type="entity_form_ruleset",
        entity_id=row.id,
        details={
            "entity_type": row.entity_type,
            "tax_year": row.tax_year,
            "version": row.version,
            "required_forms": row.required_forms,
            "superseded_ids": [str(p.id) for p in prior],
        },
    )
    return row


__all__ = [
    "EntityFormRulesetError",
    "EntityFormRulesetForbiddenError",
    "EntityFormRulesetNotFoundError",
    "EntityFormRulesetStateError",
    "NeedsRulesetError",
    "activate_ruleset",
    "get_active_ruleset",
    "get_form_set_for_client",
]
