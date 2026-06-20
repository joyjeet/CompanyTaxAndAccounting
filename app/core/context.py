"""Per-request context vars consumed by the logging formatter and metrics.

These are deliberately decoupled from FastAPI's request object so that the
worker process and admin scripts can also populate them. Anything emitted
via `logging.*` while one of these is set will be tagged on the log record.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Final
from uuid import UUID

request_id_var: Final[ContextVar[str | None]] = ContextVar("request_id", default=None)
firm_id_var: Final[ContextVar[UUID | None]] = ContextVar("firm_id", default=None)
client_id_var: Final[ContextVar[UUID | None]] = ContextVar("client_id", default=None)
actor_var: Final[ContextVar[str | None]] = ContextVar("actor", default=None)
access_scope_var: Final[ContextVar[str | None]] = ContextVar("access_scope", default=None)


def reset_all() -> None:
    request_id_var.set(None)
    firm_id_var.set(None)
    client_id_var.set(None)
    actor_var.set(None)
    access_scope_var.set(None)
