from __future__ import annotations

import re

from collector.auth.pkce import (
    derive_code_challenge,
    generate_code_verifier,
)


_BASE64URL_NOPAD = re.compile(r"^[A-Za-z0-9_-]+$")


def test_generate_code_verifier_is_base64url_no_padding() -> None:
    verifier = generate_code_verifier()
    assert _BASE64URL_NOPAD.match(verifier)
    # 32 bytes of entropy → 43 base64url chars (no padding).
    assert len(verifier) == 43


def test_derive_code_challenge_known_vector() -> None:
    # RFC 7636 Appendix B test vector
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert derive_code_challenge(verifier) == expected


def test_derive_code_challenge_is_base64url_no_padding() -> None:
    challenge = derive_code_challenge(generate_code_verifier())
    assert _BASE64URL_NOPAD.match(challenge)
    # SHA-256 → 32 bytes → 43 base64url chars.
    assert len(challenge) == 43
