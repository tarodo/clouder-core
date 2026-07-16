from types import SimpleNamespace

from collector.label_enrichment.vendors.openai_gpt import OpenAIAdapter
from collector.label_enrichment.schemas import LabelInfoRequest


class FakeResponses:
    def __init__(self, raise_on_knobs=False):
        self.last_kwargs = None
        self.calls = 0
        self.raise_on_knobs = raise_on_knobs

    def parse(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.raise_on_knobs and ("max_tool_calls" in kwargs or "reasoning" in kwargs):
            import openai
            raise openai.BadRequestError.__new__(openai.BadRequestError)
        parsed = LabelInfoRequest(label_name="X", summary="s", confidence=0.5)
        usage = SimpleNamespace(
            input_tokens=100, output_tokens=50,
            output_tokens_details=SimpleNamespace(reasoning_tokens=17),
        )
        output = [SimpleNamespace(type="web_search_call"),
                  SimpleNamespace(type="web_search_call"),
                  SimpleNamespace(type="message")]
        return SimpleNamespace(output_parsed=parsed, usage=usage, output=output, citations=[])


def make_adapter(fake):
    client = SimpleNamespace(responses=fake)
    return OpenAIAdapter(api_key="k", default_model="gpt-5.4-mini", client=client,
                         max_tool_calls=3, reasoning_effort="low")


def test_knobs_passed_and_usage_instrumented():
    fake = FakeResponses()
    resp = make_adapter(fake).run(system="s", user="u", schema=LabelInfoRequest)
    assert fake.last_kwargs["max_tool_calls"] == 3
    assert fake.last_kwargs["reasoning"] == {"effort": "low"}
    assert resp.usage["web_search_calls"] == 2
    assert resp.usage["reasoning_tokens"] == 17
    assert abs(resp.usage["cost_usd"] - (100/1e6*0.25 + 50/1e6*2.0 + 2*0.01)) < 1e-9


def test_empty_effort_not_sent_and_default_cap():
    fake = FakeResponses()
    client = SimpleNamespace(responses=fake)
    OpenAIAdapter(api_key="k", default_model="gpt-5.4-mini", client=client).run(
        system="s", user="u", schema=LabelInfoRequest)
    assert "reasoning" not in fake.last_kwargs
    assert fake.last_kwargs["max_tool_calls"] == 3


def test_bad_request_on_knobs_retries_bare():
    fake = FakeResponses(raise_on_knobs=True)
    resp = make_adapter(fake).run(system="s", user="u", schema=LabelInfoRequest)
    assert fake.calls == 2
    assert "max_tool_calls" not in fake.last_kwargs and "reasoning" not in fake.last_kwargs
    assert resp.error is None
