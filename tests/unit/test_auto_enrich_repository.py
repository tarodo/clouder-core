import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from collector.label_enrichment.auto_repository import AutoEnrichRepository


def _now():
    return datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)


def _repo():
    data_api = MagicMock()
    return AutoEnrichRepository(data_api=data_api, now=_now), data_api


def test_get_config_returns_none_when_absent():
    repo, data_api = _repo()
    data_api.execute.return_value = []
    assert repo.get_config("labels") is None


def test_get_config_parses_jsonb_strings():
    repo, data_api = _repo()
    data_api.execute.return_value = [{
        "kind": "labels", "enabled": True,
        "vendors": json.dumps(["gemini"]), "models": json.dumps({"gemini": "g"}),
        "prompt_slug": "s", "prompt_version": "v",
        "merge_vendor": "deepseek", "merge_model": "m",
    }]
    cfg = repo.get_config("labels")
    assert cfg["enabled"] is True
    assert cfg["vendors"] == ["gemini"]
    assert cfg["models"] == {"gemini": "g"}


def test_upsert_config_writes_all_columns():
    repo, data_api = _repo()
    data_api.execute.return_value = []
    repo.upsert_config(
        kind="labels", enabled=True, vendors=["gemini"], models={"gemini": "g"},
        prompt_slug="s", prompt_version="v", merge_vendor="deepseek",
        merge_model="m", user_id="user-1",
    )
    sql, params = data_api.execute.call_args[0]
    assert "INSERT INTO auto_enrich_config" in sql
    assert "ON CONFLICT (kind) DO UPDATE" in sql
    assert params["kind"] == "labels"
    assert params["enabled"] is True
    assert params["vendors"] == ["gemini"]
    assert params["models"] == {"gemini": "g"}
    assert params["updated_by_user_id"] == "user-1"


def test_claim_inserts_brand_new_label():
    repo, data_api = _repo()
    # 1st call: UPDATE (reclaim/retry) → no rows; 2nd call: INSERT → claimed
    data_api.execute.side_effect = [[], [{"label_id": "lbl-1"}]]
    claimed = repo.claim_labels(["lbl-1"])
    assert claimed == ["lbl-1"]
    update_sql = data_api.execute.call_args_list[0][0][0]
    insert_sql = data_api.execute.call_args_list[1][0][0]
    assert "UPDATE label_auto_enrich_state" in update_sql
    assert "INSERT INTO label_auto_enrich_state" in insert_sql
    assert "NOT EXISTS" in insert_sql and "clouder_label_info" in insert_sql


def test_claim_retries_failed_label_via_update():
    repo, data_api = _repo()
    # UPDATE claims it; INSERT is still issued but returns nothing (NOT EXISTS
    # on the state row excludes the already-reclaimed id at DB level).
    data_api.execute.side_effect = [[{"label_id": "lbl-2"}], []]
    claimed = repo.claim_labels(["lbl-2"])
    assert claimed == ["lbl-2"]
    assert data_api.execute.call_count == 2
    sql, params = data_api.execute.call_args_list[0][0]
    assert "attempts < :max_attempts" in sql
    assert params["max_attempts"] == 2


def test_claim_skips_when_neither_update_nor_insert_match():
    repo, data_api = _repo()
    data_api.execute.side_effect = [[], []]  # update no-match, insert no-match
    assert repo.claim_labels(["lbl-3"]) == []


def test_claim_empty_input_is_noop():
    repo, data_api = _repo()
    assert repo.claim_labels([]) == []
    data_api.execute.assert_not_called()


def test_attach_run_updates_last_run_id():
    repo, data_api = _repo()
    data_api.execute.return_value = []
    repo.attach_run(["lbl-1"], "run-9")
    sql, params = data_api.execute.call_args[0]
    assert "SET last_run_id = :run_id" in sql
    assert params["run_id"] == "run-9"
    assert params["label_id"] == "lbl-1"


def test_mark_outcome_completed_on_success():
    repo, data_api = _repo()
    data_api.execute.return_value = []
    repo.mark_auto_enrich_outcome("lbl-1", True)
    sql, params = data_api.execute.call_args[0]
    assert "SET status = :new_status" in sql
    assert "WHERE label_id = :label_id AND status = 'queued'" in sql
    assert params["new_status"] == "completed"
    assert params["label_id"] == "lbl-1"


def test_mark_outcome_failed_on_failure():
    repo, data_api = _repo()
    data_api.execute.return_value = []
    repo.mark_auto_enrich_outcome("lbl-1", False)
    _, params = data_api.execute.call_args[0]
    assert params["new_status"] == "failed"


def test_label_id_for_track():
    repo, data_api = _repo()
    data_api.execute.return_value = [{"label_id": "lbl-1"}]
    assert repo.label_id_for_track("trk-1") == "lbl-1"


def test_label_id_for_track_none_when_no_label():
    repo, data_api = _repo()
    data_api.execute.return_value = []
    assert repo.label_id_for_track("trk-1") is None


def test_label_ids_for_triage_block():
    repo, data_api = _repo()
    data_api.execute.return_value = [{"label_id": "a"}, {"label_id": "b"}]
    assert repo.label_ids_for_triage_block("blk-1") == ["a", "b"]
    sql, params = data_api.execute.call_args[0]
    assert "source_triage_block_id = :block_id" in sql
    assert params["block_id"] == "blk-1"


def test_claim_reclaims_stale_queued_via_update():
    repo, data_api = _repo()
    # UPDATE reclaims the stale-queued row; INSERT is still issued but the
    # NOT EXISTS(state) guard at DB level returns nothing for the same id.
    data_api.execute.side_effect = [[{"label_id": "lbl-7"}], []]
    claimed = repo.claim_labels(["lbl-7"])
    assert claimed == ["lbl-7"]
    assert data_api.execute.call_count == 2
    sql, params = data_api.execute.call_args_list[0][0]
    assert "status = 'queued' AND updated_at < :stale_cutoff" in sql
    assert "stale_cutoff" in params


def test_claim_labels_uses_two_statements_regardless_of_count():
    calls = []

    class FakeDataAPI:
        def execute(self, sql, params=None, transaction_id=None):
            calls.append(sql.strip().split()[0].upper())
            if sql.strip().upper().startswith("UPDATE"):
                return [{"label_id": "l1"}]
            return [{"label_id": "l3"}]

    from collector.label_enrichment.auto_repository import AutoEnrichRepository
    repo = AutoEnrichRepository(data_api=FakeDataAPI())
    claimed = repo.claim_labels(["l1", "l2", "l3"])
    assert calls.count("UPDATE") == 1
    assert calls.count("INSERT") == 1
    assert set(claimed) == {"l1", "l3"}


def test_claim_labels_empty_returns_empty_no_query():
    class FakeDataAPI:
        def execute(self, *a, **k):  # pragma: no cover
            raise AssertionError("no query for empty input")

    from collector.label_enrichment.auto_repository import AutoEnrichRepository
    assert AutoEnrichRepository(data_api=FakeDataAPI()).claim_labels([]) == []
