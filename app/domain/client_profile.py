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

import re
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
# Validation helpers for contact fields (added Phase 8c)
# --------------------------------------------------------------------------- #
_EIN_RE = re.compile(r"^\d{2}-?\d{7}$")  # XX-XXXXXXX (hyphen optional)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_ein(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned == "":
        return None
    if not _EIN_RE.match(cleaned):
        raise ClientProfileValidationError(
            f"EIN must be in the form XX-XXXXXXX (9 digits), got {value!r}."
        )
    # Persist with the hyphen for human readability.
    digits = cleaned.replace("-", "")
    return f"{digits[:2]}-{digits[2:]}"


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned == "":
        return None
    if not _EMAIL_RE.match(cleaned):
        raise ClientProfileValidationError(
            f"Email is not a valid address: {value!r}."
        )
    return cleaned.lower()


def _trim_or_none(value: str | None, *, max_len: int, field: str) -> str | None:
    """Trim whitespace; treat empty as NULL; enforce max length."""
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned == "":
        return None
    if len(cleaned) > max_len:
        raise ClientProfileValidationError(
            f"{field} must be at most {max_len} characters."
        )
    return cleaned


# --------------------------------------------------------------------------- #
# Upsert
# --------------------------------------------------------------------------- #
# A sentinel that means "don't touch this field" — different from
# explicit None which means "clear this field". Used so a portal-side
# PATCH-style call only touches the fields it sends.
_UNSET = object()


