"""Structured, tenant-scoped, redacting JSON logger.

Design goals
------------
1. Every record is JSON, single-line, suitable for App Insights / Log
   Analytics ingestion without further parsing.
2. Every record carries the tenant fields (firm_id, client_id, request_id,
   actor, access_scope) pulled from `app.core.context` ContextVars.
3. A redaction filter scrubs:
     * US SSNs (``\\d{3}-\\d{2}-\\d{4}``)
     * EINs (``\\d{2}-\\d{7}``)
     * Long base64-ish blobs that look like document bytes (length >= 80).
   And it refuses to emit certain field names that, by convention, hold raw
   client data: ``body``, ``content``, ``raw``, ``payload_bytes``,
   ``file_bytes``, ``data``.
4. No third-party logger lib — uses only stdlib. Keeps dependency surface
   tight (compliance-friendly).

This is deliberately conservative: false-positive redactions are better than
leaking a client SSN into a log aggregator.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.core.context import (
    access_scope_var,
    actor_var,
    client_id_var,
    firm_id_var,
    request_id_var,
)

# ---- Redaction --------------------------------------------------------------

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EIN_RE = re.compile(r"\b\d{2}-\d{7}\b")
_BIG_BLOB_RE = re.compile(r"[A-Za-z0-9+/=]{80,}")

_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {"body", "content", "raw", "payload_bytes", "file_bytes", "data"}
)

_REDACTED = "[REDACTED]"


def _scrub_string(s: str) -> str:
    s = _SSN_RE.sub(_REDACTED, s)
    s = _EIN_RE.sub(_REDACTED, s)
    s = _BIG_BLOB_RE.sub(_REDACTED, s)
    return s


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return _scrub_string(value)
    if isinstance(value, dict):
        return {k: _REDACTED if k in _FORBIDDEN_FIELDS else _scrub_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_value(v) for v in value]
    return value


class RedactionFilter(logging.Filter):
    """Mutates the LogRecord message and extras in place."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = _scrub_value(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = _scrub_value(record.args)
                else:
                    record.args = tuple(_scrub_value(a) for a in record.args)
        except Exception:
            # Never let logging blow up the request.
            pass
        return True


# ---- Formatter --------------------------------------------------------------

_STANDARD_KEYS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        firm = firm_id_var.get()
        client = client_id_var.get()
        rid = request_id_var.get()
        actor = actor_var.get()
        scope = access_scope_var.get()
        if firm is not None:
            payload["firm_id"] = str(firm)
        if client is not None:
            payload["client_id"] = str(client)
        if rid is not None:
            payload["request_id"] = rid
        if actor is not None:
            payload["actor"] = actor
        if scope is not None:
            payload["access_scope"] = scope

        # Surface any `extra={...}` fields the caller passed.
        for k, v in record.__dict__.items():
            if k in _STANDARD_KEYS or k.startswith("_"):
                continue
            if k in _FORBIDDEN_FIELDS:
                payload[k] = _REDACTED
            else:
                payload[k] = _scrub_value(v)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info

        return json.dumps(payload, default=str, separators=(",", ":"))


# ---- Configuration ----------------------------------------------------------

def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.app_log_level.upper(), logging.INFO)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
