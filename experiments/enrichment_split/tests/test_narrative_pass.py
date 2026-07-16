from types import SimpleNamespace

from splitlab.narrative_pass import (
    LABEL_SYSTEM,
    ARTIST_SYSTEM,
    NarrativeResult,
    run_narrative_pass,
)
from splitlab.schemas import LabelNarrative

LABEL_ENTITY = {"name": "Defiant", "style": "dnb", "baseline": {}}
ARTIST_ENTITY = {
    "name": "Vision", "style": "drum and bass", "baseline": {},
    "sample_tracks": ["Deep"], "known_labels": ["Hospital Records"],
}


class FakeLLM:
    def __init__(self):
        self.last_kwargs = None

    @property
    def responses(self):
        return self

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        parsed = LabelNarrative(label_name="Defiant", summary="s", confidence=0.5)
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        output = [SimpleNamespace(type="web_search_call"),
                  SimpleNamespace(type="web_search_call"),
                  SimpleNamespace(type="message")]
        return SimpleNamespace(output_parsed=parsed, usage=usage, output=output)


def test_passes_cap_and_counts_searches():
    llm = FakeLLM()
    r = run_narrative_pass(LABEL_ENTITY, "label", llm, model="gpt-5.4-mini", max_tool_calls=2)
    assert isinstance(r, NarrativeResult)
    assert llm.last_kwargs["max_tool_calls"] == 2
    assert llm.last_kwargs["tools"] == [{"type": "web_search"}]
    assert r.web_search_calls == 2
    assert r.narrative["label_name"] == "Defiant"


def test_prompts_have_no_ai_or_url_or_numeric_asks():
    for text in (LABEL_SYSTEM, ARTIST_SYSTEM):
        low = text.lower()
        assert "ai-content" not in low and "ai_" not in low
        assert "instagram" not in low and "url" not in low.replace("source urls", "")
        assert "founded" not in low and "catalog" not in low


def test_artist_prompt_uses_context():
    llm = FakeLLM()
    run_narrative_pass(ARTIST_ENTITY, "artist", llm, model="m", max_tool_calls=1)
    user_msg = llm.last_kwargs["input"][0]["content"]
    assert "Hospital Records" in user_msg and "Deep" in user_msg


def test_error_captured():
    class Boom:
        @property
        def responses(self):
            return self
        def parse(self, **kwargs):
            raise RuntimeError("quota")

    r = run_narrative_pass(LABEL_ENTITY, "label", Boom(), model="m", max_tool_calls=2)
    assert r.error and "quota" in r.error
    assert r.narrative == {}
