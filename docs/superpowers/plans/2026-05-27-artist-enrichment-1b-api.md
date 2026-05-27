# Artist Enrichment 1B — API Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the full artist-enrichment HTTP API at parity with labels — admin manual enrich + runs/backlog/history, user-facing `/artists` list + detail, user preferences, and auto-enrich config — wired into the collector Lambda dispatch + OpenAPI + API Gateway.

**Architecture:** Extend the `src/collector/artist_enrichment/` package (built in plan 1A) with the read/list/preference repository methods, the auto-enrich repository (config + claim + state + all-roles resolution), the HTTP route handlers (`routes.py`, `auto_routes.py`) and their request models (`messages.py`/`auto_messages.py`), then register the routes in `collector/handler.py` dispatch, `scripts/generate_openapi.py`, and `infra/api_gateway.tf`. Mirror the proven label handlers; the genuinely different code is the artist many-to-many SQL (track/style counts + `artist_ids_for_track` over `clouder_track_artists`, all roles) and the artist denormalized columns.

**Tech Stack:** Python 3.12, pydantic v2, Aurora RDS Data API, pytest. No live API calls in tests.

**Spec:** `docs/superpowers/specs/2026-05-27-artist-enrichment-backend-design.md` (sub-project 1). This is **plan 1B of 3** (1A core ✅ → 1B API → 1C infra+auto). 1A built the migration, schema/prompt/aggregator, repository write-path, orchestrator, and the SQS worker handler. 1B adds the HTTP surface. 1C adds infra (SQS/worker Lambda/env) + the auto-dispatch trigger wiring into curation.

**Conventions (same as 1A):**
- `<repo>` = `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/improve_artist_search`; `<main-repo>` = `/Users/roman/Projects/clouder-projects/clouder-core`. Test binary `<main-repo>/.venv/bin/pytest`; run from `<repo>` with `PYTHONPATH=src`.
- Each task: failing test → impl → green → commit. Commit messages via `caveman:caveman-commit` style; hook enforces Conventional Commits, no AI attribution. After committing, verify `git log -1` + `git status --short` (clean) — subagents have silently skipped commits.
- **Mirror source-of-truth:** `src/collector/label_enrichment/{repository,auto_repository,routes,auto_routes,messages,auto_messages}.py`, `src/collector/handler.py`, `scripts/generate_openapi.py`, `infra/api_gateway.tf`. "Copy + transform" = copy the named label code and apply the listed entity swaps; do not invent from memory.
- **Entity swaps (apply consistently):** `label`→`artist`, `label_id`→`artist_id`, `LabelInfo`→`ArtistInfo`, `clouder_labels`→`clouder_artists`, `clouder_label_info`→`clouder_artist_info`, `clouder_label_enrichment_*`→`clouder_artist_enrichment_*`, `clouder_user_label_prefs`→`clouder_user_artist_prefs`, `label_auto_enrich_state`→`artist_auto_enrich_state`, `requested_labels`→`requested_artists`, `LABEL_ENRICHMENT_QUEUE_URL`→`ARTIST_ENRICHMENT_QUEUE_URL`, `_KIND="labels"`→`_KIND="artists"`. **Denormalized columns differ:** label `founded_year`/`activity`/`last_release_date` are replaced by artist `active_since`/`artist_type` (no `last_release_date`/`activity`). **The track/artist join differs** — see Task 1/Task 2.

---

## File Structure

```
src/collector/artist_enrichment/repository.py   Task 1 (ADD read/list/pref methods to the 1A file)
src/collector/artist_enrichment/auto_repository.py  Task 2 (NEW — config + claim + state + all-roles resolve)
src/collector/artist_enrichment/auto_messages.py    Task 2 (NEW — AutoEnrichConfigIn)
src/collector/artist_enrichment/messages.py     Task 3 (ADD EnrichArtistInput + EnrichArtistsRequestIn)
src/collector/artist_enrichment/routes.py       Task 3 (NEW — HTTP handlers)
src/collector/artist_enrichment/auto_routes.py  Task 4 (NEW — auto-config handlers)
src/collector/handler.py                        Task 5 (ADD artist route_keys + dispatch + admin set)
scripts/generate_openapi.py                     Task 6 (ADD artist ROUTES + schemas)
docs/api/openapi.yaml                           Task 6 (regenerated)
frontend/src/api/schema.d.ts                    Task 6 (regenerated)
infra/api_gateway.tf                            Task 6 (ADD artist route resources)
tests/unit/test_artist_enrichment_repository_reads.py  Task 1
tests/unit/test_artist_enrichment_auto_repository.py   Task 2
tests/unit/test_artist_enrichment_routes.py            Task 3
tests/unit/test_artist_enrichment_auto_routes.py       Task 4
tests/unit/test_artist_handler_dispatch.py             Task 5
```

The prompts' `list_prompt_versions` (used by `routes.handle_get_options`) must exist — Task 3 Step 0 adds it if the 1A prompts/__init__ lacks it.

---

## Task 1: Repository read / list / preference methods

**Files:**
- Modify: `src/collector/artist_enrichment/repository.py` (append methods to the `ArtistEnrichmentRepository` class from 1A)
- Test: `tests/unit/test_artist_enrichment_repository_reads.py`

