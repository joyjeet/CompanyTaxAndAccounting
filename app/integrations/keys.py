"""Per-tenant Key-Encryption-Key (KEK) provider.

Two real implementations sit behind the `KeyProvider` ABC:

* `LocalKeyProvider`         — derives a per-firm 256-bit KEK from a master
                              secret (HKDF-SHA256), wraps DEKs with AES Key
                              Wrap (RFC 3394). Suitable for tests and local
                              dev. Crypto-shred is implemented by recording
                              the firm in a destroyed-keys registry; unwraps
                              for destroyed firms raise `KeyDestroyedError`.
* `AzureKeyVaultKeyProvider` — per-firm RSA key in Azure Key Vault. Wrap /
                              unwrap go through the Key Vault Crypto API.
                              Destroy issues `begin_delete_key`. Per-firm key
                              naming is configurable via settings.

The application never sees plaintext KEK material in the Azure case; for the
local case the KEK is derived on demand and never persisted.

The destroyed-key check is performed on every wrap/unwrap so a destroy
operation takes effect immediately for any subsequent read.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Protocol
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.keywrap import (
    InvalidUnwrap,
    aes_key_unwrap,
    aes_key_wrap,
)


class KeyDestroyedError(Exception):
    """The KEK for this firm has been destroyed (crypto-shred). All ciphertext
    encrypted under this firm is now unrecoverable. Surface to callers as a
    permanent failure; never retry."""


class KeyProvider(ABC):
    @property
    @abstractmethod
    def kek_id(self) -> str:
        """Identifier of the key-encryption key used by this provider."""

    @abstractmethod
    def wrap_data_key(self, *, firm_id: UUID, dek: bytes) -> bytes:
        ...

    @abstractmethod
    def unwrap_data_key(self, *, firm_id: UUID, wrapped: bytes) -> bytes:
        ...

    @abstractmethod
    def destroy_tenant_keys(self, *, firm_id: UUID) -> None:
        """Permanently destroy the KEK for a tenant. Crypto-shred."""


# --------------------------------------------------------------------------- #
# Destroyed-key registry — pluggable.
# --------------------------------------------------------------------------- #
class DestroyedKeyRegistry(Protocol):
    """Records which firms have had their KEK destroyed.

    The default impl is in-memory (suitable for tests). Production wires this
    to the `tenant_encryption_key` table via `DbDestroyedKeyRegistry`.
    """
    def is_destroyed(self, firm_id: UUID) -> bool: ...
    def mark_destroyed(self, firm_id: UUID) -> None: ...


class InMemoryDestroyedKeyRegistry:
    def __init__(self) -> None:
        self._destroyed: set[UUID] = set()

    def is_destroyed(self, firm_id: UUID) -> bool:
        return firm_id in self._destroyed

    def mark_destroyed(self, firm_id: UUID) -> None:
        self._destroyed.add(firm_id)

    def reset(self) -> None:
        self._destroyed.clear()


# --------------------------------------------------------------------------- #
# Local provider — real AES-KW with per-firm KEK derived from a master.
# --------------------------------------------------------------------------- #
class LocalKeyProvider(KeyProvider):
    """Real cryptography. Per-firm KEK = HKDF-SHA256(master, info=firm_id).

    The master secret should come from a real KMS in production; for tests we
    pass a deterministic byte string so wraps round-trip across instances.
    """

    KEK_LEN = 32  # 256-bit
    HKDF_SALT = b"ctaa-kek-v1"

    def __init__(
        self,
        *,
        master_secret: bytes,
        registry: DestroyedKeyRegistry | None = None,
        kek_id: str = "local:hkdf:v1",
    ) -> None:
        if not master_secret or len(master_secret) < 16:
            raise ValueError("master_secret must be >= 16 bytes")
        self._master = master_secret
        self._registry: DestroyedKeyRegistry = (
            registry if registry is not None else InMemoryDestroyedKeyRegistry()
        )
        self._kek_id = kek_id

    @property
    def kek_id(self) -> str:
        return self._kek_id

    def _firm_kek(self, firm_id: UUID) -> bytes:
        if self._registry.is_destroyed(firm_id):
            raise KeyDestroyedError(f"KEK for firm {firm_id} has been destroyed")
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=self.KEK_LEN,
            salt=self.HKDF_SALT,
            info=f"firm:{firm_id}".encode(),
        )
        return hkdf.derive(self._master)

    def wrap_data_key(self, *, firm_id: UUID, dek: bytes) -> bytes:
        if len(dek) not in (16, 24, 32):
            raise ValueError("DEK must be 128/192/256 bits for AES Key Wrap")
        kek = self._firm_kek(firm_id)
        return aes_key_wrap(kek, dek)

    def unwrap_data_key(self, *, firm_id: UUID, wrapped: bytes) -> bytes:
        kek = self._firm_kek(firm_id)
        try:
            return aes_key_unwrap(kek, wrapped)
        except InvalidUnwrap as e:
            raise ValueError("AES key unwrap failed (integrity check)") from e

    def destroy_tenant_keys(self, *, firm_id: UUID) -> None:
        self._registry.mark_destroyed(firm_id)


# --------------------------------------------------------------------------- #
# DB-backed registry (production path).
# --------------------------------------------------------------------------- #
class DbDestroyedKeyRegistry:
    """Reads/writes the `tenant_encryption_key` table.

    The table is admin-only (no RLS). `engine_factory` is a zero-arg callable
    returning the *owner* engine — never the app_user one — because this
    registry is admin-plane.
    """

    def __init__(self, engine_factory) -> None:  # noqa: ANN001 — duck-typed
        self._engine_factory = engine_factory

    def is_destroyed(self, firm_id: UUID) -> bool:
        from sqlalchemy import text

        with self._engine_factory().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT status FROM tenant_encryption_key WHERE firm_id = :fid"
                ),
                {"fid": str(firm_id)},
            ).first()
        return row is not None and row[0] == "destroyed"

    def mark_destroyed(self, firm_id: UUID) -> None:
        from datetime import UTC, datetime

        from sqlalchemy import text

        with self._engine_factory().begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenant_encryption_key
                        (firm_id, kek_id, status, created_at, destroyed_at)
                    VALUES (:fid, :kid, 'destroyed', :now, :now)
                    ON CONFLICT (firm_id) DO UPDATE
                       SET status='destroyed', destroyed_at=:now
                    """
                ),
                {
                    "fid": str(firm_id),
                    "kid": "destroyed",
                    "now": datetime.now(UTC),
                },
            )


