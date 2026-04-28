"""Unit tests for TriageRepository (mocked Data API)."""

from __future__ import annotations

from typing import Any

from collector.curation.triage_repository import (
    TriageRepository,
    TriageBlockRow,
    TriageBucketRow,
    BucketTrackRowOut,
)


def test_module_exposes_repository_class() -> None:
    assert hasattr(TriageRepository, "create_block")
    assert hasattr(TriageRepository, "get_block")
    assert hasattr(TriageRepository, "list_blocks_by_style")
    assert hasattr(TriageRepository, "list_blocks_all")
    assert hasattr(TriageRepository, "list_bucket_tracks")
    assert hasattr(TriageRepository, "move_tracks")
    assert hasattr(TriageRepository, "transfer_tracks")
    assert hasattr(TriageRepository, "finalize_block")
    assert hasattr(TriageRepository, "soft_delete_block")
    assert hasattr(
        TriageRepository, "snapshot_category_into_active_blocks"
    )
    assert hasattr(
        TriageRepository, "mark_staging_inactive_for_category"
    )


def test_dataclasses_have_expected_fields() -> None:
    row = TriageBlockRow(
        id="b-1",
        user_id="u-1",
        style_id="s-1",
        style_name="House",
        name="Tech House W17",
        date_from="2026-04-20",
        date_to="2026-04-26",
        status="IN_PROGRESS",
        created_at="2026-04-28T00:00:00+00:00",
        updated_at="2026-04-28T00:00:00+00:00",
        finalized_at=None,
        buckets=(),
    )
    assert row.id == "b-1"
    assert row.buckets == ()


from datetime import date
from unittest.mock import MagicMock, call

import pytest

from collector.curation import (
    InactiveBucketError,
    InvalidStateError,
    NotFoundError,
    StyleMismatchError,
    TracksNotInSourceError,
)
from collector.curation.triage_repository import (
    TriageRepository,
    TriageBlockRow,
)


class _FakeTx:
    """Context manager mimicking DataAPIClient.transaction()."""

    def __init__(self, tx_id: str = "tx-1") -> None:
        self.tx_id = tx_id

    def __enter__(self) -> str:
        return self.tx_id

    def __exit__(self, *exc: Any) -> None:
        return None


def _api_with_responses(responses: list[Any]) -> MagicMock:
    api = MagicMock()
    api.transaction.return_value = _FakeTx()
    api.execute.side_effect = responses
    return api


def test_create_block_happy_path() -> None:
    """Six-step TX: insert block, 5 tech buckets, N staging buckets,
    classify-and-insert tracks, return assembled block."""
    style_response = [{"id": "s-1", "name": "House"}]
    block_response = [{"id": "b-1"}]
    tech_buckets_response = [
        {"id": f"buck-tech-{i}", "bucket_type": t}
        for i, t in enumerate(["NEW", "OLD", "NOT", "DISCARD", "UNCLASSIFIED"])
    ]
    categories_response = [
        {"id": "c-1", "name": "Tech House", "position": 0},
    ]
    staging_buckets_response = [
        {"id": "buck-stg-1", "category_id": "c-1"},
    ]
    classify_response: list[dict[str, Any]] = []
    detail_response = [
        {
            "id": "b-1",
            "user_id": "u-1",
            "style_id": "s-1",
            "style_name": "House",
            "name": "Tech House W17",
            "date_from": "2026-04-20",
            "date_to": "2026-04-26",
            "status": "IN_PROGRESS",
            "created_at": "2026-04-28T00:00:00+00:00",
            "updated_at": "2026-04-28T00:00:00+00:00",
            "finalized_at": None,
        }
    ]
    buckets_with_counts_response = [
        {
            "id": f"buck-tech-{i}",
            "bucket_type": t,
            "category_id": None,
            "category_name": None,
            "inactive": False,
            "track_count": 0,
        }
        for i, t in enumerate(["NEW", "OLD", "NOT", "UNCLASSIFIED", "DISCARD"])
    ] + [
        {
            "id": "buck-stg-1",
            "bucket_type": "STAGING",
            "category_id": "c-1",
            "category_name": "Tech House",
            "inactive": False,
            "track_count": 0,
        }
    ]

    api = _api_with_responses(
        [
            style_response,
            block_response,
            tech_buckets_response,
            categories_response,
            staging_buckets_response,
            classify_response,
            detail_response,
            buckets_with_counts_response,
        ]
    )
    repo = TriageRepository(api)
    out = repo.create_block(
        user_id="u-1",
        style_id="s-1",
        name="Tech House W17",
        date_from=date(2026, 4, 20),
        date_to=date(2026, 4, 26),
    )

    assert isinstance(out, TriageBlockRow)
    assert out.style_name == "House"
    assert out.status == "IN_PROGRESS"
    assert len(out.buckets) == 6
    types = [b.bucket_type for b in out.buckets]
    assert types[:5] == ["NEW", "OLD", "NOT", "UNCLASSIFIED", "DISCARD"]
    assert types[5] == "STAGING"


