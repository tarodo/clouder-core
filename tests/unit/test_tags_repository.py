from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.curation import (
    TagNameConflictError,
    TagNotFoundError,
    TrackNotInAnyCategoryError,
)
from collector.curation.tags_repository import (
    TagRow,
    TagsRepository,
    TrackTagRow,
)


def _now() -> datetime:
    return datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)


def _make() -> tuple[TagsRepository, MagicMock]:
    data_api = MagicMock()
    return TagsRepository(data_api=data_api), data_api


def test_repository_constructs() -> None:
    repo, _ = _make()
    assert repo is not None


def test_tag_row_dataclass_shape() -> None:
    row = TagRow(
        id="tg1",
        name="Vocal",
        color="#ff8800",
        created_at="2026-05-11T12:00:00Z",
        updated_at="2026-05-11T12:00:00Z",
    )
    assert row.id == "tg1"
    assert row.color == "#ff8800"


def test_track_tag_row_dataclass_shape() -> None:
    row = TrackTagRow(track_id="t1", tag_id="tg1", name="Vocal", color="#ff8800")
    assert row.track_id == "t1"
    assert row.tag_id == "tg1"


def test_create_tag_inserts_and_returns_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {
            "id": "tg1",
            "name": "Vocal",
            "color": "#ff8800",
            "created_at": "2026-05-11T12:00:00Z",
            "updated_at": "2026-05-11T12:00:00Z",
        }
    ]

    row = repo.create_tag(
        user_id="u1",
        tag_id="tg1",
        name="Vocal",
        normalized_name="vocal",
        color="#ff8800",
        now=_now(),
    )

    assert isinstance(row, TagRow)
    assert row.id == "tg1"
    call = data_api.execute.call_args
    assert "INSERT INTO user_tags" in call.args[0]
    params = call.args[1]
    assert params["user_id"] == "u1"
    assert params["normalized_name"] == "vocal"
    assert params["color"] == "#ff8800"


def test_create_tag_maps_unique_violation() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = Exception("uq_user_tags_user_normalized_name")
    with pytest.raises(TagNameConflictError):
        repo.create_tag(
            user_id="u1",
            tag_id="tg1",
            name="Vocal",
            normalized_name="vocal",
            color="#ff8800",
            now=_now(),
        )


def test_list_tags_returns_rows_and_total() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [
            {
                "id": "tg1",
                "name": "Vocal",
                "color": "#ff8800",
                "created_at": "2026-05-11T12:00:00Z",
                "updated_at": "2026-05-11T12:00:00Z",
            },
        ],
        [{"total": 1}],
    ]
    page = repo.list_tags(user_id="u1", limit=20, offset=0, search=None)
    assert page.total == 1
    assert page.items[0].id == "tg1"


def test_list_tags_with_search_passes_lower_prefix() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [[], [{"total": 0}]]
    repo.list_tags(user_id="u1", limit=20, offset=0, search="VoCaL")
    assert data_api.execute.call_args_list[0].args[1]["search"] == "vocal%"


def test_get_tag_returns_none_when_missing() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = []
    assert repo.get_tag(user_id="u1", tag_id="missing") is None


def test_get_tag_returns_row_when_found() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {
            "id": "tg1",
            "name": "Vocal",
            "color": "#ff8800",
            "created_at": "2026-05-11T12:00:00Z",
            "updated_at": "2026-05-11T12:00:00Z",
        }
    ]
    row = repo.get_tag(user_id="u1", tag_id="tg1")
    assert row is not None
    assert row.id == "tg1"


def test_rename_tag_updates_returned_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {
            "id": "tg1",
            "name": "Vocal F",
            "color": "#ff8800",
            "created_at": "2026-05-11T12:00:00Z",
            "updated_at": "2026-05-11T12:01:00Z",
        }
    ]
    row = repo.rename_tag(
        user_id="u1",
        tag_id="tg1",
        name="Vocal F",
        normalized_name="vocal f",
        color=None,
        now=_now(),
    )
    assert row.name == "Vocal F"


def test_rename_tag_raises_when_no_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = []
    with pytest.raises(TagNotFoundError):
        repo.rename_tag(
            user_id="u1",
            tag_id="missing",
            name="X",
            normalized_name="x",
            color=None,
            now=_now(),
        )


