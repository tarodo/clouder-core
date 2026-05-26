# Auto Label Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user adds a track to a category (single add or triage finalize), automatically enqueue a label-enrichment search for that track's label if the label has never been successfully searched — using an admin-configured model/prompt set, with a one-retry cap on failures.

**Architecture:** A best-effort dispatch helper runs inline in the curation handlers *after* their DB writes commit. It reads a singleton config row, atomically claims eligible labels via a dedicated state table (closing the concurrent-add race), creates one `source='auto'` enrichment run, and fans the labels onto the existing `LABEL_ENRICHMENT_QUEUE_URL`. The existing worker processes them in the background — curation never waits for search results. The worker, on completion, stamps each auto-claimed label's state (`completed`/`failed`) so failures can retry exactly once and in-flight labels are skipped.

**Tech Stack:** Python 3.12 Lambdas (collector API + label_enrichment worker), Aurora via RDS Data API, SQS, Alembic migrations, Terraform (API Gateway HTTP routes), React 19 + Mantine 9 + TanStack Query frontend, pytest + Vitest.

---

## Reference: existing pieces this plan reuses

- Enqueue handler: `src/collector/label_enrichment/routes.py:61` (`handle_post_enrich`), options: `:266` (`handle_get_options`).
- Request schema: `src/collector/label_enrichment/messages.py:40` (`EnrichLabelsRequestIn`), SQS message: `:13` (`LabelEnrichmentMessage`).
- Repository: `src/collector/label_enrichment/repository.py` — `RunSpec` (`:64`), `create_run` (`:564`), `get_label_by_id` (`:86`), `derive_style_for_label` (`:516`), `list_runs` (`:369`).
- Worker orchestration: `src/collector/label_enrichment/orchestrator.py:73` (`enrich_label_for_run`); worker entry: `src/collector/label_enrichment_handler.py:46`.
- Curation handlers: `src/collector/curation_handler.py:551` (`_handle_add_track`), `:1309` (`_finalize_triage_block`).
- Main router + admin gate: `src/collector/handler.py` — `_ADMIN_ROUTES` (`:61`), `lambda_handler` (`:88`), route dispatch branches (`~:160`).
- Data API client: `src/collector/data_api.py:14` (`DataAPIClient.execute`, `.transaction`).
- OpenAPI route list: `scripts/generate_openapi.py` `ROUTES` (label-enrichment block starts `:1149`).
- API Gateway routes: `infra/api_gateway.tf` (e.g. `labels_enrich_post` `:113`). Collector lambda env already has `LABEL_ENRICHMENT_QUEUE_URL` + SQS perms (`infra/lambda.tf:21`, `infra/iam.tf:92`).
- Frontend: hooks `frontend/src/features/admin/hooks/`, drawer `frontend/src/features/admin/components/enrichment/EnqueueDrawer.tsx`, types `frontend/src/api/labels.ts`, client `frontend/src/api/client.ts:48`, router `frontend/src/routes/router.tsx:111` (admin children).

## File Structure

**Create (backend):**
- `alembic/versions/20260525_25_auto_enrich.py` — migration: `source` column on runs, `auto_enrich_config`, `label_auto_enrich_state`.
- `src/collector/label_enrichment/auto_messages.py` — `AutoEnrichConfigIn` pydantic body.
- `src/collector/label_enrichment/auto_repository.py` — `AutoEnrichRepository`: config get/upsert, label claim, run attach, outcome stamp, label-id lookups.
- `src/collector/label_enrichment/auto_dispatch.py` — `try_dispatch_for_triage_block`, `try_dispatch_for_track`, internal `_dispatch_labels`.
- `src/collector/label_enrichment/auto_routes.py` — `handle_get_auto_config`, `handle_put_auto_config`.

**Create (frontend):**
- `frontend/src/api/autoEnrich.ts` — typed aliases.
- `frontend/src/features/admin/hooks/useAutoEnrichConfig.ts`, `useSaveAutoEnrichConfig.ts`.
- `frontend/src/features/admin/components/enrichment/EnrichConfigForm.tsx` — extracted controlled form.
- `frontend/src/features/admin/routes/AdminAutoEnrichPage.tsx` — tabs window.

**Modify (backend):**
- `src/collector/label_enrichment/repository.py` — `RunSpec.source` + `create_run` + `list_runs`.
- `src/collector/label_enrichment/orchestrator.py` — `enrich_label_for_run(..., on_outcome=None)`.
- `src/collector/label_enrichment_handler.py` — build `AutoEnrichRepository`, pass `on_outcome`.
- `src/collector/label_enrichment/routes.py` — `handle_get_runs_list` accepts `source` filter.
- `src/collector/handler.py` — `_ADMIN_ROUTES` + dispatch branches for the 2 new routes.
- `src/collector/curation_handler.py` — best-effort dispatch calls in `_handle_add_track` + `_finalize_triage_block`.
- `infra/api_gateway.tf` — 2 new `aws_apigatewayv2_route` resources.
- `scripts/generate_openapi.py` — 2 new `ROUTES` entries + `source` on runs-list response/param.

**Modify (frontend):**
- `frontend/src/features/admin/components/enrichment/EnqueueDrawer.tsx` — use `EnrichConfigForm`.
- `frontend/src/routes/router.tsx` — register `/admin/auto-enrich`.
- `frontend/src/features/admin/routes/AdminLayout.tsx` — nav link (inspect to match existing nav pattern).

**Regenerate:** `docs/api/openapi.yaml` + `frontend/src/api/schema.d.ts`.

---

## Phase 1 — Schema

### Task 1: Migration — source column, config + state tables

**Files:**
- Create: `alembic/versions/20260525_25_auto_enrich.py`

- [ ] **Step 1: Write the migration**

```python
"""auto label enrichment: source column, config + state tables

Revision ID: 20260525_25
Revises: 20260522_24
Create Date: 2026-05-25 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260525_25"
down_revision = "20260522_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clouder_label_enrichment_runs",
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'manual'")),
    )

    op.create_table(
        "auto_enrich_config",
        sa.Column("kind", sa.Text, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("vendors", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("models", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("prompt_slug", sa.Text),
        sa.Column("prompt_version", sa.Text),
        sa.Column("merge_vendor", sa.Text),
        sa.Column("merge_model", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.String(36)),
    )

    op.create_table(
        "label_auto_enrich_state",
        sa.Column(
            "label_id", sa.String(36),
            sa.ForeignKey("clouder_labels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column(
            "last_run_id", sa.String(36),
            sa.ForeignKey("clouder_label_enrichment_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("first_enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_label_auto_enrich_state_status",
        "label_auto_enrich_state",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_label_auto_enrich_state_status", table_name="label_auto_enrich_state")
    op.drop_table("label_auto_enrich_state")
    op.drop_table("auto_enrich_config")
    op.drop_column("clouder_label_enrichment_runs", "source")
```

- [ ] **Step 2: Verify migration imports cleanly**

Run: `PYTHONPATH=src python3 -c "import ast; ast.parse(open('alembic/versions/20260525_25_auto_enrich.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Confirm single head**

Run: `cd /Users/roman/Projects/clouder-projects/clouder-core && grep -rl 'down_revision = "20260522_24"' alembic/versions/`
Expected: only `20260525_25_auto_enrich.py` (no second migration branches off 24).

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/20260525_25_auto_enrich.py
git commit -m "feat(db): add auto-enrich config + label state tables"
```

> Note: this repo runs Alembic against a real Postgres (`ALEMBIC_DATABASE_URL`) and the new tables are migration-only (not in `db_models.py`, matching the existing enrichment tables). No SQLAlchemy model needed.

---

## Phase 2 — Config repository, schema, routes

### Task 2: AutoEnrichConfigIn body schema

**Files:**
- Create: `src/collector/label_enrichment/auto_messages.py`
- Test: `tests/unit/test_auto_enrich_messages.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from pydantic import ValidationError

from collector.label_enrichment.auto_messages import AutoEnrichConfigIn


def test_disabled_config_allows_empty_fields():
    cfg = AutoEnrichConfigIn.model_validate({"enabled": False})
    assert cfg.enabled is False
    assert cfg.vendors == []
    assert cfg.models == {}


def test_enabled_requires_vendors():
    with pytest.raises(ValidationError, match="vendors required"):
        AutoEnrichConfigIn.model_validate({"enabled": True, "vendors": []})


def test_enabled_requires_model_per_vendor():
    with pytest.raises(ValidationError, match="model missing for vendor 'gemini'"):
        AutoEnrichConfigIn.model_validate({
            "enabled": True, "vendors": ["gemini"], "models": {},
            "prompt_slug": "s", "prompt_version": "v", "merge_model": "m",
        })


def test_enabled_requires_prompt_and_merge_model():
    with pytest.raises(ValidationError, match="prompt required"):
        AutoEnrichConfigIn.model_validate({
            "enabled": True, "vendors": ["gemini"],
            "models": {"gemini": "g"}, "merge_model": "m",
        })


def test_enabled_full_config_ok():
    cfg = AutoEnrichConfigIn.model_validate({
        "enabled": True, "vendors": ["gemini", "openai"],
        "models": {"gemini": "g", "openai": "o"},
        "prompt_slug": "label_v3", "prompt_version": "v1",
        "merge_vendor": "deepseek", "merge_model": "deepseek-v4-flash",
    })
    assert cfg.vendors == ["gemini", "openai"]
    assert cfg.merge_vendor == "deepseek"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_auto_enrich_messages.py -q`
