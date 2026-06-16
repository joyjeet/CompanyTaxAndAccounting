"""Tests for the per-tenant blob storage layer."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.integrations.storage import (
    LocalFilesystemStorage,
    sha256_hex,
    tenant_path,
)


def test_tenant_path_partitioning_is_predictable() -> None:
    firm_id = uuid4()
    client_id = uuid4()
    obj_id = uuid4()
    p = tenant_path(
        firm_id=firm_id,
        client_id=client_id,
        doc_type="invoice",
        obj_id=obj_id,
        ext=".pdf",
    )
    assert p.startswith(f"firm-{firm_id}/client-{client_id}/")
    assert p.endswith(f"{obj_id}.pdf")


def test_tenant_path_rejects_unsafe_inputs() -> None:
    firm_id = uuid4()
    client_id = uuid4()
    obj_id = uuid4()
    with pytest.raises(ValueError):
        tenant_path(
            firm_id=firm_id, client_id=client_id, doc_type="../escape",
            obj_id=obj_id, ext=".pdf",
        )
    with pytest.raises(ValueError):
        tenant_path(
            firm_id=firm_id, client_id=client_id, doc_type="invoice",
            obj_id=obj_id, ext="../etc/passwd",
        )


def test_local_storage_writes_and_reads(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(root=tmp_path)
    firm_id = uuid4()
    client_id = uuid4()
    data = b"hello world"
    obj = storage.put(
        firm_id=firm_id,
        client_id=client_id,
        doc_type="invoice",
        data=data,
        filename="file.pdf",
        content_type="application/pdf",
    )
    assert obj.size == len(data)
    assert obj.sha256 == sha256_hex(data)
    # Round-trip
    assert storage.get(firm_id=firm_id, client_id=client_id, storage_uri=obj.storage_uri) == data
    assert storage.exists(firm_id=firm_id, client_id=client_id, storage_uri=obj.storage_uri)


def test_local_storage_blocks_cross_tenant_read(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(root=tmp_path)
    firm_a = uuid4()
    firm_b = uuid4()
    client_a = uuid4()
    client_b = uuid4()
    obj = storage.put(
        firm_id=firm_a, client_id=client_a, doc_type="invoice",
        data=b"secret-a", filename="a.pdf", content_type="application/pdf",
    )
    # Firm B trying to read firm A's URI must be refused.
    with pytest.raises(PermissionError):
        storage.get(firm_id=firm_b, client_id=client_b, storage_uri=obj.storage_uri)
    with pytest.raises(PermissionError):
        storage.exists(firm_id=firm_b, client_id=client_b, storage_uri=obj.storage_uri)


def test_local_storage_path_traversal_is_blocked(tmp_path: Path) -> None:
    storage = LocalFilesystemStorage(root=tmp_path)
    firm_id = uuid4()
    client_id = uuid4()
    # An attacker-supplied URI that tries to escape the root:
    bad = f"firm-{firm_id}/client-{client_id}/../../etc/passwd"
    # The prefix check passes (it starts with the right prefix), but the
    # filesystem resolution must still refuse to step outside `root`.
    with pytest.raises((PermissionError, FileNotFoundError, IsADirectoryError, OSError)):
        storage.get(firm_id=firm_id, client_id=client_id, storage_uri=bad)


def test_two_puts_of_same_bytes_produce_distinct_uris(tmp_path: Path) -> None:
    """Storage.put() is NOT itself idempotent on bytes — idempotency lives in
    the ingest layer (via SourceDocument.sha256 lookup). Two puts of the same
    bytes yield distinct keys (different uuid suffixes)."""
    storage = LocalFilesystemStorage(root=tmp_path)
    firm_id = uuid4()
    client_id = uuid4()
    a = storage.put(
        firm_id=firm_id, client_id=client_id, doc_type="invoice",
        data=b"x", filename="x.pdf", content_type="application/pdf",
    )
    b = storage.put(
        firm_id=firm_id, client_id=client_id, doc_type="invoice",
        data=b"x", filename="x.pdf", content_type="application/pdf",
    )
    assert a.storage_uri != b.storage_uri
    assert a.sha256 == b.sha256
