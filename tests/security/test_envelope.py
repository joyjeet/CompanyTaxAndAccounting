"""Envelope encryption tests."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.integrations.keys import LocalKeyProvider
from app.security.envelope import (
    DecryptionError,
    Envelope,
    decrypt,
    decrypt_string,
    encrypt,
    encrypt_string,
)


@pytest.fixture
def kp() -> LocalKeyProvider:
    return LocalKeyProvider(master_secret=b"x" * 32)


def test_round_trip(kp: LocalKeyProvider) -> None:
    firm = uuid4()
    plaintext = b"the quick brown fox" * 100
    env = encrypt(plaintext=plaintext, firm_id=firm, key_provider=kp)
    assert env.ciphertext != plaintext
    assert decrypt(envelope=env, firm_id=firm, key_provider=kp) == plaintext


def test_serialise_round_trip(kp: LocalKeyProvider) -> None:
    firm = uuid4()
    env = encrypt(plaintext=b"hello", firm_id=firm, key_provider=kp)
    blob = env.to_bytes()
    env2 = Envelope.from_bytes(blob)
    assert decrypt(envelope=env2, firm_id=firm, key_provider=kp) == b"hello"


def test_dict_round_trip(kp: LocalKeyProvider) -> None:
    firm = uuid4()
    env = encrypt(plaintext=b"data", firm_id=firm, key_provider=kp)
    d = env.to_dict()
    env2 = Envelope.from_dict(d)
    assert decrypt(envelope=env2, firm_id=firm, key_provider=kp) == b"data"


def test_string_helpers(kp: LocalKeyProvider) -> None:
    firm = uuid4()
    d = encrypt_string(plaintext="ssn 123-45-6789", firm_id=firm, key_provider=kp)
    assert decrypt_string(envelope=d, firm_id=firm, key_provider=kp) == "ssn 123-45-6789"


def test_cross_firm_cannot_decrypt(kp: LocalKeyProvider) -> None:
    """Ciphertext encrypted under firm A must not decrypt under firm B —
    even though the same KeyProvider is used. AAD binding + per-firm KEK
    derivation must both reject."""
    firm_a, firm_b = uuid4(), uuid4()
    env = encrypt(plaintext=b"secret", firm_id=firm_a, key_provider=kp)
    with pytest.raises(DecryptionError):
        decrypt(envelope=env, firm_id=firm_b, key_provider=kp)


def test_tampered_ciphertext_rejected(kp: LocalKeyProvider) -> None:
    firm = uuid4()
    env = encrypt(plaintext=b"secret", firm_id=firm, key_provider=kp)
    bad_ct = bytes([env.ciphertext[0] ^ 0xFF]) + env.ciphertext[1:]
    bad = Envelope(
        alg=env.alg,
        kek_id=env.kek_id,
        wrapped_dek=env.wrapped_dek,
        nonce=env.nonce,
        ciphertext=bad_ct,
    )
    with pytest.raises(DecryptionError):
        decrypt(envelope=bad, firm_id=firm, key_provider=kp)


def test_aad_round_trip(kp: LocalKeyProvider) -> None:
    """Optional AAD is round-tripped intact."""
    firm = uuid4()
    env = encrypt(
        plaintext=b"secret", firm_id=firm, key_provider=kp, aad=b"doc-id-12345"
    )
    assert decrypt(envelope=env, firm_id=firm, key_provider=kp) == b"secret"


def test_unsupported_version_rejected() -> None:
    with pytest.raises(DecryptionError):
        Envelope.from_dict({"v": 999, "alg": "AES-256-GCM", "kek_id": "x",
                            "wrapped_dek": "AAAA", "nonce": "AAAA", "ct": "AAAA"})


def test_unsupported_alg_rejected() -> None:
    with pytest.raises(DecryptionError):
        Envelope.from_dict({"v": 1, "alg": "ChaCha20-Poly1305", "kek_id": "x",
                            "wrapped_dek": "AAAA", "nonce": "AAAA", "ct": "AAAA"})


def test_random_bytes_rejected() -> None:
    with pytest.raises(DecryptionError):
        Envelope.from_bytes(os.urandom(64))
