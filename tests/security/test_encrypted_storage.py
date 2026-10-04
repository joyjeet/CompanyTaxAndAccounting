"""EncryptedStorage wrapper tests."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.integrations.keys import LocalKeyProvider
from app.integrations.storage import LocalFilesystemStorage
from app.security.encrypted_storage import EncryptedStorage


@pytest.fixture
def storage(tmp_path):  # type: ignore[no-untyped-def]
    inner = LocalFilesystemStorage(root=tmp_path / "blob")
    kp = LocalKeyProvider(master_secret=b"y" * 32)
    return EncryptedStorage(inner=inner, key_provider=kp), inner, kp


def test_put_and_get_round_trip(storage) -> None:  # type: ignore[no-untyped-def]
    enc, _inner, _kp = storage
    firm, client = uuid4(), uuid4()
    plaintext = b"the IRS has questions" * 50
    stored = enc.put(
        firm_id=firm, client_id=client, doc_type="w2", data=plaintext
    )
    assert stored.size > len(plaintext)  # JSON envelope overhead
    out = enc.get(firm_id=firm, client_id=client, storage_uri=stored.storage_uri)
    assert out == plaintext


def test_at_rest_does_not_contain_plaintext(storage, tmp_path) -> None:  # type: ignore[no-untyped-def]
    enc, inner, _kp = storage
    firm, client = uuid4(), uuid4()
    plaintext = b"SSN: 123-45-6789 secret-marker-xyz"
    stored = enc.put(
        firm_id=firm, client_id=client, doc_type="receipt", data=plaintext
    )
    raw_on_disk = inner.get(
        firm_id=firm, client_id=client, storage_uri=stored.storage_uri
    )
    assert b"secret-marker-xyz" not in raw_on_disk
    # Assert the SSN *value* is absent, not the label "SSN": the base64
    # ciphertext can coincidentally contain a 3-letter run like "SSN", but the
    # base64 alphabet has no hyphens, so the hyphenated number never collides.
    assert b"123-45-6789" not in raw_on_disk


def test_cross_firm_read_refused(storage) -> None:  # type: ignore[no-untyped-def]
    """Even at the storage layer, the prefix-guard refuses cross-firm reads.
    This test exercises the path where firm B tries to read firm A's URI —
    the guard fires before decryption is attempted."""
    enc, _inner, _kp = storage
    firm_a, firm_b, client = uuid4(), uuid4(), uuid4()
    stored = enc.put(
        firm_id=firm_a, client_id=client, doc_type="w2", data=b"x"
    )
    with pytest.raises(PermissionError):
        enc.get(firm_id=firm_b, client_id=client, storage_uri=stored.storage_uri)


def test_exists_passes_through(storage) -> None:  # type: ignore[no-untyped-def]
    enc, _inner, _kp = storage
    firm, client = uuid4(), uuid4()
    stored = enc.put(firm_id=firm, client_id=client, doc_type="w2", data=b"x")
    assert enc.exists(firm_id=firm, client_id=client, storage_uri=stored.storage_uri)


def test_corrupted_blob_fails_decryption(storage) -> None:  # type: ignore[no-untyped-def]
    """If the on-disk bytes are corrupted, get() must raise — never silently
    return garbage. Easiest way: write garbage at the inner layer and try to
    read through the wrapper."""
    enc, inner, _kp = storage
    firm, client = uuid4(), uuid4()
    stored = inner.put(
        firm_id=firm, client_id=client, doc_type="w2", data=b"not an envelope"
    )
    with pytest.raises(Exception):  # noqa: B017,PT011 — DecryptionError
        enc.get(firm_id=firm, client_id=client, storage_uri=stored.storage_uri)