Add (mirroring `label_enrichment/repository.py`): `get_artist_info`, `get_artist_info_for_user`, `list_runs`, `list_cells_for_run`, `list_history_for_artist`, `upsert_user_artist_pref`, `delete_user_artist_pref`, `list_user_artist_prefs`, `list_artists`, `list_backlog`. Most are token-swap mirrors; `list_artists` and `list_backlog` need the artist **many-to-many** track/style CTEs (count via `clouder_track_artists`, not `clouder_albums`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artist_enrichment_repository_reads.py` (uses the `FakeDataAPI` pattern from 1A's repository test — seed responses FIFO, assert SQL substrings + params):

```python
from collector.artist_enrichment.repository import ArtistEnrichmentRepository


class FakeDataAPI:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return self._responses.pop(0) if self._responses else []


def test_upsert_user_artist_pref_rejects_bad_status():
    repo = ArtistEnrichmentRepository(FakeDataAPI())
    import pytest
    with pytest.raises(ValueError):
        repo.upsert_user_artist_pref(user_id="u", artist_id="a", status="bogus")


def test_upsert_user_artist_pref_writes_prefs_table():
    api = FakeDataAPI()
    repo = ArtistEnrichmentRepository(api)
    repo.upsert_user_artist_pref(user_id="u", artist_id="a", status="liked")
    sql, params = api.calls[-1]
    assert "clouder_user_artist_prefs" in sql
    assert params["status"] == "liked" and params["artist_id"] == "a"


def test_get_artist_info_for_user_strips_admin_fields():
    api = FakeDataAPI(responses=[[{"merged": {"artist_name": "ANNA", "summary": "x", "provenance": {"a": 1}, "cost_usd": 9}, "my_preference": "liked"}]])
    repo = ArtistEnrichmentRepository(api)
    out = repo.get_artist_info_for_user("a", user_id="u")
    assert out["artist_name"] == "ANNA"
    assert "provenance" not in out and "cost_usd" not in out
    assert out["my_preference"] == "liked"


def test_list_artists_counts_tracks_via_track_artists():
    api = FakeDataAPI(responses=[
        [{"id": "a", "name": "ANNA", "status": "completed", "tagline": None, "country": "Brazil",
          "active_since": 2008, "primary_styles": ["techno"], "artist_type": "solo",
          "ai_content": "none_detected", "updated_at": None, "dominant_style": "techno",
          "track_count": 12, "my_preference": None}],
        [{"c": 1}],
    ])
    repo = ArtistEnrichmentRepository(api)
    items, total = repo.list_artists(style=None, q=None, sort="name", page=1, limit=50, user_id="u", my="all")
    # the list query must count tracks via the many-to-many join, not albums
    list_sql = api.calls[0][0]
    assert "clouder_track_artists" in list_sql
    assert "clouder_artist_info" in list_sql
    assert items[0]["info"]["active_since"] == 2008
    assert items[0]["info"]["artist_type"] == "solo"
    assert "founded_year" not in items[0]["info"]
    assert total == 1


def test_list_backlog_joins_track_artists():
    api = FakeDataAPI(responses=[
        [{"id": "a", "name": "ANNA", "style": "techno", "track_count": 5, "status": "none", "last_attempted_at": None}],
        [{"c": 1}],
    ])
    repo = ArtistEnrichmentRepository(api)
    items, cursor, total = repo.list_backlog(style=None, status="none", cursor=None, limit=100)
    assert "clouder_track_artists" in api.calls[0][0]
    assert items[0]["id"] == "a" and total == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_repository_reads.py -q`
Expected: FAIL — `AttributeError: 'ArtistEnrichmentRepository' object has no attribute 'upsert_user_artist_pref'` (and the others).

- [ ] **Step 3: Add the mirror methods (token-swap)**

Open `src/collector/label_enrichment/repository.py` and copy these methods into `src/collector/artist_enrichment/repository.py` (inside the `ArtistEnrichmentRepository` class), applying the entity swaps from Conventions. Also copy the module-level `_USER_FACING_FORBIDDEN` frozenset and the `_STYLE_SLUG_EXPR` string from the label repository to the top of the artist repository (needed by `get_artist_info_for_user` and the list CTEs):
- `get_label_info` → `get_artist_info` (SELECT `clouder_artist_info` joined `clouder_artists`; decode merged/provenance JSON, ai_confidence Decimal→float). Replace the denorm SELECT columns: drop `founded_year, activity, last_release_date`; add `artist_type, active_since`.
- `get_label_info_for_user` → `get_artist_info_for_user` (strip `_USER_FACING_FORBIDDEN`, fall back to `{artist_name, my_preference}`; join `clouder_user_artist_prefs`). The fallback selects `art.name AS artist_name`.
- `list_runs` → token-swap (SELECT `clouder_artist_enrichment_runs`, `requested_artists`); JSON-decode vendors/models; Decimal cost.
- `list_cells_for_run` → token-swap (`clouder_artist_enrichment_cells` joined `clouder_artists` for `artist_name`).
- `list_history_for_label` → `list_history_for_artist` (token-swap; `clouder_artist_enrichment_cells`/`_runs`).
- `upsert_user_label_pref` → `upsert_user_artist_pref` (INSERT `clouder_user_artist_prefs (user_id, artist_id, status, updated_at)` ON CONFLICT `(user_id, artist_id)`; status in liked|disliked).
- `delete_user_label_pref` → `delete_user_artist_pref`.
- `list_user_label_prefs` → `list_user_artist_prefs` (JOIN `clouder_artists`).

- [ ] **Step 4: Add `list_artists` (artist many-to-many CTEs)**

Add to `src/collector/artist_enrichment/repository.py`. This is NOT a token swap — track/style counts join through `clouder_track_artists`:

```python
    def list_artists(
        self,
        *,
        style: str | None,
        q: str | None,
        sort: str,
        page: int,
        limit: int,
        user_id: str | None = None,
        my: str = "all",
    ) -> tuple[list[dict[str, Any]], int]:
        if my not in ("all", "liked", "disliked", "unrated"):
            raise ValueError(f"my must be one of all|liked|disliked|unrated, got {my!r}")

        where: list[str] = []
        params: dict[str, Any] = {"lim": limit, "off": max(page - 1, 0) * limit}
        if style:
            where.append(
                "EXISTS (SELECT 1 FROM artist_style_counts asc2 "
                "WHERE asc2.artist_id = art.id AND asc2.style_slug = LOWER(:style))"
            )
            params["style"] = style
        if q:
            where.append("LOWER(art.name) LIKE :q")
            params["q"] = f"{q.lower()}%"
        params["pref_user_id"] = user_id or ""
        if my == "liked":
            where.append("uap.status = 'liked'")
        elif my == "disliked":
            where.append("uap.status = 'disliked'")
        elif my == "unrated":
            where.append("uap.user_id IS NULL")

        order_by = (
            "ai.updated_at DESC NULLS LAST, art.id DESC"
            if sort == "recent"
            else "art.name ASC, art.id ASC"
        )
        where_sql = " AND ".join(where) if where else "TRUE"

        ctes = f"""
            WITH artist_track_counts AS (
                SELECT ta.artist_id, COUNT(*) AS cnt
                FROM clouder_track_artists ta
                GROUP BY ta.artist_id
            ),
            artist_style_counts AS (
                SELECT ta.artist_id, {_STYLE_SLUG_EXPR} AS style_slug, COUNT(*) AS cnt
                FROM clouder_track_artists ta
                JOIN clouder_tracks t ON t.id = ta.track_id
                JOIN clouder_styles s ON s.id = t.style_id
                GROUP BY ta.artist_id, s.name
            ),
            artist_dominant_style AS (
                SELECT DISTINCT ON (artist_id) artist_id, style_slug
                FROM artist_style_counts
                ORDER BY artist_id, cnt DESC
            )
        """

        rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT art.id, art.name,
                   CASE WHEN ai.artist_id IS NULL THEN 'none' ELSE 'completed' END AS status,
                   ai.tagline, ai.country, ai.active_since, ai.primary_styles,
                   ai.artist_type, ai.ai_content, ai.updated_at,
                   ads.style_slug AS dominant_style,
                   COALESCE(atc.cnt, 0) AS track_count,
                   uap.status AS my_preference
            FROM clouder_artists art
            LEFT JOIN clouder_artist_info ai ON ai.artist_id = art.id
            LEFT JOIN artist_dominant_style ads ON ads.artist_id = art.id
            LEFT JOIN artist_track_counts atc ON atc.artist_id = art.id
            LEFT JOIN clouder_user_artist_prefs uap
                ON uap.artist_id = art.id AND uap.user_id = :pref_user_id
            WHERE {where_sql}
            ORDER BY {order_by}
            LIMIT :lim OFFSET :off
            """,
            params,
        )

        items: list[dict[str, Any]] = []
        for r in rows:
            info = None
            if r.get("status") == "completed":
                info = {
                    "tagline": r.get("tagline"),
                    "country": r.get("country"),
                    "active_since": r.get("active_since"),
                    "primary_styles": r.get("primary_styles") or [],
                    "artist_type": r.get("artist_type"),
                    "ai_content": r.get("ai_content"),
                    "updated_at": r.get("updated_at"),
                }
            items.append({
                "id": r["id"],
                "name": r["name"],
                "style": r.get("dominant_style") or "",
                "status": r.get("status") or "none",
                "track_count": int(r.get("track_count") or 0),
                "info": info,
                "my_preference": r.get("my_preference"),
            })

        count_params = {k: v for k, v in params.items() if k not in ("lim", "off")}
        total_rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT COUNT(*) AS c
            FROM clouder_artists art
            LEFT JOIN clouder_artist_info ai ON ai.artist_id = art.id
            LEFT JOIN clouder_user_artist_prefs uap
                ON uap.artist_id = art.id AND uap.user_id = :pref_user_id
            WHERE {where_sql}
            """,
            count_params,
        )
        total = int(total_rows[0]["c"]) if total_rows else 0
        return items, total
