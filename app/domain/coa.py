"""Chart-of-accounts mutation service.

The model carries a materialized hierarchy (`parent_account_id`, `path`,
`depth`, `is_leaf`) that until now was only ever populated by
`coa_templates.instantiate_for_client`. Hand-created accounts went in through
the API with `path=""`, `depth=0`, `is_leaf=True` regardless of where they
actually sat, so the two creation paths disagreed. Every mutation now routes
through here, which keeps the materialized columns true.

Invariants enforced:

* `code` is unique per client. The DB has `uq_coa_client_code` as the
  backstop; we check first so the caller gets a usable message instead of an
  IntegrityError.
* A sub-account has the same `account_type` as its parent. Nesting an expense
  under a liability would make the parent's rolled-up subtree total
  meaningless.
* `normal_balance` is derived from `account_type` via `NORMAL_BALANCE_FOR`,
  never supplied. It is an accounting invariant, so a caller-provided value
  can only ever agree or be wrong.
* Reparenting cannot create a cycle: the new parent may not be the account
  itself nor any of its descendants.
* An account is deletable only when nothing references it — no journal lines
  and no children. Anything with history is deactivated instead, which
  preserves the audit trail that posted entries depend on.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.audit import write_audit
from app.domain.exceptions import DomainError
from app.models.accounting import ChartOfAccounts, JournalLine
from app.models.enums import NORMAL_BALANCE_FOR, AccountType, AuditAction


class CoaError(DomainError):
    """Base for chart-of-accounts mutation failures."""


class CoaConflictError(CoaError):
    """The change collides with existing data (duplicate code, still in use)."""


class CoaValidationError(CoaError):
    """The change is structurally invalid (bad parent, type mismatch, cycle)."""


class CoaNotFoundError(CoaError):
    """No such account in this tenant."""


class _Unset:
    """Sentinel type so PATCH can tell "not supplied" from "explicitly null".

    Matters for `parent_account_id`, where None is a real value meaning
    "promote to top level".
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"


UNSET = _Unset()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _load(sess: Session, *, client_id: UUID, account_id: UUID) -> ChartOfAccounts:
    a = sess.get(ChartOfAccounts, account_id)
    if a is None or a.client_id != client_id:
        # Missing or masked by RLS — same answer either way.
        raise CoaNotFoundError("Account not found in this tenant.")
    return a


def _assert_code_free(
    sess: Session,
    *,
    client_id: UUID,
    code: str,
    exclude_id: UUID | None = None,
) -> None:
    stmt = select(ChartOfAccounts.id).where(
        ChartOfAccounts.client_id == client_id,
        ChartOfAccounts.code == code,
    )
    if exclude_id is not None:
        stmt = stmt.where(ChartOfAccounts.id != exclude_id)
    if sess.execute(stmt.limit(1)).scalar_one_or_none() is not None:
        raise CoaConflictError(
            f"Account code '{code}' is already used by another account for "
            "this client. Codes must be unique."
        )


def _path_for(parent: ChartOfAccounts | None, code: str) -> str:
    return f"{parent.path}>{code}" if parent is not None and parent.path else code


def _resolve_parent(
    sess: Session,
    *,
    client_id: UUID,
    parent_account_id: UUID | None,
    account_type: AccountType,
    child_id: UUID | None = None,
) -> ChartOfAccounts | None:
    if parent_account_id is None:
        return None
    parent = sess.get(ChartOfAccounts, parent_account_id)
    if parent is None or parent.client_id != client_id:
        raise CoaValidationError("Parent account not found for this client.")
    if parent.account_type is not account_type:
        raise CoaValidationError(
            f"A sub-account must have the same type as its parent. Parent "
            f"'{parent.code} {parent.name}' is {parent.account_type.value}, "
            f"but this account is {account_type.value}."
        )
    if child_id is not None:
        if parent.id == child_id:
            raise CoaValidationError("An account cannot be its own parent.")
        # Descendant check via the materialized path: any descendant's path is
        # prefixed by this account's path.
        me = sess.get(ChartOfAccounts, child_id)
        if me is not None and me.path and parent.path.startswith(f"{me.path}>"):
            raise CoaValidationError(
                f"'{parent.code} {parent.name}' is below this account in the "
                "hierarchy; making it the parent would create a cycle."
            )
    return parent


