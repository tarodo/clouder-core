# Spotify Coverage Stats + Not-Found Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show per-week Spotify found/not-found counts in the admin coverage-matrix tooltip, and let admins re-run the Spotify search for not-found tracks in a Beatport release-date range.

**Architecture:** Additive extension of `GET /admin/coverage` (one new aggregate query keyed by Saturday week of `clouder_tracks.publish_date`), plus one new admin route `POST /admin/spotify/retry-not-found` that resets `spotify_searched_at` and re-uses the existing `spotify_search` SQS worker untouched. Frontend: multi-line tooltip in `CoverageMatrix`, date-range filter + retry button on the Spotify not-found page.

**Tech Stack:** Python 3.12 Lambda (RDS Data API, no psycopg), pytest, Terraform (API Gateway v2), React 19 + Mantine 9 + TanStack Query, vitest + msw.

**Spec:** `docs/superpowers/specs/2026-07-13-spotify-coverage-retry-design.md`

## Global Constraints

- Runtime DB access is the RDS Data API only — never import `psycopg` from `src/collector/`.
- `PYTHONPATH=src` for scripts outside pytest; use `.venv/bin/python` (macOS has no `python`).
- Backend tests: `pytest -q` from the repo root. In a worktree, call pytest by absolute main-repo path.
- Commit subjects must match Conventional Commits (`feat|fix|chore|docs|refactor|test|perf: ...`); no `Co-Authored-By`/AI trailers (a hook blocks them). Multi-line bodies need the heredoc form; single `-m "subject"` is fine.
- `docs/api/openapi.yaml` is generated — never hand-edit; regenerate via `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`, then `cd frontend && pnpm api:types` (CI diff-checks `frontend/src/api/schema.d.ts`).
- Saturday-week convention (ADR-0003): week 1 starts on the first Saturday on or after Jan 1; helpers in `src/collector/saturday_week.py`.
- New structlog field names must be added to `ALLOWED_LOG_FIELDS` in `src/collector/logging_utils.py` or they are silently dropped.
- Frontend gates before merge: `cd frontend && pnpm typecheck && pnpm lint && pnpm test`.
- `DataAPIClient.execute()` returns only result rows (no `numberOfRecordsUpdated`) — affected-row counts must use `RETURNING id` + `len(rows)`.

---

### Task 1: Repository — `spotify_stats_for_year`

**Files:**
- Modify: `src/collector/repositories.py` (add method near `coverage_for_year`, ~line 1070; extend imports)
- Test: `tests/unit/test_repositories_spotify_stats.py` (create)

