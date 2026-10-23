# ruff: noqa: RUF001  # look-alike letters are the point of this file
"""Fold stylised and foreign letters to plain ASCII before names and titles are
compared: "XØRØ" is "Xoro", "GΛLXɆɆ RΛIN" is "Galxee Rain", "ЛСП" is "LSP".

The tables come from the catalog's own artist names (2026-10-23): letters NFKD
does not decompose, Greek letters used as Latin lookalikes, symbols standing for
letters, decorations, and Cyrillic, transliterated. Scripts without a Latin
reading (CJK, Hangul, Hebrew, ...) are left as they are.
"""

from __future__ import annotations

import re
import unicodedata

# Latin letters with a stroke or ligature: NFKD leaves them whole.
_LATIN = {
    "ø": "o", "æ": "ae", "œ": "oe", "ı": "i", "đ": "d", "ð": "d", "þ": "th",
    "ł": "l", "ɇ": "e", "ə": "e", "ǝ": "e", "ɛ": "e", "ɔ": "o", "ħ": "h",
    "ŧ": "t", "ƀ": "b", "ɨ": "i", "ʉ": "u", "ƶ": "z", "ȼ": "c", "ɍ": "r",
    "ɏ": "y", "ŋ": "n",
}  # fmt: skip
# Symbols written for letters: "G€€NA", "LUN∆", "MIN▲", "KUNA¥", "DRK $ZN".
_SYMBOLS = {
    "€": "e", "∆": "a", "▲": "a", "△": "a", "¥": "y", "£": "l", "×": "x",
    "$": "s", "@": "a",
}  # fmt: skip
# Decorations: dots, stars, marks.
_DROP = frozenset("•·°®©™✧✦★☆⋆❀∞±♥♡♪♫")
# Greek inside a Latin name is a lookalike ("SANCHΞZ", "CΔDENZ", "UηκηΘωN") ...
_GREEK_LOOKALIKE = {
    "α": "a", "β": "b", "γ": "y", "δ": "a", "ε": "e", "ζ": "z", "η": "n",
    "θ": "o", "ι": "i", "κ": "k", "λ": "a", "μ": "u", "ν": "v", "ξ": "e",
    "ο": "o", "π": "n", "ρ": "p", "σ": "e", "ς": "s", "τ": "t", "υ": "u",
    "φ": "o", "χ": "x", "ψ": "w", "ω": "w",
}  # fmt: skip
# ... and a Greek name is transliterated ("ΠΑΝΟΣ" is "Panos").
_GREEK = {
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
}  # fmt: skip
# Russian and Ukrainian, as a Latin spelling of the name would read.
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e",
    "ё": "e", "є": "ye", "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "yi",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya", "ә": "e",
}  # fmt: skip
# "GR!N", "P!nk": an exclamation mark between letters is an i.
_BANG = re.compile(r"(?<=[a-z])!(?=[a-z])")


def fold(s: str | None) -> str:
    """Lower-case ASCII reading of *s*; other scripts kept, whitespace as is."""
    s = unicodedata.normalize("NFKC", s or "").casefold()
    greek = _GREEK_LOOKALIKE if re.search("[a-z]", s) else _GREEK
    out = []
    for ch in s:
        if ch in _DROP or unicodedata.category(ch) == "Cf":  # Cf: zero-width marks
            continue
        out.append(_LATIN.get(ch) or _SYMBOLS.get(ch) or greek.get(ch) or _CYRILLIC.get(ch, ch))
    decomposed = unicodedata.normalize("NFKD", _BANG.sub("i", "".join(out)))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))