def upsert_profile(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    # ----- Tax-profile fields (writeable by FIRM scope; portal may
    # populate their own value to indicate self-attested entity type).
    entity_type: EntityType | str | None = _UNSET,  # type: ignore[assignment]
    tax_year: int | None = _UNSET,  # type: ignore[assignment]
    industry: Industry | str | None = _UNSET,  # type: ignore[assignment]
    home_state: str | None = _UNSET,  # type: ignore[assignment]
    additional_states: list[str] | None = _UNSET,  # type: ignore[assignment]
    fiscal_year_end_month: int | None = _UNSET,  # type: ignore[assignment]
    entity_attributes: dict | None = _UNSET,  # type: ignore[assignment]
    # ----- Contact / address fields (writeable by FIRM or CLIENT scope).
    business_legal_name: str | None = _UNSET,  # type: ignore[assignment]
    dba_name: str | None = _UNSET,  # type: ignore[assignment]
    ein: str | None = _UNSET,  # type: ignore[assignment]
    phone: str | None = _UNSET,  # type: ignore[assignment]
    email: str | None = _UNSET,  # type: ignore[assignment]
    website: str | None = _UNSET,  # type: ignore[assignment]
    address_line1: str | None = _UNSET,  # type: ignore[assignment]
    address_line2: str | None = _UNSET,  # type: ignore[assignment]
    city: str | None = _UNSET,  # type: ignore[assignment]
    address_state: str | None = _UNSET,  # type: ignore[assignment]
    postal_code: str | None = _UNSET,  # type: ignore[assignment]
    country: str | None = _UNSET,  # type: ignore[assignment]
) -> ClientProfile:
    """Create or update the client's profile row.

    PATCH semantics: any field passed (including ``None``) is written;
    any field left at the ``_UNSET`` sentinel is preserved.

    Scope rules (Phase 8c):
      * **CLIENT** scope (portal) may write all of the contact/address
        fields, plus may self-attest ``entity_type`` / ``tax_year`` /
        ``industry`` / ``home_state`` / ``fiscal_year_end_month``. The
        firm can still override later. We intentionally let the client
        say "I'm an S-corp" — the firm reviews this in their queue
        before generating tax artifacts.
      * **FIRM** scope may write everything.
    """
    if scope not in (AccessScope.FIRM, AccessScope.CLIENT):
        raise ClientProfileForbiddenError(
            "Unknown access scope for client profile upsert."
        )

    # Validate any provided fields (skip _UNSET).
    if entity_type is not _UNSET and entity_type is not None:
        entity_value: str | None = _coerce_entity_type(entity_type).value
    elif entity_type is None:
        entity_value = None
    else:
        entity_value = _UNSET  # type: ignore[assignment]

    if industry is not _UNSET and industry is not None:
        industry_value: str | None = _coerce_industry(industry)
    elif industry is None:
        industry_value = Industry.GENERIC.value
    else:
        industry_value = _UNSET  # type: ignore[assignment]

    home_value = (
        _validate_state(home_state)
        if home_state is not _UNSET
        else _UNSET  # type: ignore[assignment]
    )
    addr_state_value = (
        _validate_state(address_state)
        if address_state is not _UNSET
        else _UNSET  # type: ignore[assignment]
    )
    fye_value = (
        _validate_month(fiscal_year_end_month)
        if fiscal_year_end_month is not _UNSET and fiscal_year_end_month is not None
        else (12 if fiscal_year_end_month is None else _UNSET)
    )
    addl_value = (
        [_validate_state(s) for s in additional_states]
        if additional_states is not _UNSET and additional_states is not None
        else (None if additional_states is None else _UNSET)
    )

    # Contact-field normalization.
    ein_value = _normalize_ein(ein) if ein is not _UNSET else _UNSET  # type: ignore[assignment]
    email_value = _normalize_email(email) if email is not _UNSET else _UNSET  # type: ignore[assignment]
    bln_value = (
        _trim_or_none(business_legal_name, max_len=255, field="business_legal_name")
        if business_legal_name is not _UNSET
        else _UNSET  # type: ignore[assignment]
    )
    dba_value = (
        _trim_or_none(dba_name, max_len=255, field="dba_name")
        if dba_name is not _UNSET
        else _UNSET  # type: ignore[assignment]
    )
    phone_value = (
        _trim_or_none(phone, max_len=64, field="phone")
        if phone is not _UNSET
        else _UNSET  # type: ignore[assignment]
    )
    website_value = (
        _trim_or_none(website, max_len=512, field="website")
        if website is not _UNSET
        else _UNSET  # type: ignore[assignment]
    )
    a1_value = (
        _trim_or_none(address_line1, max_len=255, field="address_line1")
        if address_line1 is not _UNSET
        else _UNSET  # type: ignore[assignment]
    )
    a2_value = (
        _trim_or_none(address_line2, max_len=255, field="address_line2")
        if address_line2 is not _UNSET
        else _UNSET  # type: ignore[assignment]
    )
    city_value = (
        _trim_or_none(city, max_len=128, field="city")
        if city is not _UNSET
        else _UNSET  # type: ignore[assignment]
    )
    postal_value = (
        _trim_or_none(postal_code, max_len=16, field="postal_code")
        if postal_code is not _UNSET
        else _UNSET  # type: ignore[assignment]
    )

    if country is not _UNSET:
        if country is None or str(country).strip() == "":
            country_value: str | None = "US"
        else:
            c = str(country).strip().upper()
            if len(c) != 2:
                raise ClientProfileValidationError(
                    f"Country must be a 2-letter ISO code, got {country!r}."
                )
            country_value = c
    else:
        country_value = _UNSET  # type: ignore[assignment]

    existing = sess.execute(
        select(ClientProfile).where(ClientProfile.client_id == client_id)
    ).scalar_one_or_none()

    if existing is None:
        row = ClientProfile(
            firm_id=firm_id,
            client_id=client_id,
            entity_type=None if entity_value is _UNSET else entity_value,
            industry=Industry.GENERIC.value if industry_value is _UNSET else industry_value,
            tax_year=None if tax_year is _UNSET else tax_year,
            home_state=None if home_value is _UNSET else home_value,
            additional_states=None if addl_value is _UNSET else addl_value,
            fiscal_year_end_month=12 if fye_value is _UNSET else fye_value,
            entity_attributes=None if entity_attributes is _UNSET else entity_attributes,
            business_legal_name=None if bln_value is _UNSET else bln_value,
            dba_name=None if dba_value is _UNSET else dba_value,
            ein=None if ein_value is _UNSET else ein_value,
            phone=None if phone_value is _UNSET else phone_value,
            email=None if email_value is _UNSET else email_value,
            website=None if website_value is _UNSET else website_value,
            address_line1=None if a1_value is _UNSET else a1_value,
            address_line2=None if a2_value is _UNSET else a2_value,
            city=None if city_value is _UNSET else city_value,
            address_state=None if addr_state_value is _UNSET else addr_state_value,
            postal_code=None if postal_value is _UNSET else postal_value,
            country="US" if country_value is _UNSET else country_value,
        )
        sess.add(row)
        action_detail: dict = {"created": True}
    else:
        row = existing
        if entity_value is not _UNSET:
            row.entity_type = entity_value
        if industry_value is not _UNSET:
            row.industry = industry_value
        if tax_year is not _UNSET:
            row.tax_year = tax_year
        if home_value is not _UNSET:
            row.home_state = home_value
        if addl_value is not _UNSET:
            row.additional_states = addl_value
        if fye_value is not _UNSET:
            row.fiscal_year_end_month = fye_value
        if entity_attributes is not _UNSET:
            row.entity_attributes = entity_attributes
        if bln_value is not _UNSET:
            row.business_legal_name = bln_value
        if dba_value is not _UNSET:
            row.dba_name = dba_value
        if ein_value is not _UNSET:
            row.ein = ein_value
        if phone_value is not _UNSET:
            row.phone = phone_value
        if email_value is not _UNSET:
            row.email = email_value
        if website_value is not _UNSET:
            row.website = website_value
        if a1_value is not _UNSET:
            row.address_line1 = a1_value
        if a2_value is not _UNSET:
            row.address_line2 = a2_value
        if city_value is not _UNSET:
            row.city = city_value
        if addr_state_value is not _UNSET:
            row.address_state = addr_state_value
        if postal_value is not _UNSET:
            row.postal_code = postal_value
        if country_value is not _UNSET:
            row.country = country_value
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
            "scope": scope.value,
            "entity_type": row.entity_type,
            "industry": row.industry,
            "tax_year": row.tax_year,
            "home_state": row.home_state,
            "fiscal_year_end_month": row.fiscal_year_end_month,
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