**Interfaces:**
- Consumes: `saturday_week.first_saturday(year)`, `saturday_week.weeks_in_year(year)`; `self._data_api.execute(sql, params)`.
- Produces: `ClouderRepository.spotify_stats_for_year(week_year: int) -> list[dict[str, Any]]` returning rows with keys `beatport_style_id` (str), `week_number` (int), `total`, `found`, `not_found`, `pending`, `no_isrc` (ints). Task 2 consumes this.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_repositories_spotify_stats.py`:

```python
"""Tests for the per-week Spotify stats aggregate."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from collector.repositories import ClouderRepository


def test_spotify_stats_for_year_sql_and_bounds() -> None:
    fake_data_api = MagicMock()
    fake_data_api.execute.return_value = [
        {
            "beatport_style_id": "90",
            "week_number": 27,
            "total": 50,
            "found": 45,
            "not_found": 3,
            "pending": 1,
            "no_isrc": 1,
        }
    ]
    repo = ClouderRepository(data_api=fake_data_api)

    rows = repo.spotify_stats_for_year(2026)

    assert rows == fake_data_api.execute.return_value
    sql, params = fake_data_api.execute.call_args[0]
    # 2026-01-01 is a Thursday -> first Saturday is Jan 3; 52 weeks end 2027-01-01.
    assert params == {
        "year_start": date(2026, 1, 3),
        "year_end": date(2027, 1, 1),
    }
    assert "(t.publish_date - :year_start) / 7 + 1" in sql
    assert "FILTER (WHERE t.spotify_id IS NOT NULL)" in sql
    assert "im.source = 'beatport'" in sql
    assert "t.publish_date BETWEEN :year_start AND :year_end" in sql
    assert "GROUP BY 1, 2" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_repositories_spotify_stats.py -v`
Expected: FAIL with `AttributeError: 'ClouderRepository' object has no attribute 'spotify_stats_for_year'`

- [ ] **Step 3: Write minimal implementation**

In `src/collector/repositories.py`:

1. Extend the datetime import (top of file) to include `timedelta` if not present:

```python
from datetime import date, datetime, timedelta, timezone
```

2. Add next to the existing `from .saturday_week import ...` import if one exists, otherwise add:

```python
from .saturday_week import first_saturday, weeks_in_year
```

3. Add the method right after `coverage_for_year` (~line 1116):

```python
    def spotify_stats_for_year(self, week_year: int) -> list[dict[str, Any]]:
        """Per (beatport style, Saturday week of publish_date) Spotify-match
        counts for one Saturday-year. The four buckets are mutually exclusive
        and sum to total."""
        year_start = first_saturday(week_year)
        year_end = year_start + timedelta(days=weeks_in_year(week_year) * 7 - 1)
        return self._data_api.execute(
            """
            SELECT
                im.external_id                         AS beatport_style_id,
                (t.publish_date - :year_start) / 7 + 1 AS week_number,
                COUNT(*)                               AS total,
                COUNT(*) FILTER (WHERE t.spotify_id IS NOT NULL) AS found,
                COUNT(*) FILTER (WHERE t.spotify_id IS NULL
                                   AND t.spotify_searched_at IS NOT NULL)
                                                       AS not_found,
                COUNT(*) FILTER (WHERE t.isrc IS NOT NULL
                                   AND t.spotify_searched_at IS NULL)
                                                       AS pending,
                COUNT(*) FILTER (WHERE t.isrc IS NULL) AS no_isrc
            FROM clouder_tracks t
            JOIN clouder_styles cs ON cs.id = t.style_id
            JOIN identity_map im
              ON im.source = 'beatport'
              AND im.entity_type = 'style'
              AND im.clouder_entity_type = 'style'
              AND im.clouder_id = cs.id
            WHERE t.publish_date BETWEEN :year_start AND :year_end
            GROUP BY 1, 2
            """,
            {"year_start": year_start, "year_end": year_end},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_repositories_spotify_stats.py -v`
Expected: PASS

- [ ] **Step 5: Run the whole unit suite to catch regressions**

Run: `pytest tests/unit -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/collector/repositories.py tests/unit/test_repositories_spotify_stats.py
git commit -m "feat(admin): add per-week spotify stats aggregate query"
```

---

### Task 2: Coverage handler merges `spotify_weeks`

**Files:**
- Modify: `src/collector/handler.py` (`_handle_admin_coverage`, lines 559–621)
- Test: `tests/integration/test_admin_coverage_endpoint.py` (extend; also update the existing `FakeRepo`)

**Interfaces:**
- Consumes: `repository.spotify_stats_for_year(week_year)` from Task 1.
- Produces: `GET /admin/coverage` response — each entry of `styles` gains `"spotify_weeks": [{"week_number": int, "total": int, "found": int, "not_found": int, "pending": int, "no_isrc": int}, ...]` (empty list when the style has no tracks that year). Task 7 consumes this shape.

- [ ] **Step 1: Update the existing FakeRepo so current tests keep passing**

In `tests/integration/test_admin_coverage_endpoint.py`, every `FakeRepo` class used by `test_coverage_returns_grouped_styles` (and any other test that monkeypatches `create_clouder_repository_from_env`) must grow:

```python
        def spotify_stats_for_year(self, week_year):
            return []
```

- [ ] **Step 2: Write the failing test**

Append to `tests/integration/test_admin_coverage_endpoint.py`:

```python
def test_coverage_merges_spotify_weeks(monkeypatch):
    coverage_rows = [
        {
            "clouder_style_id": "uuid-s1",
            "style_name": "Tech House",
            "beatport_style_id": "90",
            "run_id": "r1",
            "week_number": 1,
            "status": "completed",
            "item_count": 147,
            "is_custom_range": False,
            "period_start": "2026-01-03",
            "period_end": "2026-01-09",
            "started_at": "2026-01-04T09:12:00Z",
            "finished_at": "2026-01-04T09:14:00Z",
        },
        {
            "clouder_style_id": "uuid-s2",
            "style_name": "Melodic",
            "beatport_style_id": "131",
            "run_id": None,
            "week_number": None,
            "status": None,
            "item_count": None,
            "is_custom_range": None,
            "period_start": None,
            "period_end": None,
            "started_at": None,
            "finished_at": None,
        },
    ]
    stats_rows = [
        {
            "beatport_style_id": "90",
            "week_number": 1,
            "total": 50,
            "found": 45,
            "not_found": 3,
            "pending": 1,
            "no_isrc": 1,
        },
        {
            "beatport_style_id": "90",
            "week_number": 2,
            "total": 10,
            "found": 10,
            "not_found": 0,
            "pending": 0,
            "no_isrc": 0,
        },
    ]

    class FakeRepo:
        def coverage_for_year(self, week_year):
            return coverage_rows

        def spotify_stats_for_year(self, week_year):
            assert week_year == 2026
            return stats_rows

    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: FakeRepo()
    )
    response = handler.lambda_handler(_event({"week_year": "2026"}), _ctx())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    by_id = {s["style_id"]: s for s in body["styles"]}
    assert by_id[90]["spotify_weeks"] == [
        {"week_number": 1, "total": 50, "found": 45, "not_found": 3,
         "pending": 1, "no_isrc": 1},
        {"week_number": 2, "total": 10, "found": 10, "not_found": 0,
         "pending": 0, "no_isrc": 0},
    ]
    assert by_id[131]["spotify_weeks"] == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/integration/test_admin_coverage_endpoint.py -v`
Expected: the new test FAILS with `KeyError: 'spotify_weeks'`; the pre-existing tests PASS (thanks to Step 1).

- [ ] **Step 4: Implement the merge**

In `src/collector/handler.py`, inside `_handle_admin_coverage`, after the `grouped` loop finishes (after line 610, before `return _json_response(...)`), add:

```python
    stats_rows = repository.spotify_stats_for_year(week_year)
    spotify_by_style: dict[int, list[dict[str, Any]]] = {}
    for row in stats_rows:
        try:
            sid = int(row.get("beatport_style_id"))
        except (TypeError, ValueError):
            continue
        spotify_by_style.setdefault(sid, []).append(
            {
                "week_number": int(row["week_number"]),
                "total": int(row["total"]),
                "found": int(row["found"]),
                "not_found": int(row["not_found"]),
                "pending": int(row["pending"]),
                "no_isrc": int(row["no_isrc"]),
            }
        )
    for sid, style_entry in grouped.items():
        style_entry["spotify_weeks"] = sorted(
            spotify_by_style.get(sid, []), key=lambda w: w["week_number"]
        )
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/integration/test_admin_coverage_endpoint.py -q && pytest tests/unit -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/collector/handler.py tests/integration/test_admin_coverage_endpoint.py
git commit -m "feat(admin): include spotify_weeks in coverage response"
```

---

### Task 3: Repository — retry reset, pending count, date filters on not-found list

**Files:**
- Modify: `src/collector/repositories.py` (extend `find_tracks_not_found_on_spotify` ~line 757 and `count_tracks_not_found_on_spotify` ~line 783; add two methods after them)
- Test: `tests/unit/test_repositories_spotify_retry.py` (create)

**Interfaces:**
- Produces (Tasks 4–5 consume):
  - `find_tracks_not_found_on_spotify(limit: int, offset: int, search: str | None = None, publish_date_from: date | None = None, publish_date_to: date | None = None) -> list[dict]`
  - `count_tracks_not_found_on_spotify(search: str | None = None, publish_date_from: date | None = None, publish_date_to: date | None = None) -> int`
  - `reset_spotify_not_found(publish_date_from: date, publish_date_to: date, now: datetime) -> int` (affected rows)
  - `count_spotify_pending_in_range(publish_date_from: date, publish_date_to: date) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_repositories_spotify_retry.py`:

```python
"""Tests for Spotify not-found retry repository methods."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from collector.repositories import ClouderRepository


def _repo(rows):
    fake = MagicMock()
    fake.execute.return_value = rows
    return ClouderRepository(data_api=fake), fake


def test_reset_spotify_not_found_counts_returned_rows() -> None:
    repo, fake = _repo([{"id": "t1"}, {"id": "t2"}])
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)

    count = repo.reset_spotify_not_found(date(2026, 6, 1), date(2026, 6, 30), now)

    assert count == 2
    sql, params = fake.execute.call_args[0]
    assert "SET spotify_searched_at = NULL" in sql
    assert "updated_at = :now" in sql
    assert "isrc IS NOT NULL" in sql
    assert "spotify_id IS NULL" in sql
    assert "spotify_searched_at IS NOT NULL" in sql
    assert "publish_date BETWEEN :date_from AND :date_to" in sql
    assert "RETURNING id" in sql
    assert params == {
        "now": now,
        "date_from": date(2026, 6, 1),
        "date_to": date(2026, 6, 30),
    }


def test_count_spotify_pending_in_range() -> None:
    repo, fake = _repo([{"cnt": 7}])

    count = repo.count_spotify_pending_in_range(date(2026, 6, 1), date(2026, 6, 30))

    assert count == 7
    sql, params = fake.execute.call_args[0]
    assert "spotify_searched_at IS NULL" in sql
    assert "isrc IS NOT NULL" in sql
    assert "publish_date BETWEEN :date_from AND :date_to" in sql
    assert params == {"date_from": date(2026, 6, 1), "date_to": date(2026, 6, 30)}


