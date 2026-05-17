"""label_v3_ai_focus — label_v2_facts plus a structured AI-assessment section."""

from __future__ import annotations

from . import register
from .base import PromptConfig
from .label_v2_facts import SYSTEM as V2_SYSTEM, USER_TEMPLATE as V2_USER
from ..schemas import LabelInfo

AI_BLOCK = (
    "\n\nAI-content assessment — required steps:\n"
    "1. Check release cadence. Greater than 60 releases per 12 months "
    "from fewer than 5 artists is a volume signal.\n"
    "2. Check artist names. Generic or algorithmically-generated names "
    "('John Smith 47', 'Lofi Producer X') are a name signal.\n"
    "3. Check press and interviews for explicit AI tool credits "
    "('made with Suno', 'Udio', etc.).\n"
    "4. Check cover art. Stylistically identical AI-generated artwork "
    "across releases is a cover signal.\n"
    "5. Populate ai_signals[] with one entry per finding, each with "
    "kind, description, source_url.\n"
    "6. Set ai_content:\n"
    "   - confirmed: explicit credit or the label publicly markets AI "
    "tracks\n"
    "   - suspected: >=2 signals from steps 1-4 with sources\n"
    "   - none_detected: searched but found nothing\n"
    "   - unknown: could not search effectively\n"
    "7. ai_reasoning: 1-3 sentences citing the signals."
)


register(
    PromptConfig(
        slug="label_v3_ai_focus",
        version="v1",
        description="Facts-discipline plus structured AI assessment.",
        system=V2_SYSTEM + AI_BLOCK,
        user_template=V2_USER,
        schema=LabelInfo,
    )
)
