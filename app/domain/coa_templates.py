"""COA-template domain service.

Two-stage flow:

  1. **Activation** — a firm CPA flips a DRAFT template version to ACTIVE.
     Only one (key, ACTIVE) row may exist at a time; any prior ACTIVE row
     with the same key becomes SUPERSEDED. This is the gating step: until
     it happens, no client can use that template.

  2. **Instantiation** — for one client, walk the ACTIVE general
     template's nodes (and optionally an industry overlay) in
     parent-before-child order and INSERT `chart_of_accounts` rows
     carrying lineage to the source `coa_template_node.id`. Idempotent
     per (firm, client).

Notes:
 * The general base is what defines structure; an overlay only adds extra
   accounts. Overlay nodes whose parent_code matches a general code
   attach under the general node by FK on the client's COA row.
 * Path on the resulting client COA row is the merged real path:
   `<root_code>>...>self_code`, using the client's own UUIDs but the
   template's code structure.
 * Errors raise `CoaTemplateError`; the API layer maps to HTTP 4xx.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tenant import AccessScope
from app.domain.audit import write_audit
from app.models.accounting import ChartOfAccounts
from app.models.coa_template import CoaTemplate, CoaTemplateNode
from app.models.enums import (
    NORMAL_BALANCE_FOR,
    AuditAction,
    CoaNodeOrigin,
    CoaTemplateKind,
    CoaTemplateStatus,
    Industry,
)


class CoaTemplateError(Exception):
    """Raised by the COA template domain service for client-visible errors."""


class CoaTemplateForbiddenError(CoaTemplateError):
    """Raised when scope/role disallows the operation."""


# --------------------------------------------------------------------------- #
# Read helpers
# --------------------------------------------------------------------------- #
def get_active_general(sess: Session) -> CoaTemplate | None:
    """Return the currently ACTIVE general base template, if any."""
    return sess.execute(
        select(CoaTemplate).where(
            CoaTemplate.key == "general",
            CoaTemplate.status == CoaTemplateStatus.ACTIVE,
        )
    ).scalar_one_or_none()


def get_active_overlay(sess: Session, industry: Industry) -> CoaTemplate | None:
    """Return the ACTIVE overlay for an industry, or None (incl. GENERIC)."""
    return sess.execute(
        select(CoaTemplate).where(
            CoaTemplate.key == f"industry:{industry.value}",
            CoaTemplate.status == CoaTemplateStatus.ACTIVE,
        )
    ).scalar_one_or_none()


def list_drafts(sess: Session) -> list[CoaTemplate]:
    """All DRAFT templates, for the CPA review queue."""
    return list(
        sess.execute(
            select(CoaTemplate)
            .where(CoaTemplate.status == CoaTemplateStatus.DRAFT)
            .order_by(CoaTemplate.kind, CoaTemplate.industry, CoaTemplate.version)
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------- #
# Activation
# --------------------------------------------------------------------------- #
def activate_template(
    sess: Session,
    *,
    firm_id: UUID,
    actor: str,
    scope: AccessScope,
    template_id: UUID,
) -> CoaTemplate:
    """Flip DRAFT → ACTIVE, superseding any prior ACTIVE row with the same key.

    Templates are reference data (NOT tenant-scoped), but activation is
    still a firm-level governance action: only AccessScope.FIRM may run it,
    and the audit row is written against the firm with NIL client_id.
    """
    if scope is not AccessScope.FIRM:
        raise CoaTemplateForbiddenError(
            "Only firm staff may activate COA templates."
        )

    tpl = sess.get(CoaTemplate, template_id)
    if tpl is None:
        raise CoaTemplateError("Template not found.")
    if tpl.status is CoaTemplateStatus.ACTIVE:
        # Idempotent — already active.
        return tpl
    if tpl.status is not CoaTemplateStatus.DRAFT:
        raise CoaTemplateError(
            f"Cannot activate template in status {tpl.status.value}; "
            "only DRAFT templates may be activated."
        )

    # Supersede any prior ACTIVE row with the same key.
    prior = sess.execute(
        select(CoaTemplate).where(
            CoaTemplate.key == tpl.key,
            CoaTemplate.status == CoaTemplateStatus.ACTIVE,
            CoaTemplate.id != tpl.id,
        )
    ).scalars().all()
    now = datetime.now(tz=UTC)
    for p in prior:
        p.status = CoaTemplateStatus.SUPERSEDED
    if prior:
        sess.flush()

    tpl.status = CoaTemplateStatus.ACTIVE
    tpl.activated_at = now
    tpl.activated_by = actor
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=UUID(int=0),  # NIL — activation is firm-level
        actor=actor,
        action=AuditAction.COA_TEMPLATE_ACTIVATE,
        entity_type="coa_template",
        entity_id=tpl.id,
        details={
            "key": tpl.key,
            "version": tpl.version,
            "kind": tpl.kind.value,
            "industry": tpl.industry,
            "superseded_ids": [str(p.id) for p in prior],
        },
    )
    return tpl


# --------------------------------------------------------------------------- #
# Instantiation
# --------------------------------------------------------------------------- #
@dataclass
class InstantiationResult:
    """Returned by `instantiate_for_client`."""

    created_count: int
    general_template_id: UUID
    overlay_template_id: UUID | None
    industry: Industry


def instantiate_for_client(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    industry: Industry,
    actor: str,
    scope: AccessScope,
) -> InstantiationResult:
    """Create the chart_of_accounts rows for this client from active templates.

    Order:
      * general nodes first, parent-before-child (BFS by parent_code)
      * then overlay nodes — if an overlay node's parent_code matches a
        general code, the overlay row's parent_account_id points at the
        client's general row of that code; otherwise its parent_code is
        treated as a sibling within the overlay (rare).

    Idempotent: if the client already has any non-custom COA rows, this
    raises a CoaTemplateError. Custom-only seeds (pre-existing flat) are
    *not* a blocker — the caller should explicitly choose to wipe vs. keep
    via a separate admin tool.
    """
    if scope is not AccessScope.FIRM:
        raise CoaTemplateForbiddenError(
            "Only firm staff may instantiate the COA from templates."
        )

    general = get_active_general(sess)
    if general is None:
        raise CoaTemplateError(
            "No ACTIVE general COA template exists. The firm CPA must "
            "activate a 'general' template before any client can be onboarded."
        )

    overlay = get_active_overlay(sess, industry)
    # GENERIC overlay is allowed to be absent — no extra rows is fine.
    if overlay is None and industry is not Industry.GENERIC:
        raise CoaTemplateError(
            f"No ACTIVE overlay exists for industry={industry.value}. "
            "Either activate the overlay or pick 'generic'."
        )

    # Reject if the client already has template-derived rows.
    existing_templated = sess.execute(
        select(ChartOfAccounts.id)
        .where(
            ChartOfAccounts.client_id == client_id,
            ChartOfAccounts.template_node_id.is_not(None),
        )
        .limit(1)
    ).first()
    if existing_templated is not None:
        raise CoaTemplateError(
            "Client already has template-instantiated COA rows. Refusing to "
            "re-instantiate. Use a migration/admin path to re-seed."
        )

    # Load nodes for general + overlay.
    general_nodes = list(
        sess.execute(
            select(CoaTemplateNode)
            .where(CoaTemplateNode.template_id == general.id)
            .order_by(CoaTemplateNode.sort_order, CoaTemplateNode.code)
        )
        .scalars()
        .all()
    )
    overlay_nodes: list[CoaTemplateNode] = []
    if overlay is not None:
        overlay_nodes = list(
            sess.execute(
                select(CoaTemplateNode)
                .where(CoaTemplateNode.template_id == overlay.id)
                .order_by(CoaTemplateNode.sort_order, CoaTemplateNode.code)
            )
            .scalars()
            .all()
        )

    # code -> persisted ChartOfAccounts.id (used to wire up parent_account_id).
    code_to_account: dict[str, UUID] = {}
    code_to_path: dict[str, str] = {}
    code_to_depth: dict[str, int] = {}

    # General-tree first.
    by_parent: dict[str | None, list[CoaTemplateNode]] = defaultdict(list)
    for n in general_nodes:
        by_parent[n.parent_code].append(n)

    # BFS so parents are persisted before children. Root parents have
    # parent_code = None.
    queue: deque[CoaTemplateNode] = deque(by_parent[None])
    has_child_codes: set[str] = {n.parent_code for n in general_nodes if n.parent_code}
    # Compute is_leaf for overlay later by joining both sets.
    overlay_parent_codes: set[str] = {n.parent_code for n in overlay_nodes if n.parent_code}

    created = 0
    while queue:
        n = queue.popleft()
        parent_id = code_to_account.get(n.parent_code) if n.parent_code else None
        parent_path = code_to_path.get(n.parent_code) if n.parent_code else ""
        path = f"{parent_path}>{n.code}" if parent_path else n.code
        depth = (code_to_depth.get(n.parent_code, -1) if n.parent_code else -1) + 1
        # Leaf if no child references this code in general AND no overlay
        # node attaches under it.
        is_leaf = n.code not in has_child_codes and n.code not in overlay_parent_codes

        row = ChartOfAccounts(
            firm_id=firm_id,
            client_id=client_id,
            code=n.code,
            name=n.name,
            account_type=n.account_type,
            normal_balance=NORMAL_BALANCE_FOR[n.account_type],
            parent_account_id=parent_id,
            path=path,
            depth=depth,
            is_leaf=is_leaf,
            template_node_id=n.id,
            origin=CoaNodeOrigin.GENERAL,
            is_active=True,
        )
        sess.add(row)
        sess.flush()  # need row.id to wire children
        code_to_account[n.code] = row.id
        code_to_path[n.code] = path
        code_to_depth[n.code] = depth
        created += 1

        for child in by_parent.get(n.code, []):
            queue.append(child)

    # Overlay rows. Each overlay node's parent_code references either:
    #   * a general node code  (already in code_to_account)
    #   * another overlay node's code (resolved progressively below)
    # Process in topological order of parent_code reachability.
    overlay_by_code = {n.code: n for n in overlay_nodes}
    pending: list[CoaTemplateNode] = list(overlay_nodes)

    safety = len(pending) + 1
    while pending and safety > 0:
        safety -= 1
        deferred: list[CoaTemplateNode] = []
        for n in pending:
            parent_id: UUID | None = None
            parent_path = ""
            parent_depth = -1
            if n.parent_code:
                if n.parent_code in code_to_account:
                    parent_id = code_to_account[n.parent_code]
                    parent_path = code_to_path[n.parent_code]
                    parent_depth = code_to_depth[n.parent_code]
                elif n.parent_code in overlay_by_code:
                    # Parent is another overlay node not yet inserted.
                    deferred.append(n)
                    continue
                else:
                    # Parent_code doesn't exist anywhere — treat as root for safety.
                    parent_id = None
            path = f"{parent_path}>{n.code}" if parent_path else n.code
            depth = parent_depth + 1
            # Leaf if nothing in either set claims this code as its parent.
            is_leaf = n.code not in has_child_codes and n.code not in overlay_parent_codes

            row = ChartOfAccounts(
                firm_id=firm_id,
                client_id=client_id,
                code=n.code,
                name=n.name,
                account_type=n.account_type,
                normal_balance=NORMAL_BALANCE_FOR[n.account_type],
                parent_account_id=parent_id,
                path=path,
                depth=depth,
                is_leaf=is_leaf,
                template_node_id=n.id,
                origin=CoaNodeOrigin.INDUSTRY_OVERLAY,
                is_active=True,
            )
            sess.add(row)
            sess.flush()
            code_to_account[n.code] = row.id
            code_to_path[n.code] = path
            code_to_depth[n.code] = depth
            created += 1
        if len(deferred) == len(pending):
            # No progress this pass — broken parent_code chain in overlay.
            raise CoaTemplateError(
                "Overlay has unresolvable parent_code references: "
                + ", ".join(sorted(n.code for n in deferred))
            )
        pending = deferred

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.COA_TEMPLATE_INSTANTIATE,
        entity_type="chart_of_accounts",
        entity_id=None,
        details={
            "general_template_id": str(general.id),
            "general_version": general.version,
            "overlay_template_id": str(overlay.id) if overlay else None,
            "overlay_version": overlay.version if overlay else None,
            "industry": industry.value,
            "created_count": created,
        },
    )

    return InstantiationResult(
        created_count=created,
        general_template_id=general.id,
        overlay_template_id=overlay.id if overlay else None,
        industry=industry,
    )


__all__ = [
    "CoaTemplateError",
    "CoaTemplateForbiddenError",
    "InstantiationResult",
    "activate_template",
    "get_active_general",
    "get_active_overlay",
    "instantiate_for_client",
    "list_drafts",
]