Expected: FAIL — `ModuleNotFoundError: collector.label_enrichment.auto_messages`

- [ ] **Step 3: Write the implementation**

```python
"""PUT body schema for auto-enrichment config."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AutoEnrichConfigIn(BaseModel):
    """PUT /admin/auto-enrich/labels body.

    When `enabled` is False the model/prompt fields may be partial — the admin
    can switch the feature off without re-entering a full config. When True the
    same completeness rules as a manual enqueue apply.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    vendors: list[Literal["gemini", "openai", "tavily_deepseek"]] = Field(default_factory=list)
    models: dict[str, str] = Field(default_factory=dict)
    prompt_slug: str | None = None
    prompt_version: str | None = None
    merge_vendor: Literal["deepseek"] = "deepseek"
    merge_model: str | None = None

    @model_validator(mode="after")
    def _validate_when_enabled(self) -> "AutoEnrichConfigIn":
        if not self.enabled:
            return self
        if not self.vendors:
            raise ValueError("vendors required when enabled")
        for vendor in self.vendors:
            if vendor not in self.models or not self.models[vendor].strip():
                raise ValueError(f"model missing for vendor {vendor!r}")
        if not self.prompt_slug or not self.prompt_version:
            raise ValueError("prompt required when enabled")
        if not self.merge_model or not self.merge_model.strip():
            raise ValueError("merge_model required when enabled")
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_auto_enrich_messages.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/auto_messages.py tests/unit/test_auto_enrich_messages.py
git commit -m "feat(enrich): add auto-enrich config request schema"
```

---

### Task 3: AutoEnrichRepository — config get/upsert

**Files:**
- Create: `src/collector/label_enrichment/auto_repository.py`
- Test: `tests/unit/test_auto_enrich_repository.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_auto_enrich_repository.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
"""Aurora Data API persistence for auto-enrichment config + label claim state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..data_api import DataAPIClient

_MAX_ATTEMPTS = 2
_STALE_QUEUED_HOURS = 6


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_json_col(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


class AutoEnrichRepository:
    def __init__(
        self,
        data_api: DataAPIClient,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._data_api = data_api
        self._now = now

    # ── config ──────────────────────────────────────────────────────
    def get_config(self, kind: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            """
            SELECT kind, enabled, vendors, models, prompt_slug, prompt_version,
                   merge_vendor, merge_model
            FROM auto_enrich_config
            WHERE kind = :kind
            LIMIT 1
            """,
            {"kind": kind},
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["vendors"] = _parse_json_col(row.get("vendors"), [])
        row["models"] = _parse_json_col(row.get("models"), {})
        row["enabled"] = bool(row.get("enabled"))
        return row

    def upsert_config(
        self,
        *,
        kind: str,
        enabled: bool,
        vendors: list[str],
        models: dict[str, str],
        prompt_slug: str | None,
        prompt_version: str | None,
        merge_vendor: str | None,
        merge_model: str | None,
        user_id: str | None,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO auto_enrich_config (
                kind, enabled, vendors, models, prompt_slug, prompt_version,
                merge_vendor, merge_model, updated_at, updated_by_user_id
            ) VALUES (
                :kind, :enabled, :vendors, :models, :prompt_slug, :prompt_version,
                :merge_vendor, :merge_model, :updated_at, :updated_by_user_id
            )
            ON CONFLICT (kind) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                vendors = EXCLUDED.vendors,
                models = EXCLUDED.models,
                prompt_slug = EXCLUDED.prompt_slug,
                prompt_version = EXCLUDED.prompt_version,
                merge_vendor = EXCLUDED.merge_vendor,
                merge_model = EXCLUDED.merge_model,
                updated_at = EXCLUDED.updated_at,
                updated_by_user_id = EXCLUDED.updated_by_user_id
            """,
            {
                "kind": kind,
                "enabled": enabled,
                "vendors": list(vendors),
                "models": dict(models),
                "prompt_slug": prompt_slug,
                "prompt_version": prompt_version,
                "merge_vendor": merge_vendor,
                "merge_model": merge_model,
                "updated_at": self._now(),
                "updated_by_user_id": user_id,
            },
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_auto_enrich_repository.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/auto_repository.py tests/unit/test_auto_enrich_repository.py
git commit -m "feat(enrich): add auto-enrich config repository"
```

---

### Task 4: Config HTTP handlers (GET + PUT)

**Files:**
- Create: `src/collector/label_enrichment/auto_routes.py`
- Test: `tests/unit/test_auto_enrich_routes.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from unittest.mock import MagicMock, patch

from collector.label_enrichment import auto_routes


def _put_event(body: dict) -> dict:
    return {
        "body": json.dumps(body),
        "requestContext": {"authorizer": {"lambda": {"user_id": "user-1"}}},
    }


def test_get_returns_defaults_when_no_config():
    repo = MagicMock()
    repo.get_config.return_value = None
    with patch.object(auto_routes, "_build_repository", return_value=repo):
        status, body = auto_routes.handle_get_auto_config({})
    assert status == 200
    assert body["config"]["enabled"] is False
    assert body["config"]["merge_vendor"] == "deepseek"
    # options block mirrors the manual enqueue options
    assert set(body["options"]["vendors"]) <= {"gemini", "openai", "tavily_deepseek"}
    assert body["options"]["default_models"]["openai"] == "gpt-5.4-mini"


def test_get_returns_saved_config():
    repo = MagicMock()
    repo.get_config.return_value = {
        "kind": "labels", "enabled": True, "vendors": ["gemini"],
        "models": {"gemini": "g"}, "prompt_slug": "s", "prompt_version": "v",
        "merge_vendor": "deepseek", "merge_model": "m",
    }
    with patch.object(auto_routes, "_build_repository", return_value=repo):
        status, body = auto_routes.handle_get_auto_config({})
    assert status == 200
    assert body["config"]["enabled"] is True
    assert body["config"]["vendors"] == ["gemini"]


def test_put_validation_error_when_enabled_without_vendors():
    with patch.object(auto_routes, "_build_repository", return_value=MagicMock()):
        try:
            auto_routes.handle_put_auto_config(_put_event({"enabled": True, "vendors": []}))
            assert False, "expected ValidationError"
        except Exception as exc:  # ValidationError from collector.errors
            assert "vendors required" in str(exc)


def test_put_persists_and_returns_204():
    repo = MagicMock()
    with patch.object(auto_routes, "_build_repository", return_value=repo):
        status, body = auto_routes.handle_put_auto_config(_put_event({
            "enabled": True, "vendors": ["gemini"], "models": {"gemini": "g"},
            "prompt_slug": "s", "prompt_version": "v",
            "merge_vendor": "deepseek", "merge_model": "m",
        }))
    assert status == 204
    repo.upsert_config.assert_called_once()
    kwargs = repo.upsert_config.call_args.kwargs
    assert kwargs["kind"] == "labels"
    assert kwargs["enabled"] is True
    assert kwargs["user_id"] == "user-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_auto_enrich_routes.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
"""HTTP handlers for auto-enrichment config (labels only for now)."""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from ..data_api import create_default_data_api_client
from ..errors import ValidationError
from ..settings import get_data_api_settings
from .auto_messages import AutoEnrichConfigIn
from .auto_repository import AutoEnrichRepository

_KIND = "labels"


def _build_repository() -> AutoEnrichRepository:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return AutoEnrichRepository(data_api=client)


def _extract_user_id(event: Mapping[str, Any]) -> str | None:
    rc = event.get("requestContext")
    if not isinstance(rc, Mapping):
        return None
    authz = rc.get("authorizer")
    if not isinstance(authz, Mapping):
        return None
    ctx = authz.get("lambda")
    if isinstance(ctx, Mapping):
        return ctx.get("user_id")
    return None


def _options() -> dict[str, Any]:
    """Same payload shape the manual enqueue form consumes."""
    from .prompts import list_prompt_versions, load_builtin_prompts

    load_builtin_prompts()
    return {
        "vendors": ["gemini", "openai", "tavily_deepseek"],
        "prompt_versions": list_prompt_versions(),
        "default_models": {
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-5.4-mini",
            "tavily_deepseek": "deepseek-v4-flash",
        },
        "merge": {"vendor": "deepseek", "default_model": "deepseek-v4-flash"},
    }


def _default_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "vendors": [],
        "models": {},
        "prompt_slug": None,
        "prompt_version": None,
        "merge_vendor": "deepseek",
        "merge_model": None,
    }


def handle_get_auto_config(event: Mapping[str, Any]) -> tuple[int, dict]:
    del event  # static + singleton config
    repo = _build_repository()
    saved = repo.get_config(_KIND)
    if saved is None:
        config = _default_config()
    else:
        config = {
            "enabled": bool(saved["enabled"]),
            "vendors": saved["vendors"],
            "models": saved["models"],
            "prompt_slug": saved.get("prompt_slug"),
            "prompt_version": saved.get("prompt_version"),
            "merge_vendor": saved.get("merge_vendor") or "deepseek",
            "merge_model": saved.get("merge_model"),
        }
    return 200, {"config": config, "options": _options()}


def handle_put_auto_config(event: Mapping[str, Any]) -> tuple[int, dict]:
    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON body: {exc}")
    try:
        req = AutoEnrichConfigIn.model_validate(body)
    except PydanticValidationError as exc:
        raise ValidationError(exc.errors()[0]["msg"]) from exc

    repo = _build_repository()
    repo.upsert_config(
        kind=_KIND,
        enabled=req.enabled,
        vendors=list(req.vendors),
        models=dict(req.models),
        prompt_slug=req.prompt_slug,
        prompt_version=req.prompt_version,
        merge_vendor=req.merge_vendor,
        merge_model=req.merge_model,
        user_id=_extract_user_id(event),
    )
    return 204, {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_auto_enrich_routes.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/auto_routes.py tests/unit/test_auto_enrich_routes.py
git commit -m "feat(enrich): add auto-enrich config GET/PUT handlers"
```