# --------------------------------------------------------------------------- #
# Azure Key Vault provider — real wrap/unwrap, real destroy.
# --------------------------------------------------------------------------- #
class AzureKeyVaultKeyProvider(KeyProvider):
    """Per-firm KEK in Azure Key Vault.

    Lazy-imports the azure-keyvault-keys / azure-identity packages so they're
    NOT required for tests/local dev. In production the credential is a
    Managed Identity; the env passes the vault URL via settings.
    """

    def __init__(
        self,
        *,
        vault_url: str,
        credential: object,
        key_name_template: str = "ctaa-firm-{firm_id}",
        registry: DestroyedKeyRegistry | None = None,
    ) -> None:
        self._vault_url = vault_url
        self._credential = credential
        self._template = key_name_template
        self._registry: DestroyedKeyRegistry = (
            registry if registry is not None else InMemoryDestroyedKeyRegistry()
        )

    @property
    def kek_id(self) -> str:
        return f"{self._vault_url}|{self._template}"

    def _crypto_client(self, firm_id: UUID):  # noqa: ANN202 — lazy import
        from azure.keyvault.keys.crypto import (  # type: ignore[import-not-found]
            CryptographyClient,
        )

        if self._registry.is_destroyed(firm_id):
            raise KeyDestroyedError(f"KEK for firm {firm_id} has been destroyed")
        key_name = self._template.format(firm_id=firm_id)
        return CryptographyClient(
            f"{self._vault_url}/keys/{key_name}", credential=self._credential
        )

    def wrap_data_key(self, *, firm_id: UUID, dek: bytes) -> bytes:
        from azure.keyvault.keys.crypto import (  # type: ignore[import-not-found]
            KeyWrapAlgorithm,
        )

        return self._crypto_client(firm_id).wrap_key(
            KeyWrapAlgorithm.rsa_oaep_256, dek
        ).encrypted_key

    def unwrap_data_key(self, *, firm_id: UUID, wrapped: bytes) -> bytes:
        from azure.keyvault.keys.crypto import (  # type: ignore[import-not-found]
            KeyWrapAlgorithm,
        )

        return self._crypto_client(firm_id).unwrap_key(
            KeyWrapAlgorithm.rsa_oaep_256, wrapped
        ).key

    def destroy_tenant_keys(self, *, firm_id: UUID) -> None:
        from azure.keyvault.keys import KeyClient  # type: ignore[import-not-found]

        key_name = self._template.format(firm_id=firm_id)
        kc = KeyClient(vault_url=self._vault_url, credential=self._credential)
        try:
            kc.begin_delete_key(key_name)
        finally:
            # Even if Key Vault soft-delete preserves the key bytes, mark the
            # firm destroyed locally so unwraps are refused immediately.
            self._registry.mark_destroyed(firm_id)


# --------------------------------------------------------------------------- #
# Backwards-compat shim: tests/integrations that previously imported
# `StubKeyProvider`. New code should use `LocalKeyProvider` directly.
# --------------------------------------------------------------------------- #
class StubKeyProvider(LocalKeyProvider):
    """DEPRECATED. Same surface as `LocalKeyProvider` but auto-derives a
    32-byte master from any input length so legacy callers keep working."""

    def __init__(self, master_secret: bytes | None = None) -> None:
        seed = master_secret or b"local-dev-master-secret-change-in-prod"
        derived = hashlib.sha256(b"ctaa-stub|" + seed).digest()
        super().__init__(master_secret=derived, kek_id="stub:firm-derived")


__all__ = [
    "AzureKeyVaultKeyProvider",
    "DbDestroyedKeyRegistry",
    "DestroyedKeyRegistry",
    "InMemoryDestroyedKeyRegistry",
    "KeyDestroyedError",
    "KeyProvider",
    "LocalKeyProvider",
    "StubKeyProvider",
]