```

- [ ] **Step 5: Add `list_backlog` (artist many-to-many)**

Add to the artist repository, mirroring the label `list_backlog` but with the artist CTEs (same `artist_track_counts`/`artist_style_counts`/`artist_dominant_style` as Step 4) and `clouder_artist_info`/`clouder_artists`/`clouder_track_artists`. The status filter values stay `none|completed|outdated|all`; the stale clause uses `ai.updated_at`; the cursor encodes `track_count|id`. Copy the label `list_backlog` body and apply: `lbl`→`art`, `li`→`ai`, `label_track_counts`→`artist_track_counts` (counting `clouder_track_artists` grouped by `artist_id`), `label_style_counts`→`artist_style_counts`, `label_dominant_style`→`artist_dominant_style`, `clouder_label_info`→`clouder_artist_info`, `clouder_labels`→`clouder_artists`. The SELECT/items shape (`id, name, style, track_count, status, last_attempted_at`) is unchanged.

- [ ] **Step 6: Run to verify it passes**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_repository_reads.py -q`
Expected: PASS (5 passed). Also rerun the 1A repository test to ensure no regression: `... tests/unit/test_artist_enrichment_repository.py -q` → 8 passed.

- [ ] **Step 7: Commit**

```bash
git add src/collector/artist_enrichment/repository.py tests/unit/test_artist_enrichment_repository_reads.py
git commit -m "feat(artist-enrich): add repository read/list/preference methods"
git log -1 --format='%H %s'
git status --short
```