def _refresh_is_leaf(sess: Session, account: ChartOfAccounts | None) -> None:
    if account is None:
        return
    has_child = (
        sess.execute(
            select(ChartOfAccounts.id)
            .where(ChartOfAccounts.parent_account_id == account.id)
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )
    account.is_leaf = not has_child


def _descendants(sess: Session, account: ChartOfAccounts) -> list[ChartOfAccounts]:
    """Every account below `account`, found by path prefix."""
    if not account.path:
        return []
    return list(
        sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == account.client_id,
                ChartOfAccounts.path.like(f"{account.path}>%"),
            )
        )
        .scalars()
        .all()
    )


def _repath_subtree(
    sess: Session, account: ChartOfAccounts, *, old_path: str
) -> None:
    """Rewrite descendants' path/depth after `account` moved or was recoded.

    Called AFTER `account.path` and `account.depth` are updated. Descendants
    are located by the OLD prefix, so this must run before the session is
    flushed with a stale path.
    """
    if not old_path or old_path == account.path:
        return
    rows = (
        sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == account.client_id,
                ChartOfAccounts.path.like(f"{old_path}>%"),
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        suffix = row.path[len(old_path):]  # keeps the leading ">"
        row.path = f"{account.path}{suffix}"
        row.depth = row.path.count(">")


def account_usage(sess: Session, *, client_id: UUID) -> dict[UUID, tuple[int, int]]:
    """Return {account_id: (journal_line_count, child_count)} for a client.

    One pass for the whole COA so the list endpoint stays a fixed number of
    queries rather than N+1.
    """
    line_counts = {
        row.account_id: row.n
        for row in sess.execute(
            select(
                JournalLine.account_id.label("account_id"),
                func.count().label("n"),
            )
            .where(JournalLine.client_id == client_id)
            .group_by(JournalLine.account_id)
        ).all()
    }
    child_counts = {
        row.parent_account_id: row.n
        for row in sess.execute(
            select(
                ChartOfAccounts.parent_account_id.label("parent_account_id"),
                func.count().label("n"),
            )
            .where(
                ChartOfAccounts.client_id == client_id,
                ChartOfAccounts.parent_account_id.is_not(None),
            )
            .group_by(ChartOfAccounts.parent_account_id)
        ).all()
    }
    ids = (
        sess.execute(
            select(ChartOfAccounts.id).where(ChartOfAccounts.client_id == client_id)
        )
        .scalars()
        .all()
    )
    return {i: (line_counts.get(i, 0), child_counts.get(i, 0)) for i in ids}


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #
def create_account(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    code: str,
    name: str,
    account_type: AccountType,
    parent_account_id: UUID | None = None,
) -> ChartOfAccounts:
    code = code.strip()
    name = name.strip()
    _assert_code_free(sess, client_id=client_id, code=code)
    parent = _resolve_parent(
        sess,
        client_id=client_id,
        parent_account_id=parent_account_id,
        account_type=account_type,
    )

    account = ChartOfAccounts(
        id=uuid4(),
        firm_id=firm_id,
        client_id=client_id,
        code=code,
        name=name,
        account_type=account_type,
        normal_balance=NORMAL_BALANCE_FOR[account_type],
        parent_account_id=parent.id if parent else None,
        path=_path_for(parent, code),
        depth=(parent.depth + 1) if parent else 0,
        is_leaf=True,
        is_active=True,
    )
    sess.add(account)
    if parent is not None:
        parent.is_leaf = False
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="chart_of_accounts",
        entity_id=account.id,
        details={
            "code": account.code,
            "name": account.name,
            "account_type": account.account_type.value,
            "parent_account_id": str(parent.id) if parent else None,
        },
    )
    return account


