"""Tenant-partitioned blob storage.

Two implementations:
  * `LocalFilesystemStorage`  — dev/test default; writes under ./data/blob/.
  * `AzureBlobStorage`         — production; lazy import of azure-storage-blob.

Critical safety property
------------------------
The full storage path is ALWAYS computed by `_tenant_path()` from the caller's
identity (firm_id, client_id) plus a server-generated UUID and the *server*
content type. Callers cannot pass a path. This makes it impossible for a
session bound to client A to write into / read from client B's prefix.

Path layout:
    firm-{firm_id}/client-{client_id}/{yyyy}/{doc_type}/{uuid}{ext}
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
_DOC_TYPE_RE = re.compile(r"^[a-z0-9_\-]+$")
_SAFE_EXT_RE = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def guess_extension(filename: str | None, mime_type: str | None) -> str:
    if filename:
        ext = os.path.splitext(filename)[1]
        if ext and _SAFE_EXT_RE.match(ext):
            return ext.lower()
    if mime_type:
        ext = mimetypes.guess_extension(mime_type) or ""
        if ext and _SAFE_EXT_RE.match(ext):
            return ext.lower()
    return ".bin"


def tenant_path(
    *,
    firm_id: UUID,
    client_id: UUID,
    doc_type: str,
    obj_id: UUID,
    ext: str,
    when: datetime | None = None,
) -> str:
    """Compute the canonical tenant-partitioned object key.

    Inputs are normalized: doc_type must be a lowercase slug; ext must look
    like a real file extension. UUIDs are stringified through the type system,
    so a caller cannot inject path traversal into the firm or client segment.
    """
    if not _DOC_TYPE_RE.match(doc_type):
        raise ValueError(f"doc_type {doc_type!r} must be a lowercase slug")
    if not _SAFE_EXT_RE.match(ext):
        raise ValueError(f"ext {ext!r} is not a safe extension")
    when = when or datetime.now(tz=UTC)
    return (
        f"firm-{firm_id}/client-{client_id}/{when:%Y}/{doc_type}/{obj_id}{ext}"
    )


# --------------------------------------------------------------------------- #
# Service interface
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class StoredObject:
    storage_uri: str
    sha256: str
    size: int
    content_type: str | None


class StorageService(ABC):
    """Per-tenant blob storage.

    `put()` is the only sanctioned write path. It does NOT accept a `key`
    argument: keys are computed from the tenant identity. `get()` and
    `exists()` accept a `storage_uri` previously returned by `put()` and
    refuse if the URI does not begin with the calling tenant's prefix.
    """

    @abstractmethod
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
        ...

    @abstractmethod
    def get(self, *, firm_id: UUID, client_id: UUID, storage_uri: str) -> bytes:
        ...

    @abstractmethod
    def exists(self, *, firm_id: UUID, client_id: UUID, storage_uri: str) -> bool:
        ...

    # ----- Tenant-prefix guard (shared by impls) ------------------------ #
    @staticmethod
    def _check_prefix(storage_uri: str, firm_id: UUID, client_id: UUID) -> None:
        prefix = f"firm-{firm_id}/client-{client_id}/"
        if not storage_uri.startswith(prefix):
            raise PermissionError(
                "storage_uri does not belong to the calling tenant"
            )


# --------------------------------------------------------------------------- #
# Local filesystem (dev/test)
# --------------------------------------------------------------------------- #
class LocalFilesystemStorage(StorageService):
    def __init__(self, root: str | Path = "./data/blob") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _full(self, storage_uri: str) -> Path:
        # Resolve and ensure the result is still inside `self.root`. Defense
        # in depth: tenant_path already prevents traversal, but this catches
        # any pathological key.
        candidate = (self.root / storage_uri).resolve()
        if not str(candidate).startswith(str(self.root) + os.sep) and candidate != self.root:
            raise PermissionError("path traversal detected")
        return candidate

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
        ext = guess_extension(filename, content_type)
        obj_id = uuid4()
        key = tenant_path(
            firm_id=firm_id, client_id=client_id, doc_type=doc_type,
            obj_id=obj_id, ext=ext,
        )
        full = self._full(key)
        full.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically: write to .tmp then rename.
        tmp = full.with_suffix(full.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(full)
        return StoredObject(
            storage_uri=key,
            sha256=sha256_hex(data),
            size=len(data),
            content_type=content_type,
        )

    def get(self, *, firm_id: UUID, client_id: UUID, storage_uri: str) -> bytes:
        self._check_prefix(storage_uri, firm_id, client_id)
        return self._full(storage_uri).read_bytes()

    def exists(self, *, firm_id: UUID, client_id: UUID, storage_uri: str) -> bool:
        self._check_prefix(storage_uri, firm_id, client_id)
        return self._full(storage_uri).is_file()

    def reset(self) -> None:
        """Test helper: wipe the local store. Not on the ABC."""
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Azure Blob Storage (lazy import — optional dep)
# --------------------------------------------------------------------------- #
class AzureBlobStorage(StorageService):
    """Azure Blob backend. Imported lazily so the dev environment doesn't
    require `azure-storage-blob` until you actually run against Azure."""

    def __init__(self, *, account_url: str, container: str, credential: object) -> None:
        # Lazy import keeps `pip install -e .[dev]` light.
        from azure.storage.blob import BlobServiceClient  # type: ignore[import-not-found]

        self._service = BlobServiceClient(account_url=account_url, credential=credential)
        self._container = self._service.get_container_client(container)

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
        from azure.storage.blob import ContentSettings  # type: ignore[import-not-found]

        ext = guess_extension(filename, content_type)
        obj_id = uuid4()
        key = tenant_path(
            firm_id=firm_id, client_id=client_id, doc_type=doc_type,
            obj_id=obj_id, ext=ext,
        )
        cs = ContentSettings(content_type=content_type) if content_type else None
        # if_none_match='*' makes the upload fail if the blob exists, giving
        # immutable-create semantics.
        self._container.upload_blob(
            name=key, data=data, overwrite=False, content_settings=cs,
            if_none_match="*",
        )
        return StoredObject(
            storage_uri=key,
            sha256=sha256_hex(data),
            size=len(data),
            content_type=content_type,
        )

    def get(self, *, firm_id: UUID, client_id: UUID, storage_uri: str) -> bytes:
        self._check_prefix(storage_uri, firm_id, client_id)
        blob = self._container.get_blob_client(storage_uri)
        return blob.download_blob().readall()

    def exists(self, *, firm_id: UUID, client_id: UUID, storage_uri: str) -> bool:
        self._check_prefix(storage_uri, firm_id, client_id)
        return self._container.get_blob_client(storage_uri).exists()


__all__ = [
    "AzureBlobStorage",
    "LocalFilesystemStorage",
    "StorageService",
    "StoredObject",
    "guess_extension",
    "sha256_hex",
    "tenant_path",
]
