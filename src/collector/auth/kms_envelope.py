"""KMS envelope encryption with AES-GCM and a 5-min in-memory data-key cache."""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class EnvelopePayload:
    data_key_enc: bytes
    nonce: bytes
    ciphertext: bytes

    def serialize(self) -> bytes:
        return (
            struct.pack(">I", len(self.data_key_enc))
            + self.data_key_enc
            + self.nonce
            + self.ciphertext
        )

    @classmethod
    def deserialize(cls, blob: bytes) -> "EnvelopePayload":
        (key_len,) = struct.unpack(">I", blob[:4])
        offset = 4
        data_key_enc = blob[offset : offset + key_len]
        offset += key_len
        nonce = blob[offset : offset + 12]
        offset += 12
        ciphertext = blob[offset:]
        return cls(data_key_enc=data_key_enc, nonce=nonce, ciphertext=ciphertext)


class KmsEnvelope:
    """Wraps KMS GenerateDataKey/Decrypt with AES-GCM and a small TTL cache."""

    def __init__(
        self,
        kms_client: Any,
        key_arn: str,
        cache_ttl_seconds: int = 300,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._kms = kms_client
        self._key_arn = key_arn
        self._cache_ttl_seconds = cache_ttl_seconds
        self._monotonic = monotonic
        # Encryption-side cache: (plaintext_key, data_key_enc, expires_at_monotonic).
        self._enc_cache: tuple[bytes, bytes, float] | None = None
        # Decryption-side cache: data_key_enc -> (plaintext_key, expires_at_monotonic).
        self._dec_cache: dict[bytes, tuple[bytes, float]] = {}

    def encrypt(self, plaintext: bytes) -> EnvelopePayload:
        key, data_key_enc = self._fresh_data_key()
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
        return EnvelopePayload(
            data_key_enc=data_key_enc, nonce=nonce, ciphertext=ciphertext
        )

    def decrypt(self, payload: EnvelopePayload) -> bytes:
        key = self._unwrap_data_key(payload.data_key_enc)
        return AESGCM(key).decrypt(payload.nonce, payload.ciphertext, associated_data=None)

    def _fresh_data_key(self) -> tuple[bytes, bytes]:
        now = self._monotonic()
        if self._enc_cache is not None:
            key, wrapped, expires = self._enc_cache
            if now < expires:
                return key, wrapped
        response = self._kms.generate_data_key(
            KeyId=self._key_arn, KeySpec="AES_256"
        )
        key = response["Plaintext"]
        wrapped = response["CiphertextBlob"]
        self._enc_cache = (key, wrapped, now + self._cache_ttl_seconds)
        return key, wrapped

    def _unwrap_data_key(self, data_key_enc: bytes) -> bytes:
        now = self._monotonic()
        cached = self._dec_cache.get(data_key_enc)
        if cached is not None:
            key, expires = cached
            if now < expires:
                return key
        response = self._kms.decrypt(CiphertextBlob=data_key_enc)
        key = response["Plaintext"]
        self._dec_cache[data_key_enc] = (key, now + self._cache_ttl_seconds)
        return key
