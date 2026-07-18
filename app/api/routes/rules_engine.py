"""Rules-engine admin endpoints.

Firm staff can view/edit the transaction categorization rules file used by the
Xero-style rule engine. Updates are validated (JSON/YAML) and applied by
reloading the categorizer/classifier wiring in-process.
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.core.config import get_settings
from app.db.tenant import AccessScope
from app.data.coa_templates.general import TEMPLATE as GENERAL_COA_TEMPLATE
from app.models.accounting import ChartOfAccounts, Client
from app.models.enums import AccountType, NormalBalance
from app.integrations.account_categorizer import load_rules_from_file, parse_rules_content
from app.integrations import registry

router = APIRouter(prefix="/admin/rules-engine", tags=["admin"])


class RuleConditionOut(BaseModel):
    field: str
    operator: str
    value: str


class RuleOut(BaseModel):
    name: str
    target_code: str
    match: str
    conditions: list[RuleConditionOut]


class RulesEngineOut(BaseModel):
    backend: str
    rules_file: str
    format: str
    content: str
    rule_count: int
    rules: list[RuleOut]
    coa_sync_clients: int = 0
    coa_sync_accounts_added: int = 0


class RulesEngineUpdateIn(BaseModel):
    content: str


def _require_firm(identity: AuthIdentity) -> None:
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="firm-scope identity required",
        )


def _resolve_rules_file() -> Path:
    settings = get_settings()
    p = Path(settings.app_categorizer_rules_file)
    if p.is_absolute():
        return p
    return Path.cwd() / p


def _format_from_suffix(path: Path) -> str:
    return "yaml" if path.suffix.lower() in {".yaml", ".yml"} else "json"


def _serialize_rules(content: str, fmt: str) -> list[RuleOut]:
    rules = parse_rules_content(content, format_hint=fmt)
    out: list[RuleOut] = []
    for r in rules:
        out.append(
            RuleOut(
                name=r.name,
                target_code=r.target_code,
                match=r.match,
                conditions=[
                    RuleConditionOut(
                        field=c.field,
                        operator=c.operator,
                        value=c.value,
                    )
                    for c in r.conditions
                ],
            )
        )
    return out


def _default_rules_content(fmt: str) -> str:
    rules = load_rules_from_file(Path("/__missing__/categorization_rules.yaml"))
    payload = {
        "rules": [
            {
                "name": r.name,
                "target_code": r.target_code,
                "match": r.match,
                "conditions": [
                    {
                        "field": c.field,
                        "operator": c.operator,
                        "value": c.value,
                    }
                    for c in r.conditions
                ],
            }
            for r in rules
        ]
    }
    # JSON is valid YAML, so this stays parseable for both .json and .yaml.
    _ = fmt
    return json.dumps(payload, indent=2)


def _reload_runtime() -> None:
    # Rebuild categorizer + classifier from settings without touching other
    # integrations already initialized in this process.
    registry.set_categorizer(None)
    registry.set_classifier(None)
    registry.bootstrap_from_settings()


def _default_normal_balance_for_type(account_type: AccountType) -> NormalBalance:
    if account_type in {AccountType.ASSET, AccountType.EXPENSE}:
        return NormalBalance.DEBIT
    return NormalBalance.CREDIT


def _template_account_metadata() -> dict[str, tuple[str, AccountType, NormalBalance]]:
    out: dict[str, tuple[str, AccountType, NormalBalance]] = {}
    for n in GENERAL_COA_TEMPLATE.get("nodes", []):
        code = str(n.get("code") or "").strip()
        if not code:
            continue
        name = str(n.get("name") or f"Account {code}").strip()
        at = n.get("account_type")
        if isinstance(at, AccountType):
            acct_type = at
        else:
            try:
                acct_type = AccountType(str(at))
            except ValueError:
                acct_type = AccountType.EXPENSE
        out[code] = (name, acct_type, _default_normal_balance_for_type(acct_type))
    return out


def _sync_rule_target_codes_into_coa(
    sess: Session,
    *,
    firm_id,
    rules: list[RuleOut],
) -> tuple[int, int]:
    target_codes = sorted({r.target_code.strip() for r in rules if r.target_code.strip()})
    if not target_codes:
        return (0, 0)

    clients = (
        sess.execute(
            select(Client).where(Client.firm_id == firm_id)
        )
        .scalars()
        .all()
    )
    if not clients:
        return (0, 0)

    tmpl = _template_account_metadata()
    created = 0
    touched_clients = 0

    for c in clients:
        existing = {
            a.code
            for a in sess.execute(
                select(ChartOfAccounts).where(ChartOfAccounts.client_id == c.id)
            )
            .scalars()
            .all()
        }
        added_for_client = 0
        for code in target_codes:
            if code in existing:
                continue
            name, acct_type, normal = tmpl.get(
                code,
                (f"Rule Engine Account {code}", AccountType.EXPENSE, NormalBalance.DEBIT),
            )
            sess.add(
                ChartOfAccounts(
                    id=uuid4(),
                    firm_id=firm_id,
                    client_id=c.id,
                    code=code,
                    name=name,
                    account_type=acct_type,
                    normal_balance=normal,
                    is_active=True,
                )
            )
            existing.add(code)
            created += 1
            added_for_client += 1
        if added_for_client > 0:
            touched_clients += 1

    return (touched_clients, created)


@router.get("", response_model=RulesEngineOut)
def get_rules_engine(identity: AuthIdentity = Depends(get_identity)) -> RulesEngineOut:
    _require_firm(identity)
    settings = get_settings()
    path = _resolve_rules_file()
    fmt = _format_from_suffix(path)

    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = _default_rules_content(fmt)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"rules file not found and could not be created: {e}",
            ) from e

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to read rules file: {e}",
        ) from e

    try:
        rules = _serialize_rules(content, fmt)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"rules file is invalid: {e}",
        ) from e

    return RulesEngineOut(
        backend=settings.app_categorizer_backend,
        rules_file=str(path),
        format=fmt,
        content=content,
        rule_count=len(rules),
        rules=rules,
    )


@router.put("", response_model=RulesEngineOut)
def update_rules_engine(
    body: RulesEngineUpdateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> RulesEngineOut:
    _require_firm(identity)
    settings = get_settings()
    path = _resolve_rules_file()
    fmt = _format_from_suffix(path)

    try:
        rules = _serialize_rules(body.content, fmt)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid rules document: {e}",
        ) from e

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body.content, encoding="utf-8")
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"failed to write rules file: {e}",
        ) from e

    try:
        _reload_runtime()
    except Exception as e:  # pragma: no cover - defensive path
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"rules saved but runtime reload failed: {e}",
        ) from e

    synced_clients, synced_accounts = _sync_rule_target_codes_into_coa(
        sess,
        firm_id=identity.firm_id,
        rules=rules,
    )

    return RulesEngineOut(
        backend=settings.app_categorizer_backend,
        rules_file=str(path),
        format=fmt,
        content=body.content,
        rule_count=len(rules),
        rules=rules,
        coa_sync_clients=synced_clients,
        coa_sync_accounts_added=synced_accounts,
    )