def test_create_block_style_not_found() -> None:
    api = _api_with_responses([[]])
    repo = TriageRepository(api)
    with pytest.raises(NotFoundError) as ei:
        repo.create_block(
            user_id="u-1",
            style_id="missing",
            name="X",
            date_from=date(2026, 4, 20),
            date_to=date(2026, 4, 26),
        )
    assert ei.value.error_code == "style_not_found"


def test_create_block_classify_sql_includes_filters_and_case() -> None:
    """Spot-check the R4 INSERT-FROM-SELECT statement."""
    api = _api_with_responses(
        [
            [{"id": "s-1", "name": "House"}],
            [{"id": "b-1"}],
            [
                {"id": f"t-{i}", "bucket_type": t}
                for i, t in enumerate(
                    ["NEW", "OLD", "NOT", "DISCARD", "UNCLASSIFIED"]
                )
            ],
            [],  # no alive categories
            [],  # classify INSERT
            [
                {
                    "id": "b-1",
                    "user_id": "u-1",
                    "style_id": "s-1",
                    "style_name": "House",
                    "name": "X",
                    "date_from": "2026-04-20",
                    "date_to": "2026-04-26",
                    "status": "IN_PROGRESS",
                    "created_at": "2026-04-28T00:00:00+00:00",
                    "updated_at": "2026-04-28T00:00:00+00:00",
                    "finalized_at": None,
                }
            ],
            [],  # buckets-with-counts (5 technical, no staging)
        ]
    )
    repo = TriageRepository(api)
    repo.create_block(
        user_id="u-1",
        style_id="s-1",
        name="X",
        date_from=date(2026, 4, 20),
        date_to=date(2026, 4, 26),
    )

    classify_call = api.execute.call_args_list[4]
    sql = classify_call.args[0]
    params = classify_call.args[1]
    assert "INSERT INTO triage_bucket_tracks" in sql
    assert "FROM clouder_tracks t" in sql
    assert "spotify_release_date IS NULL" in sql
    assert "t.spotify_release_date < :date_from" in sql
    assert "release_type = 'compilation'" in sql
    assert "NOT EXISTS" in sql
    assert "categories c" in sql
    assert "c.deleted_at IS NULL" in sql
    assert params["user_id"] == "u-1"
    assert params["style_id"] == "s-1"
    assert params["date_from"] == date(2026, 4, 20)
    assert params["date_to"] == date(2026, 4, 26)
    assert "new_bucket_id" in params
    assert "old_bucket_id" in params
    assert "not_bucket_id" in params
    assert "unclassified_bucket_id" in params


def test_get_block_returns_full_detail() -> None:
    api = _api_with_responses(
        [
            [
                {
                    "id": "b-1",
                    "user_id": "u-1",
                    "style_id": "s-1",
                    "style_name": "House",
                    "name": "X",
                    "date_from": "2026-04-20",
                    "date_to": "2026-04-26",
                    "status": "IN_PROGRESS",
                    "created_at": "2026-04-28T00:00:00+00:00",
                    "updated_at": "2026-04-28T00:00:00+00:00",
                    "finalized_at": None,
                }
            ],
            [],
        ]
    )
    repo = TriageRepository(api)
    out = repo.get_block(user_id="u-1", block_id="b-1")
    assert out is not None
    assert out.style_name == "House"


def test_get_block_missing_returns_none() -> None:
    api = _api_with_responses([[]])
    repo = TriageRepository(api)
    assert repo.get_block(user_id="u-1", block_id="missing") is None


