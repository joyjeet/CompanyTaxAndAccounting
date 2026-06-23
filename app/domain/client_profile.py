"""Client profile domain service (Phase 8b).

A client has a 1:1 ``ClientProfile`` row capturing the structured
attributes that drive the entity-form ruleset: entity_type, industry,
tax_year, home_state, additional_states, fiscal_year_end_month, and a
free-form ``entity_attributes`` jsonb.

* ``upsert_profile`` — firm staff create or update the profile. The
  ``entity_type`` value must parse to a known ``EntityType`` enum
  member; that is the only schema validation we apply here.

* ``get_profile_for_client`` — both firm staff and the client portal
  may read. RLS makes cross-tenant access impossible.

Audit writes the entity_type/industry/tax_year changes so the CPA can
trace when a client was reclassified — those changes affect the form
set the system offers.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tenant import AccessScope
from app.domain.audit import write_audit
from app.models.client_profile import ClientProfile
from app.models.enums import AuditAction, EntityType, Industry


class ClientProfileError(Exception):
    """Base for client-profile domain errors."""


class ClientProfileForbiddenError(ClientProfileError):
    """Caller's scope/role is not allowed to perform the operation."""


class ClientProfileNotFoundError(ClientProfileError):
    """No profile exists for the requested client."""


class ClientProfileValidationError(ClientProfileError):
    """A field value (entity_type/industry/state/month) is invalid."""


# Allow callers to pass the enum value or its string form.
def _coerce_entity_type(value: EntityType | str) -> EntityType:
    if isinstance(value, EntityType):
        return value
    try:
        return EntityType(value)
    except ValueError as e:
        raise ClientProfileValidationError(
            f"Unknown entity_type {value!r}. Supported: "
            f"{[e.value for e in EntityType]}"
        ) from e


def _coerce_industry(value: Industry | str | None) -> str:
    if value is None:
        return Industry.GENERIC.value
    if isinstance(value, Industry):
        return value.value
    try:
        return Industry(value).value
    except ValueError as e:
        raise ClientProfileValidationError(
            f"Unknown industry {value!r}. Supported: "
            f"{[i.value for i in Industry]}"
        ) from e


def _validate_state(code: str | None) -> str | None:
    if code is None:
        return None
    if not (isinstance(code, str) and len(code) == 2 and code.isalpha()):
        raise ClientProfileValidationError(
            f"State code must be a 2-letter abbreviation, got {code!r}."
        )
    return code.upper()


def _validate_month(month: int) -> int:
    if not (isinstance(month, int) and 1 <= month <= 12):
        raise ClientProfileValidationError(
            f"fiscal_year_end_month must be 1..12, got {month!r}."
        )
    return month


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def get_profile_for_client(
    sess: Session, *, client_id: UUID,
) -> ClientProfile | None:
    """Return the ClientProfile for ``client_id`` if one exists.

    RLS guarantees the caller can only see their own tenant's row.
    Returns None if no profile exists yet.
    """
    return sess.execute(
        select(ClientProfile).where(ClientProfile.client_id == client_id)
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Upsert
# --------------------------------------------------------------------------- #
def upsert_profile(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    entity_type: EntityType | str,
    tax_year: int,
    industry: Industry | str | None = None,
    home_state: str | None = None,
    additional_states: list[str] | None = None,
    fiscal_year_end_month: int = 12,
    entity_attributes: dict | None = None,
) -> ClientProfile:
    """Create or update the client's profile row.

    Firm-scoped writes only. The client portal must not change the
    structured profile because it drives the form-set engine.
    """
    if scope is not AccessScope.FIRM:
        raise ClientProfileForbiddenError(
            "Only firm staff may upsert client profile."
        )

    entity = _coerce_entity_type(entity_type)
    industry_value = _coerce_industry(industry)
    home = _validate_state(home_state)
    fye = _validate_month(fiscal_year_end_month)
    addl = (
        [_validate_state(s) for s in additional_states]
        if additional_states is not None
        else None
    )

    existing = sess.execute(
        select(ClientProfile).where(ClientProfile.client_id == client_id)
    ).scalar_one_or_none()

    if existing is None:
        row = ClientProfile(
            firm_id=firm_id,
            client_id=client_id,
            entity_type=entity.value,
            industry=industry_value,
            tax_year=tax_year,
            home_state=home,
            additional_states=addl,
            fiscal_year_end_month=fye,
            entity_attributes=entity_attributes,
        )
        sess.add(row)
        action_detail = {"created": True}
    else:
        row = existing
        row.entity_type = entity.value
        row.industry = industry_value
        row.tax_year = tax_year
        row.home_state = home
        row.additional_states = addl
        row.fiscal_year_end_month = fye
        row.entity_attributes = entity_attributes
        row.updated_at = datetime.now(tz=UTC)
        action_detail = {"updated": True}

    sess.flush()
    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.CLIENT_PROFILE_UPSERT,
        entity_type="client_profile",
        entity_id=row.id,
        details={
            **action_detail,
            "entity_type": entity.value,
            "industry": industry_value,
            "tax_year": tax_year,
            "home_state": home,
            "fiscal_year_end_month": fye,
        },
    )
    return row


__all__ = [
    "ClientProfileError",
    "ClientProfileForbiddenError",
    "ClientProfileNotFoundError",
    "ClientProfileValidationError",
    "get_profile_for_client",
    "upsert_profile",
]
