from unittest.mock import MagicMock, patch


def _add_track_event(category_id="cat-1", track_id="trk-1"):
    return {
        "routeKey": "POST /categories/{id}/tracks",
        "pathParameters": {"id": category_id},
        "body": '{"track_id": "trk-1"}',
        "requestContext": {"authorizer": {"lambda": {"user_id": "u1"}}},
    }


def test_add_track_triggers_artist_dispatch_for_track():
    from collector import curation_handler as ch

    repo = MagicMock()
    repo.add_track.return_value = ({"added_at": "t", "source_triage_block_id": None}, True)
    with patch.object(ch, "try_dispatch_artists_for_track") as dispatch:
        ch._handle_add_track(_add_track_event(), repo, "u1", "corr-1")
    dispatch.assert_called_once()
    assert dispatch.call_args.kwargs["track_id"] == "trk-1"
    assert dispatch.call_args.kwargs["user_id"] == "u1"


def test_add_track_no_artist_dispatch_when_already_present():
    from collector import curation_handler as ch

    repo = MagicMock()
    repo.add_track.return_value = ({"added_at": "t", "source_triage_block_id": None}, False)
    with patch.object(ch, "try_dispatch_artists_for_track") as dispatch:
        ch._handle_add_track(_add_track_event(), repo, "u1", "corr-1")
    dispatch.assert_not_called()


def _finalize_event(block_id="blk-1"):
    return {
        "routeKey": "POST /triage/blocks/{id}/finalize",
        "pathParameters": {"id": block_id},
        "requestContext": {"authorizer": {"lambda": {"user_id": "u1"}}},
    }


def test_finalize_triggers_artist_dispatch_for_block():
    from collector import curation_handler as ch

    repo = MagicMock()
    finalize_result = MagicMock()
    finalize_result.block = MagicMock(finalized_at="t")
    finalize_result.promoted = {"cat-1": 3}
    repo.finalize_block.return_value = finalize_result

    cat_repo = MagicMock()
    with patch.object(ch, "try_dispatch_artists_for_triage_block") as dispatch, \
         patch.object(ch, "create_default_categories_repository", return_value=cat_repo), \
         patch.object(ch, "_serialize_triage_block", return_value={}):
        ch._finalize_triage_block(_finalize_event(), repo, "u1", "corr-1")
    dispatch.assert_called_once()
    assert dispatch.call_args.kwargs["block_id"] == "blk-1"
    assert dispatch.call_args.kwargs["user_id"] == "u1"