def test_rename_tag_maps_unique_violation() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = Exception("uq_user_tags_user_normalized_name")
    with pytest.raises(TagNameConflictError):
        repo.rename_tag(
            user_id="u1",
            tag_id="tg1",
            name="Vocal",
            normalized_name="vocal",
            color=None,
            now=_now(),
        )


def test_delete_tag_returns_true_on_delete() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [{"id": "tg1"}]
    assert repo.delete_tag(user_id="u1", tag_id="tg1") is True


def test_delete_tag_returns_false_when_missing() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = []
    assert repo.delete_tag(user_id="u1", tag_id="missing") is False


# --- track-tag ops ---------------------------------------------------------


def _bind_tx(data_api: MagicMock, tx_id: str = "tx-1") -> None:
    data_api.transaction.return_value.__enter__.return_value = tx_id
    data_api.transaction.return_value.__exit__.return_value = False


def test_set_track_tags_replaces_set() -> None:
    repo, data_api = _make()
    _bind_tx(data_api)
    data_api.execute.side_effect = [
        [{"x": 1}],                           # category probe
        [{"id": "tg1"}, {"id": "tg2"}],       # tag ownership probe
        [],                                    # DELETE existing
        [],                                    # INSERT new
        [                                      # SELECT joined for return
            {"id": "tg1", "name": "Vocal", "color": "#f00",
             "created_at": "2026-05-11T12:00:00Z",
             "updated_at": "2026-05-11T12:00:00Z"},
            {"id": "tg2", "name": "Dark", "color": "#000",
             "created_at": "2026-05-11T12:00:00Z",
             "updated_at": "2026-05-11T12:00:00Z"},
        ],
    ]
    result = repo.set_track_tags(
        user_id="u1", track_id="t1", tag_ids=["tg1", "tg2"], now=_now(),
    )
    assert [r.id for r in result] == ["tg1", "tg2"]


def test_set_track_tags_empty_clears() -> None:
    repo, data_api = _make()
    _bind_tx(data_api)
    data_api.execute.side_effect = [
        [{"x": 1}],   # category probe
        [],            # DELETE existing
        [],            # SELECT joined returns empty
    ]
    result = repo.set_track_tags(user_id="u1", track_id="t1", tag_ids=[], now=_now())
    assert result == []


def test_set_track_tags_dedupes_input() -> None:
    repo, data_api = _make()
    _bind_tx(data_api)
    data_api.execute.side_effect = [
        [{"x": 1}],          # category probe
        [{"id": "tg1"}],     # tag ownership probe — only tg1 needed
        [],                   # DELETE
        [],                   # INSERT
        [
            {"id": "tg1", "name": "Vocal", "color": "#f00",
             "created_at": "2026-05-11T12:00:00Z",
             "updated_at": "2026-05-11T12:00:00Z"},
        ],
    ]
    result = repo.set_track_tags(
        user_id="u1", track_id="t1", tag_ids=["tg1", "tg1"], now=_now(),
    )
    assert [r.id for r in result] == ["tg1"]


def test_set_track_tags_raises_when_track_not_in_category() -> None:
    repo, data_api = _make()
    _bind_tx(data_api)
    data_api.execute.side_effect = [
        [],  # category probe returns no rows
    ]
    with pytest.raises(TrackNotInAnyCategoryError):
        repo.set_track_tags(user_id="u1", track_id="t1", tag_ids=["tg1"], now=_now())


def test_set_track_tags_raises_when_foreign_tag() -> None:
    repo, data_api = _make()
    _bind_tx(data_api)
    data_api.execute.side_effect = [
        [{"x": 1}],         # category probe ok
        [{"id": "tg1"}],    # only one of two requested tag_ids is owned
    ]
    with pytest.raises(TagNotFoundError):
        repo.set_track_tags(
            user_id="u1", track_id="t1", tag_ids=["tg1", "tg2"], now=_now(),
        )


