"""Tenant context types and helpers.

The RLS policies on every tenant-scoped table are keyed on three transaction-local
GUCs:

    app.current_firm    — UUID of the firm
    app.current_client  — UUID of the client (only enforced for 'client' scope)
    app.access_scope    — 'firm' or 'client'

The values are read from Postgres with `current_setting(..., true)` (the second
argument means "missing setting -> NULL"), so an unset context evaluates the
policy to FALSE and returns zero rows. Fail closed by construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class AccessScope(StrEnum):
    """Who is acting.

    - FIRM: a CPA-firm staff member; can read/write all clients within the firm.
    - CLIENT: a client portal user; can only read/write their own client_id.
    """

    FIRM = "firm"
    CLIENT = "client"


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Identity-derived tenant context. NEVER constructed from request body/query."""

    firm_id: UUID
    scope: AccessScope
    # Required if scope == CLIENT. May be set for FIRM scope to scope a particular
    # working session to a single client; if None for FIRM, all clients in the
    # firm are visible.
    client_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.scope is AccessScope.CLIENT and self.client_id is None:
            raise ValueError("client_id is required when access_scope='client'")