def test_find_not_found_applies_date_filters() -> None:
    repo, fake = _repo([])

    repo.find_tracks_not_found_on_spotify(
        limit=50,
        offset=0,
        search=None,
        publish_date_from=date(2026, 6, 1),
        publish_date_to=date(2026, 6, 30),
    )

    sql, params = fake.execute.call_args[0]
    assert "t.publish_date >= :date_from" in sql
    assert "t.publish_date <= :date_to" in sql
    assert params["date_from"] == date(2026, 6, 1)
    assert params["date_to"] == date(2026, 6, 30)


def test_find_not_found_without_dates_keeps_old_sql() -> None:
    repo, fake = _repo([])

    repo.find_tracks_not_found_on_spotify(limit=50, offset=0)

    sql, params = fake.execute.call_args[0]
    assert ":date_from" not in sql
    assert ":date_to" not in sql
    assert params == {"limit": 50, "offset": 0}


def test_count_not_found_applies_date_filters() -> None:
    repo, fake = _repo([{"cnt": 3}])

    count = repo.count_tracks_not_found_on_spotify(
        search=None,
        publish_date_from=date(2026, 6, 1),
        publish_date_to=date(2026, 6, 30),
    )

    assert count == 3
    sql, params = fake.execute.call_args[0]
    assert "publish_date >= :date_from" in sql
    assert "publish_date <= :date_to" in sql
    assert params == {"date_from": date(2026, 6, 1), "date_to": date(2026, 6, 30)}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_repositories_spotify_retry.py -v`
Expected: FAIL (`AttributeError` for the new methods, `TypeError: unexpected keyword argument` for the extended ones)

- [ ] **Step 3: Implement**

In `src/collector/repositories.py` replace `find_tracks_not_found_on_spotify` and `count_tracks_not_found_on_spotify` with:

```python
    def find_tracks_not_found_on_spotify(
        self,
        limit: int,
        offset: int,
        search: str | None = None,
        publish_date_from: date | None = None,
        publish_date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where_extra = ""
        if search:
            where_extra += "AND t.normalized_title LIKE :search\n"
            params["search"] = f"%{search.lower()}%"
        if publish_date_from is not None:
            where_extra += "AND t.publish_date >= :date_from\n"
            params["date_from"] = publish_date_from
        if publish_date_to is not None:
            where_extra += "AND t.publish_date <= :date_to\n"
            params["date_to"] = publish_date_to
        return self._data_api.execute(
            f"""
            SELECT t.id, t.title, t.isrc, t.bpm, t.publish_date,
                   string_agg(DISTINCT a.name, ', ' ORDER BY a.name) AS artist_names
            FROM clouder_tracks t
            LEFT JOIN clouder_track_artists ta ON ta.track_id = t.id
            LEFT JOIN clouder_artists a ON ta.artist_id = a.id
            WHERE t.isrc IS NOT NULL
              AND t.spotify_searched_at IS NOT NULL
              AND t.spotify_id IS NULL
              {where_extra}
            GROUP BY t.id
            ORDER BY t.publish_date DESC NULLS LAST
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_tracks_not_found_on_spotify(
        self,
        search: str | None = None,
        publish_date_from: date | None = None,
        publish_date_to: date | None = None,
    ) -> int:
        params: dict[str, Any] = {}
        where_extra = ""
        if search:
            where_extra += "AND normalized_title LIKE :search\n"
            params["search"] = f"%{search.lower()}%"
        if publish_date_from is not None:
            where_extra += "AND publish_date >= :date_from\n"
            params["date_from"] = publish_date_from
        if publish_date_to is not None:
            where_extra += "AND publish_date <= :date_to\n"
            params["date_to"] = publish_date_to
        rows = self._data_api.execute(
            f"""
            SELECT count(*) AS cnt
            FROM clouder_tracks
            WHERE isrc IS NOT NULL
              AND spotify_searched_at IS NOT NULL
              AND spotify_id IS NULL
              {where_extra}
            """,
            params,
        )
        return int(rows[0]["cnt"]) if rows else 0
```

Then add the two new methods right after `count_tracks_not_found_on_spotify`:

```python
    def reset_spotify_not_found(
        self,
        publish_date_from: date,
        publish_date_to: date,
        now: datetime,
    ) -> int:
        """Clear spotify_searched_at for not-found tracks in the publish-date
        range so the existing search worker picks them up again. Returns the
        number of tracks reset (via RETURNING — the Data API wrapper exposes
        rows, not numberOfRecordsUpdated)."""
        rows = self._data_api.execute(
            """
            UPDATE clouder_tracks
            SET spotify_searched_at = NULL,
                updated_at = :now
            WHERE isrc IS NOT NULL
              AND spotify_id IS NULL
              AND spotify_searched_at IS NOT NULL
              AND publish_date BETWEEN :date_from AND :date_to
            RETURNING id
            """,
            {
                "now": now,
                "date_from": publish_date_from,
                "date_to": publish_date_to,
            },
        )
        return len(rows)

    def count_spotify_pending_in_range(
        self,
        publish_date_from: date,
        publish_date_to: date,
    ) -> int:
        rows = self._data_api.execute(
            """
            SELECT count(*) AS cnt
            FROM clouder_tracks
            WHERE isrc IS NOT NULL
              AND spotify_searched_at IS NULL
              AND publish_date BETWEEN :date_from AND :date_to
            """,
            {"date_from": publish_date_from, "date_to": publish_date_to},
        )
        return int(rows[0]["cnt"]) if rows else 0
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_repositories_spotify_retry.py tests/unit/test_repositories_spotify.py -v`
Expected: all pass (old tests unaffected — new kwargs default to `None`)

- [ ] **Step 5: Commit**

```bash
git add src/collector/repositories.py tests/unit/test_repositories_spotify_retry.py
git commit -m "feat(admin): repo methods for spotify retry + date filters"
```

---

### Task 4: `GET /tracks/spotify-not-found` — publish-date query params

**Files:**
- Modify: `src/collector/handler.py` (`_handle_spotify_not_found` ~line 806; add `_parse_date_param` helper near `_parse_pagination_params` ~line 867)
- Test: `tests/integration/test_spotify_not_found_endpoint.py` (create)

**Interfaces:**
- Consumes: Task 3 repo signatures.
- Produces: `GET /tracks/spotify-not-found?publish_date_from=YYYY-MM-DD&publish_date_to=YYYY-MM-DD` — both optional, each independently applied; 400 `validation_error` on malformed date or `from > to`. Task 8 consumes.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_spotify_not_found_endpoint.py`:

```python
"""Integration tests for GET /tracks/spotify-not-found date filters."""

from __future__ import annotations

import json
from datetime import date

import pytest

from collector import handler
from collector.settings import reset_settings_cache
from collector.providers import registry


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    yield
    reset_settings_cache()
    registry.reset_cache()


def _event(qs: dict[str, str] | None, *, is_admin: bool = True):
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "GET /tracks/spotify-not-found",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/tracks/spotify-not-found",
        "queryStringParameters": qs,
        "headers": {"x-correlation-id": "c"},
        "body": None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


class FakeRepo:
    def __init__(self):
        self.find_kwargs = None
        self.count_kwargs = None

    def find_tracks_not_found_on_spotify(self, limit, offset, search=None,
                                         publish_date_from=None,
                                         publish_date_to=None):
        self.find_kwargs = {
            "limit": limit, "offset": offset, "search": search,
            "publish_date_from": publish_date_from,
            "publish_date_to": publish_date_to,
        }
        return []

    def count_tracks_not_found_on_spotify(self, search=None,
                                          publish_date_from=None,
                                          publish_date_to=None):
        self.count_kwargs = {
            "search": search,
            "publish_date_from": publish_date_from,
            "publish_date_to": publish_date_to,
        }
        return 0


def _install(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: repo
    )
    return repo


def test_not_found_passes_date_range(monkeypatch):
    repo = _install(monkeypatch)
    response = handler.lambda_handler(
        _event({"publish_date_from": "2026-06-01",
                "publish_date_to": "2026-06-30"}),
        _ctx(),
    )
    assert response["statusCode"] == 200
    assert repo.find_kwargs["publish_date_from"] == date(2026, 6, 1)
    assert repo.find_kwargs["publish_date_to"] == date(2026, 6, 30)
    assert repo.count_kwargs["publish_date_from"] == date(2026, 6, 1)


def test_not_found_without_dates_passes_none(monkeypatch):
    repo = _install(monkeypatch)
    response = handler.lambda_handler(_event(None), _ctx())
    assert response["statusCode"] == 200
    assert repo.find_kwargs["publish_date_from"] is None
    assert repo.find_kwargs["publish_date_to"] is None


def test_not_found_bad_date_400(monkeypatch):
    _install(monkeypatch)
    response = handler.lambda_handler(
        _event({"publish_date_from": "06/01/2026"}), _ctx()
    )
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error_code"] == "validation_error"


def test_not_found_from_after_to_400(monkeypatch):
    _install(monkeypatch)
    response = handler.lambda_handler(
        _event({"publish_date_from": "2026-07-01",
                "publish_date_to": "2026-06-01"}),
        _ctx(),
    )
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error_code"] == "validation_error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_spotify_not_found_endpoint.py -v`
Expected: the two date tests FAIL (dates ignored / no 400); the no-dates test may already pass.

- [ ] **Step 3: Implement**

In `src/collector/handler.py`:

1. Ensure `date` is imported at the top (`from datetime import date` — check existing imports first and extend, don't duplicate).

2. Add a helper next to `_parse_pagination_params`:

```python
def _parse_date_param(event: Mapping[str, Any], name: str) -> date | None:
    query_params = event.get("queryStringParameters") or {}
    raw = query_params.get(name) if isinstance(query_params, Mapping) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ValidationError(f"{name} must be an ISO date (YYYY-MM-DD)")
```

3. In `_handle_spotify_not_found`, inside the existing `try` that wraps `_parse_pagination_params` (so date errors reuse the same 400 path), extend to:

```python
    try:
        limit, offset, search = _parse_pagination_params(event)
        publish_date_from = _parse_date_param(event, "publish_date_from")
        publish_date_to = _parse_date_param(event, "publish_date_to")
        if (
            publish_date_from is not None
            and publish_date_to is not None
            and publish_date_from > publish_date_to
        ):
            raise ValidationError(
                "publish_date_from must be <= publish_date_to"
            )
    except ValidationError as exc:
        ...  # existing 400 return stays as-is
```

4. Thread the values into both repo calls:

```python
    rows = repository.find_tracks_not_found_on_spotify(
        limit,
        offset,
        search,
        publish_date_from=publish_date_from,
        publish_date_to=publish_date_to,
    )
    total = repository.count_tracks_not_found_on_spotify(
        search,
        publish_date_from=publish_date_from,
        publish_date_to=publish_date_to,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_spotify_not_found_endpoint.py -q && pytest tests/unit -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/collector/handler.py tests/integration/test_spotify_not_found_endpoint.py
git commit -m "feat(admin): date-range filter on spotify-not-found list"
```

---

### Task 5: `POST /admin/spotify/retry-not-found` endpoint

**Files:**
- Modify: `src/collector/handler.py` (`_ADMIN_ROUTES` ~line 60, `_route` dispatch ~line 167, new handler function after `_handle_spotify_not_found`)
- Modify: `src/collector/logging_utils.py` (`ALLOWED_LOG_FIELDS` — add `"reset_count"`, `"pending_count"`)
- Test: `tests/integration/test_spotify_retry_endpoint.py` (create)

**Interfaces:**
- Consumes: `reset_spotify_not_found`, `count_spotify_pending_in_range` (Task 3); `_load_api_settings()` (`ApiSettings.spotify_search_queue_url` already exists); `create_default_sqs_client()` (handler.py ~line 996); `utc_now` (already imported into handler from `.repositories` — verify, otherwise import it).
- Produces: `POST /admin/spotify/retry-not-found` with JSON body `{"publish_date_from": "YYYY-MM-DD", "publish_date_to": "YYYY-MM-DD"}` → 200 `{"queued_count": N, "correlation_id": ...}`. Errors: 400 `validation_error`, 403 `admin_required`, 500 `enqueue_failed`, 503 `db_not_configured`. Tasks 6 and 8 consume.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_spotify_retry_endpoint.py`:

```python
"""Integration tests for POST /admin/spotify/retry-not-found."""

from __future__ import annotations

import json
from datetime import date

import pytest

from collector import handler
from collector.settings import reset_settings_cache
from collector.providers import registry


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("SPOTIFY_SEARCH_QUEUE_URL", "https://sqs.test/queue")
    yield
    reset_settings_cache()
    registry.reset_cache()


def _event(body: dict | None, *, is_admin: bool = True):
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "POST /admin/spotify/retry-not-found",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/admin/spotify/retry-not-found",
        "queryStringParameters": None,
        "headers": {"x-correlation-id": "c"},
        "body": json.dumps(body) if body is not None else None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


class FakeRepo:
    def __init__(self, reset_count=2, pending_count=0):
        self._reset_count = reset_count
        self._pending_count = pending_count
        self.reset_args = None

    def reset_spotify_not_found(self, publish_date_from, publish_date_to, now):
        self.reset_args = (publish_date_from, publish_date_to)
        return self._reset_count

    def count_spotify_pending_in_range(self, publish_date_from, publish_date_to):
        return self._pending_count


class FakeSqs:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    def send_message(self, **kwargs):
        if self.fail:
            raise RuntimeError("sqs down")
        self.sent.append(kwargs)


def _install(monkeypatch, repo, sqs):
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr(
        "collector.handler.create_default_sqs_client", lambda: sqs
    )


BODY = {"publish_date_from": "2026-06-01", "publish_date_to": "2026-06-30"}


def test_retry_requires_admin(monkeypatch):
    _install(monkeypatch, FakeRepo(), FakeSqs())
    response = handler.lambda_handler(_event(BODY, is_admin=False), _ctx())
    assert response["statusCode"] == 403


def test_retry_resets_and_enqueues(monkeypatch):
    repo, sqs = FakeRepo(reset_count=2), FakeSqs()
    _install(monkeypatch, repo, sqs)
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["queued_count"] == 2
    assert repo.reset_args == (date(2026, 6, 1), date(2026, 6, 30))
    assert len(sqs.sent) == 1
    message = json.loads(sqs.sent[0]["MessageBody"])
    assert message == {"batch_size": 200, "auto_continue": True}
    assert sqs.sent[0]["QueueUrl"] == "https://sqs.test/queue"


def test_retry_zero_reset_zero_pending_skips_enqueue(monkeypatch):
    repo, sqs = FakeRepo(reset_count=0, pending_count=0), FakeSqs()
    _install(monkeypatch, repo, sqs)
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["queued_count"] == 0
    assert sqs.sent == []


def test_retry_zero_reset_with_pending_still_enqueues(monkeypatch):
    repo, sqs = FakeRepo(reset_count=0, pending_count=5), FakeSqs()
    _install(monkeypatch, repo, sqs)
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 200
    assert len(sqs.sent) == 1


def test_retry_sqs_failure_500(monkeypatch):
    _install(monkeypatch, FakeRepo(reset_count=2), FakeSqs(fail=True))
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 500
    assert json.loads(response["body"])["error_code"] == "enqueue_failed"


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"publish_date_from": "2026-06-01"},
        {"publish_date_from": "bad", "publish_date_to": "2026-06-30"},
        {"publish_date_from": "2026-07-01", "publish_date_to": "2026-06-01"},
    ],
)
def test_retry_validation_400(monkeypatch, body):
    _install(monkeypatch, FakeRepo(), FakeSqs())
    response = handler.lambda_handler(_event(body), _ctx())
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error_code"] == "validation_error"


def test_retry_db_not_configured_503(monkeypatch):
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: None
    )
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 503
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_spotify_retry_endpoint.py -v`
Expected: FAIL — unknown route returns 404/not-found shape, not the expected codes.

- [ ] **Step 3: Implement**

In `src/collector/logging_utils.py`, add to `ALLOWED_LOG_FIELDS`:

```python
    "reset_count",
    "pending_count",
```

(If `tests/unit/test_logging_utils.py` asserts the exact allowlist, update it accordingly.)

In `src/collector/handler.py`:

1. Add `"POST /admin/spotify/retry-not-found"` to `_ADMIN_ROUTES`.

2. Add the dispatch branch in `_route` after the `GET /tracks/spotify-not-found` branch:

```python
    if route_key == "POST /admin/spotify/retry-not-found":
        return _handle_spotify_retry_not_found(event)
```

3. Add after `_handle_spotify_not_found`:

```python
def _parse_iso_date_field(payload: Mapping[str, Any], name: str) -> date:
    raw = payload.get(name)
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError(f"{name} is required (YYYY-MM-DD)")
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ValidationError(f"{name} must be an ISO date (YYYY-MM-DD)")


def _handle_spotify_retry_not_found(event: Mapping[str, Any]) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)

    raw_body = event.get("body")
    if not isinstance(raw_body, str) or not raw_body.strip():
        raise ValidationError("request body is required")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise ValidationError("request body must be valid JSON")
    if not isinstance(payload, Mapping):
        raise ValidationError("request body must be a JSON object")

    publish_date_from = _parse_iso_date_field(payload, "publish_date_from")
    publish_date_to = _parse_iso_date_field(payload, "publish_date_to")
    if publish_date_from > publish_date_to:
        raise ValidationError("publish_date_from must be <= publish_date_to")

    repository = create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {
                "error_code": "db_not_configured",
                "message": "Database is not configured",
            },
            correlation_id,
        )

    now = utc_now()
    reset_count = repository.reset_spotify_not_found(
        publish_date_from, publish_date_to, now
    )
    pending_count = repository.count_spotify_pending_in_range(
        publish_date_from, publish_date_to
    )

    log_event(
        "INFO",
        "spotify_retry_requested",
        correlation_id=correlation_id,
        reset_count=reset_count,
        pending_count=pending_count,
    )

    if reset_count > 0 or pending_count > 0:
        settings = _load_api_settings()
        queue_url = settings.spotify_search_queue_url.strip()
        if not queue_url:
            return _json_response(
                500,
                {
                    "error_code": "enqueue_failed",
                    "message": "SPOTIFY_SEARCH_QUEUE_URL is not configured",
                },
                correlation_id,
            )
        message = {"batch_size": 200, "auto_continue": True}
        try:
            client = create_default_sqs_client()
            client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(
                    message, ensure_ascii=False, separators=(",", ":")
                ),
                MessageAttributes={
                    "correlation_id": {
                        "DataType": "String",
                        "StringValue": correlation_id,
                    }
                },
            )
            log_event(
                "INFO",
                "spotify_retry_enqueued",
                correlation_id=correlation_id,
                reset_count=reset_count,
            )
        except Exception as exc:
            log_event(
                "ERROR",
                "spotify_retry_enqueue_failed",
                correlation_id=correlation_id,
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:500],
            )
            return _json_response(
                500,
                {
                    "error_code": "enqueue_failed",
                    "message": (
                        "Tracks were reset but the search message could not "
                        "be enqueued; retry the request"
                    ),
                },
                correlation_id,
            )

    return _json_response(
        200,
        {"queued_count": reset_count, "correlation_id": correlation_id},
        correlation_id,
    )
```

Notes for the implementer:
- `utc_now` — check the imports from `.repositories` at the top of `handler.py`; add `utc_now` to that import list if it is not there yet.
- `ValidationError` raised from the handler propagates to `lambda_handler`'s `AppError` catch and becomes a 400 with `error_code: validation_error` — that is why the tests expect 400 without a local try/except.

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_spotify_retry_endpoint.py -v && pytest tests/unit -q && pytest tests/integration -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/collector/handler.py src/collector/logging_utils.py tests/integration/test_spotify_retry_endpoint.py
git commit -m "feat(admin): POST /admin/spotify/retry-not-found endpoint"
```

---

### Task 6: Route registration — Terraform + OpenAPI + generated types

**Files:**
- Modify: `infra/api_gateway.tf` (add route resource after `admin_runs`, ~line 119)
- Modify: `scripts/generate_openapi.py` (retry route entry; date params on the spotify-not-found entry ~line 2097; mention `spotify_weeks` in the coverage 200 description ~line 1650)
- Regenerate: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: route contract from Task 5.
- Produces: deployable API Gateway route; regenerated `openapi.yaml` + `schema.d.ts` that CI diff-checks.

- [ ] **Step 1: Add the API Gateway route**

In `infra/api_gateway.tf`, after the `admin_runs` route resource:

```hcl
resource "aws_apigatewayv2_route" "admin_spotify_retry_not_found" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /admin/spotify/retry-not-found"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 2: Validate terraform formatting**

Run: `cd infra && terraform fmt -check api_gateway.tf && terraform validate 2>/dev/null || true; cd ..`
Expected: fmt check passes (validate may need init — do not run `terraform apply`).

- [ ] **Step 3: Update `scripts/generate_openapi.py`**

1. In the `/tracks/spotify-not-found` entry (~line 2097), replace `"parameters": PAGINATION_PARAMS,` with:

```python
        "parameters": PAGINATION_PARAMS + [
            {
                "name": "publish_date_from",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "format": "date"},
            },
            {
                "name": "publish_date_to",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "format": "date"},
            },
        ],
```

2. In the `/admin/coverage` entry, change the 200 response description from `"Coverage payload."` to `"Coverage payload (per-style cells + spotify_weeks per-week match stats)."`.

3. Add a new entry right after the `/admin/coverage` entry:

```python
    {
        "method": "post",
        "path": "/admin/spotify/retry-not-found",
        "auth": ADMIN,
        "summary": "Admin: re-run Spotify search for not-found tracks in a publish-date range.",
        "description": (
            "Resets spotify_searched_at for not-found tracks (with ISRC) whose "
            "Beatport publish_date falls in the range, then enqueues a regular "
            "spotify-search message. Tracks temporarily leave the not-found "
            "list and return only if the search misses again."
        ),
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["publish_date_from", "publish_date_to"],
                "properties": {
                    "publish_date_from": {"type": "string", "format": "date"},
                    "publish_date_to": {"type": "string", "format": "date"},
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {
            "publish_date_from": "2026-06-01",
            "publish_date_to": "2026-06-30",
        },
        "responses": {
            "200": _make_response(
                200, "Tracks reset and search enqueued.", {"type": "object"}
            ),
            "400": _error(400, "validation_error."),
            "500": _error(500, "enqueue_failed."),
            "503": _error(503, "db_not_configured."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
```

(Match the exact helper names — `ADMIN`, `PAGINATION_PARAMS`, `_make_response`, `_error`, `COMMON_AUTH_ERRORS` — already used by neighboring entries in this file.)

- [ ] **Step 4: Regenerate the contract artifacts**

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
cd frontend && pnpm api:types && cd ..
git status --short docs/api/openapi.yaml frontend/src/api/schema.d.ts
```

Expected: both files modified; `openapi.yaml` gains the new path and params.

- [ ] **Step 5: Commit**

```bash
git add infra/api_gateway.tf scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts
git commit -m "feat(infra): register spotify retry route + openapi"
```

---

### Task 7: Frontend — Spotify stats line in the coverage tooltip

**Files:**
- Modify: `frontend/src/features/admin/hooks/useCoverage.ts` (extend `CoveragePayload`)
- Create: `frontend/src/features/admin/lib/spotifyStats.ts`
- Modify: `frontend/src/features/admin/components/CoverageMatrix.tsx` (Row tooltip)
- Modify: `frontend/src/features/admin/components/CoverageMatrixCell.tsx` (tooltip prop type)
- Modify: `frontend/src/test/handlers.ts` (coverage handler payload shape — `styles: []` still valid, no change needed unless styles are added; verify)
- Test: `frontend/src/features/admin/lib/__tests__/spotifyStats.test.ts` (create), `frontend/src/features/admin/components/__tests__/CoverageMatrix.test.tsx` (extend)

**Interfaces:**
- Consumes: `spotify_weeks` response field (Task 2).
- Produces: `SpotifyWeekStats` type exported from `useCoverage.ts`; `formatSpotifyStats(stats: SpotifyWeekStats): string` from `lib/spotifyStats.ts`.

Note: the existing tooltip line (`Wk 1 · … · 10 items`) is hard-coded English, not i18n — keep the new stats line consistent with that (hard-coded English, no `useTranslation` in `Row`).

- [ ] **Step 1: Write the failing unit test for the formatter**

Create `frontend/src/features/admin/lib/__tests__/spotifyStats.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { formatSpotifyStats } from '../spotifyStats';

describe('formatSpotifyStats', () => {
  it('renders found and not-found always', () => {
    expect(
      formatSpotifyStats({
        week_number: 1, total: 50, found: 45, not_found: 5,
        pending: 0, no_isrc: 0,
      }),
    ).toBe('Spotify: 45/50 found · 5 not found');
  });

  it('appends pending and no-ISRC only when non-zero', () => {
    expect(
      formatSpotifyStats({
        week_number: 1, total: 50, found: 45, not_found: 3,
        pending: 1, no_isrc: 1,
      }),
    ).toBe('Spotify: 45/50 found · 3 not found · 1 pending · 1 no ISRC');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && pnpm test src/features/admin/lib/__tests__/spotifyStats.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement types + formatter**

In `frontend/src/features/admin/hooks/useCoverage.ts`, add and wire the type:

```typescript
export interface SpotifyWeekStats {
  week_number: number;
  total: number;
  found: number;
  not_found: number;
  pending: number;
  no_isrc: number;
}
```

and inside `CoveragePayload.styles` array element, after `cells`:

```typescript
    spotify_weeks: SpotifyWeekStats[];
```

Create `frontend/src/features/admin/lib/spotifyStats.ts`:

```typescript
import type { SpotifyWeekStats } from '../hooks/useCoverage';

export function formatSpotifyStats(s: SpotifyWeekStats): string {
  const parts = [
    `Spotify: ${s.found}/${s.total} found`,
    `${s.not_found} not found`,
  ];
  if (s.pending > 0) parts.push(`${s.pending} pending`);
  if (s.no_isrc > 0) parts.push(`${s.no_isrc} no ISRC`);
  return parts.join(' · ');
}
```

- [ ] **Step 4: Run the formatter test**

Run: `cd frontend && pnpm test src/features/admin/lib/__tests__/spotifyStats.test.ts`
Expected: PASS

- [ ] **Step 5: Write the failing component test**

In `frontend/src/features/admin/components/__tests__/CoverageMatrix.test.tsx`:

1. The `sample` payload's style entry needs the new required field — add after `cells: [...]`:

```typescript
      spotify_weeks: [
        {
          week_number: 1, total: 50, found: 45, not_found: 3,
          pending: 1, no_isrc: 1,
        },
        {
          week_number: 5, total: 8, found: 8, not_found: 0,
          pending: 0, no_isrc: 0,
        },
      ],
```

2. Add tests:

```typescript
  it('shows spotify stats in the tooltip on hover', async () => {
    render(ui({ data: sample, onCellClick: vi.fn() }));
    await userEvent.hover(screen.getByLabelText('Tech House week 1 loaded'));
    expect(
      await screen.findByText(/Spotify: 45\/50 found · 3 not found · 1 pending · 1 no ISRC/),
    ).toBeInTheDocument();
  });

  it('shows spotify stats on empty cells that have tracks', async () => {
    render(ui({ data: sample, onCellClick: vi.fn() }));
    await userEvent.hover(screen.getByLabelText('Tech House week 5 empty'));
    expect(
      await screen.findByText(/Spotify: 8\/8 found · 0 not found/),
    ).toBeInTheDocument();
  });
```

- [ ] **Step 6: Run to verify failure**

Run: `cd frontend && pnpm test src/features/admin/components/__tests__/CoverageMatrix.test.tsx`
Expected: the two new tests FAIL (stats not rendered).

- [ ] **Step 7: Implement the tooltip**

In `frontend/src/features/admin/components/CoverageMatrixCell.tsx`, change the prop type:

```typescript
import type { ReactNode } from 'react';
// ...
  tooltip: ReactNode;
```

and the `disabled` guard stays `disabled={!tooltip}`.

In `frontend/src/features/admin/components/CoverageMatrix.tsx`:

1. Import the helper and type:

```typescript
import { formatSpotifyStats } from '../lib/spotifyStats';
import type { SpotifyWeekStats } from '../hooks/useCoverage';
```

2. In `CoverageMatrix`, build the stats map per style and pass to `Row` (inside `data.styles.map`):

```typescript
          const statsByWeek = new Map<number, SpotifyWeekStats>();
          for (const s of style.spotify_weeks ?? []) statsByWeek.set(s.week_number, s);
```

and add `statsByWeek={statsByWeek}` to the `<Row />` props.

3. In `Row` (add `statsByWeek: Map<number, SpotifyWeekStats>` to its props), replace the tooltip construction:

```typescript
        const baseLine = cell
          ? `Wk ${w} · ${cell.period_start} – ${cell.period_end} · ${cell.item_count} items${
              cell.is_custom_range ? ' · custom range' : ''
            }`
          : `Wk ${w} · empty`;
        const stats = statsByWeek.get(w);
        const tooltip = stats ? (
          <>
            {baseLine}
            <br />
            {formatSpotifyStats(stats)}
          </>
        ) : (
          baseLine
        );
```

- [ ] **Step 8: Run frontend tests**

Run: `cd frontend && pnpm test src/features/admin`
Expected: all pass. If other files construct `CoveragePayload` literals (e.g. `AdminCoveragePage` tests, `src/test/handlers.ts` uses `styles: []` which stays valid), fix any TypeScript errors by adding `spotify_weeks: []`.

- [ ] **Step 9: Typecheck + lint**

Run: `cd frontend && pnpm typecheck && pnpm lint`
Expected: clean

- [ ] **Step 10: Commit**

```bash
git add frontend/src/features/admin frontend/src/test/handlers.ts
git commit -m "feat(admin): spotify match stats in coverage tooltip"
```

---

### Task 8: Frontend — date-range filter + retry button on the not-found page

**Files:**
- Modify: `frontend/src/features/admin/hooks/useSpotifyNotFound.ts` (date params)
- Create: `frontend/src/features/admin/hooks/useRetrySpotifySearch.ts`
- Modify: `frontend/src/features/admin/components/SpotifyNotFoundTable.tsx`
- Modify: `frontend/src/i18n/en.json` (`admin.spotify_not_found` keys)
- Modify: `frontend/src/test/handlers.ts` (default GET/POST handlers)
- Test: `frontend/src/features/admin/components/__tests__/SpotifyNotFoundTable.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /tracks/spotify-not-found?publish_date_from=&publish_date_to=` (Task 4), `POST /admin/spotify/retry-not-found` (Task 5).
- Produces: `useRetrySpotifySearch(): UseMutationResult<RetryResponse, ApiError, RetryInput>` with `RetryInput = {publish_date_from: string; publish_date_to: string}`, `RetryResponse = {queued_count: number}`.

Implementation notes:
- `DatePickerInput` comes from `@mantine/dates` (installed; see `frontend/src/features/triage/components/CreateTriageBlockDialog.tsx` for this repo's value-type convention — Mantine 8+ range values are `[string | null, string | null]` in `YYYY-MM-DD`; copy whatever that file does).
- Confirm dialog: `modals.openConfirmModal` from `@mantine/modals` (pattern: `frontend/src/features/playlists/routes/PlaylistsListPage.tsx:92`). Tests must wrap in `ModalsProvider`.
- Toast: `notifications.show` from `@mantine/notifications` (pattern: `frontend/src/features/admin/components/enrichment/EnqueueDrawer.tsx:47`). Tests must mount `<Notifications />`.

- [ ] **Step 1: Add i18n keys**

In `frontend/src/i18n/en.json`, extend `admin.spotify_not_found` with:

```json
"date_range": "Release date range",
"retry_button": "Retry Spotify search",
"retry_title": "Retry Spotify search",
"retry_confirm": "Re-run the Spotify search for {{count}} not-found tracks in the selected release-date range? They temporarily leave this list and come back only if the search misses again.",
"retry_confirm_label": "Retry",
"retry_cancel_label": "Cancel",
"retry_queued": "Queued {{count}} tracks",
"retry_nothing": "Nothing to retry",
"retry_failed": "Retry request failed"
```

- [ ] **Step 2: Extend the list hook**

Replace `frontend/src/features/admin/hooks/useSpotifyNotFound.ts` argument handling:

```typescript
export function useSpotifyNotFound(args: {
  limit: number;
  offset: number;
  search: string;
  publishDateFrom?: string | null;
  publishDateTo?: string | null;
}) {
  const params = new URLSearchParams({
    limit: String(args.limit),
    offset: String(args.offset),
  });
  if (args.search) params.set('search', args.search);
  if (args.publishDateFrom) params.set('publish_date_from', args.publishDateFrom);
  if (args.publishDateTo) params.set('publish_date_to', args.publishDateTo);
  return useQuery({
    queryKey: [
      'admin',
      'spotifyNotFound',
      args.limit,
      args.offset,
      args.search,
      args.publishDateFrom ?? null,
      args.publishDateTo ?? null,
    ],
    queryFn: () =>
      api<{ items: SpotifyNotFoundItem[]; total: number; limit: number; offset: number }>(
        `/tracks/spotify-not-found?${params.toString()}`,
      ),
    placeholderData: keepPreviousData,
  });
}
```

- [ ] **Step 3: Create the mutation hook**

Create `frontend/src/features/admin/hooks/useRetrySpotifySearch.ts`:

```typescript
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface RetryInput {
  publish_date_from: string;
  publish_date_to: string;
}

export interface RetryResponse {
  queued_count: number;
}

export function useRetrySpotifySearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: RetryInput) =>
      api<RetryResponse>('/admin/spotify/retry-not-found', {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'spotifyNotFound'] });
      queryClient.invalidateQueries({ queryKey: ['admin', 'coverage'] });
    },
  });
}
```

- [ ] **Step 4: Write the failing component test**

Create `frontend/src/features/admin/components/__tests__/SpotifyNotFoundTable.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/server';
import { testTheme } from '../../../../test/theme';
import { SpotifyNotFoundTable } from '../SpotifyNotFoundTable';

function ui() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications />
          <SpotifyNotFoundTable />
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>
  );
}

const LIST = {
  items: [
    { track_id: 't1', title: 'Lost Groove', artists: ['DJ A'], isrc: 'ZZ1' },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

describe('SpotifyNotFoundTable retry', () => {
  it('disables the retry button until a full date range is picked', async () => {
    server.use(
      http.get('http://localhost/tracks/spotify-not-found', () =>
        HttpResponse.json(LIST),
      ),
    );
    render(ui());
    const button = await screen.findByRole('button', {
      name: 'Retry Spotify search',
    });
    expect(button).toBeDisabled();
  });

  it('confirms and posts the retry, then shows the queued toast', async () => {
    let posted: unknown = null;
    server.use(
      http.get('http://localhost/tracks/spotify-not-found', () =>
        HttpResponse.json(LIST),
      ),
      http.post(
        'http://localhost/admin/spotify/retry-not-found',
        async ({ request }) => {
          posted = await request.json();
          return HttpResponse.json({ queued_count: 3 });
        },
      ),
    );
    render(ui());
    await screen.findByText('Lost Groove');

    // Type the range into the DatePickerInput (free-form input mode).
    const rangeInput = screen.getByLabelText('Release date range');
    await userEvent.click(rangeInput);
    // Pick the 1st and the 15th of the visible month via the calendar popover:
    const [first] = await screen.findAllByText('1', { selector: 'button *' });
    await userEvent.click(first);
    const [fifteenth] = await screen.findAllByText('15', { selector: 'button *' });
    await userEvent.click(fifteenth);

    const button = screen.getByRole('button', { name: 'Retry Spotify search' });
    expect(button).toBeEnabled();
    await userEvent.click(button);

    await userEvent.click(await screen.findByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('Queued 3 tracks')).toBeInTheDocument();
    expect(posted).toMatchObject({
      publish_date_from: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      publish_date_to: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    });
  });
});
```

(If the calendar-click selectors prove brittle, drive the state through the component instead: keep the test but select dates via the same interaction `CreateTriageBlockDialog.test.tsx` uses — copy its working approach.)

- [ ] **Step 5: Run to verify failure**

Run: `cd frontend && pnpm test src/features/admin/components/__tests__/SpotifyNotFoundTable.test.tsx`
Expected: FAIL — no retry button rendered.

- [ ] **Step 6: Implement the table changes**

In `frontend/src/features/admin/components/SpotifyNotFoundTable.tsx`:

```tsx
import { Button, Group, Pagination, Skeleton, Stack, Table, Text, TextInput } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useDebouncedValue } from '@mantine/hooks';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useRetrySpotifySearch } from '../hooks/useRetrySpotifySearch';
import { useSpotifyNotFound } from '../hooks/useSpotifyNotFound';

const LIMIT = 50;

export function SpotifyNotFoundTable() {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(search, 300);
  const [page, setPage] = useState(1);
  const [dates, setDates] = useState<[string | null, string | null]>([null, null]);
  const offset = (page - 1) * LIMIT;
  const q = useSpotifyNotFound({
    limit: LIMIT,
    offset,
    search: debouncedSearch,
    publishDateFrom: dates[0],
    publishDateTo: dates[1],
  });
  const retry = useRetrySpotifySearch();

  const canRetry = Boolean(dates[0] && dates[1]);

  function confirmRetry() {
    modals.openConfirmModal({
      title: t('admin.spotify_not_found.retry_title'),
      children: (
        <Text size="sm">
          {t('admin.spotify_not_found.retry_confirm', { count: q.data?.total ?? 0 })}
        </Text>
      ),
      labels: {
        confirm: t('admin.spotify_not_found.retry_confirm_label'),
        cancel: t('admin.spotify_not_found.retry_cancel_label'),
      },
      onConfirm: () =>
        retry.mutate(
          { publish_date_from: dates[0]!, publish_date_to: dates[1]! },
          {
            onSuccess: (data) => {
              notifications.show({
                message:
                  data.queued_count > 0
                    ? t('admin.spotify_not_found.retry_queued', {
                        count: data.queued_count,
                      })
                    : t('admin.spotify_not_found.retry_nothing'),
              });
            },
            onError: () => {
              notifications.show({
                color: 'red',
                message: t('admin.spotify_not_found.retry_failed'),
              });
            },
          },
        ),
    });
  }

  if (q.isLoading) return <Skeleton h={400} />;
  if (q.isError) return <Text c="red">{t('admin.spotify_not_found.load_failed')}</Text>;
  if (!q.data) return null;

  const totalPages = Math.max(1, Math.ceil(q.data.total / LIMIT));

  return (
    <Stack>
      <TextInput
        placeholder={t('admin.spotify_not_found.search')}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
      />
      <Group align="end">
        <DatePickerInput
          type="range"
          allowSingleDateInRange
          clearable
          label={t('admin.spotify_not_found.date_range')}
          value={dates}
          onChange={(value) => {
            setDates(value);
            setPage(1);
          }}
        />
        <Button onClick={confirmRetry} disabled={!canRetry} loading={retry.isPending}>
          {t('admin.spotify_not_found.retry_button')}
        </Button>
      </Group>
      <Text size="sm" c="dimmed">
        {t('admin.spotify_not_found.total_label', { count: q.data.total })}
      </Text>
      {/* existing Table + Pagination markup unchanged */}
    </Stack>
  );
}
```

Keep the existing `<Table>` and `<Pagination>` blocks exactly as they are today. If this Mantine version types `DatePickerInput type="range"` values as `[Date | null, Date | null]` instead of strings (check `CreateTriageBlockDialog.tsx`), store `Date` state and convert with a local `const toIso = (d: Date) => d.toISOString().slice(0, 10);` when calling the hook and mutation.

- [ ] **Step 7: Add default msw handlers**

In `frontend/src/test/handlers.ts` add to the `handlers` array (keeps unrelated tests from hitting unhandled requests):

```typescript
  http.get('http://localhost/tracks/spotify-not-found', () =>
    HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
  ),
  http.post('http://localhost/admin/spotify/retry-not-found', () =>
    HttpResponse.json({ queued_count: 0 }),
  ),
```

- [ ] **Step 8: Run the new tests, then the full frontend gate**

Run: `cd frontend && pnpm test src/features/admin/components/__tests__/SpotifyNotFoundTable.test.tsx`
Expected: PASS

Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm test`
Expected: all clean (this is the CI gate).

- [ ] **Step 9: Commit**

```bash
git add frontend/src
git commit -m "feat(admin): retry spotify search for not-found tracks"
```

---

### Task 9: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite**

Run: `pytest -q`
Expected: all pass

- [ ] **Step 2: Contract freshness**

Run: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py && cd frontend && pnpm api:types && cd .. && git status --short`
Expected: no unstaged changes to `docs/api/openapi.yaml` or `frontend/src/api/schema.d.ts` (already regenerated in Task 6).

- [ ] **Step 3: Frontend gate**

Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm test`
Expected: all clean

- [ ] **Step 4: Deploy checklist (manual, when merging)**

- `scripts/package_lambda.sh` then `cd infra && terraform apply` (new route only; the shared `collector_lambda` role already has `sqs:SendMessage` on the `spotify_search` queue — verified in `infra/iam.tf` `AllowSQSSend`).
- Frontend deploys through the normal pipeline.
