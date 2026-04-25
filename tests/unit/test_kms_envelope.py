from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from collector.auth.kms_envelope import KmsEnvelope, EnvelopePayload


def _make_kms_client(plaintext_key: bytes) -> MagicMock:
    client = MagicMock()
    client.generate_data_key.return_value = {
        "Plaintext": plaintext_key,
        "CiphertextBlob": b"wrapped:" + plaintext_key,
    }
    client.decrypt.return_value = {"Plaintext": plaintext_key}
    return client


def test_encrypt_decrypt_round_trip() -> None:
    key = b"\x00" * 32
    client = _make_kms_client(key)
    envelope = KmsEnvelope(kms_client=client, key_arn="arn:k", cache_ttl_seconds=300)

    payload = envelope.encrypt(b"sekret-token-bytes")
    assert payload.ciphertext != b"sekret-token-bytes"
    assert payload.data_key_enc == b"wrapped:" + key

    plaintext = envelope.decrypt(payload)
    assert plaintext == b"sekret-token-bytes"


def test_encrypt_caches_data_key_within_ttl() -> None:
    key = b"\x01" * 32
    client = _make_kms_client(key)
    envelope = KmsEnvelope(kms_client=client, key_arn="arn:k", cache_ttl_seconds=300)

    envelope.encrypt(b"a")
    envelope.encrypt(b"b")

    assert client.generate_data_key.call_count == 1


def test_encrypt_refreshes_data_key_after_ttl() -> None:
    key = b"\x02" * 32
    client = _make_kms_client(key)
    clock = [0.0]

    def fake_monotonic() -> float:
        return clock[0]

    envelope = KmsEnvelope(
        kms_client=client,
        key_arn="arn:k",
        cache_ttl_seconds=10,
        monotonic=fake_monotonic,
    )

    envelope.encrypt(b"a")
    clock[0] = 11.0
    envelope.encrypt(b"b")

    assert client.generate_data_key.call_count == 2


def test_decrypt_caches_unwrapped_data_key() -> None:
    key = b"\x03" * 32
    client = _make_kms_client(key)
    envelope = KmsEnvelope(kms_client=client, key_arn="arn:k", cache_ttl_seconds=300)

    payload = envelope.encrypt(b"first")
    envelope.decrypt(payload)
    envelope.decrypt(payload)

    # First decrypt populates cache; second uses cache.
    assert client.decrypt.call_count == 1


def test_payload_serialize_round_trip() -> None:
    payload = EnvelopePayload(data_key_enc=b"\xaa\xbb", nonce=b"n" * 12, ciphertext=b"c")
    blob = payload.serialize()
    parsed = EnvelopePayload.deserialize(blob)
    assert parsed == payload
