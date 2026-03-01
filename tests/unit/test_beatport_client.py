import pytest

from collector.beatport_client import BeatportClient, is_retryable_status
from collector.errors import UpstreamUnavailableError


def test_retryable_status_matrix() -> None:
    assert is_retryable_status(429)
    assert is_retryable_status(503)
    assert not is_retryable_status(401)
    assert not is_retryable_status(403)


def test_fetch_weekly_releases_uses_tracks_endpoint_and_next_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BeatportClient(base_url="https://api.beatport.com/v4/catalog")
    calls = []

    def fake_request_page(url: str, params: dict[str, str], bp_token: str, correlation_id: str):
        calls.append((url, params.copy(), bp_token, correlation_id))
        if len(calls) == 1:
            return {
                "results": [{"id": 1}],
                "next": "https://api.beatport.com/v4/catalog/tracks/?genre_id=5&publish_date=2026-02-23:2026-03-01&page=2&per_page=100&order_by=-publish_date",
            }
        return {"results": [{"id": 2}], "next": None}

    monkeypatch.setattr(client, "_request_page", fake_request_page)

    items, pages_fetched = client.fetch_weekly_releases(
        bp_token="secret",
        style_id=5,
        week_start="2026-02-23",
        week_end="2026-03-01",
        correlation_id="cid-1",
    )

    assert items == [{"id": 1}, {"id": 2}]
    assert pages_fetched == 2

    first_url, first_params, first_token, first_correlation = calls[0]
    assert first_url == "https://api.beatport.com/v4/catalog/tracks/"
    assert first_params == {
        "genre_id": "5",
        "publish_date": "2026-02-23:2026-03-01",
        "page": "1",
        "per_page": "100",
        "order_by": "-publish_date",
    }
    assert first_token == "secret"
    assert first_correlation == "cid-1"

    _, second_params, _, _ = calls[1]
    assert second_params["page"] == "2"


def test_fetch_weekly_releases_rejects_malformed_next_link(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BeatportClient(base_url="https://api.beatport.com/v4/catalog")

    def fake_request_page(url: str, params: dict[str, str], bp_token: str, correlation_id: str):
        return {
            "results": [{"id": 1}],
            "next": "https://api.beatport.com/v4/catalog/tracks/",
        }

    monkeypatch.setattr(client, "_request_page", fake_request_page)

    with pytest.raises(UpstreamUnavailableError, match="pagination link is malformed"):
        client.fetch_weekly_releases(
            bp_token="secret",
            style_id=5,
            week_start="2026-02-23",
            week_end="2026-03-01",
            correlation_id="cid-1",
        )
