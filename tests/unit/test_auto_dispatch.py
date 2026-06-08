import json
from unittest.mock import MagicMock, patch

from collector.label_enrichment import auto_dispatch


def _patch_clients(auto_repo, le_repo, sqs):
    return patch.multiple(
        auto_dispatch,
        _build_auto_repository=MagicMock(return_value=auto_repo),
        _build_label_repository=MagicMock(return_value=le_repo),
        _build_sqs_client=MagicMock(return_value=sqs),
        _queue_url=MagicMock(return_value="https://sqs/queue"),
    )


def test_dispatch_disabled_does_nothing():
    auto_repo = MagicMock()
    auto_repo.get_config.return_value = {"enabled": False}
    le_repo, sqs = MagicMock(), MagicMock()
    with _patch_clients(auto_repo, le_repo, sqs):
        auto_dispatch._dispatch_labels(
            label_ids=["lbl-1"], source_hint="single", user_id="u1",
        )
    auto_repo.claim_labels.assert_not_called()
    sqs.send_message_batch.assert_not_called()


def test_dispatch_no_config_does_nothing():
    auto_repo = MagicMock()
    auto_repo.get_config.return_value = None
    le_repo, sqs = MagicMock(), MagicMock()
    with _patch_clients(auto_repo, le_repo, sqs):
        auto_dispatch._dispatch_labels(label_ids=["lbl-1"], source_hint="x", user_id=None)
    auto_repo.claim_labels.assert_not_called()


def test_dispatch_claims_creates_run_and_enqueues():
    auto_repo = MagicMock()
    auto_repo.get_config.return_value = {
        "enabled": True, "vendors": ["gemini"], "models": {"gemini": "g"},
        "prompt_slug": "s", "prompt_version": "v",
        "merge_vendor": "deepseek", "merge_model": "m",
    }
    auto_repo.claim_labels.return_value = ["lbl-1", "lbl-2"]
    le_repo = MagicMock()
    le_repo.get_labels_by_ids.return_value = {"lbl-1": "name-lbl-1", "lbl-2": "name-lbl-2"}
    le_repo.derive_styles_for_labels.return_value = {"lbl-1": "techno", "lbl-2": "techno"}
    le_repo.create_run.return_value = "run-1"
    sqs = MagicMock()
    sqs.send_message_batch.return_value = {"Successful": [], "Failed": []}
    with _patch_clients(auto_repo, le_repo, sqs):
        auto_dispatch._dispatch_labels(
            label_ids=["lbl-1", "lbl-2"], source_hint="triage", user_id="u1",
        )
    spec = le_repo.create_run.call_args[0][0]
    assert spec.source == "auto"
    assert spec.requested_labels == 2
    assert spec.vendors == ["gemini"]
    auto_repo.attach_run.assert_called_once_with(["lbl-1", "lbl-2"], "run-1")
    assert sqs.send_message_batch.call_count == 1
    entries = sqs.send_message_batch.call_args.kwargs["Entries"]
    assert len(entries) == 2
    body = json.loads(entries[0]["MessageBody"])
    assert body["run_id"] == "run-1"
    assert body["label_id"] == "lbl-1"
    assert body["style"] == "techno"


def test_dispatch_no_claims_skips_run():
    auto_repo = MagicMock()
    auto_repo.get_config.return_value = {
        "enabled": True, "vendors": ["gemini"], "models": {"gemini": "g"},
        "prompt_slug": "s", "prompt_version": "v",
        "merge_vendor": "deepseek", "merge_model": "m",
    }
    auto_repo.claim_labels.return_value = []
    le_repo, sqs = MagicMock(), MagicMock()
    with _patch_clients(auto_repo, le_repo, sqs):
        auto_dispatch._dispatch_labels(label_ids=["lbl-1"], source_hint="x", user_id=None)
    le_repo.create_run.assert_not_called()
    sqs.send_message_batch.assert_not_called()


def test_try_dispatch_for_track_swallows_errors():
    with patch.object(auto_dispatch, "_build_auto_repository", side_effect=RuntimeError("boom")):
        auto_dispatch.try_dispatch_for_track(track_id="t1", user_id="u1")  # must not raise


def test_try_dispatch_for_track_resolves_label():
    auto_repo = MagicMock()
    auto_repo.label_id_for_track.return_value = "lbl-1"
    auto_repo.get_config.return_value = {"enabled": False}
    with _patch_clients(auto_repo, MagicMock(), MagicMock()):
        auto_dispatch.try_dispatch_for_track(track_id="t1", user_id="u1")
    auto_repo.label_id_for_track.assert_called_once_with("t1")


def test_try_dispatch_for_track_skips_when_no_label():
    auto_repo = MagicMock()
    auto_repo.label_id_for_track.return_value = None
    with _patch_clients(auto_repo, MagicMock(), MagicMock()):
        auto_dispatch.try_dispatch_for_track(track_id="t1", user_id="u1")
    auto_repo.get_config.assert_not_called()
