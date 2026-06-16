"""Minimal tenant-scoped read endpoint to verify the RLS pipeline end-to-end.

Real CRUD endpoints for clients, COA, journal entries, etc. arrive in the next
phase. This handler exists so the foundation is demonstrably wired together.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.models.accounting import Client

router = APIRouter(prefix="/clients", tags=["clients"])


class ClientOut(BaseModel):
    id: UUID
    firm_id: UUID
    name: str
    external_code: str | None


@router.get("", response_model=list[ClientOut])
def list_clients(sess: Session = Depends(db_session)) -> list[ClientOut]:
    """Returns the clients visible to the caller under their tenant context.

    RLS guarantees we never see another firm's clients, and a portal user
    (scope='client') sees only their own client row.
    """
    rows = sess.execute(select(Client)).scalars().all()
    return [
        ClientOut(
            id=c.id, firm_id=c.firm_id, name=c.name, external_code=c.external_code
        )
        for c in rows
    ]