---

## Task 2: Auto-enrich repository + config message model

**Files:**
- Create: `src/collector/artist_enrichment/auto_repository.py`
- Create: `src/collector/artist_enrichment/auto_messages.py`
- Test: `tests/unit/test_artist_enrichment_auto_repository.py`

`auto_repository` holds the auto-enrich config (the `auto_enrich_config` row `kind="artists"`), the claim/state machinery, the worker outcome callback, and — the artist-specific part — the **all-roles** trigger resolution over `clouder_track_artists`. The full module is needed in 1B because `auto_routes` (Task 4) uses `get_config`/`upsert_config` and the 1A worker handler's `on_outcome` uses `mark_auto_enrich_outcome`. 1C's auto-dispatch will use `claim_artists`/`artist_ids_for_track`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artist_enrichment_auto_repository.py`:

```python
from collector.artist_enrichment.auto_repository import AutoEnrichRepository


class FakeDataAPI:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses or [])

    def execute(self, sql, params=None):
        self.calls.append((sql, dict(params or {})))
        return self._responses.pop(0) if self._responses else []


def test_get_config_uses_auto_enrich_config_table():
    api = FakeDataAPI(responses=[[{"kind": "artists", "enabled": True, "vendors": ["openai"],
                                   "models": {"openai": "m"}, "prompt_slug": "artist_v1",
                                   "prompt_version": "v1", "merge_vendor": "deepseek", "merge_model": "d"}]])
    repo = AutoEnrichRepository(api)
    cfg = repo.get_config("artists")
    assert "auto_enrich_config" in api.calls[0][0]
    assert api.calls[0][1]["kind"] == "artists"
    assert cfg["enabled"] is True and cfg["vendors"] == ["openai"]


def test_artist_ids_for_track_returns_all_roles():
    api = FakeDataAPI(responses=[[{"artist_id": "a1"}, {"artist_id": "a2"}, {"artist_id": "a3"}]])
    repo = AutoEnrichRepository(api)
    ids = repo.artist_ids_for_track("t1")
    sql = api.calls[0][0]
    assert "clouder_track_artists" in sql
    assert "role" not in sql.lower().split("where")[1] if "where" in sql.lower() else True  # no role filter
    assert ids == ["a1", "a2", "a3"]


def test_artist_ids_for_triage_block_all_roles():
    api = FakeDataAPI(responses=[[{"artist_id": "a1"}, {"artist_id": "a2"}]])
    repo = AutoEnrichRepository(api)
    ids = repo.artist_ids_for_triage_block("b1")
    assert "clouder_track_artists" in api.calls[0][0]
    assert "category_tracks" in api.calls[0][0]
    assert ids == ["a1", "a2"]


def test_mark_outcome_flips_queued_state():
    api = FakeDataAPI()
    repo = AutoEnrichRepository(api)
    repo.mark_auto_enrich_outcome("a1", True)
    sql, params = api.calls[-1]
    assert "artist_auto_enrich_state" in sql
    assert params["new_status"] == "completed"


def test_claim_artists_skips_when_info_exists():
    # reclaim UPDATE returns nothing, INSERT returns nothing (info exists) → not claimed
    api = FakeDataAPI(responses=[[], []])
    repo = AutoEnrichRepository(api)
    claimed = repo.claim_artists(["a1"])
    assert claimed == []
    assert "artist_auto_enrich_state" in api.calls[0][0]
    assert "clouder_artist_info" in api.calls[1][0]
```

- [ ] **Step 2: Run → FAIL** (`No module named 'collector.artist_enrichment.auto_repository'`).

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit/test_artist_enrichment_auto_repository.py -q`

- [ ] **Step 3: Create `auto_messages.py`**

Copy `src/collector/label_enrichment/auto_messages.py` → `src/collector/artist_enrichment/auto_messages.py` VERBATIM (the `AutoEnrichConfigIn` model is entity-agnostic — vendors/models/prompt/merge fields only; just update the docstring `/admin/auto-enrich/labels` → `/admin/auto-enrich/artists`).

