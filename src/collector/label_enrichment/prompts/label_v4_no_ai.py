"""label_v4_no_ai — label_v3_app_fields minus every AI-detection mention."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from .label_v3_app_fields import APP_FIELDS_BLOCK
from ..schemas import LabelInfoRequest

V2_SYSTEM_NO_AI = (
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
    "notable_artists are all sourced."
)

USER_TEMPLATE = (
    'Research label "{label_name}" in style "{style}".\n'
    "Find: founding year, country, status (active/inactive), parent and "
    "sublabels, catalog and roster size, releases in the last 12 months, "
    "last release date, primary style tags, official channels (website, "
    "Bandcamp, Resident Advisor, Discogs, Beatport, SoundCloud, "
    "Instagram, Twitter/X), notable artists, distributor.\n"
    "Write a one-sentence tagline capturing the label's identity."
)


register(
    PromptConfig(
        slug="label_v4_no_ai",
        version="v1",
        description="v3 app fields without AI-detection.",
        system=V2_SYSTEM_NO_AI + APP_FIELDS_BLOCK,
        user_template=USER_TEMPLATE,
        schema=LabelInfoRequest,
    )
)
