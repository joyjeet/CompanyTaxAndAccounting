"""Envelope-encrypted storage decorator.

`EncryptedStorage` composes any `StorageService` and transparently
envelope-encrypts payloads before they hit the underlying backend, then
decrypts on read. Tenant-prefix safety is preserved because the wrapper
delegates `put()` to the inner service (which computes the canonical key
from `firm_id` / `client_id`); the wrapper does not invent its own keys.

Wire format
-----------
We serialise the entire `Envelope` (header + ciphertext) as one JSON blob
and write it as the object body. That keeps the storage contract simple
(one `put`, one `get`) and avoids the consistency problem of a separate
sidecar object. The trade-off is ~30% overhead from base64; acceptable for
documents we already chose to encrypt.

`storage_uri` returned to callers is the underlying service's storage_uri.
The `sha256` field on `StoredObject` is intentionally the SHA-256 of the
ciphertext (what's actually at rest), not the plaintext, because
deduplication/verification on the storage side must match what's stored.
The plaintext sha256 is computed by the ingest layer BEFORE handing to
storage and is what's recorded on `source_document.sha256`, so dedup-by-
content still works.
"""
from __future__ import annotations

from uuid import UUID

from app.integrations.keys import KeyProvider
from app.integrations.storage import StorageService, StoredObject, sha256_hex
from app.security.envelope import Envelope, decrypt, encrypt


class EncryptedStorage(StorageService):
    """Decorator. Wraps any underlying StorageService."""

    def __init__(self, *, inner: StorageService, key_provider: KeyProvider) -> None:
        self._inner = inner
        self._kp = key_provider

    # ------------------------------------------------------------------ #
    def put(
        self,
        *,
        firm_id: UUID,
        client_id: UUID,
        doc_type: str,
        data: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> StoredObject:
        envelope = encrypt(
            plaintext=data,
            firm_id=firm_id,
            key_provider=self._kp,
        )
        ciphertext_bytes = envelope.to_bytes()
        # Force `.bin` extension for stored object — the actual MIME on disk
        # is application/octet-stream regardless of original.
        stored = self._inner.put(
            firm_id=firm_id,
            client_id=client_id,
            doc_type=doc_type,
            data=ciphertext_bytes,
            filename=None,
            content_type="application/octet-stream",
        )
        # Override sha256/size with the on-disk values so callers reasoning
        # about dedup of the at-rest object see consistent numbers.
        return StoredObject(
            storage_uri=stored.storage_uri,
            sha256=sha256_hex(ciphertext_bytes),
            size=len(ciphertext_bytes),
            content_type=content_type,  # echo caller's intent for the plaintext
        )

    # ------------------------------------------------------------------ #
    def get(self, *, firm_id: UUID, client_id: UUID, storage_uri: str) -> bytes:
        raw = self._inner.get(
            firm_id=firm_id, client_id=client_id, storage_uri=storage_uri
        )
        envelope = Envelope.from_bytes(raw)
        return decrypt(envelope=envelope, firm_id=firm_id, key_provider=self._kp)

    # ------------------------------------------------------------------ #
    def exists(self, *, firm_id: UUID, client_id: UUID, storage_uri: str) -> bool:
        return self._inner.exists(
            firm_id=firm_id, client_id=client_id, storage_uri=storage_uri
        )


__all__ = ["EncryptedStorage"]
