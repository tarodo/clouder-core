"""label_v1_baseline — port of the production label prompt onto the new schema."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from ..schemas import LabelInfo

SYSTEM = (
    "You are a music industry research assistant. Your task is to search "
    "for information about a specific music record label and produce a "
    "structured analysis.\n"
    "Rules:\n"
    "- Search the web for real, factual information about the label.\n"
    "- Estimate catalog_size_estimate, roster_size_estimate, and "
    "releases_last_12_months as integers based on what you find; leave null "
    "if you cannot tell.\n"
    "- founded_year is the year the label was established.\n"
    "- For ai_content: look for evidence of AI-generated music in their "
    "catalog (releases by known AI music generators, suspiciously high "
    "release volumes from unknown artists, mentions of AI in press).\n"
    "- Set confidence based on how much verifiable info you found "
    "(0.0 = guessing, 1.0 = fully verified).\n"
    "- If you cannot find the label at all, leave nullable fields null "
    "and confidence near 0."
)

USER_TEMPLATE = (
    'Research the music record label "{label_name}" that releases '
    '"{style}" music.{release_block}\n'
    "Return structured information about:\n"
    "1. How big this label is (catalog size, number of artists, market "
    "presence)\n"
    "2. How old this label is (founding year, history)\n"
    "3. Whether this label has AI-generated releases in its catalog"
)


register(
    PromptConfig(
        slug="label_v1_baseline",
        version="v1",
        description="Port of the production prompt onto the new schema.",
        system=SYSTEM,
        user_template=USER_TEMPLATE,
        schema=LabelInfo,
    )
)
