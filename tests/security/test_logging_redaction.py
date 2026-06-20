"""Phase 7 — structured logging redaction tests.

Verifies SSN/EIN scrubbing, forbidden-field allowlist, and that tenant
ContextVars surface on each log record. Captures stdout because the
configured logger writes JSON to stdout.
"""
from __future__ import annotations

import io
import json
import logging
from uuid import uuid4

import pytest

from app.core import context
from app.core.logging import JsonFormatter, RedactionFilter, configure_logging


@pytest.fixture(autouse=True)
def _reset_ctx() -> None:
    context.reset_all()


def _emit_and_capture(record_factory) -> dict:
    """Build a record through the formatter+filter, return the parsed JSON."""
    fmt = JsonFormatter()
    flt = RedactionFilter()
    rec = record_factory()
    flt.filter(rec)
    out = fmt.format(rec)
    return json.loads(out)


def _make_record(msg: str, **extra: object) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="ctaa.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=None,
    )
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_ssn_in_message_is_redacted() -> None:
    payload = _emit_and_capture(lambda: _make_record("processing ssn=123-45-6789 for client"))
    assert "123-45-6789" not in payload["msg"]
    assert "[REDACTED]" in payload["msg"]


def test_ein_in_message_is_redacted() -> None:
    payload = _emit_and_capture(lambda: _make_record("ein 12-3456789 lookup"))
    assert "12-3456789" not in payload["msg"]
    assert "[REDACTED]" in payload["msg"]


def test_long_base64_blob_in_message_is_redacted() -> None:
    blob = "A" * 200
    payload = _emit_and_capture(lambda: _make_record(f"payload={blob}"))
    assert blob not in payload["msg"]
    assert "[REDACTED]" in payload["msg"]


def test_forbidden_extra_field_name_is_redacted() -> None:
    payload = _emit_and_capture(
        lambda: _make_record("uploaded", body=b"actual file bytes here")
    )
    assert payload["body"] == "[REDACTED]"


def test_ssn_in_extra_dict_value_is_redacted() -> None:
    payload = _emit_and_capture(
        lambda: _make_record("ok", meta={"note": "patient ssn 123-45-6789 included"})
    )
    assert "123-45-6789" not in json.dumps(payload)


def test_tenant_context_appears_on_record() -> None:
    firm = uuid4()
    client = uuid4()
    context.firm_id_var.set(firm)
    context.client_id_var.set(client)
    context.request_id_var.set("req-abc")
    context.actor_var.set("user-1")
    context.access_scope_var.set("firm")
    payload = _emit_and_capture(lambda: _make_record("hello"))
    assert payload["firm_id"] == str(firm)
    assert payload["client_id"] == str(client)
    assert payload["request_id"] == "req-abc"
    assert payload["actor"] == "user-1"
    assert payload["access_scope"] == "firm"


def test_full_logger_path_writes_json_to_stdout(capsys) -> None:  # type: ignore[no-untyped-def]
    """End-to-end: configure_logging() + log a sensitive line."""
    # Reset root handlers and reconfigure to capture cleanly.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    # Redirect StreamHandler to stdout (which capsys captures).
    configure_logging()
    handler = root.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    # Force the handler to write to a fresh buffer we can read.
    buf = io.StringIO()
    handler.stream = buf
    logging.getLogger("ctaa.audit").info("seen ssn 555-11-2222 in upload")
    line = buf.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)
    assert "555-11-2222" not in payload["msg"]
    assert payload["level"] == "INFO"
    assert payload["logger"] == "ctaa.audit"
