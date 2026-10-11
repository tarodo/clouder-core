# Phase 5 — Code quality: split the API handler and the repository, stricter mypy and ruff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `handler.py` (1 593 lines) becomes a thin router over `collector/api/routes_*`, `repositories.py` (1 713 lines) becomes a package split by aggregate, mypy checks untyped bodies (and the core modules strictly), ruff adds `UP`/`SIM`/`RUF`, and CI checks `ruff format` — with no behaviour change.

**Architecture:** Follow the curation refactor already in the repo: route modules plus `deps.py` (collaborators that tests patch, called as `deps.X()`) and `http.py` (event/response helpers); the Lambda entry point keeps its name (`collector.handler.lambda_handler`, Terraform unchanged) and dispatches through a `_ROUTE_TABLE`. `ClouderRepository` keeps its name and API as a facade composed of six aggregate mixins, so its ~20 importers do not change. Formatting goes last, in its own commit listed in `.git-blame-ignore-revs`, so the moves stay traceable in `git log --follow`.

**Tech Stack:** Python 3.12, ruff 0.16, mypy 2.4 (pydantic plugin), pytest, GitHub Actions.

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-08.ru.md` §0 phase 5, §7.2 (module size, typing, linting rows), §11 P1 rows "Разрезать `handler.py`" and "Строже статический анализ". Measured on `origin/main` 2026-10-11: `mypy --check-untyped-defs` → 1 error; strict on the core modules → 7 errors in 2 files; `ruff --select UP,SIM,RUF` → 526 findings (423 auto-fixable); `ruff format --check` → 327 of 447 files.

## Global Constraints

- Worktree `<repo>` (`clouder-core-p1`), branch `refactor/code-quality` from `origin/main`. `<venv>` = the main checkout's `.venv/bin` (gotcha 3 in CLAUDE.md).
- No behaviour change: every existing test passes unmodified except for patch targets that move with the code (`collector.handler.X` → `collector.api.deps.X` or the route module).
- Lambda handler strings and Terraform stay as they are; the zip still packages `src/collector` whole.
- Runtime DB access stays on the Data API (no `psycopg` under `src/collector`, ADR-0001).
- `UP042` (`str, Enum` → `StrEnum`) stays off: `StrEnum` changes `str()` and f-string output of members.
- Commits and PR text via `caveman:caveman-commit`; no attribution lines.

## Review Focus

1. **Every route resolves to the same code after the split** — incl. the legacy empty route key (direct invoke → collect), admin gating before dispatch, 404 for an unknown key, 204 with an empty body from the delegated `PUT` routes. Pinned by `test_route_table_serves_exactly_the_gateway_routes`, `test_legacy_direct_invoke_still_collects`, `test_unknown_route_is_404` (Task 3) and the existing admin-gating / preference tests.
2. **Tests that patch collaborators really patch them** — a route module that binds `create_clouder_repository_from_env` at import would ignore a patch on `deps` and hit the real factory; routes must call `deps.X()`. Pinned by the existing handler tests (they fail with 503 if the patch misses) after retargeting, plus `test_routes_call_collaborators_through_deps` (Task 3).
3. **Enrichment code stays out of the cold start** — today the label/artist route modules are imported on first use; the router must keep that. Pinned by `test_enrichment_routes_load_on_first_use` (Task 3).
4. **ruff autofixes change no behaviour** — `UP042` excluded; manual `SIM`/`RUF` fixes are local rewrites; the full suite plus the final review cover them.
5. **The format commit is formatting only** — ruff verifies AST equivalence; the suite runs after it; the commit is listed in `.git-blame-ignore-revs`.

---

### Task 1: ruff `UP`, `SIM`, `RUF`

**Files:** `pyproject.toml` (`[tool.ruff.lint]`), auto- and hand-fixes across `src/`, `tests/`, `scripts/`.

- [ ] **Step 1:** `pyproject.toml`:

```toml
[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "B", "UP", "SIM", "RUF"]
# B904/B905: raise-from and zip(strict=) are style changes across ~40 call sites.
# UP042: StrEnum changes str() and f-string output of members.
ignore = ["B904", "B905", "UP042"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["B011", "B017", "E402"]  # local helpers before imports are fine in tests
"src/collector/*/prompts/**" = ["RUF001", "RUF002"]  # LLM prompt text uses typographic characters on purpose
```

- [ ] **Step 2 (RED):** `<venv>/ruff check src tests scripts --statistics` → Expected: ~520 findings.
- [ ] **Step 3:** `<venv>/ruff check --fix src tests scripts`, then fix the rest by hand, rule by rule:
  - `RUF059` unused unpacked variable → prefix with `_`.
  - `SIM102` nested `if` → one `if … and …`; `SIM117` nested `with` → one `with a, b:`; `SIM105` `try/except/pass` → `contextlib.suppress(...)`; `SIM108` → conditional expression; `SIM118` → `key in d`; `SIM115` → `with open(...)`.
  - `RUF005` → `[*a, b]`; `RUF015` → `next(iter(x))`; `RUF007` → `itertools.pairwise`; `RUF012` → `ClassVar[...]`; `RUF043` → raw-string `match=`; `RUF046` → drop the redundant `int()`; `RUF002` outside prompts → replace the character.
  - `UP035` leftovers → import from `collections.abc`; `UP046` → PEP 695 class syntax if mypy accepts it, otherwise a `# noqa: UP046` with the reason.
- [ ] **Step 4 (GREEN):** `ruff check src tests scripts` → `All checks passed!`; `<venv>/mypy` → no issues; full suite → green.
- [ ] **Step 5: Commit** (`refactor: adopt ruff UP, SIM and RUF rules`).

---

### Task 2: mypy checks untyped bodies; core modules strict

**Files:** `pyproject.toml` (`[tool.mypy]`), `src/collector/curation/routes_playlists.py:190-198`, `src/collector/canonicalize.py`, `src/collector/data_api.py`, `src/collector/repositories.py` (`transaction`).

- [ ] **Step 1:** `pyproject.toml` — add to `[tool.mypy]` `check_untyped_defs = true`, and (mypy's `strict` is global-only, so the flags are listed per module):

```toml
# The modules every ingest and DQ result passes through are checked strictly.
[[tool.mypy.overrides]]
module = [
  "collector.canonicalize",
  "collector.contracts",
  "collector.data_quality",
  "collector.data_api",
  "collector.data_api_retry",
]
disallow_untyped_defs = true
disallow_incomplete_defs = true
disallow_untyped_calls = true
disallow_any_generics = true
warn_return_any = true
strict_equality = true
```

- [ ] **Step 2 (RED):** `<venv>/mypy` → Expected: the `arg-type` error at `routes_playlists.py:197` plus ~7 strict errors (`canonicalize.py:88, 286, 334, 386, 435, 614`, `data_api.py:95`).
- [ ] **Step 3:** fix:
  - `routes_playlists.py`: `ResolveMatchIn` guarantees `vendor_track_id` on accept; narrow it once at the top of the accept branch: `video_id = body.vendor_track_id` + `assert video_id is not None  # ResolveMatchIn requires it on accept`, and use `video_id` in the payload, the candidate match and `try_dispatch_comment_collection`.
  - `repositories.py` `transaction(self)` → `-> AbstractContextManager[None]` (match `DataAPIClient.transaction`'s return type); annotate the two `canonicalize.py` functions; `data_api.py:95` → `str(...)` around the `Any` value.
- [ ] **Step 4 (GREEN):** `<venv>/mypy` → `Success`; full suite green.
- [ ] **Step 5: Commit** (`build(mypy): check untyped defs, strict core`).

---

### Task 3: `handler.py` → `collector/api/`

**Files:**
- Create: `src/collector/api/__init__.py`, `http.py`, `deps.py`, `routes_ingest.py`, `routes_runs.py`, `routes_admin.py`, `routes_spotify.py`, `routes_catalog.py`.
- Rewrite: `src/collector/handler.py` (router only).
- Test: `tests/unit/test_collector_api_routes.py` (new); retarget patches in existing tests.

**Interfaces:**
- Produces: `collector.handler.lambda_handler` (unchanged), `collector.handler._ROUTE_TABLE: dict[str, Route]`, `Route = Callable[[Mapping[str, Any], Any, str], dict[str, Any]]` — every route function takes `(event, context, correlation_id)`. Patch targets: `collector.api.deps.{create_clouder_repository_from_env, utc_now, S3Storage, create_default_s3_client, create_default_sqs_client, fetch_access_token, read_beatport_credentials, registry, _auto_ingest_repository, _invoke_auto_ingest}`, `collector.api.routes_ingest.{collect_period, _enqueue_canonicalization}`.

- [ ] **Step 1: Failing tests** `tests/unit/test_collector_api_routes.py`:

```python
"""collector-api: the router serves exactly the gateway routes; routes live in collector/api."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _gateway_routes() -> set[str]:
    keys = set()
    for tf in (ROOT / "infra").glob("*.tf"):
        for body in re.findall(r'resource "aws_apigatewayv2_route" "[^"]+" \{(.*?)\n\}', tf.read_text(), re.S):
            if "collector_lambda" in body:
                keys.add(re.search(r'route_key\s*=\s*"([^"]+)"', body).group(1))
    return keys


def test_route_table_serves_exactly_the_gateway_routes() -> None:
    from collector.handler import _ROUTE_TABLE

    assert set(_ROUTE_TABLE) - {""} == _gateway_routes()


def test_handler_module_is_a_thin_router() -> None:
    assert len((ROOT / "src/collector/handler.py").read_text().splitlines()) <= 250


def test_routes_call_collaborators_through_deps() -> None:
    # A route that imports a collaborator by name ignores a patch on `deps`.
    names = ("create_clouder_repository_from_env", "create_default_s3_client", "create_default_sqs_client",
             "fetch_access_token", "read_beatport_credentials", "S3Storage")
    for module in (ROOT / "src/collector/api").glob("routes_*.py"):
        text = module.read_text()
        for name in names:
            assert not re.search(rf"import[^\n]*\b{name}\b", text), f"{module.name} binds {name}"


def test_enrichment_routes_load_on_first_use() -> None:
    code = ("import sys, collector.handler; "
            "print(json.dumps(sorted(m for m in sys.modules if m.endswith(('enrichment.routes', 'enrichment.auto_routes')))))")
    out = subprocess.run([sys.executable, "-c", "import json; " + code], capture_output=True, text=True,
                         env={"PYTHONPATH": str(ROOT / "src")}, check=True).stdout
    assert json.loads(out) == []


def test_legacy_direct_invoke_still_collects() -> None:
    # No routeKey = direct Lambda invoke of the collect endpoint; an empty body is a validation error, not a 404.
    from collector.handler import lambda_handler

    resp = lambda_handler({"body": "{}"}, None)
    assert resp["statusCode"] == 400


def test_unknown_route_is_404() -> None:
    from collector.handler import lambda_handler

    resp = lambda_handler({"requestContext": {"routeKey": "GET /nope"}}, None)
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error_code"] == "not_found"
```

- [ ] **Step 2 (RED):** run it → Expected: `test_route_table_serves_exactly_the_gateway_routes` (ImportError `_ROUTE_TABLE`), `test_handler_module_is_a_thin_router` and `test_routes_call_collaborators_through_deps` (no `api/`… passes vacuously — acceptable, it guards the move) fail; the 404 / legacy / lazy-import tests pass today and pin the behaviour across the move. If `test_legacy_direct_invoke_still_collects` does not give 400 today, change its expectation to today's status before moving code.
- [ ] **Step 3: Move the code.** Bodies move verbatim; the only edits are imports, `deps.` in front of a collaborator call, and the uniform `(event, context, correlation_id)` signature on route functions.

| New module | Moves from `handler.py` |
|---|---|
| `api/http.py` | `_require_admin`, `_parse_iso_date_field`, `_parse_pagination_params`, `_parse_date_param`, `_load_api_settings`, `_parse_json_body`, `_extract_route_key`, `_extract_api_request_id`, `_extract_correlation_id`, `_iso`, `_json_response` |
| `api/deps.py` | `create_default_sqs_client`, `_auto_ingest_repository`, `_invoke_auto_ingest`; re-exports `create_clouder_repository_from_env`, `utc_now` (`..repositories`), `S3Storage`, `create_default_s3_client` (`..storage`), `fetch_access_token`, `read_credentials as read_beatport_credentials` (`..beatport_auth`), `registry` (`..providers`) |
| `api/routes_ingest.py` | `EnqueueResult`, `_IngestParams`, `_run_beatport_ingest`, `collect_period`, `_handle_collect`, `_handle_admin_ingest`, `_beatport_token`, `_parse_collect_request`, `_enqueue_canonicalization`, `_auto_ingest_view`, `_handle_auto_ingest_get`, `_handle_auto_ingest_put`, new `_handle_auto_ingest_run` (body of today's inline branch) |
| `api/routes_runs.py` | `_PHASE_PREFIX`, `_split_phase_prefix`, `_handle_admin_runs`, `_handle_get_run` |
| `api/routes_admin.py` | `_handle_admin_coverage`, `_handle_admin_style_visibility`, `_handle_admin_users` |
| `api/routes_spotify.py` | `_handle_spotify_not_found`, `_handle_spotify_search_status`, `_handle_spotify_retry_not_found` |
| `api/routes_catalog.py` | `_LIST_ROUTES`, `_handle_list` (reads the route key itself via `_extract_route_key`), `_FUNNEL_STAGES`, `_handle_analytics_funnel`, new `_handle_get_styles` and `_handle_put_my_styles` (today's inline `GET /styles` / `PUT /me/styles` branches, keeping their lazy `from ..user_styles.routes import …`) |

`deps.py` header:

```python
"""Collaborators of the collector-API routes.

Route modules call these through the module (`deps.X()`), so tests patch
`collector.api.deps` — same pattern as `collector.curation.deps`.
"""
```

New `handler.py` (complete; `_ADMIN_ROUTES` moves over unchanged):

```python
"""AWS Lambda handler for the collector API: admin gating and dispatch.

Routes live in `collector/api/routes_*`; `_ROUTE_TABLE` is the single source of
truth and must match the API Gateway routes wired to this Lambda.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

from .api import routes_admin, routes_catalog, routes_ingest, routes_runs, routes_spotify
from .api.http import (
    _extract_api_request_id,
    _extract_correlation_id,
    _extract_route_key,
    _json_response,
    _require_admin,
)
from .errors import AppError
from .logging_utils import log_event

Route = Callable[[Mapping[str, Any], Any, str], dict[str, Any]]

_ADMIN_ROUTES = frozenset({...})  # unchanged


def _delegate(module: str, func: str) -> Route:
    """A route served by a domain package, imported on first use to keep cold starts lean."""

    def route(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
        handle = getattr(importlib.import_module(f"{__package__}.{module}"), func)
        status, body = handle(event)
        if status == 204:
            return {"statusCode": 204, "headers": {"x-correlation-id": correlation_id}, "body": ""}
        return _json_response(status, body, correlation_id)

    return route


_ROUTE_TABLE: dict[str, Route] = {
    "": routes_ingest._handle_collect,  # direct Lambda invoke (no API Gateway)
    "POST /collect_bp_releases": routes_ingest._handle_collect,
    "POST /admin/beatport/ingest": routes_ingest._handle_admin_ingest,
    "GET /admin/auto-ingest": routes_ingest._handle_auto_ingest_get,
    "PUT /admin/auto-ingest": routes_ingest._handle_auto_ingest_put,
    "POST /admin/auto-ingest/run": routes_ingest._handle_auto_ingest_run,
    "GET /runs/{run_id}": routes_runs._handle_get_run,
    "GET /admin/runs": routes_runs._handle_admin_runs,
    "GET /admin/coverage": routes_admin._handle_admin_coverage,
    "PATCH /admin/styles/{style_id}": routes_admin._handle_admin_style_visibility,
    "GET /admin/users": routes_admin._handle_admin_users,
    "GET /tracks/spotify-not-found": routes_spotify._handle_spotify_not_found,
    "POST /admin/spotify/retry-not-found": routes_spotify._handle_spotify_retry_not_found,
    "GET /admin/spotify/search-status": routes_spotify._handle_spotify_search_status,
    "GET /tracks": routes_catalog._handle_list,
    "GET /albums": routes_catalog._handle_list,
    "GET /v1/analytics/funnel": routes_catalog._handle_analytics_funnel,
    "GET /styles": routes_catalog._handle_get_styles,
    "PUT /me/styles": routes_catalog._handle_put_my_styles,
    "POST /admin/labels/enrich": _delegate("label_enrichment.routes", "handle_post_enrich"),
    "POST /admin/labels/{label_id}/enrich-auto": _delegate("label_enrichment.routes", "handle_post_enrich_auto"),
    "GET /admin/labels/enrich/options": _delegate("label_enrichment.routes", "handle_get_options"),
    "GET /admin/labels/enrich-runs": _delegate("label_enrichment.routes", "handle_get_runs_list"),
    "GET /admin/labels/enrich-runs/{run_id}": _delegate("label_enrichment.routes", "handle_get_run"),
    "GET /admin/labels/backlog": _delegate("label_enrichment.routes", "handle_get_backlog"),
    "GET /admin/labels/{label_id}/history": _delegate("label_enrichment.routes", "handle_get_label_history"),
    "GET /admin/labels/{label_id}": _delegate("label_enrichment.routes", "handle_get_label"),
    "GET /admin/auto-enrich/labels": _delegate("label_enrichment.auto_routes", "handle_get_auto_config"),
    "PUT /admin/auto-enrich/labels": _delegate("label_enrichment.auto_routes", "handle_put_auto_config"),
    "PUT /labels/{label_id}/preference": _delegate("label_enrichment.routes", "handle_put_label_preference"),
    "GET /me/label-preferences": _delegate("label_enrichment.routes", "handle_get_my_label_preferences"),
    "GET /labels": _delegate("label_enrichment.routes", "handle_get_labels_list"),
    "GET /labels/{label_id}": _delegate("label_enrichment.routes", "handle_get_label_user"),
    "POST /admin/artists/enrich": _delegate("artist_enrichment.routes", "handle_post_enrich"),
    "POST /admin/artists/{artist_id}/enrich-auto": _delegate("artist_enrichment.routes", "handle_post_enrich_auto"),
    "GET /admin/artists/enrich/options": _delegate("artist_enrichment.routes", "handle_get_options"),
    "GET /admin/artists/enrich-runs": _delegate("artist_enrichment.routes", "handle_get_runs_list"),
    "GET /admin/artists/enrich-runs/{run_id}": _delegate("artist_enrichment.routes", "handle_get_run"),
    "GET /admin/artists/backlog": _delegate("artist_enrichment.routes", "handle_get_backlog"),
    "GET /admin/artists/{artist_id}/history": _delegate("artist_enrichment.routes", "handle_get_artist_history"),
    "GET /admin/artists/{artist_id}": _delegate("artist_enrichment.routes", "handle_get_artist"),
    "GET /admin/auto-enrich/artists": _delegate("artist_enrichment.auto_routes", "handle_get_auto_config"),
    "PUT /admin/auto-enrich/artists": _delegate("artist_enrichment.auto_routes", "handle_put_auto_config"),
    "PUT /artists/{artist_id}/preference": _delegate("artist_enrichment.routes", "handle_put_artist_preference"),
    "GET /me/artist-preferences": _delegate("artist_enrichment.routes", "handle_get_my_artist_preferences"),
    "GET /artists": _delegate("artist_enrichment.routes", "handle_get_artists_list"),
    "GET /artists/{artist_id}": _delegate("artist_enrichment.routes", "handle_get_artist_user"),
}


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    ...  # unchanged body: AppError / unexpected-exception envelopes around _route


def _route(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
    route_key = _extract_route_key(event)
    if route_key in _ADMIN_ROUTES:
        _require_admin(event)
    route = _ROUTE_TABLE.get(route_key)
    if route is None:
        return _json_response(404, {"error_code": "not_found", "message": "Route not found"}, correlation_id)
    return route(event, context, correlation_id)
```

- [ ] **Step 4: Retarget patches** in `tests/`: `collector.handler.<name>` → `collector.api.deps.<name>` for the deps names above; `collector.handler._enqueue_canonicalization` / `collect_period` → `collector.api.routes_ingest.…`; `monkeypatch.setattr(handler, "<name>", …)` where `handler` is `collector.handler` → the new module object. Attribute reads such as `handler.EnqueueResult` → `routes_ingest.EnqueueResult`. Find them with `grep -rnE "collector\.handler\.[A-Za-z_]|setattr\(handler," tests`.
- [ ] **Step 5 (GREEN):** `test_collector_api_routes.py` → 6 passed; full suite green; `ruff check`; `mypy`.
- [ ] **Step 6: Commit** (`refactor(api): split handler into route modules`).

---

### Task 4: `repositories.py` → package by aggregate

**Files:** `git mv src/collector/repositories.py src/collector/repositories/__init__.py`, then create `_base.py`, `commands.py`, `runs.py`, `lineage.py`, `catalog_writes.py`, `spotify.py`, `vendor_match.py`, `api_views.py` next to it. Test: `tests/unit/test_repositories_layout.py` (new).

**Interfaces:**
- Produces: `collector.repositories` exports exactly the names it exports today (`ClouderRepository`, the 14 command/value dataclasses, `create_clouder_repository_from_env`, `utc_now`, `parse_iso_date`, `as_utc_datetime`, `_identity_params`, `_named_entity_params`); `ClouderRepository(data_api)` keeps all 51 methods.

- [ ] **Step 1: Failing test** `tests/unit/test_repositories_layout.py`:

```python
"""ClouderRepository is a facade over one module per aggregate; its API is unchanged."""

from __future__ import annotations

from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "src" / "collector" / "repositories"

API = [
    "analytics_funnel", "batch_conservative_update_tracks", "batch_create_albums", "batch_create_artists",
    "batch_create_labels", "batch_create_styles", "batch_create_tracks", "batch_update_spotify_results",
    "batch_upsert_identities", "batch_upsert_source_entities", "batch_upsert_source_relations",
    "batch_upsert_track_artists", "claim_identities", "claim_tracks_for_spotify_search", "count_albums",
    "count_artists", "count_spotify_pending_in_range", "count_tracks", "count_tracks_not_found_on_spotify",
    "coverage_for_year", "create_ingest_run", "find_identities", "find_tracks_needing_spotify_search",
    "find_tracks_not_found_on_spotify", "get_run", "get_vendor_blocked_until", "get_vendor_match",
    "insert_review_candidate", "list_albums", "list_artists", "list_replayable_runs", "list_runs_for_cell",
    "list_tracks", "list_users", "mark_no_match", "propagate_release_type_to_albums", "read_track_state",
    "release_spotify_search_claim", "reset_spotify_not_found", "set_run_completed", "set_run_failed",
    "set_style_hidden", "set_vendor_blocked_until", "spotify_search_counts", "spotify_stats_for_year",
    "transaction", "upsert_identity", "upsert_source_entity", "upsert_source_relation", "upsert_track_artist",
    "upsert_vendor_match",
]


def test_facade_keeps_its_api() -> None:
    from collector.repositories import ClouderRepository

    assert sorted(n for n in dir(ClouderRepository) if not n.startswith("_")) == API


def test_each_method_lives_in_one_aggregate_module() -> None:
    from collector.repositories import ClouderRepository

    homes = {n: getattr(ClouderRepository, n).__module__ for n in API}
    assert set(homes.values()) >= {
        "collector.repositories.runs", "collector.repositories.lineage", "collector.repositories.catalog_writes",
        "collector.repositories.spotify", "collector.repositories.vendor_match", "collector.repositories.api_views",
    }


def test_aggregate_modules_stay_small() -> None:
    for module in PKG.glob("*.py"):
        assert len(module.read_text().splitlines()) <= 600, module.name
```

- [ ] **Step 2 (RED):** run → Expected: `test_each_method_lives_in_one_aggregate_module` fails (all in `collector.repositories`), `test_aggregate_modules_stay_small` fails (no package dir → assert on glob is vacuous; it fails once `__init__.py` holds 1 713 lines after the `git mv`). `test_facade_keeps_its_api` passes today and pins the API.
- [ ] **Step 3: Split.** `git mv` first (history follows), then move method bodies verbatim:

| Module | Contents |
|---|---|
| `_base.py` | `RepositoryBase` (declares `_data_api: DataAPIClient`), `parse_iso_date`, `utc_now`, `as_utc_datetime` |
| `commands.py` | `IdentityMapEntry` … `UpsertVendorMatchCmd` (lines 28–184 today) |
| `runs.py` | `IngestRunsMixin`: `create_ingest_run`, `set_run_completed`, `set_run_failed`, `get_run`, `list_replayable_runs`, `list_runs_for_cell` |
| `lineage.py` | `LineageMixin`: `upsert_source_entity`, `batch_upsert_source_entities`, `upsert_source_relation`, `batch_upsert_source_relations`, `upsert_identity`, `batch_upsert_identities`, `find_identities`, `claim_identities`; `_identity_params` |
| `catalog_writes.py` | `CatalogWritesMixin`: `read_track_state`, `batch_create_{labels,styles,artists,albums,tracks}`, `batch_conservative_update_tracks`, `upsert_track_artist`, `batch_upsert_track_artists`, `propagate_release_type_to_albums`; `_named_entity_params` |
| `spotify.py` | `SpotifySearchMixin`: `claim_tracks_for_spotify_search`, `get_vendor_blocked_until`, `set_vendor_blocked_until`, `release_spotify_search_claim`, `find_tracks_needing_spotify_search`, `find_tracks_not_found_on_spotify`, `count_tracks_not_found_on_spotify`, `reset_spotify_not_found`, `count_spotify_pending_in_range`, `spotify_search_counts`, `batch_update_spotify_results`, `spotify_stats_for_year` |
| `vendor_match.py` | `VendorMatchMixin`: `get_vendor_match`, `upsert_vendor_match`, `insert_review_candidate`, `mark_no_match` |
| `api_views.py` | `ApiViewsMixin` (what the collector API reads, plus the admin style toggle): `list_/count_{tracks,artists,albums}`, `coverage_for_year`, `set_style_hidden`, `analytics_funnel`, `list_users` |

`__init__.py`:

```python
"""Aurora (Data API) repository for the ingest pipeline and the collector API.

`ClouderRepository` composes one mixin per aggregate; callers keep one object.
Every mixin uses only `self._data_api`, so they do not depend on each other.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from ..data_api import DataAPIClient, create_default_data_api_client
from ..settings import get_data_api_settings
from ._base import as_utc_datetime, parse_iso_date, utc_now
from .api_views import ApiViewsMixin
from .catalog_writes import CatalogWritesMixin, _named_entity_params
from .commands import (...)  # the 14 dataclasses
from .lineage import LineageMixin, _identity_params
from .runs import IngestRunsMixin
from .spotify import SpotifySearchMixin
from .vendor_match import VendorMatchMixin


class ClouderRepository(
    IngestRunsMixin, LineageMixin, CatalogWritesMixin, SpotifySearchMixin, VendorMatchMixin, ApiViewsMixin
):
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    def transaction(self) -> AbstractContextManager[None]:
        return self._data_api.transaction()


def create_clouder_repository_from_env() -> ClouderRepository | None:
    ...  # unchanged body

__all__ = [...]  # every name above, so ruff F401 and `from collector.repositories import X` keep working
```

(Use the imports the moved bodies actually need — copy from today's module header; the return type of `transaction` follows Task 2.)

- [ ] **Step 4 (GREEN):** layout test → 3 passed; full suite green (incl. `tests/unit/test_raw_sql_parses.py`, which parses the SQL in these modules — point it at the package if it reads the file path); `ruff check`; `mypy`.
- [ ] **Step 5: Commit** (`refactor(repositories): split by aggregate`).

---

### Task 5: `ruff format` + CI check + module-size guard

**Files:** `pyproject.toml` (`[tool.ruff] line-length = 100`), every Python file under `src/ tests/ scripts/`, `.git-blame-ignore-revs` (new), `.github/workflows/pr.yml` (lint job), `Makefile` (`lint`), `tests/unit/test_ci_workflows.py` (append), `tests/unit/test_module_sizes.py` (new).

- [ ] **Step 1: Failing tests:**

```python
# tests/unit/test_ci_workflows.py (append)
def test_lint_job_checks_formatting() -> None:
    wf = (ROOT / ".github" / "workflows" / "pr.yml").read_text()
    assert "ruff format --check src tests scripts" in wf
```

```python
# tests/unit/test_module_sizes.py
"""No module under src/collector grows back into a monolith."""

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "collector"
LIMIT = 1300  # the largest today (curation repositories) are ~1 250 lines after formatting


def test_no_module_over_the_limit() -> None:
    big = {p.relative_to(SRC).as_posix(): n for p in SRC.rglob("*.py") if (n := len(p.read_text().splitlines())) > LIMIT}
    assert big == {}
```

(`ROOT` as defined in `test_ci_workflows.py`; add it if missing.)

- [ ] **Step 2 (RED):** `test_lint_job_checks_formatting` fails; `test_module_sizes` passes (Tasks 3–4 already split the two monoliths) and guards from here on.
- [ ] **Step 3:** `pyproject.toml` `[tool.ruff]` gets `line-length = 100` (same churn as 88, fewer wrapped lines). Run `<venv>/ruff format src tests scripts`; `ruff check` still clean; suite green. **Commit this alone** (`style: ruff format`).
- [ ] **Step 4:** `.git-blame-ignore-revs`:

```
# ruff format of the whole Python tree (phase 5); `git blame` skips it.
<sha of the style commit>
```

`pr.yml` lint job: after `Ruff`, a step `- name: Ruff format` / `run: ruff format --check src tests scripts`. `Makefile` `lint:` adds `$(VENV)/ruff format --check src tests scripts`.
- [ ] **Step 5 (GREEN):** both tests pass; full suite green.
- [ ] **Step 6: Commit** (`ci: check ruff format`).

---

### Task 6: Docs

**Files:** `docs/backend/handlers.md` (API Lambda section: router + `collector/api/routes_*`, patch `collector.api.deps`), `docs/data/raw-ingestion.md:5` (`collector/api/routes_ingest.py`), `docs/backend/gotchas.md:79` (`handler.py` → `collector/api/routes_ingest.py`), `docs/engineering-highlights.md:11` (link → `src/collector/repositories/`), `docs/ops/deploy.md:14` (`lint` row: `ruff check`, `ruff format --check`, `mypy`), `docs/backend/testing.md` (one line: collector-API tests patch `collector.api.deps`, curation tests `collector.curation.deps`), `CLAUDE.md` "Where things are" (`src/collector/api/` routes of the collector API).

- [ ] Edit; `grep -rn "src/collector/handler.py\|repositories.py" docs README.md CLAUDE.md | grep -v -e superpowers -e archive -e postmortems` → only intended mentions remain.
- [ ] Guard tests (`test_docs_links`, `test_docs_freshness`, `test_readme`) green. Commit (`docs: collector API routes and lint gates`).

---

### Task 7: PR, review, merge, deploy, verify

- [ ] Plan commit, graphify refresh commit, push, PR (`caveman:caveman-commit`); fresh whole-branch review (exclude the `style:` commit from the review package — formatting only); one fix pass.
- [ ] Checks green → merge → Deploy green: smoke 9/9 (each API Lambda answers through `live`), alias rollback step not triggered.
- [ ] Prod: `collector-api` errors 0 in the 30 minutes after the deploy; one admin route through the SPA works (owner) or `GET /styles` 401 from the smoke stands in.
- [ ] **Rollback drill (owed by phase 3):** this deploy publishes new versions of the six API Lambdas. Record `aws lambda get-alias --function-name clouder-prod-<fn> --name live` → `N`; write `{fn: N-1}` for the six into a JSON file; `scripts/api_aliases.py restore prev.json`; run `scripts/smoke.py` (expect 9/9 on the previous code); restore `{fn: N}`; smoke again. Record timings in `docs/ops/deploy.md` Rollback ("drilled 2026-10-11: …").
- [ ] §0 board: phase 5 done; phase 3 drill noted.