---

### Task 5: Wire config routes into the API lambda

**Files:**
- Modify: `src/collector/handler.py` — `_ADMIN_ROUTES` (`:61`) + dispatch branches (after the existing `GET /admin/labels/...` branches, ~`:183`)
- Test: `tests/unit/test_auto_enrich_handler_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from unittest.mock import MagicMock, patch


def _admin_event(method_path: str, body: dict | None = None) -> dict:
    return {
        "routeKey": method_path,
        "queryStringParameters": None,
        "pathParameters": {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"lambda": {"is_admin": True, "user_id": "u1"}}},
    }


def test_get_auto_config_routed():
    from collector import handler
    repo = MagicMock()
    repo.get_config.return_value = None
    with patch("collector.label_enrichment.auto_routes._build_repository", return_value=repo):
        resp = handler.lambda_handler(_admin_event("GET /admin/auto-enrich/labels"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["config"]["enabled"] is False


def test_put_auto_config_routed_returns_204():
    from collector import handler
    repo = MagicMock()
    with patch("collector.label_enrichment.auto_routes._build_repository", return_value=repo):
        resp = handler.lambda_handler(_admin_event(
            "PUT /admin/auto-enrich/labels",
            {"enabled": False},
        ), None)
    assert resp["statusCode"] == 204


def test_auto_config_requires_admin():
    from collector import handler
    event = _admin_event("GET /admin/auto-enrich/labels")
    event["requestContext"]["authorizer"]["lambda"]["is_admin"] = False
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_auto_enrich_handler_wiring.py -q`
Expected: FAIL — routes return 404 / not admin-gated yet

- [ ] **Step 3: Add the two routes to `_ADMIN_ROUTES`**

In `src/collector/handler.py`, inside the `_ADMIN_ROUTES = frozenset({ ... })` block, add:

```python
    "GET /admin/auto-enrich/labels",
    "PUT /admin/auto-enrich/labels",
```

- [ ] **Step 4: Add dispatch branches**

In `src/collector/handler.py`, immediately after the `if route_key == "GET /admin/labels/{label_id}":` branch (the block ending with its `return _json_response(...)`), add:

```python
    if route_key == "GET /admin/auto-enrich/labels":
        from .label_enrichment.auto_routes import handle_get_auto_config
        status, body = handle_get_auto_config(event)
        return _json_response(status, body, correlation_id)
    if route_key == "PUT /admin/auto-enrich/labels":
        from .label_enrichment.auto_routes import handle_put_auto_config
        status, body = handle_put_auto_config(event)
        if status == 204:
            return {
                "statusCode": 204,
                "headers": {"x-correlation-id": correlation_id},
                "body": "",
            }
        return _json_response(status, body, correlation_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_auto_enrich_handler_wiring.py -q`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/collector/handler.py tests/unit/test_auto_enrich_handler_wiring.py
git commit -m "feat(api): route auto-enrich config endpoints"
```

---

### Task 6: Infra routes + OpenAPI for config endpoints

**Files:**
- Modify: `infra/api_gateway.tf`
- Modify: `scripts/generate_openapi.py`
- Regenerate: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`

- [ ] **Step 1: Add API Gateway routes**

Append to `infra/api_gateway.tf` (mirror the `labels_enrich_post` block at `:113`):

```hcl
resource "aws_apigatewayv2_route" "auto_enrich_labels_get" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /admin/auto-enrich/labels"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "auto_enrich_labels_put" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "PUT /admin/auto-enrich/labels"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 2: Add OpenAPI ROUTES entries**

In `scripts/generate_openapi.py`, find the label-enrichment block (starts `:1149`) and add these two entries inside the `ROUTES` list (use `ADMIN` for `auth`, consistent with neighbours). Define the schemas inline:

```python
    {
        "method": "get",
        "path": "/admin/auto-enrich/labels",
        "auth": ADMIN,
        "summary": "Admin: get auto-enrichment config for labels + form options.",
        "responses": {
            "200": _make_response(
                200,
                "Saved config (or defaults) plus the model/prompt options.",
                {
                    "type": "object",
                    "required": ["config", "options"],
                    "properties": {
                        "config": {
                            "type": "object",
                            "required": ["enabled", "vendors", "models", "merge_vendor"],
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "vendors": {"type": "array", "items": {"type": "string"}},
                                "models": {"type": "object", "additionalProperties": {"type": "string"}},
                                "prompt_slug": {"type": "string", "nullable": True},
                                "prompt_version": {"type": "string", "nullable": True},
                                "merge_vendor": {"type": "string"},
                                "merge_model": {"type": "string", "nullable": True},
                            },
                        },
                        "options": ENRICHMENT_OPTIONS,
                    },
                },
            ),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "put",
        "path": "/admin/auto-enrich/labels",
        "auth": ADMIN,
        "summary": "Admin: upsert auto-enrichment config for labels.",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["enabled"],
                        "properties": {
                            "enabled": {"type": "boolean"},
                            "vendors": {"type": "array", "items": {"type": "string"}},
                            "models": {"type": "object", "additionalProperties": {"type": "string"}},
                            "prompt_slug": {"type": "string", "nullable": True},
                            "prompt_version": {"type": "string", "nullable": True},
                            "merge_vendor": {"type": "string", "enum": ["deepseek"]},
                            "merge_model": {"type": "string", "nullable": True},
                        },
                    },
                }
            },
        },
        "responses": {
            "204": {"description": "Config saved."},
            "400": _error(400, "validation_error."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
```

If a reusable `ENRICHMENT_OPTIONS` schema constant does not already exist next to `LABEL_ENRICH_REQUEST`, define it near the other schema constants in `scripts/generate_openapi.py`:

```python
ENRICHMENT_OPTIONS = {
    "type": "object",
    "required": ["vendors", "prompt_versions", "default_models", "merge"],
    "properties": {
        "vendors": {"type": "array", "items": {"type": "string"}},
        "prompt_versions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "version": {"type": "string"},
                    "is_default": {"type": "boolean"},
                },
            },
        },
        "default_models": {"type": "object", "additionalProperties": {"type": "string"}},
        "merge": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "default_model": {"type": "string"},
            },
        },
    },
}
```

> Before writing this, open `scripts/generate_openapi.py` and check whether the existing `GET /admin/labels/enrich/options` entry already references a named options schema constant — if so, reuse that exact constant instead of defining a new one, and match its property names.

- [ ] **Step 3: Regenerate OpenAPI + frontend schema**

Run:
```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
cd frontend && pnpm run gen:api 2>/dev/null || true
```
(Generation command for `schema.d.ts` may differ — check `frontend/package.json` scripts; the CI diff-checks `schema.d.ts` against `openapi.yaml`, so regenerate by the project's documented method.)

Expected: `docs/api/openapi.yaml` now contains `/admin/auto-enrich/labels`; `frontend/src/api/schema.d.ts` gains the matching `paths` entries.

- [ ] **Step 4: Verify generation is clean**

Run: `cd /Users/roman/Projects/clouder-projects/clouder-core && grep -c "auto-enrich" docs/api/openapi.yaml frontend/src/api/schema.d.ts`
Expected: both > 0.

- [ ] **Step 5: Commit**

```bash
git add infra/api_gateway.tf scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts
git commit -m "feat(api): declare auto-enrich config routes + schema"
```

---

## Phase 3 — Claim, run source, dispatch, worker outcome

### Task 7: Add `source` to RunSpec, create_run, list_runs

**Files:**
- Modify: `src/collector/label_enrichment/repository.py` — `RunSpec` (`:64`), `create_run` (`:564`), `list_runs` (`:369`)
- Test: `tests/unit/test_label_enrichment_repository.py` (extend)

- [ ] **Step 1: Write the failing tests** (append to existing file)

```python
def test_create_run_defaults_source_manual():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    spec = RunSpec(
        prompt_slug="s", prompt_version="v", vendors=["gemini"],
        models={"gemini": "g"}, merge_vendor="deepseek", merge_model="m",
        requested_labels=1,
    )
    repo.create_run(spec)
    _, params = data_api.execute.call_args[0]
    assert params["source"] == "manual"


def test_create_run_accepts_source_auto():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    spec = RunSpec(
        prompt_slug="s", prompt_version="v", vendors=["gemini"],
        models={"gemini": "g"}, merge_vendor="deepseek", merge_model="m",
        requested_labels=1, source="auto",
    )
    repo.create_run(spec)
    sql, params = data_api.execute.call_args[0]
    assert "source" in sql
    assert params["source"] == "auto"


def test_list_runs_source_filter_adds_predicate():
    repo, data_api = _repo_with_fake()
    data_api.execute.return_value = []
    repo.list_runs(status=None, cursor=None, limit=10, source="auto")
    sql, params = data_api.execute.call_args[0]
    assert "source = :source" in sql
    assert params["source"] == "auto"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_label_enrichment_repository.py -k "source" -q`
Expected: FAIL — `RunSpec` has no `source`; `list_runs` has no `source` kwarg

- [ ] **Step 3: Add `source` to `RunSpec`**

In `repository.py`, in the `RunSpec` dataclass (`:64`), add after `created_by_user_id`:

```python
    source: str = "manual"
