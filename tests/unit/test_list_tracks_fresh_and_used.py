"""Tests for fresh=true + used_in_playlist projection in list_tracks."""
from __future__ import annotations
from collector.curation.categories_repository import CategoriesRepository
from collector.curation.tags_repository import TagsRepository


class _FakeDataAPI:
    """Stub DataAPIClient that records every SQL invocation."""

    def __init__(self, scripted: list[list[dict]]) -> None:
        self._scripted = list(scripted)
        self.calls: list[tuple[str, dict]] = []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, dict(params or {})))
        return self._scripted.pop(0)


def _category_exists() -> list[dict]:
    return [{"id": "cat-1"}]


def _row(track_id: str, used: bool) -> dict:
    return {
        "id": track_id, "title": "T", "mix_name": None, "isrc": None,
        "bpm": 120, "length_ms": 200000, "publish_date": None,
        "spotify_id": "sp1", "release_type": None, "is_ai_suspected": False,
        "spotify_release_date": "2024-01-01",
        "artists_json": "[]", "label_id": None, "label_name": None,
        "added_at": "2024-01-02T00:00:00Z", "source_triage_block_id": None,
        "used_in_playlist": used,
    }


def test_list_tracks_projects_used_in_playlist():
    api = _FakeDataAPI([_category_exists(), [_row("t1", True), _row("t2", False)], [{"total": 2}]])
    repo = CategoriesRepository(api)
    result = repo.list_tracks(
        user_id="u-1", category_id="cat-1", limit=50, offset=0,
        search=None, sort="added_at", order="desc",
        tag_ids=None, tag_match="all", tags_repo=None,
    )
    select_sql = api.calls[1][0]
    assert "used_in_playlist" in select_sql
    track_used = [r.track["used_in_playlist"] for r in result.items]
    assert track_used == [True, False]


def test_list_tracks_fresh_true_adds_not_exists_clause():
    api = _FakeDataAPI([_category_exists(), [], [{"total": 0}]])
    repo = CategoriesRepository(api)
    repo.list_tracks(
        user_id="u-1", category_id="cat-1", limit=50, offset=0,
        search=None, sort="added_at", order="desc",
        tag_ids=None, tag_match="all", tags_repo=None,
        fresh=True,
    )
    rows_sql = api.calls[1][0]
    count_sql = api.calls[2][0]
    assert "NOT EXISTS" in rows_sql
    assert "NOT EXISTS" in count_sql
    assert ":user_id" in rows_sql
    assert api.calls[1][1].get("user_id") == "u-1"
    assert api.calls[2][1].get("user_id") == "u-1"


def test_list_tracks_fresh_false_default_no_filter():
    api = _FakeDataAPI([_category_exists(), [], [{"total": 0}]])
    repo = CategoriesRepository(api)
    repo.list_tracks(
        user_id="u-1", category_id="cat-1", limit=50, offset=0,
        search=None, sort="added_at", order="desc",
        tag_ids=None, tag_match="all", tags_repo=None,
    )
    rows_sql = api.calls[1][0]
    count_sql = api.calls[2][0]
    assert "NOT EXISTS" not in rows_sql
    assert "NOT EXISTS" not in count_sql


def test_list_tracks_fresh_combines_with_search_and_tags():
    api = _FakeDataAPI([_category_exists(), [], [{"total": 0}]])
    repo = CategoriesRepository(api)
    repo.list_tracks(
        user_id="u-1", category_id="cat-1", limit=50, offset=0,
        search="house", sort="title", order="asc",
        tag_ids=["tag-a"], tag_match="any", tags_repo=None,
        fresh=True,
    )
    rows_sql = api.calls[1][0]
    params = api.calls[1][1]
    assert "NOT EXISTS" in rows_sql
    assert "ILIKE" in rows_sql or "ilike" in rows_sql.lower()
    assert params["user_id"] == "u-1"
    assert params["search"] == "%house%"
    assert params["tag0"] == "tag-a"