def test_list_blocks_by_style_status_filter_in_sql() -> None:
    api = _api_with_responses(
        [
            [{"id": "s-1"}],
            [],
            [{"total": 0}],
        ]
    )
    repo = TriageRepository(api)
    repo.list_blocks_by_style(
        user_id="u-1",
        style_id="s-1",
        limit=50,
        offset=0,
        status="FINALIZED",
    )
    list_call = api.execute.call_args_list[1]
    assert "status = :status" in list_call.args[0]
    assert list_call.args[1]["status"] == "FINALIZED"


def test_list_blocks_by_style_style_not_found() -> None:
    api = _api_with_responses([[]])
    repo = TriageRepository(api)
    with pytest.raises(NotFoundError) as ei:
        repo.list_blocks_by_style(
            user_id="u-1", style_id="missing", limit=50, offset=0
        )
    assert ei.value.error_code == "style_not_found"


def test_list_blocks_all_no_style_filter() -> None:
    api = _api_with_responses([[], [{"total": 0}]])
    repo = TriageRepository(api)
    repo.list_blocks_all(user_id="u-1", limit=50, offset=0)
    list_call = api.execute.call_args_list[0]
    sql = list_call.args[0]
    assert "tb.user_id = :user_id" in sql
    assert ":style_id" not in sql


def test_list_bucket_tracks_validates_block_and_bucket() -> None:
    api = _api_with_responses([[]])
    repo = TriageRepository(api)
    with pytest.raises(NotFoundError) as ei:
        repo.list_bucket_tracks(
            user_id="u-1",
            block_id="b-missing",
            bucket_id="bk-missing",
            limit=50,
            offset=0,
        )
    assert ei.value.error_code == "bucket_not_in_block"


def test_list_bucket_tracks_search_lowers_term() -> None:
    api = _api_with_responses(
        [
            [{"block_id": "b-1", "bucket_id": "bk-1"}],
            [],
            [{"total": 0}],
        ]
    )
    repo = TriageRepository(api)
    repo.list_bucket_tracks(
        user_id="u-1",
        block_id="b-1",
        bucket_id="bk-1",
        limit=50,
        offset=0,
        search="  Tech  ",
    )
    rows_call = api.execute.call_args_list[1]
    sql = rows_call.args[0]
    params = rows_call.args[1]
    assert "ILIKE :search" in sql
    assert params["search"] == "%tech%"


