"""Admin / compliance endpoints.

All endpoints here require FIRM scope (i.e. a CPA-firm staff token), and
each one writes an audit_event before returning. They are mounted under
``/admin``. Per design, there is no client-portal access to anything in
this router.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.core.config import get_settings
from app.db.session import get_owner_engine
from app.db.tenant import AccessScope
from app.integrations.keys import (
    AzureKeyVaultKeyProvider,
    DbDestroyedKeyRegistry,
    LocalKeyProvider,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class DestroyKeysRequest(BaseModel):
    confirm: str
    reason: str


class DestroyKeysResponse(BaseModel):
    firm_id: UUID
    status: str


def _require_firm_admin(identity: AuthIdentity, target_firm_id: UUID) -> None:
    """Hard fail-closed: only the firm's own staff token can act on it.

    Cross-tenant admin actions are forbidden by design — a token issued for
    firm A cannot destroy keys for firm B, regardless of role.
    """
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="firm-scope identity required",
        )
    if identity.firm_id != target_firm_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cross-tenant admin actions are forbidden",
        )


def _build_key_provider():
    """Construct the configured KeyProvider with a DB-backed destroyed registry.

    The registry uses the *owner* engine; it writes to the admin-only
    `tenant_encryption_key` table (no RLS).
    """
    s = get_settings()
    registry = DbDestroyedKeyRegistry(engine_factory=get_owner_engine)
    if s.app_kek_provider == "keyvault":
        if not s.azure_keyvault_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Key Vault provider configured but azure_keyvault_url is empty",
            )
        # Lazy import — keeps tests from needing azure-identity installed.
        from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]

        return AzureKeyVaultKeyProvider(
            vault_url=s.azure_keyvault_url,
            credential=DefaultAzureCredential(),
            key_name_template=s.azure_keyvault_key_name_template,
            registry=registry,
        )
    return LocalKeyProvider(
        master_secret=s.app_local_kek_master.encode(),
        registry=registry,
    )


@router.post(
    "/tenants/{firm_id}/destroy-keys",
    response_model=DestroyKeysResponse,
    status_code=status.HTTP_200_OK,
)
def destroy_tenant_keys(
    firm_id: UUID,
    body: DestroyKeysRequest,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> DestroyKeysResponse:
    """Crypto-shred all per-firm encryption keys.

    This is IRREVERSIBLE. Once destroyed, any document/artifact whose DEK was
    wrapped with this firm's KEK becomes permanently unreadable. The audit
    record is written BEFORE the destruction so the trail survives even if
    the key destruction call later raises.

    Requires:
      * firm-scope identity (no client-portal access);
      * the identity's firm_id == the path firm_id (no cross-tenant);
      * request body `confirm == "DESTROY"` and a non-empty `reason`.
    """
    _require_firm_admin(identity, firm_id)
    if body.confirm != "DESTROY":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='confirm field must equal the literal string "DESTROY"',
        )
    if not body.reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reason must be a non-empty justification (logged in audit trail)",
        )

    # Write audit FIRST so the trail is preserved even on partial failure.
    # Use a separate, OWNER-level connection so the audit row is committed
    # independently of the request transaction. The request transaction may
    # later roll back (e.g. if the key destruction step itself errors); the
    # audit record must survive that.
    import json as _json

    from sqlalchemy import text as _text

    with get_owner_engine().begin() as conn:
        # Owner role is subject to FORCE RLS — set the GUC so the firm-scoped
        # policy on audit_event accepts this insert.
        conn.execute(_text("SELECT set_config('app.current_firm', :v, true)"), {"v": str(firm_id)})
        conn.execute(_text("SELECT set_config('app.current_client', :v, true)"), {"v": str(firm_id)})
        conn.execute(_text("SELECT set_config('app.access_scope', 'firm', true)"))
        conn.execute(
            _text(
                """
                INSERT INTO audit_event
                    (id, firm_id, client_id, actor, action, entity_type, entity_id, details)
                VALUES (
                    gen_random_uuid(), :fid, :fid, :actor,
                    'tenant_keys_destroy', 'firm', :fid, CAST(:details AS jsonb)
                )
                """
            ),
            {
                "fid": str(firm_id),
                "actor": identity.subject,
                "details": _json.dumps({"reason": body.reason}),
            },
        )

    provider = _build_key_provider()
    provider.destroy_tenant_keys(firm_id=firm_id)

    return DestroyKeysResponse(firm_id=firm_id, status="destroyed")
