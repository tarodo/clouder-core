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
