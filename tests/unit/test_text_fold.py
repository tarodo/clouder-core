# ruff: noqa: RUF001  # look-alike letters are the point of this file
"""Stylised and foreign letters fold to plain ASCII for matching (real catalog names)."""

from __future__ import annotations

import pytest

from collector.vendor_match.textfold import fold


@pytest.mark.parametrize(
    ("raw", "folded"),
    [
        ("DØSHI", "doshi"),  # letters NFKD does not decompose
        ("XØRØ", "xoro"),
        ("KRÆK", "kraek"),
        ("Fasıl-ı Jazz", "fasil-i jazz"),
        ("Quang Đăng Trần", "quang dang tran"),
        ("FOMɆɆN", "fomeen"),
        ("Rəind Səid", "reind seid"),
        ("Bałka", "balka"),
        ("Dabü", "dabu"),  # diacritics
        ("GΛLXɆɆ RΛIN", "galxee rain"),  # Greek as Latin lookalikes
        ("KARIM SANCHΞZ", "karim sanchez"),
        ("CΔDENZ", "cadenz"),
        ("UηκηΘωN", "unknown"),
        ("ΠΑΝΟΣ", "panos"),  # a Greek name is transliterated
        ("G€€NA", "geena"),  # symbols standing for letters
        ("LUN∆", "luna"),
        ("MIN▲", "mina"),
        ("PR△TA", "prata"),
        ("KUNA¥", "kunay"),
        ("ANML×PRTY", "anmlxprty"),
        ("DRK $ZN", "drk szn"),
        ("GR!N", "grin"),  # "!" inside a word
        ("This!", "this!"),  # ... but not punctuation
        ("ЛСП", "lsp"),  # Cyrillic transliterated
        ("Августа Уляндина", "avgusta ulyandina"),
        ("Невідома Особа", "nevidoma osoba"),
        ("​​Alex Alta", "alex alta"),  # zero-width spaces
        ("Mid•L", "midl"),  # decorations dropped
        ("LadyLove®", "ladylove"),
        ("ＦＵＬＬ ＷＩＤＴＨ", "full width"),
    ],
)
def test_fold(raw, folded) -> None:
    assert fold(raw) == folded


def test_other_scripts_stay_as_they_are() -> None:
    assert fold("HINOIチーム") == "hinoiチーム"