def test_move_tracks_target_inactive() -> None:
    api = _api_with_responses(
        [
            [
                {
                    "block_status": "IN_PROGRESS",
                    "from_id": "bk-from",
                    "from_inactive": False,
                    "to_id": "bk-to",
                    "to_inactive": True,
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    with pytest.raises(InactiveBucketError):
        repo.move_tracks(
            user_id="u-1",
            block_id="b-1",
            from_bucket_id="bk-from",
            to_bucket_id="bk-to",
            track_ids=["00000000-0000-0000-0000-000000000001"],
        )


def test_move_tracks_block_not_editable() -> None:
    api = _api_with_responses(
        [
            [
                {
                    "block_status": "FINALIZED",
                    "from_id": "bk-from",
                    "from_inactive": False,
                    "to_id": "bk-to",
                    "to_inactive": False,
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    with pytest.raises(InvalidStateError):
        repo.move_tracks(
            user_id="u-1",
            block_id="b-1",
            from_bucket_id="bk-from",
            to_bucket_id="bk-to",
            track_ids=["00000000-0000-0000-0000-000000000001"],
        )


def test_move_tracks_tracks_not_in_source() -> None:
    api = _api_with_responses(
        [
            [
                {
                    "block_status": "IN_PROGRESS",
                    "from_id": "bk-from",
                    "from_inactive": False,
                    "to_id": "bk-to",
                    "to_inactive": False,
                }
            ],
            [{"track_id": "00000000-0000-0000-0000-000000000001"}],
        ]
    )
    repo = TriageRepository(api)
    with pytest.raises(TracksNotInSourceError) as ei:
        repo.move_tracks(
            user_id="u-1",
            block_id="b-1",
            from_bucket_id="bk-from",
            to_bucket_id="bk-to",
            track_ids=[
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
            ],
        )
    assert "00000000-0000-0000-0000-000000000002" in ei.value.not_in_source


def test_move_tracks_happy_path() -> None:
    ids_present = [
        {"track_id": f"00000000-0000-0000-0000-{n:012d}"} for n in (1, 2)
    ]
    api = _api_with_responses(
        [
            [
                {
                    "block_status": "IN_PROGRESS",
                    "from_id": "bk-from",
                    "from_inactive": False,
                    "to_id": "bk-to",
                    "to_inactive": False,
                }
            ],
            ids_present,
            [],  # DELETE
            [],  # INSERT
        ]
    )
    repo = TriageRepository(api)
    out = repo.move_tracks(
        user_id="u-1",
        block_id="b-1",
        from_bucket_id="bk-from",
        to_bucket_id="bk-to",
        track_ids=[
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
    )
    assert out.moved == 2
    delete_call = api.execute.call_args_list[2]
    insert_call = api.execute.call_args_list[3]
    assert "DELETE FROM triage_bucket_tracks" in delete_call.args[0]
    assert "INSERT INTO triage_bucket_tracks" in insert_call.args[0]
    assert "ON CONFLICT" in insert_call.args[0]


def test_move_tracks_self_noop() -> None:
    api = _api_with_responses(
        [
            [
                {
                    "block_status": "IN_PROGRESS",
                    "from_id": "bk-x",
                    "from_inactive": False,
                    "to_id": "bk-x",
                    "to_inactive": False,
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    out = repo.move_tracks(
        user_id="u-1",
        block_id="b-1",
        from_bucket_id="bk-x",
        to_bucket_id="bk-x",
        track_ids=["00000000-0000-0000-0000-000000000001"],
    )
    assert out.moved == 0
    assert api.execute.call_count == 1


def test_transfer_tracks_validates_target_state() -> None:
    api = _api_with_responses(
        [
            [{"id": "b-src", "style_id": "s-1", "status": "FINALIZED"}],
            [
                {
                    "bucket_id": "bk-tgt",
                    "bucket_inactive": False,
                    "block_id": "b-tgt",
                    "block_user_id": "u-1",
                    "block_style_id": "s-1",
                    "block_status": "FINALIZED",
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    with pytest.raises(InvalidStateError):
        repo.transfer_tracks(
            user_id="u-1",
            src_block_id="b-src",
            target_bucket_id="bk-tgt",
            track_ids=["00000000-0000-0000-0000-000000000001"],
        )


def test_transfer_tracks_style_mismatch() -> None:
    api = _api_with_responses(
        [
            [{"id": "b-src", "style_id": "s-1", "status": "FINALIZED"}],
            [
                {
                    "bucket_id": "bk-tgt",
                    "bucket_inactive": False,
                    "block_id": "b-tgt",
                    "block_user_id": "u-1",
                    "block_style_id": "s-2",
                    "block_status": "IN_PROGRESS",
                }
            ],
        ]
    )
    repo = TriageRepository(api)
    with pytest.raises(StyleMismatchError):
        repo.transfer_tracks(
            user_id="u-1",
            src_block_id="b-src",
            target_bucket_id="bk-tgt",
            track_ids=["00000000-0000-0000-0000-000000000001"],
        )


def test_transfer_tracks_happy_path() -> None:
    api = _api_with_responses(
        [
            [{"id": "b-src", "style_id": "s-1", "status": "FINALIZED"}],
            [
                {
                    "bucket_id": "bk-tgt",
                    "bucket_inactive": False,
                    "block_id": "b-tgt",
                    "block_user_id": "u-1",
                    "block_style_id": "s-1",
                    "block_status": "IN_PROGRESS",
                }
            ],
            [
                {"track_id": "00000000-0000-0000-0000-000000000001"},
                {"track_id": "00000000-0000-0000-0000-000000000002"},
            ],
            [
                {"track_id": "00000000-0000-0000-0000-000000000001"},
                {"track_id": "00000000-0000-0000-0000-000000000002"},
            ],
        ]
    )
    repo = TriageRepository(api)
    out = repo.transfer_tracks(
        user_id="u-1",
        src_block_id="b-src",
        target_bucket_id="bk-tgt",
        track_ids=[
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
    )
    assert out.transferred == 2
    insert_call = api.execute.call_args_list[3]
    assert "INSERT INTO triage_bucket_tracks" in insert_call.args[0]
    assert "ON CONFLICT" in insert_call.args[0]
