"""label_v3_app_fields — label_v2_facts plus logo, socials, tagline for app integration."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from .label_v2_facts import SYSTEM as V2_SYSTEM
from ..schemas import LabelInfo

APP_FIELDS_BLOCK = (
    "\n\n"
    "- `instagram_url` / `twitter_url`: official accounts only. Prefer "
    "https://www.instagram.com/<handle> and https://x.com/<handle>. The "
    "handle must match the label name or be clearly linked from the "
    "label's website / Bandcamp / RA. Leave null when uncertain.\n"
    "- `tagline`: one short sentence, max 100 characters, capturing the "
    "label's identity. Examples:\n"
    "    * \"Swedish techno powerhouse since 1996.\"\n"
    "    * \"London home of melodic deep house.\"\n"
    "    * \"AI-generated lofi YouTube channel.\"\n"
    "  Avoid generic copy (\"a record label\"). Leave null only if the "
    "label is truly unknown.\n"
    "- `status`: \"active\" if `releases_last_12_months >= 1` OR the label "
    "has visible recent activity (events, social posts within ~18 months); "
    "\"inactive\" if zero releases for >2 years AND no recent public "
    "activity; \"unknown\" only if you cannot determine either way.\n"
    "- `primary_styles`: 2-5 short genre tags describing what the label "
    "releases, lowercase, comma-separated values in the list. Use tags as "
    "the label itself describes them when possible (Bandcamp / RA / Discogs "
    "genre fields). Examples:\n"
    "    * [\"techno\", \"peak-time techno\"]\n"
    "    * [\"deep house\", \"progressive house\", \"melodic techno\"]\n"
    "    * [\"drum and bass\", \"neurofunk\", \"bass music\"]\n"
    "  Avoid umbrella terms (\"electronic music\") unless that's truly all "
    "you can determine."
)

USER_TEMPLATE = (
    'Research label "{label_name}" in style "{style}".\n'
    "Find: founding year, country, status (active/inactive), parent and "
    "sublabels, catalog and roster size, releases in the last 12 months, "
    "last release date, primary style tags, official channels (website, "
    "Bandcamp, Resident Advisor, Discogs, Beatport, SoundCloud, "
    "Instagram, Twitter/X), notable artists, distributor.\n"
    "Write a one-sentence tagline capturing the label's identity.\n"
    "Then assess AI-content status and explain your reasoning."
)


register(
    PromptConfig(
        slug="label_v3_app_fields",
        version="v1",
        description="Facts-discipline plus logo, socials, and tagline for app integration.",
        system=V2_SYSTEM + APP_FIELDS_BLOCK,
        user_template=USER_TEMPLATE,
        schema=LabelInfo,
    )
)