def update_account(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    account_id: UUID,
    code: str | None = None,
    name: str | None = None,
    account_type: AccountType | None = None,
    parent_account_id: UUID | None | _Unset = UNSET,
    is_active: bool | None = None,
) -> ChartOfAccounts:
    """Apply a partial update. Only supplied fields change.

    `parent_account_id` uses the `UNSET` sentinel so an explicit `None`
    (promote to top level) is distinguishable from "leave the parent alone".
    """
    account = _load(sess, client_id=client_id, account_id=account_id)
    old_path = account.path
    old_parent_id = account.parent_account_id
    changes: dict[str, object] = {}

    if code is not None and (code := code.strip()) != account.code:
        _assert_code_free(
            sess, client_id=client_id, code=code, exclude_id=account.id
        )
        changes["code"] = {"from": account.code, "to": code}
        account.code = code

    if name is not None and (name := name.strip()) != account.name:
        changes["name"] = {"from": account.name, "to": name}
        account.name = name

    if account_type is not None and account_type is not account.account_type:
        # Retyping a parent would orphan the same-type rule for its children,
        # and retyping anything with history would silently move posted
        # amounts between statements.
        if _descendants(sess, account):
            raise CoaValidationError(
                "Cannot change the type of an account that has sub-accounts. "
                "Change the sub-accounts first."
            )
        lines, _ = account_usage(sess, client_id=client_id).get(account.id, (0, 0))
        if lines:
            raise CoaConflictError(
                f"Cannot change the type of '{account.code} {account.name}': "
                f"{lines} journal line(s) already post to it. Posted amounts "
                "would move between statements."
            )
        changes["account_type"] = {
            "from": account.account_type.value,
            "to": account_type.value,
        }
        account.account_type = account_type
        account.normal_balance = NORMAL_BALANCE_FOR[account_type]

    if not isinstance(parent_account_id, _Unset):
        new_parent_id = parent_account_id
        if new_parent_id != old_parent_id:
            parent = _resolve_parent(
                sess,
                client_id=client_id,
                parent_account_id=new_parent_id,
                account_type=account.account_type,
                child_id=account.id,
            )
            changes["parent_account_id"] = {
                "from": str(old_parent_id) if old_parent_id else None,
                "to": str(parent.id) if parent else None,
            }
            account.parent_account_id = parent.id if parent else None
            account.depth = (parent.depth + 1) if parent else 0
            if parent is not None:
                parent.is_leaf = False

    if is_active is not None and is_active != account.is_active:
        changes["is_active"] = {"from": account.is_active, "to": is_active}
        account.is_active = is_active

    if not changes:
        return account

    # Recompute this node's path from its (possibly new) parent and code, then
    # carry the change down the subtree.
    parent_now = (
        sess.get(ChartOfAccounts, account.parent_account_id)
        if account.parent_account_id
        else None
    )
    account.path = _path_for(parent_now, account.code)
    _repath_subtree(sess, account, old_path=old_path)

    # The old parent may have just lost its last child.
    if old_parent_id and old_parent_id != account.parent_account_id:
        _refresh_is_leaf(sess, sess.get(ChartOfAccounts, old_parent_id))
    _refresh_is_leaf(sess, account)
    sess.flush()

    action = (
        AuditAction.COA_ACCOUNT_DEACTIVATE
        if changes.get("is_active", {}).get("to") is False  # type: ignore[union-attr]
        else AuditAction.COA_ACCOUNT_RENAME
    )
    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=action,
        entity_type="chart_of_accounts",
        entity_id=account.id,
        details={"changes": changes},
    )
    return account


def delete_account(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    account_id: UUID,
) -> None:
    """Remove an account outright. Only legal when nothing references it.

    Anything with journal history must be deactivated instead — deleting it
    would break the audit trail every posted entry depends on.
    """
    account = _load(sess, client_id=client_id, account_id=account_id)
    lines, children = account_usage(sess, client_id=client_id).get(
        account.id, (0, 0)
    )
    if lines:
        raise CoaConflictError(
            f"'{account.code} {account.name}' has {lines} journal line(s) "
            "posted to it and cannot be removed. Deactivate it instead — it "
            "will stop appearing in pickers but its history stays intact."
        )
    if children:
        raise CoaConflictError(
            f"'{account.code} {account.name}' has {children} sub-account(s). "
            "Remove or reparent them first."
        )

    parent_id = account.parent_account_id
    snapshot = {
        "code": account.code,
        "name": account.name,
        "account_type": account.account_type.value,
    }
    sess.delete(account)
    sess.flush()

    if parent_id:
        _refresh_is_leaf(sess, sess.get(ChartOfAccounts, parent_id))
        sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.DELETE,
        entity_type="chart_of_accounts",
        entity_id=account_id,
        details=snapshot,
    )


__all__ = [
    "UNSET",
    "CoaConflictError",
    "CoaError",
    "CoaNotFoundError",
    "CoaValidationError",
    "account_usage",
    "create_account",
    "delete_account",
    "update_account",
]
