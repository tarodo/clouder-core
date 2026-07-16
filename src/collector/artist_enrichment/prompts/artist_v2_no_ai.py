"""artist_v2_no_ai — artist_v1 minus every AI-detection mention."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from ..schemas import ArtistInfoRequest

SYSTEM = (
    "You research electronic-music artists. Output structured facts only.\n"
    "Rules:\n"
    "- Use the disambiguation context (sample releases + labels + style) to "
    "lock onto the CORRECT artist. Many artists share a name. If the context "
    "does not resolve which artist this is, set confidence <= 0.4 and explain "
    "the ambiguity in `notes`.\n"
    "- Every URL must clearly belong to THIS artist: the profile name must "
    "match and it should reference at least one of the known releases or "
    "labels. If a link cannot be tied to this artist, omit it.\n"
    "- active_since and any year require a supporting URL in `sources`. Never "
    "guess years.\n"
    "- aliases / real_name: list everything you find; mark uncertain ones in "
    "`notes`.\n"
    "- artist_type: solo unless there is evidence of a duo / group / alias "
    "project.\n"
    "- labels: labels the artist has actually released on, most relevant "
    "first.\n"
    "- notable_collaborators: frequent co-authors and remixers, not one-offs.\n"
    "- notable_releases: at most 5 anchor tracks/EPs that confirm identity.\n"
    "- primary_styles: 2-5 specific genre tags, no umbrella terms.\n"
    "- Narrative fields are three DISTINCT outputs, all required:\n"
    "    - tagline: ONE punchy sentence (≤100 chars) capturing the artist's "
    "identity (style / scene / era). Never leave it empty — derive it from "
    "your strongest signal.\n"
    "    - summary: 2–4 factual sentences, no superlatives.\n"
    "    - bio: 1–3 additional factual sentences (history or scene context).\n"
    "- confidence: 1.0 only if identity is confirmed via the context match "
    "AND country is sourced AND there are >=3 supporting sources."
)

USER_TEMPLATE = (
    'Research the electronic-music artist "{artist_name}".{context_block}\n'
    "Find: aliases and real name, country and city, years active, labels they "
    "release on, frequent collaborators and remixers, notable releases, "
    "streaming and social profiles (Spotify, SoundCloud, Bandcamp, Beatport, "
    "Resident Advisor, Discogs, Instagram), primary styles, a tagline (one "
    "punchy sentence ≤100 chars), a summary (2–4 sentences), and a short bio "
    "(1–3 factual sentences)."
)


register(
    PromptConfig(
        slug="artist_v2_no_ai",
        version="v1",
        description="Facts-discipline + disambiguation for artists, without AI-detection.",
        system=SYSTEM,
        user_template=USER_TEMPLATE,
        schema=ArtistInfoRequest,
    )
)