```

- [ ] **Step 4: Include `source` in `create_run`**

In `create_run` (`:564`), change the INSERT column list + values to include `source`, and add it to the params dict:

```python
        self._data_api.execute(
            """
            INSERT INTO clouder_label_enrichment_runs (
                id, status, prompt_slug, prompt_version, vendors, models,
                merge_vendor, merge_model, requested_labels, cells_total,
                cells_ok, cells_error, cost_usd, created_by_user_id, created_at,
                source
            ) VALUES (
                :id, :status, :prompt_slug, :prompt_version, :vendors, :models,
                :merge_vendor, :merge_model, :requested_labels, :cells_total,
                0, 0, 0, :created_by_user_id, :created_at,
                :source
            )
            """,
            {
                "id": run_id,
                "status": "queued",
                "prompt_slug": spec.prompt_slug,
                "prompt_version": spec.prompt_version,
                "vendors": list(spec.vendors),
                "models": dict(spec.models),
                "merge_vendor": spec.merge_vendor,
                "merge_model": spec.merge_model,
                "requested_labels": spec.requested_labels,
                "cells_total": spec.requested_labels * len(spec.vendors),
                "created_by_user_id": spec.created_by_user_id,
                "created_at": ts,
                "source": spec.source,
            },
        )
```

- [ ] **Step 5: Add `source` filter to `list_runs`**

In `list_runs` (`:369`), add `source: str | None = None` to the signature, add the SELECT column `source`, and add the predicate:

```python
    def list_runs(
        self,
        *,
        status: str | None,
        cursor: str | None,
        limit: int,
        source: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
```

After the existing `if status:` predicate block, add:

```python
        if source:
            where.append("source = :source")
            params["source"] = source
```

And add `source` to the SELECT column list in the query (`SELECT id, status, ..., started_at, finished_at, source`).

- [ ] **Step 6: Run to verify pass**

Run: `pytest tests/unit/test_label_enrichment_repository.py -k "source or create_run or list_runs" -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/collector/label_enrichment/repository.py tests/unit/test_label_enrichment_repository.py
git commit -m "feat(enrich): add run source (manual/auto) to runs"
```

---

### Task 8: Claim, attach-run, outcome, label-id lookups on AutoEnrichRepository

**Files:**
- Modify: `src/collector/label_enrichment/auto_repository.py`
- Test: `tests/unit/test_auto_enrich_repository.py` (extend)

- [ ] **Step 1: Write the failing tests** (append)

```python
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
    # UPDATE claims it → INSERT not attempted for this label
    data_api.execute.side_effect = [[{"label_id": "lbl-2"}]]
    claimed = repo.claim_labels(["lbl-2"])
    assert claimed == ["lbl-2"]
    assert data_api.execute.call_count == 1  # update claimed; no insert
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
    assert "status = 'completed'" in sql
    assert "WHERE label_id = :label_id AND status = 'queued'" in sql
    assert params["label_id"] == "lbl-1"


def test_mark_outcome_failed_on_failure():
    repo, data_api = _repo()
    data_api.execute.return_value = []
    repo.mark_auto_enrich_outcome("lbl-1", False)
    sql, _ = data_api.execute.call_args[0]
    assert "status = 'failed'" in sql


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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_auto_enrich_repository.py -q`
Expected: FAIL — methods not defined

- [ ] **Step 3: Implement the methods** (append to `AutoEnrichRepository` in `auto_repository.py`)

```python
    # ── claim / state ───────────────────────────────────────────────
    def claim_labels(self, label_ids: list[str]) -> list[str]:
        """Atomically claim labels eligible for an auto-search.

        Per label, two independent statements:
          1. Reclaim an existing row that is `failed` (retry, capped at
             _MAX_ATTEMPTS) or a stale `queued` (worker likely died / enqueue
             failed). Returns the row when it claims it.
          2. Only if (1) claimed nothing: insert a brand-new row, but skip if a
             clouder_label_info row already exists (label was searched before,
             e.g. manually).
        `completed` rows and fresh `queued` rows match neither → skipped.
        ON CONFLICT DO NOTHING + the row-level UPDATE make concurrent adds of
        the same label race-safe: exactly one writer claims.
        """
        if not label_ids:
            return []
        now = self._now()
        stale_cutoff = now - timedelta(hours=_STALE_QUEUED_HOURS)
        claimed: list[str] = []
        for label_id in label_ids:
            params = {
                "label_id": label_id,
                "ts": now,
                "max_attempts": _MAX_ATTEMPTS,
                "stale_cutoff": stale_cutoff,
            }
            reclaimed = self._data_api.execute(
                """
                UPDATE label_auto_enrich_state
                SET attempts = attempts + 1,
                    status = 'queued',
                    last_run_id = NULL,
                    updated_at = :ts
                WHERE label_id = :label_id
                  AND attempts < :max_attempts
                  AND (
                        status = 'failed'
                     OR (status = 'queued' AND updated_at < :stale_cutoff)
                  )
                RETURNING label_id
                """,
                params,
            )
            if reclaimed:
                claimed.append(label_id)
                continue
            inserted = self._data_api.execute(
                """
                INSERT INTO label_auto_enrich_state (
                    label_id, attempts, status, first_enqueued_at, updated_at
                )
                SELECT :label_id, 1, 'queued', :ts, :ts
                WHERE NOT EXISTS (
                    SELECT 1 FROM label_auto_enrich_state WHERE label_id = :label_id
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM clouder_label_info WHERE label_id = :label_id
                )
                ON CONFLICT (label_id) DO NOTHING
                RETURNING label_id
                """,
                {"label_id": label_id, "ts": now},
            )
            if inserted:
                claimed.append(label_id)
        return claimed

    def attach_run(self, label_ids: list[str], run_id: str) -> None:
        for label_id in label_ids:
            self._data_api.execute(
                """
                UPDATE label_auto_enrich_state
                SET last_run_id = :run_id, updated_at = :ts
                WHERE label_id = :label_id
                """,
                {"run_id": run_id, "label_id": label_id, "ts": self._now()},
            )

    def mark_auto_enrich_outcome(self, label_id: str, success: bool) -> None:
        """Worker touch: flip a queued auto-state row to completed/failed.

        No-op for labels with no auto-state row (manual runs) or already
        resolved rows — the `status = 'queued'` guard handles that.
        """
        new_status = "completed" if success else "failed"
        self._data_api.execute(
            f"""
            UPDATE label_auto_enrich_state
            SET status = '{new_status}', updated_at = :ts
            WHERE label_id = :label_id AND status = 'queued'
            """,
            {"label_id": label_id, "ts": self._now()},
        )

    # ── label lookups ───────────────────────────────────────────────
    def label_id_for_track(self, track_id: str) -> str | None:
        rows = self._data_api.execute(
            """
            SELECT a.label_id
            FROM clouder_tracks t
            JOIN clouder_albums a ON a.id = t.album_id
            WHERE t.id = :track_id AND a.label_id IS NOT NULL
            LIMIT 1
            """,
            {"track_id": track_id},
        )
        return rows[0]["label_id"] if rows else None

    def label_ids_for_triage_block(self, block_id: str) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT DISTINCT a.label_id
            FROM category_tracks ct
            JOIN clouder_tracks t ON t.id = ct.track_id
            JOIN clouder_albums a ON a.id = t.album_id
            WHERE ct.source_triage_block_id = :block_id
              AND a.label_id IS NOT NULL
            """,
            {"block_id": block_id},
        )
        return [r["label_id"] for r in rows]
```

> Note on `mark_auto_enrich_outcome`: `new_status` is interpolated from a fixed two-value branch (never user input), so there is no injection surface. Keep it as a literal in SQL rather than a bound param to avoid a needless parameter.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/unit/test_auto_enrich_repository.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/auto_repository.py tests/unit/test_auto_enrich_repository.py
git commit -m "feat(enrich): add label claim + outcome state to auto repo"
```

---

### Task 9: Dispatch orchestration

**Files:**
- Create: `src/collector/label_enrichment/auto_dispatch.py`
- Test: `tests/unit/test_auto_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
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
    sqs.send_message.assert_not_called()


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
    le_repo.get_label_by_id.side_effect = lambda i: {"id": i, "name": f"name-{i}"}
    le_repo.derive_style_for_label.return_value = "techno"
    le_repo.create_run.return_value = "run-1"
    sqs = MagicMock()
    with _patch_clients(auto_repo, le_repo, sqs):
        auto_dispatch._dispatch_labels(
            label_ids=["lbl-1", "lbl-2"], source_hint="triage", user_id="u1",
        )
    spec = le_repo.create_run.call_args[0][0]
    assert spec.source == "auto"
    assert spec.requested_labels == 2
    assert spec.vendors == ["gemini"]
    auto_repo.attach_run.assert_called_once_with(["lbl-1", "lbl-2"], "run-1")
    assert sqs.send_message.call_count == 2
    body = json.loads(sqs.send_message.call_args_list[0].kwargs["MessageBody"])
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
    sqs.send_message.assert_not_called()


def test_try_dispatch_for_track_swallows_errors():
    with patch.object(auto_dispatch, "_build_auto_repository", side_effect=RuntimeError("boom")):
        # must not raise
        auto_dispatch.try_dispatch_for_track(track_id="t1", user_id="u1")


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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_auto_dispatch.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
"""Best-effort auto-enrichment dispatch from curation actions.

Called inline from the curation handlers AFTER their DB writes commit. Only
enqueues work onto the existing label-enrichment SQS queue — the worker runs
the searches in the background, so curation never waits for results. Every
public entrypoint swallows exceptions: auto-search must never break curation.
"""

from __future__ import annotations

import json
import os
from typing import Iterable

from ..data_api import DataAPIClient, create_default_data_api_client
from ..logging_utils import log_event
from ..settings import get_data_api_settings
from .auto_repository import AutoEnrichRepository
from .repository import LabelEnrichmentRepository, RunSpec

_KIND = "labels"


def _build_data_api() -> DataAPIClient:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    return create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )


def _build_auto_repository() -> AutoEnrichRepository:
    return AutoEnrichRepository(data_api=_build_data_api())


def _build_label_repository() -> LabelEnrichmentRepository:
    return LabelEnrichmentRepository(data_api=_build_data_api())


def _build_sqs_client():
    import boto3
    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("LABEL_ENRICHMENT_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("LABEL_ENRICHMENT_QUEUE_URL is required")
    return url


def _dispatch_labels(*, label_ids: list[str], source_hint: str, user_id: str | None) -> None:
    if not label_ids:
        return
    auto_repo = _build_auto_repository()
    cfg = auto_repo.get_config(_KIND)
    if not cfg or not cfg.get("enabled"):
        log_event(
            "INFO", "auto_enrich_skipped_disabled",
            source_hint=source_hint, candidate_labels=len(label_ids),
        )
        return

    claimed = auto_repo.claim_labels(sorted(set(label_ids)))
    if not claimed:
        log_event(
            "INFO", "auto_enrich_dispatched",
            claimed=0, skipped=len(set(label_ids)), run_id=None, source_hint=source_hint,
        )
        return

    le_repo = _build_label_repository()
    resolved: list[tuple[str, str, str]] = []
    for label_id in claimed:
        row = le_repo.get_label_by_id(label_id)
        if row is None:
            continue
        style = le_repo.derive_style_for_label(label_id) or "music"
        resolved.append((label_id, row["name"], style))

    if not resolved:
        # Labels vanished between claim and resolve — leave state queued; the
        # stale-queued recovery in claim_labels re-enables them later.
        return

    spec = RunSpec(
        prompt_slug=cfg["prompt_slug"],
        prompt_version=cfg["prompt_version"],
        vendors=list(cfg["vendors"]),
        models=dict(cfg["models"]),
        merge_vendor=cfg["merge_vendor"],
        merge_model=cfg["merge_model"],
        requested_labels=len(resolved),
        created_by_user_id=user_id,
        source="auto",
    )
    run_id = le_repo.create_run(spec)
    auto_repo.attach_run(claimed, run_id)

    sqs = _build_sqs_client()
    queue_url = _queue_url()
    for label_id, name, style in resolved:
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "run_id": run_id,
                "label_id": label_id,
                "label_name": name,
                "style": style,
            }),
        )

    log_event(
        "INFO", "auto_enrich_dispatched",
        claimed=len(resolved), skipped=len(set(label_ids)) - len(claimed),
        run_id=run_id, source_hint=source_hint,
    )


def _safe(fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — best-effort, never break curation
        log_event("ERROR", "auto_enrich_dispatch_error", error_message=str(exc)[:500])


def try_dispatch_for_track(*, track_id: str, user_id: str | None) -> None:
    def _run() -> None:
        auto_repo = _build_auto_repository()
        label_id = auto_repo.label_id_for_track(track_id)
        if not label_id:
            return
        _dispatch_labels(label_ids=[label_id], source_hint="single", user_id=user_id)
    _safe(_run)


def try_dispatch_for_triage_block(*, block_id: str, user_id: str | None) -> None:
    def _run() -> None:
        auto_repo = _build_auto_repository()
        label_ids = auto_repo.label_ids_for_triage_block(block_id)
        if not label_ids:
            return
        _dispatch_labels(label_ids=label_ids, source_hint="triage", user_id=user_id)
    _safe(_run)
```

> The two `try_dispatch_*` helpers build their own `AutoEnrichRepository` once to resolve labels, then `_dispatch_labels` builds its own again — acceptable: these are cold, low-frequency paths and `create_default_data_api_client` only instantiates a boto3 client. Keeping `_dispatch_labels` self-contained makes it directly unit-testable.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/unit/test_auto_dispatch.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/auto_dispatch.py tests/unit/test_auto_dispatch.py
git commit -m "feat(enrich): add best-effort auto-enrich dispatch"
```

---

### Task 10: Worker stamps auto-state outcome

**Files:**
- Modify: `src/collector/label_enrichment/orchestrator.py` — `enrich_label_for_run` (`:73`)
- Modify: `src/collector/label_enrichment_handler.py` — build auto repo, pass callback
- Test: `tests/unit/test_label_enrichment_orchestrator.py` (extend)

- [ ] **Step 1: Write the failing test** (append to orchestrator test)

```python
def test_enrich_label_invokes_on_outcome_success(monkeypatch):
    # Reuse the file's existing fakes for adapters/merge/repository if present;
    # otherwise build minimal MagicMocks mirroring an existing test in this file.
    from collector.label_enrichment import orchestrator as orch

    captured = []

    def on_outcome(label_id, success):
        captured.append((label_id, success))

    # Build the same arg set an existing passing test in this file uses, but
    # add on_outcome=on_outcome and assert one vendor parses OK.
    # (Mirror the nearest existing enrich_label_for_run test for adapters,
    #  merge_client, repository, prompt, ai_flag_threshold.)
    _run_enrich_label_for_run_with(on_outcome=on_outcome, all_vendors_ok=True, orch=orch)
    assert captured == [("lbl-1", True)]


def test_enrich_label_invokes_on_outcome_failure():
    from collector.label_enrichment import orchestrator as orch
    captured = []
    _run_enrich_label_for_run_with(
        on_outcome=lambda l, s: captured.append((l, s)),
        all_vendors_ok=False, orch=orch,
    )
    assert captured == [("lbl-1", False)]
```

> When implementing: open `tests/unit/test_label_enrichment_orchestrator.py`, find the existing `enrich_label_for_run` test, and write a small `_run_enrich_label_for_run_with(on_outcome, all_vendors_ok, orch)` local helper that reuses that test's adapter/merge/repository fakes. `all_vendors_ok=True` means at least one adapter returns a parsed response (so `ok > 0`); `False` means all adapters error (so `ok == 0`). Keep the helper in the test file.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_label_enrichment_orchestrator.py -k on_outcome -q`
Expected: FAIL — `enrich_label_for_run` has no `on_outcome` param

- [ ] **Step 3: Add `on_outcome` to `enrich_label_for_run`**

In `orchestrator.py`, change the signature (`:73`) to add a keyword param:

```python
def enrich_label_for_run(
    *,
    run_id: str,
    label_id: str,
    label_name: str,
    style: str,
    adapters: list[VendorAdapter],
    merge_client: Any,
    merge_model: str,
    prompt: PromptConfig,
    repository: LabelEnrichmentRepository,
    ai_flag_threshold: float,
    on_outcome: "Callable[[str, bool], None] | None" = None,
) -> None:
```

Add `from typing import Any, Callable` to the imports (it currently imports `Any`).

At the very end of the function body (after `repository.increment_run_counters(...)`), add:

```python
    if on_outcome is not None:
        on_outcome(label_id, ok > 0)
```

- [ ] **Step 4: Wire the callback in the worker handler**

In `src/collector/label_enrichment_handler.py`:

Add import:
```python
from .label_enrichment.auto_repository import AutoEnrichRepository
```

After `repository = _build_repository()` (`~:57`), add:
```python
    auto_repository = AutoEnrichRepository(
        data_api=create_default_data_api_client(
            resource_arn=str(get_data_api_settings().aurora_cluster_arn),
            secret_arn=str(get_data_api_settings().aurora_secret_arn),
            database=get_data_api_settings().aurora_database,
        )
    )
```

In the `enrich_label_for_run(...)` call, add the argument:
```python
            on_outcome=auto_repository.mark_auto_enrich_outcome,
```

> Simpler alternative the implementer may prefer: refactor the worker's `_build_repository` to first build the client (`client = create_default_data_api_client(...)`) and return both `LabelEnrichmentRepository(client)` and `AutoEnrichRepository(client)` so the client is built once. Either is fine; keep one Data API client if convenient.

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/unit/test_label_enrichment_orchestrator.py -q && pytest tests/unit/test_label_enrichment_worker.py -q`
Expected: PASS (existing worker tests still pass; new orchestrator tests pass)

- [ ] **Step 6: Commit**

```bash
git add src/collector/label_enrichment/orchestrator.py src/collector/label_enrichment_handler.py tests/unit/test_label_enrichment_orchestrator.py
git commit -m "feat(enrich): stamp auto-state outcome after worker run"
```

---

## Phase 4 — Trigger integration

### Task 11: Trigger from single track add

**Files:**
- Modify: `src/collector/curation_handler.py` — `_handle_add_track` (`:551`)
- Test: `tests/unit/test_curation_handler_triage.py` or a new `tests/unit/test_curation_auto_enrich_trigger.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import MagicMock, patch


def _add_track_event(category_id="cat-1", track_id="trk-1"):
    return {
        "routeKey": "POST /categories/{id}/tracks",
        "pathParameters": {"id": category_id},
        "body": '{"track_id": "trk-1"}',
        "requestContext": {"authorizer": {"lambda": {"user_id": "u1"}}},
    }


def test_add_track_triggers_dispatch_for_track():
    from collector import curation_handler as ch

    repo = MagicMock()
    repo.add_track.return_value = ({"added_at": "t", "source_triage_block_id": None}, True)
    with patch.object(ch, "try_dispatch_for_track") as dispatch, \
         patch.object(ch, "create_default_categories_repository", return_value=repo):
        # Call the handler directly with its (event, repo, user_id, correlation_id) shape.
        ch._handle_add_track(_add_track_event(), repo, "u1", "corr-1")
    dispatch.assert_called_once()
    assert dispatch.call_args.kwargs["track_id"] == "trk-1"
    assert dispatch.call_args.kwargs["user_id"] == "u1"


def test_add_track_no_dispatch_when_already_present():
    from collector import curation_handler as ch
    repo = MagicMock()
    repo.add_track.return_value = ({"added_at": "t", "source_triage_block_id": None}, False)
    with patch.object(ch, "try_dispatch_for_track") as dispatch:
        ch._handle_add_track(_add_track_event(), repo, "u1", "corr-1")
    dispatch.assert_not_called()
```

> Inspect `_handle_add_track`'s exact call signature/return shape when implementing; adjust the test harness to match how other tests in `test_curation_handler_*.py` invoke handlers (some go through `handler.lambda_handler`, some call `_handle_*` directly). Prefer the same style as the nearest existing add-track test.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_curation_auto_enrich_trigger.py -q`
Expected: FAIL — `curation_handler` has no `try_dispatch_for_track`

- [ ] **Step 3: Add the import + call**

In `src/collector/curation_handler.py`, add near the other `label_enrichment` imports (or at top of file with other imports):

```python
from .label_enrichment.auto_dispatch import (
    try_dispatch_for_track,
    try_dispatch_for_triage_block,
)
```

In `_handle_add_track`, after the `log_event("INFO", "category_track_added", ...)` call and before building `payload`, add:

```python
    if was_new:
        try_dispatch_for_track(track_id=body.track_id, user_id=user_id)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/unit/test_curation_auto_enrich_trigger.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation_handler.py tests/unit/test_curation_auto_enrich_trigger.py
git commit -m "feat(curation): trigger auto-enrich on single track add"
```

---

### Task 12: Trigger from triage finalize

**Files:**
- Modify: `src/collector/curation_handler.py` — `_finalize_triage_block` (`:1309`)
- Test: `tests/unit/test_curation_auto_enrich_trigger.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import MagicMock, patch


def _finalize_event(block_id="blk-1"):
    return {
        "routeKey": "POST /triage/blocks/{id}/finalize",
        "pathParameters": {"id": block_id},
        "requestContext": {"authorizer": {"lambda": {"user_id": "u1"}}},
    }


def test_finalize_triggers_dispatch_for_block():
    from collector import curation_handler as ch

    repo = MagicMock()
    finalize_result = MagicMock()
    finalize_result.block = MagicMock(finalized_at="t")
    finalize_result.promoted = {"cat-1": 3}
    repo.finalize_block.return_value = finalize_result

    cat_repo = MagicMock()
    with patch.object(ch, "try_dispatch_for_triage_block") as dispatch, \
         patch.object(ch, "create_default_categories_repository", return_value=cat_repo), \
         patch.object(ch, "_serialize_triage_block", return_value={}):
        ch._finalize_triage_block(_finalize_event(), repo, "u1", "corr-1")
    dispatch.assert_called_once()
    assert dispatch.call_args.kwargs["block_id"] == "blk-1"
    assert dispatch.call_args.kwargs["user_id"] == "u1"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_curation_auto_enrich_trigger.py -k finalize -q`
Expected: FAIL — no dispatch call

- [ ] **Step 3: Add the call**

In `_finalize_triage_block`, after the `log_event("INFO", "triage_block_finalized", ...)` call and before the `return _json_response(...)`, add:

```python
    try_dispatch_for_triage_block(block_id=block_id, user_id=user_id)
```

(The import was already added in Task 11.)

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/unit/test_curation_auto_enrich_trigger.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation_handler.py tests/unit/test_curation_auto_enrich_trigger.py
git commit -m "feat(curation): trigger auto-enrich on triage finalize"
```

---

### Task 13: Runs-list source filter (backend route)

**Files:**
- Modify: `src/collector/label_enrichment/routes.py` — `handle_get_runs_list` (`:285`)
- Modify: `scripts/generate_openapi.py` — add `source` query param + response field to `GET /admin/labels/enrich-runs`
- Test: `tests/unit/test_handler_labels_runs_list.py` (extend)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_runs_list_passes_source_filter(monkeypatch):
    from collector.label_enrichment import routes

    captured = {}

    class FakeRepo:
        def list_runs(self, *, status, cursor, limit, source=None):
            captured["source"] = source
            return [], None

    monkeypatch.setattr(routes, "_build_repository", lambda: FakeRepo())
    event = {"queryStringParameters": {"source": "auto"}}
    status, body = routes.handle_get_runs_list(event)
    assert status == 200
    assert captured["source"] == "auto"


def test_runs_list_rejects_bad_source(monkeypatch):
    from collector.label_enrichment import routes
    from collector.errors import ValidationError

    monkeypatch.setattr(routes, "_build_repository", lambda: object())
    try:
        routes.handle_get_runs_list({"queryStringParameters": {"source": "bogus"}})
        assert False
    except ValidationError as exc:
        assert "source" in str(exc)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_handler_labels_runs_list.py -k source -q`
Expected: FAIL — `source` not handled

- [ ] **Step 3: Handle `source` in `handle_get_runs_list`**

In `routes.py` `handle_get_runs_list` (`:285`), after parsing `status`, add:

```python
    source = (qs.get("source") or "").strip() or None
    if source and source not in ("manual", "auto"):
        raise ValidationError("source must be 'manual' or 'auto'")
```

And pass it through:

```python
    items, next_cursor = repo.list_runs(
        status=status, cursor=cursor, limit=limit, source=source,
    )
```

- [ ] **Step 4: Update OpenAPI**

In `scripts/generate_openapi.py`, in the `GET /admin/labels/enrich-runs` entry (`:1370`), add a `parameters` list (or extend it) with:

```python
            {
                "name": "source",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "enum": ["manual", "auto"]},
            },
```

Find the runs-list response schema (the `RunSummary` item object) and add a `source` property `{"type": "string"}` to it so the frontend type carries `source`.

- [ ] **Step 5: Regenerate + verify**

Run:
```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
cd frontend && pnpm run gen:api 2>/dev/null || true
```
Then: `pytest tests/unit/test_handler_labels_runs_list.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/collector/label_enrichment/routes.py scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts tests/unit/test_handler_labels_runs_list.py
git commit -m "feat(enrich): filter runs list by source"
```

---

## Phase 5 — Frontend

### Task 14: Extract EnrichConfigForm from EnqueueDrawer

**Files:**
- Create: `frontend/src/features/admin/components/enrichment/EnrichConfigForm.tsx`
- Modify: `frontend/src/features/admin/components/enrichment/EnqueueDrawer.tsx`
- Test: `frontend/src/features/admin/components/enrichment/__tests__/EnrichConfigForm.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { EnrichConfigForm } from '../EnrichConfigForm';

const options = {
  vendors: ['gemini', 'openai', 'tavily_deepseek'],
  prompt_versions: [{ slug: 'label_v3', version: 'v1', is_default: true }],
  default_models: { gemini: 'g', openai: 'o', tavily_deepseek: 'd' },
  merge: { vendor: 'deepseek', default_model: 'deepseek-v4-flash' },
} as any;

function setup(value: any, onChange = vi.fn()) {
  render(
    <MantineProvider>
      <EnrichConfigForm options={options} value={value} onChange={onChange} />
    </MantineProvider>,
  );
  return onChange;
}

describe('EnrichConfigForm', () => {
  it('renders a checkbox per vendor', () => {
    setup({ vendors: [], promptSlug: '', models: {}, mergeModel: '' });
    expect(screen.getByLabelText('gemini')).toBeInTheDocument();
    expect(screen.getByLabelText('openai')).toBeInTheDocument();
  });

  it('emits onChange when a vendor is toggled', () => {
    const onChange = setup({ vendors: [], promptSlug: '', models: {}, mergeModel: '' });
    fireEvent.click(screen.getByLabelText('gemini'));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ vendors: ['gemini'] }),
    );
  });

  it('renders a model input only for selected vendors', () => {
    setup({ vendors: ['gemini'], promptSlug: 'label_v3', models: { gemini: 'g' }, mergeModel: 'm' });
    expect(screen.getByDisplayValue('g')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && pnpm test EnrichConfigForm -- --run`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `EnrichConfigForm`**

```tsx
import { Stack, Title, Checkbox, Select, TextInput, Group, Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { EnrichmentOptions } from '../../../../api/labels';

export interface EnrichConfigValue {
  vendors: string[];
  promptSlug: string;
  models: Record<string, string>;
  mergeModel: string;
}

interface Props {
  options: EnrichmentOptions;
  value: EnrichConfigValue;
  onChange: (next: EnrichConfigValue) => void;
}

export function EnrichConfigForm({ options, value, onChange }: Props) {
  const { t } = useTranslation();
  const set = (patch: Partial<EnrichConfigValue>) => onChange({ ...value, ...patch });

  return (
    <Stack gap="md">
      <Stack gap="xs">
        <Title order={6}>{t('admin_enrichment.enqueue_drawer.vendors_label')}</Title>
        {options.vendors.map((v) => (
          <Checkbox
            key={v}
            label={v}
            checked={value.vendors.includes(v)}
            onChange={(e) =>
              set({
                vendors: e.currentTarget.checked
                  ? [...value.vendors, v]
                  : value.vendors.filter((x) => x !== v),
              })
            }
          />
        ))}
      </Stack>
      <Select
        label={t('admin_enrichment.enqueue_drawer.prompt_label')}
        value={value.promptSlug}
        data={options.prompt_versions.map((p) => ({
          value: p.slug ?? '',
          label: `${p.slug}@${p.version}`,
        }))}
        onChange={(v) => v && set({ promptSlug: v })}
      />
      <Stack gap="xs">
        <Title order={6}>{t('admin_enrichment.enqueue_drawer.models_label')}</Title>
        {value.vendors.map((v) => (
          <TextInput
            key={v}
            label={v}
            value={value.models[v] ?? ''}
            onChange={(e) => set({ models: { ...value.models, [v]: e.currentTarget.value } })}
          />
        ))}
      </Stack>
      <Group gap="xs" align="end">
        <Stack gap={4}>
          <Title order={6}>{t('admin_enrichment.enqueue_drawer.merge_vendor_label')}</Title>
          <Badge>deepseek</Badge>
        </Stack>
        <TextInput
          label={t('admin_enrichment.enqueue_drawer.merge_model_label')}
          value={value.mergeModel}
          onChange={(e) => set({ mergeModel: e.currentTarget.value })}
          style={{ flex: 1 }}
        />
      </Group>
    </Stack>
  );
}
```

- [ ] **Step 4: Refactor `EnqueueDrawer` to use the form**

In `EnqueueDrawer.tsx`, replace the inline controls (lines `77`–`122`) with the extracted form, keeping the existing state + submit. Replace the `<Stack gap="md"> ... </Stack>` body inside `options.data && (...)` with:

```tsx
        <Stack gap="md">
          <EnrichConfigForm
            options={options.data}
            value={{ vendors, promptSlug, models, mergeModel }}
            onChange={(next) => {
              setVendors(next.vendors);
              setPromptSlug(next.promptSlug);
              setModels(next.models);
              setMergeModel(next.mergeModel);
            }}
          />
          <Button
            onClick={submit}
            loading={enqueue.isPending}
            disabled={labelIds.length === 0 || vendors.length === 0}
          >
            {enqueue.isPending
              ? t('admin_enrichment.enqueue_drawer.submit_inflight')
              : t('admin_enrichment.enqueue_drawer.submit')}
          </Button>
        </Stack>
```

Add the import: `import { EnrichConfigForm } from './EnrichConfigForm';`

- [ ] **Step 5: Run tests**

Run: `cd frontend && pnpm test EnrichConfigForm EnqueueDrawer -- --run`
Expected: PASS (new form tests + any existing EnqueueDrawer tests still green)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/admin/components/enrichment/EnrichConfigForm.tsx frontend/src/features/admin/components/enrichment/EnqueueDrawer.tsx frontend/src/features/admin/components/enrichment/__tests__/EnrichConfigForm.test.tsx
git commit -m "refactor(admin): extract EnrichConfigForm from EnqueueDrawer"
```

---

### Task 15: Auto-enrich config hooks + types

**Files:**
- Create: `frontend/src/api/autoEnrich.ts`
- Create: `frontend/src/features/admin/hooks/useAutoEnrichConfig.ts`
- Create: `frontend/src/features/admin/hooks/useSaveAutoEnrichConfig.ts`

- [ ] **Step 1: Add types** (`frontend/src/api/autoEnrich.ts`)

```ts
import type { paths } from './schema';

export type AutoEnrichConfigResponse =
  paths['/admin/auto-enrich/labels']['get']['responses'][200]['content']['application/json'];
export type AutoEnrichConfigBody =
  paths['/admin/auto-enrich/labels']['put']['requestBody']['content']['application/json'];
```

- [ ] **Step 2: Add the query hook** (`useAutoEnrichConfig.ts`)

```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AutoEnrichConfigResponse } from '../../../api/autoEnrich';

export function useAutoEnrichConfig() {
  return useQuery<AutoEnrichConfigResponse, Error>({
    queryKey: ['admin', 'autoEnrich', 'labels'],
    queryFn: () => api<AutoEnrichConfigResponse>('/admin/auto-enrich/labels'),
    staleTime: 5 * 60_000,
  });
}
```

- [ ] **Step 3: Add the mutation hook** (`useSaveAutoEnrichConfig.ts`)

```ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { AutoEnrichConfigBody } from '../../../api/autoEnrich';

export function useSaveAutoEnrichConfig() {
  const qc = useQueryClient();
  return useMutation<void, Error, AutoEnrichConfigBody>({
    mutationFn: (body) =>
      api<void>('/admin/auto-enrich/labels', {
        method: 'PUT',
        body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'autoEnrich', 'labels'] });
    },
  });
}
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors (the `paths` entries exist from Task 6 regeneration).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/autoEnrich.ts frontend/src/features/admin/hooks/useAutoEnrichConfig.ts frontend/src/features/admin/hooks/useSaveAutoEnrichConfig.ts
git commit -m "feat(admin): add auto-enrich config hooks"
```

---

### Task 16: Auto-enrich settings page (tabs) + route

**Files:**
- Create: `frontend/src/features/admin/routes/AdminAutoEnrichPage.tsx`
- Modify: `frontend/src/routes/router.tsx` (admin children, `:115`)
- Modify: `frontend/src/features/admin/routes/AdminLayout.tsx` (nav link — inspect first)
- Test: `frontend/src/features/admin/routes/__tests__/AdminAutoEnrichPage.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AdminAutoEnrichPage } from '../AdminAutoEnrichPage';

const mockSave = vi.fn().mockResolvedValue(undefined);
vi.mock('../../hooks/useAutoEnrichConfig', () => ({
  useAutoEnrichConfig: () => ({
    data: {
      config: {
        enabled: false, vendors: [], models: {},
        prompt_slug: null, prompt_version: null,
        merge_vendor: 'deepseek', merge_model: null,
      },
      options: {
        vendors: ['gemini', 'openai', 'tavily_deepseek'],
        prompt_versions: [{ slug: 'label_v3', version: 'v1', is_default: true }],
        default_models: { gemini: 'g', openai: 'o', tavily_deepseek: 'd' },
        merge: { vendor: 'deepseek', default_model: 'deepseek-v4-flash' },
      },
    },
    isLoading: false,
    isError: false,
  }),
}));
vi.mock('../../hooks/useSaveAutoEnrichConfig', () => ({
  useSaveAutoEnrichConfig: () => ({ mutateAsync: mockSave, isPending: false }),
}));

function renderPage() {
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <AdminAutoEnrichPage />
      </MantineProvider>
    </QueryClientProvider>,
  );
}

describe('AdminAutoEnrichPage', () => {
  beforeEach(() => mockSave.mockClear());

  it('shows three tabs with artists/tracks disabled', () => {
    renderPage();
    expect(screen.getByRole('tab', { name: /labels/i })).toBeEnabled();
    expect(screen.getByRole('tab', { name: /artists/i })).toBeDisabled();
    expect(screen.getByRole('tab', { name: /tracks/i })).toBeDisabled();
  });

  it('saves config on Save click', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave.mock.calls[0][0]).toMatchObject({ enabled: false });
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && pnpm test AdminAutoEnrichPage -- --run`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the page**

```tsx
import { useEffect, useState } from 'react';
import { Tabs, Stack, Switch, Button, Title, Skeleton, Alert, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useAutoEnrichConfig } from '../hooks/useAutoEnrichConfig';
import { useSaveAutoEnrichConfig } from '../hooks/useSaveAutoEnrichConfig';
import { EnrichConfigForm, type EnrichConfigValue } from '../components/enrichment/EnrichConfigForm';

function LabelsTab() {
  const { t } = useTranslation();
  const query = useAutoEnrichConfig();
  const save = useSaveAutoEnrichConfig();

  const [enabled, setEnabled] = useState(false);
  const [form, setForm] = useState<EnrichConfigValue>({
    vendors: [], promptSlug: '', models: {}, mergeModel: '',
  });

  useEffect(() => {
    if (!query.data) return;
    const { config, options } = query.data;
    setEnabled(config.enabled);
    setForm({
      vendors: config.vendors ?? [],
      promptSlug: config.prompt_slug ?? options.prompt_versions.find((p) => p.is_default)?.slug ?? '',
      models: (config.models as Record<string, string>) ?? {},
      mergeModel: config.merge_model ?? options.merge?.default_model ?? '',
    });
  }, [query.data]);

  if (query.isLoading) return <Skeleton height={240} />;
  if (query.isError || !query.data) return <Alert color="red">{String(query.error)}</Alert>;

  const promptVersion =
    query.data.options.prompt_versions.find((p) => p.slug === form.promptSlug)?.version ?? '';

  const submit = async () => {
    try {
      await save.mutateAsync({
        enabled,
        vendors: form.vendors as ('gemini' | 'openai' | 'tavily_deepseek')[],
        models: form.models,
        prompt_slug: form.promptSlug,
        prompt_version: promptVersion,
        merge_vendor: 'deepseek',
        merge_model: form.mergeModel,
      });
      notifications.show({ color: 'green', title: t('admin_auto_enrich.saved'), message: '' });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: t('admin_auto_enrich.save_error', {
          message: err instanceof Error ? err.message : 'unknown',
        }),
        message: '',
      });
    }
  };

  return (
    <Stack gap="md" mt="md">
      <Switch
        label={t('admin_auto_enrich.enabled_label')}
        checked={enabled}
        onChange={(e) => setEnabled(e.currentTarget.checked)}
      />
      <EnrichConfigForm options={query.data.options} value={form} onChange={setForm} />
      <Button
        onClick={submit}
        loading={save.isPending}
        disabled={enabled && form.vendors.length === 0}
      >
        {t('admin_auto_enrich.save')}
      </Button>
    </Stack>
  );
}

export function AdminAutoEnrichPage() {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Title order={3}>{t('admin_auto_enrich.title')}</Title>
      <Tabs defaultValue="labels">
        <Tabs.List>
          <Tabs.Tab value="labels">{t('admin_auto_enrich.tab_labels')}</Tabs.Tab>
          <Tabs.Tab value="artists" disabled>{t('admin_auto_enrich.tab_artists')}</Tabs.Tab>
          <Tabs.Tab value="tracks" disabled>{t('admin_auto_enrich.tab_tracks')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="labels">
          <LabelsTab />
        </Tabs.Panel>
        <Tabs.Panel value="artists">
          <Text c="dimmed" mt="md">{t('admin_auto_enrich.coming_soon')}</Text>
        </Tabs.Panel>
        <Tabs.Panel value="tracks">
          <Text c="dimmed" mt="md">{t('admin_auto_enrich.coming_soon')}</Text>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
```

- [ ] **Step 4: Add i18n keys**

Add to the translation resource files used by the admin feature (find them via `grep -rl "admin_enrichment" frontend/src`). Add an `admin_auto_enrich` block:

```json
"admin_auto_enrich": {
  "title": "Automatic search",
  "tab_labels": "Labels",
  "tab_artists": "Artists",
  "tab_tracks": "Tracks",
  "enabled_label": "Enabled",
  "save": "Save",
  "saved": "Settings saved",
  "save_error": "Save failed: {{message}}",
  "coming_soon": "Coming soon"
}
```

Mirror the key set into every locale file that defines `admin_enrichment` (match the existing locales — at minimum `en`; replicate to others present).

- [ ] **Step 5: Register the route**

In `frontend/src/routes/router.tsx`, add the import near the other admin route imports (`:32`):

```tsx
import { AdminAutoEnrichPage } from '../features/admin/routes/AdminAutoEnrichPage';
```

And add a child to the `admin` children array (`:115`):

```tsx
          { path: 'auto-enrich', element: <AdminAutoEnrichPage /> },
```

- [ ] **Step 6: Add nav link**

Open `frontend/src/features/admin/routes/AdminLayout.tsx`, find where the existing admin nav links are rendered (e.g. links to `coverage`, `labels/enrich`), and add a link to `/admin/auto-enrich` labelled with `t('admin_auto_enrich.title')` matching the surrounding link markup.

- [ ] **Step 7: Run tests + type-check**

Run: `cd frontend && pnpm test AdminAutoEnrichPage -- --run && pnpm tsc --noEmit`
Expected: PASS, no type errors

- [ ] **Step 8: Verify in a real browser** (per CLAUDE.md gotcha #11 — visual sanity of tabs/disabled states)

Run: `cd frontend && pnpm test:browser AdminAutoEnrich 2>/dev/null || echo "add a *.browser.test.tsx if visual verification is desired"`
Expected: tabs render, Artists/Tracks visibly disabled, form controls visible. (Optional but recommended; jsdom does not apply Mantine styles.)

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/admin/routes/AdminAutoEnrichPage.tsx frontend/src/routes/router.tsx frontend/src/features/admin/routes/AdminLayout.tsx frontend/src/features/admin/routes/__tests__/AdminAutoEnrichPage.test.tsx frontend/src/**/locales* 2>/dev/null; git add -A frontend/src
git commit -m "feat(admin): add automatic-search settings window"
```

---

### Task 17: Runs-list source filter (frontend, optional polish)

**Files:**
- Modify: `frontend/src/features/admin/routes/AdminEnrichmentRunsPage.tsx`
- Modify: `frontend/src/features/admin/hooks/useEnrichmentRuns.ts`

- [ ] **Step 1: Add a `source` param to the runs hook**

Inspect `useEnrichmentRuns.ts`; add an optional `source?: 'manual' | 'auto'` argument threaded into the query string and the `queryKey`. Example shape:

```ts
export function useEnrichmentRuns(opts: { status?: string; source?: 'manual' | 'auto' } = {}) {
  const params = new URLSearchParams();
  if (opts.status) params.set('status', opts.status);
  if (opts.source) params.set('source', opts.source);
  const qs = params.toString();
  return useQuery({
    queryKey: ['admin', 'enrichmentRuns', opts.status ?? null, opts.source ?? null],
    queryFn: () => api(`/admin/labels/enrich-runs${qs ? `?${qs}` : ''}`),
  });
}
```

> Match the file's existing signature/return type — adapt rather than overwrite. If it already takes an options object, just add the `source` key.

- [ ] **Step 2: Add a SegmentedControl on the runs page**

In `AdminEnrichmentRunsPage.tsx`, add a `SegmentedControl` (All / Manual / Auto) bound to local state and pass `source` into `useEnrichmentRuns`. Render each run's `source` in the table (a small `Badge`).

- [ ] **Step 3: Type-check + test**

Run: `cd frontend && pnpm tsc --noEmit && pnpm test AdminEnrichmentRuns -- --run`
Expected: no type errors; existing runs-page tests pass (update them if they assert table columns).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/admin/routes/AdminEnrichmentRunsPage.tsx frontend/src/features/admin/hooks/useEnrichmentRuns.ts
git commit -m "feat(admin): filter enrichment runs by source"
```

---

## Phase 6 — Full verification

### Task 18: Full backend + frontend test sweep

- [ ] **Step 1: Run the full backend suite**

Run: `cd /Users/roman/Projects/clouder-projects/clouder-core && pytest -q`
Expected: all green (the worktree shares `.venv` at the MAIN repo root — call `pytest` by absolute main-repo path if not on PATH, per CLAUDE.md gotcha #3).

- [ ] **Step 2: Run the frontend suite + type-check**

Run: `cd frontend && pnpm test -- --run && pnpm tsc --noEmit`
Expected: all green.

- [ ] **Step 3: Verify OpenAPI ↔ schema.d.ts are in sync**

Run: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py && git diff --exit-code docs/api/openapi.yaml`
Expected: no diff (already committed). If a diff appears, regenerate `schema.d.ts` and commit.

- [ ] **Step 4: Final commit (if anything regenerated)**

```bash
git add -A
git commit -m "chore: regenerate openapi after auto-enrich feature" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage:**
- Singleton config table → Task 1, 3. State table → Task 1, 8. `source` column → Task 1, 7. ✓
- Dedup (skip completed; failed→1 retry; skip in-flight; race-safe) → Task 8 `claim_labels` + Task 10 outcome stamp. ✓
- Enabled toggle, default OFF → Task 1 (`server_default false`), Task 2 (validation), Task 16 (Switch). ✓
- Run-per-dispatch + `source='auto'`; triage batch = one run → Task 9 `_dispatch_labels` (single run for all claimed), Tasks 11–12 triggers. ✓
- Inline best-effort, search in background → Task 9 (`_safe` wrapper, enqueue only), Tasks 11–12 (called after commit/log). ✓
- Admin GET/PUT API → Tasks 4–6. Admin window 3 tabs (2 disabled) → Task 16. EnrichConfigForm reuse → Task 14. Hooks → Task 15. ✓
- Edge: track without label → Task 8 (`label_id IS NOT NULL`), Task 9 (resolve skip). Disabled config → Task 9. Retry cap → Task 8 (`attempts < 2`). ✓
- Observability events (`auto_enrich_dispatched`, `auto_enrich_skipped_disabled`, `auto_enrich_dispatch_error`) → Task 9. ✓
- Runs source filter (spec §key decisions 3) → Task 13 (backend) + Task 17 (frontend). ✓

**Type consistency:** `RunSpec.source` (Task 7) used identically in Task 9. `mark_auto_enrich_outcome(label_id, success)` (Task 8) matches `on_outcome(label_id, ok>0)` (Task 10). `EnrichConfigValue` shape (Task 14) consumed unchanged in Tasks 14 & 16. `AutoEnrichConfigIn` fields (Task 2) match `upsert_config` kwargs (Task 3) and the PUT handler (Task 4) and OpenAPI body (Task 6).

**Open items the implementer must confirm against live code (flagged inline):** exact frontend `schema.d.ts` regeneration command (Task 6 step 3), the nearest existing orchestrator test's fakes (Task 10), `_handle_add_track`/`_finalize_triage_block` test-invocation style (Tasks 11–12), `useEnrichmentRuns` existing signature (Task 17), locale file locations (Task 16 step 4), and whether `generate_openapi.py` already has a named options-schema constant to reuse (Task 6 step 2).