- [ ] **Step 4: Create `auto_repository.py`**

Copy `src/collector/label_enrichment/auto_repository.py` → `src/collector/artist_enrichment/auto_repository.py` and apply the entity swaps:
- `get_config` / `upsert_config` — VERBATIM (operate on the shared `auto_enrich_config` table by `kind`; no swap needed beyond the docstring).
- `claim_labels` → `claim_artists`: swap `label_auto_enrich_state`→`artist_auto_enrich_state`, `clouder_label_info`→`clouder_artist_info`, the param/var `label_id`→`artist_id`. Keep `_MAX_ATTEMPTS=2`, `_STALE_QUEUED_HOURS=6`, the two-statement reclaim/insert logic identical.
- `attach_run` → swap `label_auto_enrich_state`→`artist_auto_enrich_state`, `label_id`→`artist_id`.
- `mark_auto_enrich_outcome(artist_id, success)` → swap table to `artist_auto_enrich_state`, param to `artist_id`.
- REPLACE `label_id_for_track` and `label_ids_for_triage_block` with the artist **all-roles** versions below (these are the genuinely different part — a track has MANY artists via `clouder_track_artists`, all roles):

```python
    # ── artist lookups (all roles) ──────────────────────────────────
    def artist_ids_for_track(self, track_id: str) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT DISTINCT artist_id
            FROM clouder_track_artists
            WHERE track_id = :track_id
            """,
            {"track_id": track_id},
        )
        return [r["artist_id"] for r in rows]

    def artist_ids_for_triage_block(self, block_id: str) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT DISTINCT ta.artist_id
            FROM category_tracks ct
            JOIN clouder_track_artists ta ON ta.track_id = ct.track_id
            WHERE ct.source_triage_block_id = :block_id
            """,
            {"block_id": block_id},
        )
        return [r["artist_id"] for r in rows]
```

Keep the module-level `_MAX_ATTEMPTS`, `_STALE_QUEUED_HOURS`, `_utc_now`, `_parse_json_col` helpers verbatim.

- [ ] **Step 5: Run → PASS (5 passed).** Then commit:

```bash
git add src/collector/artist_enrichment/auto_repository.py src/collector/artist_enrichment/auto_messages.py tests/unit/test_artist_enrichment_auto_repository.py
git commit -m "feat(artist-enrich): add auto-enrich repository (all-roles resolve)"
git log -1 --format='%H %s'
git status --short
```

---

## Task 3: HTTP route handlers + request models

**Files:**
- Modify: `src/collector/artist_enrichment/messages.py` (add `EnrichArtistInput` + `EnrichArtistsRequestIn`)
- Modify: `src/collector/artist_enrichment/prompts/__init__.py` (add `list_prompt_versions` if absent)
- Create: `src/collector/artist_enrichment/routes.py`
- Test: `tests/unit/test_artist_enrichment_routes.py`

- [ ] **Step 0: Ensure `list_prompt_versions` exists**

`routes.handle_get_options` calls `from .prompts import list_prompt_versions`. Check `src/collector/artist_enrichment/prompts/__init__.py`; if it lacks `list_prompt_versions`, add it mirroring `label_enrichment/prompts/__init__.py`'s version (returns `[{"slug": ..., "version": ...}]` for each registered prompt — read the label implementation and copy it).

- [ ] **Step 1: Add request models to `messages.py`**

Copy `EnrichLabelInput` + `EnrichLabelsRequestIn` from `label_enrichment/messages.py` into `src/collector/artist_enrichment/messages.py` (alongside the 1A `ArtistEnrichmentMessage`), swapping `label`→`artist`: `EnrichArtistInput` (fields `artist_id`, `artist_name`, `style`; same `_id_or_name_required` validator), `EnrichArtistsRequestIn` (field `artists` not `labels`; same vendors/models/prompt/merge fields + `_every_vendor_has_a_model` validator).

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_artist_enrichment_routes.py`. Use a `FakeRepo` that returns canned values; monkeypatch the route module's `_build_repository`/`_build_sqs_client`/`_queue_url`. Example coverage (mirror the label routes' behavior):

```python
import json
import collector.artist_enrichment.routes as routes


class FakeRepo:
    def __init__(self):
        self.runs = []
        self.created = None
    def get_artist_by_id(self, aid): return {"id": aid, "name": "ANNA"}
    def derive_artist_context(self, aid):
        from collector.artist_enrichment.repository import ArtistContext
        return ArtistContext(style="techno", sample_tracks=[], known_labels=[])
    def create_run(self, spec): self.created = spec; return "run-1"
    def get_artist_info(self, aid): return {"artist_id": aid, "merged": {}}
    def list_artists(self, **kw): return ([{"id": "a", "name": "ANNA"}], 1)


class FakeSQS:
    def __init__(self): self.sent = []
    def send_message(self, **kw): self.sent.append(kw)


