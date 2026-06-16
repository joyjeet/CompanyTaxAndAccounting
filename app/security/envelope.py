"""Envelope encryption.

Per-item AES-256-GCM ciphertext + per-item DEK that is wrapped by a per-firm
KEK held in the configured `KeyProvider`. The on-disk/on-DB format is a
self-describing JSON-serialisable dict so we can rotate algorithms without
breaking existing data.

Wire format (`Envelope.to_dict`):
    {
        "v": 1,                # format version
        "alg": "AES-256-GCM",
        "kek_id": str,         # opaque id of the KEK used to wrap the DEK
        "wrapped_dek": bytes,  # base64 in JSON; raw bytes in dataclass
        "nonce": bytes,        # 12 bytes for GCM
        "ct": bytes,           # ciphertext || GCM tag (cryptography library returns them concatenated)
        "aad": bytes | null,   # optional additional authenticated data
    }

`firm_id` is bound into the AAD so a wrapped DEK from firm A cannot decrypt a
ciphertext authored against firm B even if the wrapped_dek byte-stream were
swapped.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.integrations.keys import KeyProvider

ALG_AES_256_GCM = "AES-256-GCM"
DEK_BYTES = 32   # 256-bit
NONCE_BYTES = 12  # 96-bit nonce — recommended for AES-GCM


class DecryptionError(Exception):
    """Catch-all for envelope decryption failures.

    Treat any failure as fatal — bad signature, wrong AAD, destroyed KEK, or
    any other shape — and DO NOT leak which one to the caller. We log the
    underlying cause server-side; we don't return it.
    """


# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Envelope:
    """Encrypted payload + the metadata needed to decrypt it."""
    alg: str
    kek_id: str
    wrapped_dek: bytes
    nonce: bytes
    ciphertext: bytes
    aad: bytes | None = None
    v: int = 1

    # ------- serialisation ---------------------------------------------- #
    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "v": self.v,
            "alg": self.alg,
            "kek_id": self.kek_id,
            "wrapped_dek": _b64(self.wrapped_dek),
            "nonce": _b64(self.nonce),
            "ct": _b64(self.ciphertext),
        }
        if self.aad is not None:
            d["aad"] = _b64(self.aad)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Envelope:
        v = int(d.get("v", 1))
        if v != 1:
            raise DecryptionError(f"unsupported envelope version {v}")
        alg = str(d.get("alg", ""))
        if alg != ALG_AES_256_GCM:
            raise DecryptionError(f"unsupported algorithm {alg!r}")
        try:
            return cls(
                v=v,
                alg=alg,
                kek_id=str(d["kek_id"]),
                wrapped_dek=_unb64(d["wrapped_dek"]),
                nonce=_unb64(d["nonce"]),
                ciphertext=_unb64(d["ct"]),
                aad=_unb64(d["aad"]) if d.get("aad") is not None else None,
            )
        except (KeyError, ValueError, TypeError) as e:
            raise DecryptionError(f"malformed envelope: {e}") from e

    def to_bytes(self) -> bytes:
        """Compact binary serialization for raw blob storage.

        We don't need a sophisticated container; for the prototype we use a
        tiny TLV: ASCII header line then the four binary fields. Callers that
        want JSON should use `to_dict`.
        """
        import json
        return json.dumps(self.to_dict()).encode("utf-8")

    @classmethod
    def from_bytes(cls, b: bytes) -> Envelope:
        import json
        try:
            return cls.from_dict(json.loads(b.decode("utf-8")))
        except (UnicodeDecodeError, ValueError) as e:
            raise DecryptionError(f"envelope bytes are not valid JSON: {e}") from e


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str | bytes) -> bytes:
    if isinstance(s, bytes):
        s = s.decode("ascii")
    return base64.b64decode(s, validate=True)


# --------------------------------------------------------------------------- #
def _bind_aad(*, firm_id: UUID, extra_aad: bytes | None) -> bytes:
    """Bind the firm_id into the AAD. A wrapped DEK + ciphertext from firm A
    cannot be decrypted under firm B even if everything else matched — the
    GCM tag check fails because the AAD differs."""
    base = f"firm:{firm_id}".encode("ascii")
    return base if not extra_aad else base + b"|" + extra_aad


def encrypt(
    *,
    plaintext: bytes,
    firm_id: UUID,
    key_provider: KeyProvider,
    aad: bytes | None = None,
) -> Envelope:
    """Generate a fresh DEK, encrypt the plaintext under it, and wrap the DEK
    with the per-firm KEK. Returns a self-describing `Envelope`."""
    dek = os.urandom(DEK_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    bound_aad = _bind_aad(firm_id=firm_id, extra_aad=aad)
    ct = AESGCM(dek).encrypt(nonce, plaintext, bound_aad)
    wrapped = key_provider.wrap_data_key(firm_id=firm_id, dek=dek)
    return Envelope(
        alg=ALG_AES_256_GCM,
        kek_id=key_provider.kek_id,
        wrapped_dek=wrapped,
        nonce=nonce,
        ciphertext=ct,
        aad=aad,
    )


def decrypt(
    *,
    envelope: Envelope,
    firm_id: UUID,
    key_provider: KeyProvider,
) -> bytes:
    """Unwrap the DEK with the per-firm KEK and decrypt. Raises
    `DecryptionError` on any failure (bad tag, unknown KEK, destroyed key)."""
    try:
        dek = key_provider.unwrap_data_key(
            firm_id=firm_id, wrapped=envelope.wrapped_dek
        )
    except Exception as e:
        # KEK destroyed, missing, or any provider-level failure.
        raise DecryptionError(f"unwrap_data_key failed: {type(e).__name__}") from e

    bound_aad = _bind_aad(firm_id=firm_id, extra_aad=envelope.aad)
    try:
        return AESGCM(dek).decrypt(envelope.nonce, envelope.ciphertext, bound_aad)
    except InvalidTag as e:
        raise DecryptionError("authentication tag mismatch") from e
    except Exception as e:
        raise DecryptionError(f"decrypt failed: {type(e).__name__}") from e


# --------------------------------------------------------------------------- #
# Convenience: encrypt/decrypt UTF-8 strings for column-level encryption.
# --------------------------------------------------------------------------- #
def encrypt_string(
    *, plaintext: str, firm_id: UUID, key_provider: KeyProvider
) -> dict[str, Any]:
    return encrypt(
        plaintext=plaintext.encode("utf-8"),
        firm_id=firm_id,
        key_provider=key_provider,
    ).to_dict()


def decrypt_string(
    *, envelope: dict[str, Any], firm_id: UUID, key_provider: KeyProvider
) -> str:
    return decrypt(
        envelope=Envelope.from_dict(envelope),
        firm_id=firm_id,
        key_provider=key_provider,
    ).decode("utf-8")


__all__ = [
    "ALG_AES_256_GCM",
    "DecryptionError",
    "Envelope",
    "decrypt",
    "decrypt_string",
    "encrypt",
    "encrypt_string",
]
