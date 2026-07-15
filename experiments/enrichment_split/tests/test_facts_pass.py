import json
from types import SimpleNamespace

from splitlab.facts_pass import FactsResult, run_facts_pass
from splitlab.schemas import LabelFacts
from splitlab.tavily_client import TavilyClient

ENTITY = {
    "name": "Anarkick Records",
    "style": "hard techno",
    "baseline": {"website": "https://www.anarkick.com", "bandcamp_url": None},
}


class FakeLLM:
    """Mimics client.responses.parse for the no-tools extraction call."""

    def __init__(self, parsed):
        self._parsed = parsed
        self.last_kwargs = None

    @property
    def responses(self):
        return self

    def parse(self, **kwargs):
        self.last_kwargs = kwargs
        usage = SimpleNamespace(input_tokens=1000, output_tokens=50)
        return SimpleNamespace(output_parsed=self._parsed, usage=usage, output=[])


def tavily_with(responses):
    """responses: list of dicts returned per POST in order."""
    it = iter(responses)
    return TavilyClient(api_key="k", post=lambda path, payload: next(it))


def test_tier1_instagram_from_raw_content():
    tavily = tavily_with([
        {"results": [{"url": "https://x.example",
                      "raw_content": "see https://www.instagram.com/anarkick_records ok",
                      "content": "Anarkick Records hard techno label"}]},
    ])
    llm = FakeLLM(LabelFacts(founded_year=2015))
    r = run_facts_pass(ENTITY, "label", tavily, llm, model="gpt-5.4-mini")
    assert isinstance(r, FactsResult)
    assert r.profiles["instagram_url"] == "https://www.instagram.com/anarkick_records"
    assert r.instagram_tier == 1
    assert r.facts["founded_year"] == 2015
    assert r.credits == 1  # search only
    assert r.llm_usage["input_tokens"] == 1000
    # extraction call must not use web_search tools
    assert "tools" not in llm.last_kwargs


def test_tier2_extract_known_pages():
    tavily = tavily_with([
        {"results": [{"url": "https://irrelevant.example", "raw_content": "nothing here"}]},
        {"results": [{"url": "https://www.anarkick.com",
                      "raw_content": "follow https://www.instagram.com/anarkick_records"}]},
    ])
    llm = FakeLLM(LabelFacts())
    r = run_facts_pass(ENTITY, "label", tavily, llm, model="m")
    assert r.instagram_tier == 2
    assert r.credits == 2  # search + extract
    assert r.profiles["instagram_url"].endswith("/anarkick_records")


def test_tier3_topup_with_validation():
    tavily = tavily_with([
        {"results": []},                       # tier1 search: nothing
        {"results": []},                       # tier2 extract on baseline website: nothing
        {"results": [                          # tier3 targeted search
            {"url": "https://www.instagram.com/ugra.music1111"},
            {"url": "https://www.instagram.com/anarkick_records"},
        ]},
    ])
    llm = FakeLLM(LabelFacts())
    r = run_facts_pass(ENTITY, "label", tavily, llm, model="m")
    assert r.instagram_tier == 3
    assert r.profiles["instagram_url"] == "https://www.instagram.com/anarkick_records"
    assert r.credits == 3


def test_no_instagram_anywhere_leaves_null():
    tavily = tavily_with([
        {"results": []},
        {"results": []},
        {"results": [{"url": "https://www.instagram.com/totally.unrelated9"}]},
    ])
    llm = FakeLLM(LabelFacts())
    r = run_facts_pass(ENTITY, "label", tavily, llm, model="m")
    assert r.instagram_tier is None
    assert "instagram_url" not in r.profiles


def test_llm_error_is_captured_not_raised():
    tavily = tavily_with([{"results": []}, {"results": []}, {"results": []}])

    class Boom:
        @property
        def responses(self):
            return self
        def parse(self, **kwargs):
            raise RuntimeError("api down")

    r = run_facts_pass(ENTITY, "label", tavily, Boom(), model="m")
    assert r.error is not None and "api down" in r.error
    assert r.facts == {}
