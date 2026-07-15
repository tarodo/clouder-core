from splitlab.tavily_client import TavilyClient


def make_client(calls):
    def fake_post(path, payload):
        calls.append((path, payload))
        return {"results": []}
    return TavilyClient(api_key="tvly-x", post=fake_post)


def test_search_counts_one_credit_and_sends_params():
    calls = []
    c = make_client(calls)
    c.search("q1", include_raw_content=True)
    c.search("q2", include_domains=["instagram.com"], max_results=5)
    assert c.credits_used == 2
    path, payload = calls[0]
    assert path == "search"
    assert payload["query"] == "q1"
    assert payload["include_raw_content"] is True
    assert payload["search_depth"] == "basic"
    assert payload["api_key"] == "tvly-x"
    assert calls[1][1]["include_domains"] == ["instagram.com"]


def test_extract_counts_credits_per_five_urls():
    calls = []
    c = make_client(calls)
    c.extract(["u1", "u2"])
    assert c.credits_used == 1
    c.extract([f"u{i}" for i in range(6)])
    assert c.credits_used == 3  # 1 + ceil(6/5)
    assert calls[1][0] == "extract"
    assert calls[1][1]["urls"] == [f"u{i}" for i in range(6)]


def test_extract_empty_is_free_noop():
    calls = []
    c = make_client(calls)
    assert c.extract([]) == {"results": []}
    assert c.credits_used == 0
    assert calls == []