def _setup(monkeypatch, repo=None, sqs=None):
    repo = repo or FakeRepo()
    sqs = sqs or FakeSQS()
    monkeypatch.setattr(routes, "_build_repository", lambda: repo)
    monkeypatch.setattr(routes, "_build_sqs_client", lambda: sqs)
    monkeypatch.setattr(routes, "_queue_url", lambda: "https://q")
    return repo, sqs


def test_post_enrich_creates_run_and_enqueues(monkeypatch):
    repo, sqs = _setup(monkeypatch)
    event = {"body": json.dumps({
        "artists": [{"artist_id": "a1"}],
        "vendors": ["openai"], "models": {"openai": "m"},
        "prompt_slug": "artist_v1", "prompt_version": "v1",
        "merge_vendor": "deepseek", "merge_model": "d",
    })}
    status, body = routes.handle_post_enrich(event)
    assert status == 202
    assert body["run_id"] == "run-1" and body["queued_artists"] == 1
    assert repo.created.requested_artists == 1
    assert len(sqs.sent) == 1
    msg = json.loads(sqs.sent[0]["MessageBody"])
    assert msg["artist_id"] == "a1" and msg["artist_name"] == "ANNA"
    assert "style" not in msg  # worker derives context; message carries no style


def test_post_enrich_rejects_unknown_prompt(monkeypatch):
    from collector.errors import ValidationError
    import pytest
    _setup(monkeypatch)
    event = {"body": json.dumps({
        "artists": [{"artist_id": "a1"}],
        "vendors": ["openai"], "models": {"openai": "m"},
        "prompt_slug": "nope", "prompt_version": "v1",
        "merge_vendor": "deepseek", "merge_model": "d",
    })}
    with pytest.raises(ValidationError):
        routes.handle_post_enrich(event)


def test_get_artist_user_404_when_missing(monkeypatch):
    class R(FakeRepo):
        def get_artist_info_for_user(self, aid, user_id=None): return None
    _setup(monkeypatch, repo=R())
    status, body = routes.handle_get_artist_user({"pathParameters": {"artist_id": "x"}})
    assert status == 404
```

(Add further cases mirroring the label route tests as useful: backlog limit validation, runs-list status filter, preference put liked/none, my-preferences pagination.)

- [ ] **Step 3: Run → FAIL** (`No module named 'collector.artist_enrichment.routes'`).

- [ ] **Step 4: Create `routes.py`**

Copy `src/collector/label_enrichment/routes.py` → `src/collector/artist_enrichment/routes.py` and apply the entity swaps. Specific points:
- `_queue_url` reads `ARTIST_ENRICHMENT_QUEUE_URL`.
- imports: `from .messages import EnrichArtistsRequestIn`, `from .repository import ArtistEnrichmentRepository, RunSpec`.
- `handle_post_enrich`: iterate `req.artists`; for `artist_id` → `repo.get_artist_by_id`; for `artist_name` → `repo.upsert_artist_by_name`. **The SQS message does NOT include `style`** — the worker derives context. Build `RunSpec(..., requested_artists=len(req.artists), ...)`. Enqueue `{"run_id", "artist_id", "artist_name"}` per artist. Return `202, {"run_id": run_id, "queued_artists": len(req.artists)}`. (Drop the label code's `derive_style_for_label`/`style` resolution — not needed since the message carries no style and the worker derives context in 1A.)
- `handle_get_run`: `repo.list_cells_for_run`.
- `handle_get_artist` (admin) ← `handle_get_label`: `repo.get_artist_info`.
- `handle_get_artist_history` ← `handle_get_label_history`: `repo.list_history_for_artist`.
- `handle_get_artist_user` ← `handle_get_label_user`: `repo.get_artist_info_for_user`.
- `handle_get_backlog`, `handle_get_runs_list`, `handle_get_artists_list` ← `handle_get_labels_list` (`repo.list_artists`, response `items/total/page/limit`).
- `handle_put_artist_preference` ← `handle_put_label_preference` (`get_artist_by_id` 404 check; `delete_user_artist_pref`/`upsert_user_artist_pref`).
- `handle_get_my_artist_preferences` ← `handle_get_my_label_preferences` (`list_user_artist_prefs`).
- `handle_get_options`: VERBATIM (static vendor/model/merge config + `list_prompt_versions`).
- `_build_repository` returns `ArtistEnrichmentRepository`.

- [ ] **Step 5: Run → PASS.** Commit:

```bash
git add src/collector/artist_enrichment/messages.py src/collector/artist_enrichment/routes.py src/collector/artist_enrichment/prompts/__init__.py tests/unit/test_artist_enrichment_routes.py
git commit -m "feat(artist-enrich): add HTTP route handlers"
git log -1 --format='%H %s'
git status --short
```

---

## Task 4: Auto-enrich config route handlers

**Files:**
- Create: `src/collector/artist_enrichment/auto_routes.py`
- Test: `tests/unit/test_artist_enrichment_auto_routes.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artist_enrichment_auto_routes.py`:

```python
import json
import collector.artist_enrichment.auto_routes as ar


class FakeRepo:
    def __init__(self): self.saved = None
    def get_config(self, kind): return None
    def upsert_config(self, **kw): self.saved = kw


