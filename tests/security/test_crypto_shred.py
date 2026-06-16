"""Crypto-shred tests: destroying a tenant's KEK renders all of that tenant's
ciphertext unrecoverable, and never affects other tenants."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.integrations.keys import (
    InMemoryDestroyedKeyRegistry,
    KeyDestroyedError,
    LocalKeyProvider,
)
from app.security.envelope import DecryptionError, decrypt, encrypt


def test_destroy_makes_decrypt_fail() -> None:
    registry = InMemoryDestroyedKeyRegistry()
    kp = LocalKeyProvider(master_secret=b"z" * 32, registry=registry)

    firm = uuid4()
    env = encrypt(plaintext=b"top secret", firm_id=firm, key_provider=kp)
    # Sanity
    assert decrypt(envelope=env, firm_id=firm, key_provider=kp) == b"top secret"

    kp.destroy_tenant_keys(firm_id=firm)

    with pytest.raises(DecryptionError):
        decrypt(envelope=env, firm_id=firm, key_provider=kp)


def test_destroy_refuses_further_wrap() -> None:
    registry = InMemoryDestroyedKeyRegistry()
    kp = LocalKeyProvider(master_secret=b"z" * 32, registry=registry)
    firm = uuid4()
    kp.destroy_tenant_keys(firm_id=firm)

    with pytest.raises(KeyDestroyedError):
        kp.wrap_data_key(firm_id=firm, dek=b"\x00" * 32)


def test_destroy_does_not_affect_other_firms() -> None:
    """Crypto-shred is per-firm. Destroying firm A's key must not break B."""
    registry = InMemoryDestroyedKeyRegistry()
    kp = LocalKeyProvider(master_secret=b"z" * 32, registry=registry)

    firm_a, firm_b = uuid4(), uuid4()
    env_a = encrypt(plaintext=b"A's data", firm_id=firm_a, key_provider=kp)
    env_b = encrypt(plaintext=b"B's data", firm_id=firm_b, key_provider=kp)

    kp.destroy_tenant_keys(firm_id=firm_a)

    with pytest.raises(DecryptionError):
        decrypt(envelope=env_a, firm_id=firm_a, key_provider=kp)
    # B is untouched.
    assert decrypt(envelope=env_b, firm_id=firm_b, key_provider=kp) == b"B's data"


def test_destroy_is_idempotent() -> None:
    registry = InMemoryDestroyedKeyRegistry()
    kp = LocalKeyProvider(master_secret=b"z" * 32, registry=registry)
    firm = uuid4()
    kp.destroy_tenant_keys(firm_id=firm)
    kp.destroy_tenant_keys(firm_id=firm)
    assert registry.is_destroyed(firm)
