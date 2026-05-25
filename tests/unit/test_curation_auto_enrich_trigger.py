from unittest.mock import MagicMock, patch


def _add_track_event(category_id="cat-1", track_id="trk-1"):
    return {
        "routeKey": "POST /categories/{id}/tracks",
        "pathParameters": {"id": category_id},
        "body": '{"track_id": "trk-1"}',
        "requestContext": {"authorizer": {"lambda": {"user_id": "u1"}}},
    }


def test_add_track_triggers_dispatch_for_track():
    from collector import curation_handler as ch

    repo = MagicMock()
    repo.add_track.return_value = ({"added_at": "t", "source_triage_block_id": None}, True)
    with patch.object(ch, "try_dispatch_for_track") as dispatch:
        ch._handle_add_track(_add_track_event(), repo, "u1", "corr-1")
    dispatch.assert_called_once()
    assert dispatch.call_args.kwargs["track_id"] == "trk-1"
    assert dispatch.call_args.kwargs["user_id"] == "u1"


def test_add_track_no_dispatch_when_already_present():
    from collector import curation_handler as ch

    repo = MagicMock()
    repo.add_track.return_value = ({"added_at": "t", "source_triage_block_id": None}, False)
    with patch.object(ch, "try_dispatch_for_track") as dispatch:
        ch._handle_add_track(_add_track_event(), repo, "u1", "corr-1")
    dispatch.assert_not_called()