def test_get_auto_config_returns_defaults(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(ar, "_build_repository", lambda: repo)
    status, body = ar.handle_get_auto_config({})
    assert status == 200
    assert body["config"]["enabled"] is False
    assert "options" in body and body["options"]["vendors"]


def test_put_auto_config_persists_with_artists_kind(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(ar, "_build_repository", lambda: repo)
    event = {"body": json.dumps({"enabled": True, "vendors": ["openai"],
                                 "models": {"openai": "m"}, "prompt_slug": "artist_v1",
                                 "prompt_version": "v1", "merge_vendor": "deepseek", "merge_model": "d"})}
    status, body = ar.handle_put_auto_config(event)
    assert status == 204
    assert repo.saved["kind"] == "artists" and repo.saved["enabled"] is True
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Create `auto_routes.py`**

Copy `src/collector/label_enrichment/auto_routes.py` → `src/collector/artist_enrichment/auto_routes.py` with swaps: `_KIND = "artists"`; imports `from .auto_messages import AutoEnrichConfigIn`, `from .auto_repository import AutoEnrichRepository`; `_build_repository` returns the artist `AutoEnrichRepository`. The `_options`/`_default_config`/`handle_get_auto_config`/`handle_put_auto_config` bodies are otherwise verbatim.

- [ ] **Step 4: Run → PASS.** Commit:

```bash
git add src/collector/artist_enrichment/auto_routes.py tests/unit/test_artist_enrichment_auto_routes.py
git commit -m "feat(artist-enrich): add auto-enrich config routes"
git log -1 --format='%H %s'
git status --short
```

---

## Task 5: Collector handler dispatch

**Files:**
- Modify: `src/collector/handler.py` (add artist route_keys to the admin set + dispatch blocks)
- Test: `tests/unit/test_artist_handler_dispatch.py`

The label routes are dispatched in `src/collector/handler.py` (admin route_keys listed ~lines 67-75; dispatch `if route_key == ...` blocks ~lines 162-223). Add the parallel artist routes.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artist_handler_dispatch.py` — assert each artist route_key dispatches to the right handler. Monkeypatch the handler functions and call the collector dispatch with a minimal event per route_key, asserting the right handler was invoked. (Mirror any existing label-dispatch test if present — `grep -rln "handle_get_labels_list\|POST /admin/labels/enrich" tests/` to find it and copy its structure.) At minimum, assert these route_keys are routed: `POST /admin/artists/enrich`, `GET /admin/artists/enrich/options`, `GET /admin/artists/enrich-runs`, `GET /admin/artists/enrich-runs/{run_id}`, `GET /admin/artists/backlog`, `GET /admin/artists/{artist_id}`, `GET /admin/artists/{artist_id}/history`, `GET /admin/auto-enrich/artists`, `PUT /admin/auto-enrich/artists`, `GET /artists`, `GET /artists/{artist_id}`, `PUT /artists/{artist_id}/preference`, `GET /me/artist-preferences`.

- [ ] **Step 2: Run → FAIL** (routes not dispatched → 404/unknown route).

- [ ] **Step 3: Add the dispatch + admin set**

In `src/collector/handler.py`:
- Add the artist admin route_keys to the admin-gating set (the list at ~lines 67-75 that the label admin routes are in): `POST /admin/artists/enrich`, `GET /admin/artists/enrich/options`, `GET /admin/artists/enrich-runs`, `GET /admin/artists/enrich-runs/{run_id}`, `GET /admin/artists/backlog`, `GET /admin/artists/{artist_id}`, `GET /admin/artists/{artist_id}/history`, `GET /admin/auto-enrich/artists`, `PUT /admin/auto-enrich/artists`.
- Add dispatch `if route_key == ...` blocks mirroring the label ones (lines 162-223), importing from `.artist_enrichment.routes` / `.artist_enrichment.auto_routes`:
  - `POST /admin/artists/enrich` → `routes.handle_post_enrich`
  - `GET /admin/artists/enrich/options` → `routes.handle_get_options`
  - `GET /admin/artists/enrich-runs` → `routes.handle_get_runs_list`
  - `GET /admin/artists/enrich-runs/{run_id}` → `routes.handle_get_run`
  - `GET /admin/artists/backlog` → `routes.handle_get_backlog`
  - `GET /admin/artists/{artist_id}/history` → `routes.handle_get_artist_history` (register BEFORE `{artist_id}` so the more specific path wins, exactly as the label code orders history before the bare id)
  - `GET /admin/artists/{artist_id}` → `routes.handle_get_artist`
  - `GET /admin/auto-enrich/artists` → `auto_routes.handle_get_auto_config`
  - `PUT /admin/auto-enrich/artists` → `auto_routes.handle_put_auto_config`
  - `PUT /artists/{artist_id}/preference` → `routes.handle_put_artist_preference`
  - `GET /me/artist-preferences` → `routes.handle_get_my_artist_preferences`
  - `GET /artists` → `routes.handle_get_artists_list`
  - `GET /artists/{artist_id}` → `routes.handle_get_artist_user`
  Use the same `_json_response(status, body, correlation_id)` wrapping the label blocks use.

- [ ] **Step 4: Run → PASS.** Sanity: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit -k "artist_enrichment or artist_handler" -q` → all artist tests green; and `... -k label -q` → label suite unbroken.

- [ ] **Step 5: Commit**

```bash
git add src/collector/handler.py tests/unit/test_artist_handler_dispatch.py
git commit -m "feat(artist-enrich): dispatch artist routes in collector handler"
git log -1 --format='%H %s'
git status --short
```

---

## Task 6: OpenAPI + API Gateway routes

**Files:**
- Modify: `scripts/generate_openapi.py` (add artist routes + schemas to `ROUTES`)
- Modify: `docs/api/openapi.yaml` (regenerated — do not hand-edit)
- Modify: `frontend/src/api/schema.d.ts` (regenerated)
- Modify: `infra/api_gateway.tf` (add artist route resources)

- [ ] **Step 1: Add artist routes + schemas to `generate_openapi.py`**

Read the label-enrichment section of `scripts/generate_openapi.py` (search for `/admin/labels/enrich`, `/labels`, `/admin/auto-enrich/labels`, and the label schema constants like `LABEL_ENRICH_REQUEST`). For EACH label route entry, add a parallel artist entry to `ROUTES` with the path swapped (`/labels`→`/artists`, `/admin/labels/...`→`/admin/artists/...`, `{label_id}`→`{artist_id}`), the same `auth` marker (ADMIN for `/admin/...`), and the artist request/response schemas. Define artist schema constants mirroring the label ones (`ARTIST_ENRICH_REQUEST` with `artists`/`vendors`/`models`/`prompt_slug`/`prompt_version`/`merge_vendor`/`merge_model`; the artist info/list response shapes using the `ArtistInfo` fields + `active_since`/`artist_type` instead of `founded_year`/`activity`). The full route set to add (parity with labels):
`POST /admin/artists/enrich`, `GET /admin/artists/enrich/options`, `GET /admin/artists/enrich-runs`, `GET /admin/artists/enrich-runs/{run_id}`, `GET /admin/artists/backlog`, `GET /admin/artists/{artist_id}`, `GET /admin/artists/{artist_id}/history`, `GET|PUT /admin/auto-enrich/artists`, `GET /artists`, `GET /artists/{artist_id}`, `PUT /artists/{artist_id}/preference`, `GET /me/artist-preferences`.

- [ ] **Step 2: Regenerate the OpenAPI + frontend schema**

Run: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/python scripts/generate_openapi.py`
Then regenerate the frontend types per the repo's documented command (check `frontend/package.json` for the `openapi-typescript` script, e.g. `cd frontend && pnpm gen:api` or the command in CLAUDE.md). Confirm `docs/api/openapi.yaml` now contains the `/artists` + `/admin/artists/*` paths and `frontend/src/api/schema.d.ts` has the matching path types.

- [ ] **Step 3: Verify the OpenAPI is valid + the diff-check passes**

Run the repo's OpenAPI/schema sync check (the CI diff-check). At minimum: `grep -c "/admin/artists/enrich\|/artists" docs/api/openapi.yaml` > 0, and `grep -c "admin/artists\|\"/artists\"" frontend/src/api/schema.d.ts` > 0. Run any existing `tests/` that validate openapi.yaml.

- [ ] **Step 4: Add API Gateway route resources**

In `infra/api_gateway.tf`, add `aws_apigatewayv2_route` resources for each artist route, mirroring the label route resources (target the SAME `collector_lambda` integration, same JWT authorizer). Mirror the label block for: `artists_enrich_post`, `artists_enrich_runs_get`, `artists_enrich_runs_list`, `artists_enrich_options`, `artists_backlog`, `artists_get_info`, `artist_history`, `auto_enrich_artists_get`, `auto_enrich_artists_put`, `list_artists`, `artist_detail_user`, `artist_preference_put`, `my_artist_preferences`. Validate: `cd infra && terraform fmt && terraform validate` (validate may need init; `terraform fmt` at minimum must pass).

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts infra/api_gateway.tf
git commit -m "feat(artist-enrich): expose artist routes in OpenAPI + API Gateway"
git log -1 --format='%H %s'
git status --short
```

---

## Done criteria for plan 1B

- Artist HTTP handlers exist and are unit-tested (post enrich, run status, backlog, artist list/detail, history, preferences, auto-config); the collector handler dispatches all artist route_keys with admin gating on `/admin/artists/*`.
- `auto_repository` provides config + claim + state + **all-roles** `artist_ids_for_track`/`artist_ids_for_triage_block`.
- OpenAPI + `schema.d.ts` + API Gateway expose the full artist API at label parity; the frontend schema diff-check passes.
- Label suite remains green; no live API calls in tests.

## Next: plan 1C (infra + auto-dispatch)

`infra/sqs.tf` artist queue+DLQ, `infra/lambda.tf` `artist_enricher_worker` + event-source-mapping, `ARTIST_ENRICHMENT_QUEUE_URL` env on curation + collector lambdas, new tunable vars; `artist_enrichment/auto_dispatch.py` (`try_dispatch_artists_for_track`/`_for_triage_block`, using `auto_repository.claim_artists` + `artist_ids_for_track` + `create_run` + SQS enqueue); wire both into `curation_handler.py` at the existing label dispatch call sites (track add, triage finalize). Then PR all of SP1 (1A+1B+1C).
