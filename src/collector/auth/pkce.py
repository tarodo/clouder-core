"""PKCE helpers for Spotify OAuth (RFC 7636)."""

from __future__ import annotations

import base64
import hashlib
import os


def generate_code_verifier(num_bytes: int = 32) -> str:
    return _b64url_nopad(os.urandom(num_bytes))


def derive_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return _b64url_nopad(digest)


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