def test_add_track_tag_idempotent() -> None:
    repo, data_api = _make()
    _bind_tx(data_api)
    data_api.execute.side_effect = [
        [{"x": 1}],          # category probe
        [{"id": "tg1"}],     # tag ownership probe
        [],                   # INSERT ON CONFLICT DO NOTHING
        [
            {"id": "tg1", "name": "Vocal", "color": "#f00",
             "created_at": "2026-05-11T12:00:00Z",
             "updated_at": "2026-05-11T12:00:00Z"},
        ],
    ]
    out = repo.add_track_tag(user_id="u1", track_id="t1", tag_id="tg1", now=_now())
    assert [r.id for r in out] == ["tg1"]


def test_add_track_tag_raises_when_track_not_in_category() -> None:
    repo, data_api = _make()
    _bind_tx(data_api)
    data_api.execute.side_effect = [[]]  # category probe empty
    with pytest.raises(TrackNotInAnyCategoryError):
        repo.add_track_tag(user_id="u1", track_id="t1", tag_id="tg1", now=_now())


def test_add_track_tag_raises_when_foreign_tag() -> None:
    repo, data_api = _make()
    _bind_tx(data_api)
    data_api.execute.side_effect = [
        [{"x": 1}],   # category probe ok
        [],            # tag ownership probe — empty (not owned)
    ]
    with pytest.raises(TagNotFoundError):
        repo.add_track_tag(user_id="u1", track_id="t1", tag_id="tg1", now=_now())


def test_remove_track_tag_returns_true_on_delete() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [{"tag_id": "tg1"}]
    assert repo.remove_track_tag(user_id="u1", track_id="t1", tag_id="tg1") is True


def test_remove_track_tag_returns_false_when_no_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = []
    assert repo.remove_track_tag(user_id="u1", track_id="t1", tag_id="tg1") is False


def test_list_tags_for_tracks_groups_by_track() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {"track_id": "t1", "id": "tg1", "name": "Vocal", "color": "#f00"},
        {"track_id": "t1", "id": "tg2", "name": "Dark",  "color": "#000"},
        {"track_id": "t2", "id": "tg1", "name": "Vocal", "color": "#f00"},
    ]
    grouped = repo.list_tags_for_tracks(user_id="u1", track_ids=["t1", "t2"])
    assert [r.tag_id for r in grouped["t1"]] == ["tg1", "tg2"]
    assert [r.tag_id for r in grouped["t2"]] == ["tg1"]


def test_list_tags_for_tracks_empty_input_short_circuits() -> None:
    repo, data_api = _make()
    grouped = repo.list_tags_for_tracks(user_id="u1", track_ids=[])
    assert grouped == {}
    data_api.execute.assert_not_called()


def test_cleanup_orphaned_track_tags_deletes_when_no_categories() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [{"track_id": "t1"}, {"track_id": "t1"}]
    n = repo.cleanup_orphaned_track_tags(
        user_id="u1", track_ids=["t1"], transaction_id="tx-1",
    )
    assert n == 2
    sql = data_api.execute.call_args.args[0]
    assert "NOT EXISTS" in sql


def test_cleanup_orphaned_track_tags_empty_short_circuits() -> None:
    repo, data_api = _make()
    n = repo.cleanup_orphaned_track_tags(
        user_id="u1", track_ids=[], transaction_id="tx-1",
    )
    assert n == 0
    data_api.execute.assert_not_called()


def test_create_tag_accepts_null_color() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {
            "id": "tg1",
            "name": "Vocal",
            "color": None,
            "created_at": "2026-05-11T12:00:00Z",
            "updated_at": "2026-05-11T12:00:00Z",
        }
    ]
    row = repo.create_tag(
        user_id="u1",
        tag_id="tg1",
        name="Vocal",
        normalized_name="vocal",
        color=None,
        now=_now(),
    )
    assert row.color is None
    params = data_api.execute.call_args.args[1]
    assert params["color"] is None


def test_rename_tag_accepts_null_color_explicitly() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {"id": "tg1", "name": "Vocal", "color": None,
         "created_at": "2026-05-11T12:00:00Z",
         "updated_at": "2026-05-11T12:01:00Z"}
    ]
    row = repo.rename_tag(
        user_id="u1",
        tag_id="tg1",
        name=None,
        normalized_name=None,
        color=None,
        now=_now(),
    )
    assert row.color is None
