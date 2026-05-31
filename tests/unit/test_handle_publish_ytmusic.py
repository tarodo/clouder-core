import json
from unittest.mock import patch

from collector import curation_handler
from collector.curation.ytmusic_publish_service import YtmusicPublishResult


def _event(pid="p1", body=None):
    return {
        "pathParameters": {"id": pid},
        "body": json.dumps(body) if body is not None else None,
    }


def test_handle_publish_ytmusic_returns_payload():
    result = YtmusicPublishResult(
        ytmusic_playlist_id="PLabc",
        ytmusic_url="https://music.youtube.com/playlist?list=PLabc",
        skipped=[{"track_id": "t2", "title": "T2", "reason": "no_ytmusic_match"}],
        published_at="2026-05-31T00:00:00+00:00",
    )

    class FakeSvc:
        def publish(self, **kwargs):
            assert kwargs["confirm_overwrite"] is True
            return result

    with patch.object(curation_handler, "_build_ytmusic_user_client", return_value=object()), \
         patch("collector.curation.ytmusic_publish_service.YtmusicPublishService",
               return_value=FakeSvc()):
        resp = curation_handler._handle_publish_ytmusic(
            _event(body={"confirm_overwrite": True}), repo=object(),
            user_id="u1", correlation_id="corr",
        )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["ytmusic_playlist_id"] == "PLabc"
    assert body["ytmusic_url"].endswith("PLabc")
    assert body["skipped_tracks"][0]["reason"] == "no_ytmusic_match"


def test_route_table_has_publish_ytmusic():
    assert "POST /playlists/{id}/publish-ytmusic" in curation_handler._ROUTE_TABLE
    handler, _factory = curation_handler._ROUTE_TABLE["POST /playlists/{id}/publish-ytmusic"]
    assert handler is curation_handler._handle_publish_ytmusic
