"""label_v2_facts — facts-discipline prompt: numbers, sources, no guessing."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from ..schemas import LabelInfo

SYSTEM = (
    "You research music labels. Output structured facts only.\n"
    "Rules:\n"
    "- Every numeric field (founded_year, catalog_size_estimate, "
    "roster_size_estimate, releases_last_12_months) requires at least one "
    "supporting URL in `sources`. If you cannot verify, leave the field "
    "null. Never guess numbers.\n"
    "- aliases, sublabels, parent_label: list everything you find, even "
    "uncertain ones, and mark uncertainty in `notes`.\n"
    "- `activity` is derived from `releases_last_12_months`: "
    "null/unknown -> unknown; 0 with last_release_date >2y ago -> dormant; "
    "<6 -> low; 6-24 -> steady; 25-60 -> high; >60 -> fire_hose. "
    "Do not set activity independently of releases_last_12_months.\n"
    "- notable_artists: at most 5, by recognizable name, not the full "
    "roster.\n"
    "- If the label name is ambiguous (multiple labels share the name), "
    "pick the one matching the style and explain the choice in `notes`.\n"
    "- confidence: 1.0 only if founded_year, country, and >=3 "
    "notable_artists are all sourced.\n"
    "- ai_reasoning is required even if status is unknown — explain why."
)

USER_TEMPLATE = (
    'Research label "{label_name}" in style "{style}".{release_block}\n'
    "Find: founding year, country, parent and sublabels, catalog and "
    "roster size, releases in the last 12 months, last release date, "
    "official channels (website, Bandcamp, Resident Advisor, Discogs, "
    "Beatport, SoundCloud), notable artists, distributor.\n"
    "Then assess AI-content status and explain your reasoning."
)


register(
    PromptConfig(
        slug="label_v2_facts",
        version="v1",
        description="Facts-discipline: numbers require sources, no guessing.",
        system=SYSTEM,
        user_template=USER_TEMPLATE,
        schema=LabelInfo,
    )
)
