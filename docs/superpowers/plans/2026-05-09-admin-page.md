# Admin Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `/admin` namespace with a Beatport coverage matrix, on-demand ingest with custom date-range override, and the existing Spotify-not-found list — all gated by `is_admin`.

**Architecture:** Backend gains a Saturday-week math module, three new admin-gated endpoints (`POST /admin/beatport/ingest`, `GET /admin/coverage`, `GET /admin/runs`), and an `ingest_runs` schema extension (`week_year`, `week_number`, `period_start`, `period_end`, `is_custom_range`). The legacy `POST /collect_bp_releases` is preserved (deprecated) and rewritten to share an internal helper with the admin handler. Frontend ships a new `features/admin` folder with `AdminLayout` (Tabs), Coverage matrix (style × week sticky grid), single Drawer for cell detail/ingest/history, in-memory `bp_token` store, persistent run-progress toasts, and a Spotify-not-found table. Routing is gated by a new `requireAdmin` loader that mirrors `requireAuth`.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy + Alembic, RDS Data API, AWS Lambda + HTTP API Gateway (Terraform). React 19, Mantine 9, TanStack Query 5, react-router 7, Zustand, Vitest + MSW.

**Spec:** [`docs/superpowers/specs/2026-05-09-admin-page-design.md`](../specs/2026-05-09-admin-page-design.md)

---

## File Structure (locked-in decomposition)

### Backend

| Path | Responsibility |
|---|---|
| `src/collector/saturday_week.py` (new) | Pure math: `first_saturday(y)`, `saturday_week_range(y, n)`, `week_of_date(d)`, `weeks_in_year(y)`. No I/O. |
| `src/collector/schemas.py` (modify) | Add `AdminIngestRequestIn`. |
| `src/collector/models.py` (modify) | Add `validate_admin_ingest_request`. Keep `compute_iso_week_date_range` for legacy. |
| `src/collector/repositories.py` (modify) | Extend `CreateIngestRunCmd` with new optional fields. Add `list_runs_for_cell`, `coverage_for_year`. |
| `src/collector/handler.py` (modify) | Refactor `_handle_collect` into `_run_beatport_ingest` helper. Add `_handle_admin_ingest`, `_handle_admin_coverage`, `_handle_admin_runs`. Extend `_ADMIN_ROUTES` and `_route`. |
| `alembic/versions/<new>.py` (new) | Schema migration. |
| `infra/api_gateway.tf` (modify) | 3 new `aws_apigatewayv2_route` blocks. |
| `scripts/generate_openapi.py` (modify) | New `AdminIngestRequestIn` import + 3 entries in `ROUTES`. |
| `tests/unit/test_saturday_week.py` (new) | Saturday-week math tests. |
| `tests/unit/test_admin_schemas.py` (new) | Pydantic validation. |
| `tests/integration/test_admin_ingest_endpoint.py` (new) | Happy path, override path, authz, validation. |
| `tests/integration/test_admin_coverage_endpoint.py` (new) | Empty / partial / latest-run-per-cell. |
| `tests/integration/test_admin_runs_endpoint.py` (new) | DESC order, missing params. |

### Frontend

| Path | Responsibility |
|---|---|
| `frontend/src/auth/requireAdmin.ts` (new) | Loader: redirect non-admins. |
| `frontend/src/auth/__tests__/requireAdmin.test.ts` (new) | Loader tests. |
| `frontend/src/components/icons.ts` (modify) | Re-export `IconShield` (admin nav). |
| `frontend/src/routes/router.tsx` (modify) | Register `/admin/*` subtree. |
| `frontend/src/routes/_layout.tsx` (modify) | Conditional `Admin` nav item. |
| `frontend/src/components/UserMenu.tsx` (modify) | "Reset Beatport token" item (admin + token-set only). |
| `frontend/src/i18n/en.json` (modify) | `admin.*` namespace. |
| `frontend/src/features/admin/lib/saturdayWeek.ts` (new) | Mirror of BE math. |
| `frontend/src/features/admin/lib/saturdayWeek.test.ts` (new) | Shared fixtures with BE. |
| `frontend/src/features/admin/lib/bpTokenStore.ts` (new) | In-memory store + `useBpToken` hook. |
| `frontend/src/features/admin/lib/cellState.ts` (new) | `cellState(cell, runsTracker)` derivation. |
| `frontend/src/features/admin/lib/runsTracker.ts` (new) | Zustand store of running run_ids. |
| `frontend/src/features/admin/lib/runsTracker.test.ts` (new) | Store tests. |
| `frontend/src/features/admin/hooks/useCoverage.ts` (new) | Coverage query. |
| `frontend/src/features/admin/hooks/useCellRuns.ts` (new) | Per-cell history query. |
| `frontend/src/features/admin/hooks/useStartIngest.ts` (new) | Mutation + `runsTracker.add`. |
| `frontend/src/features/admin/hooks/useRunPoller.ts` (new) | Polling + cache invalidation. |
| `frontend/src/features/admin/hooks/useSpotifyNotFound.ts` (new) | Paginated list. |
| `frontend/src/features/admin/components/YearNavigator.tsx` (new) | < 2026 > selector. |
| `frontend/src/features/admin/components/CoverageMatrix.tsx` (new) | Style × week grid. |
| `frontend/src/features/admin/components/CoverageMatrixCell.tsx` (new) | Memoised cell. |
| `frontend/src/features/admin/components/CellDetailDrawer.tsx` (new) | State-machine Drawer. |
| `frontend/src/features/admin/components/IngestForm.tsx` (new) | bp_token + override + advanced. |
| `frontend/src/features/admin/components/RunDetails.tsx` (new) | Run card. |
| `frontend/src/features/admin/components/RunHistoryList.tsx` (new) | Per-cell history. |
| `frontend/src/features/admin/components/BpTokenInput.tsx` (new) | Password input + reset link. |
| `frontend/src/features/admin/components/RunProgressToast.tsx` (new) | Subscribes runsTracker → notifications. |
| `frontend/src/features/admin/components/SpotifyNotFoundTable.tsx` (new) | Mantine Table. |
| `frontend/src/features/admin/routes/AdminLayout.tsx` (new) | Tabs sub-shell. |
| `frontend/src/features/admin/routes/AdminCoveragePage.tsx` (new) | Coverage page. |
| `frontend/src/features/admin/routes/AdminSpotifyNotFoundPage.tsx` (new) | List page. |
| `frontend/src/test/handlers.ts` (modify) | MSW handlers for new endpoints. |
| FE component tests | Co-located `__tests__` per component. |

### Docs

| Path | Responsibility |
|---|---|
| `CLAUDE.md` (modify) | Add gotcha lines for the new conventions (Saturday-week, deprecated `/collect_bp_releases`, `bp_token` in-memory store, admin nav gate). |
| `docs/openapi.yaml` (regenerated) | Output of `generate_openapi.py`. |

---

## Phase 1 — Backend math + schema

### Task 1: Saturday-week pure module (TDD)

**Files:**
- Create: `src/collector/saturday_week.py`
- Test: `tests/unit/test_saturday_week.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_saturday_week.py
from datetime import date

import pytest

from collector.saturday_week import (
    first_saturday,
    saturday_week_range,
    week_of_date,
    weeks_in_year,
)


def test_first_saturday_when_jan_1_is_thu():
    # 2026-01-01 is Thursday → first Saturday is Jan 3.
    assert first_saturday(2026) == date(2026, 1, 3)


def test_first_saturday_when_jan_1_is_saturday():
    # 2028-01-01 is Saturday → first Saturday is Jan 1 itself.
    assert first_saturday(2028) == date(2028, 1, 1)


def test_first_saturday_when_jan_1_is_friday():
    # 2027-01-01 is Friday → first Saturday is Jan 2.
    assert first_saturday(2027) == date(2027, 1, 2)


def test_saturday_week_range_2026_w1():
    start, end = saturday_week_range(2026, 1)
    assert start == date(2026, 1, 3)
    assert end == date(2026, 1, 9)


def test_saturday_week_range_2026_w5():
    start, end = saturday_week_range(2026, 5)
    assert start == date(2026, 1, 31)
    assert end == date(2026, 2, 6)


def test_weeks_in_year_2026_is_52():
    assert weeks_in_year(2026) == 52


def test_weeks_in_year_2028_is_53():
    # 2028 starts on Saturday (Jan 1) and ends Sunday (Dec 31).
    # Last Saturday is Dec 30 → 53 weeks fit.
    assert weeks_in_year(2028) == 53


def test_week_of_date_round_trip_2026():
    for n in range(1, weeks_in_year(2026) + 1):
        start, _ = saturday_week_range(2026, n)
        assert week_of_date(start) == (2026, n)
        assert week_of_date(start + (saturday_week_range(2026, n)[1] - start)) == (2026, n)


def test_week_of_date_jan_1_2027_belongs_to_prev_year():
    # 2027-01-01 is Friday — falls before first Saturday of 2027 → week 52 of 2026.
    assert week_of_date(date(2027, 1, 1)) == (2026, 52)


def test_saturday_week_range_rejects_out_of_range():
    with pytest.raises(ValueError):
        saturday_week_range(2026, 0)
    with pytest.raises(ValueError):
        saturday_week_range(2026, weeks_in_year(2026) + 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_saturday_week.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'collector.saturday_week'`.

- [ ] **Step 3: Implement the module**

```python
# src/collector/saturday_week.py
"""Saturday-anchored week math.

Convention used by the admin Beatport ingest UI.

- Week N of year Y starts on Saturday(Y, N) and ends on the following Friday.
- Saturday(Y, 1) is the first Saturday on or after Jan 1 of Y.
- Days from Jan 1 up to (but excluding) Saturday(Y, 1) belong to the last
  week of Y - 1.
"""

from __future__ import annotations

from datetime import date, timedelta

_SATURDAY = 5  # date.weekday(): Mon=0 .. Sun=6


def first_saturday(year: int) -> date:
    jan1 = date(year, 1, 1)
    delta = (_SATURDAY - jan1.weekday()) % 7
    return jan1 + timedelta(days=delta)


def _last_saturday_on_or_before(d: date) -> date:
    delta = (d.weekday() - _SATURDAY) % 7
    return d - timedelta(days=delta)


def weeks_in_year(year: int) -> int:
    start = first_saturday(year)
    end = _last_saturday_on_or_before(date(year, 12, 31))
    return ((end - start).days // 7) + 1


def saturday_week_range(year: int, week: int) -> tuple[date, date]:
    if week < 1 or week > weeks_in_year(year):
        raise ValueError(
            f"week {week} out of range for year {year} "
            f"(1..{weeks_in_year(year)})"
        )
    start = first_saturday(year) + timedelta(days=(week - 1) * 7)
    end = start + timedelta(days=6)
    return start, end


def week_of_date(d: date) -> tuple[int, int]:
    saturday = _last_saturday_on_or_before(d)
    year = saturday.year
    fs = first_saturday(year)
    if saturday < fs:
        # Saturday belongs to previous year's last week.
        prev = year - 1
        prev_fs = first_saturday(prev)
        week = ((saturday - prev_fs).days // 7) + 1
        return prev, week
    week = ((saturday - fs).days // 7) + 1
    return year, week
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_saturday_week.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/saturday_week.py tests/unit/test_saturday_week.py
git commit -m "feat(saturday-week): add Saturday-anchored week math"
```

---

### Task 2: AdminIngestRequestIn schema (TDD)

**Files:**
- Modify: `src/collector/schemas.py`
- Test: `tests/unit/test_admin_schemas.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_admin_schemas.py
from datetime import date

import pytest
from pydantic import ValidationError

from collector.schemas import AdminIngestRequestIn


def _base_payload() -> dict:
    return {
        "style_id": 1,
        "week_year": 2026,
        "week_number": 5,
        "bp_token": "abc",
    }


def test_minimal_payload_is_valid():
    req = AdminIngestRequestIn.model_validate(_base_payload())
    assert req.style_id == 1
    assert req.week_year == 2026
    assert req.week_number == 5
    assert req.period_start is None
    assert req.period_end is None


def test_both_period_fields_present_is_valid():
    payload = _base_payload() | {
        "period_start": "2026-01-31",
        "period_end": "2026-02-06",
    }
    req = AdminIngestRequestIn.model_validate(payload)
    assert req.period_start == date(2026, 1, 31)
    assert req.period_end == date(2026, 2, 6)


def test_only_period_start_is_rejected():
    payload = _base_payload() | {"period_start": "2026-01-31"}
    with pytest.raises(ValidationError) as exc:
        AdminIngestRequestIn.model_validate(payload)
    assert "period" in str(exc.value)


def test_only_period_end_is_rejected():
    payload = _base_payload() | {"period_end": "2026-02-06"}
    with pytest.raises(ValidationError) as exc:
        AdminIngestRequestIn.model_validate(payload)
    assert "period" in str(exc.value)


def test_period_end_before_start_is_rejected():
    payload = _base_payload() | {
        "period_start": "2026-02-06",
        "period_end": "2026-01-31",
    }
    with pytest.raises(ValidationError):
        AdminIngestRequestIn.model_validate(payload)


def test_blank_bp_token_is_rejected():
    payload = _base_payload() | {"bp_token": "   "}
    with pytest.raises(ValidationError):
        AdminIngestRequestIn.model_validate(payload)


def test_week_number_zero_is_rejected():
    payload = _base_payload() | {"week_number": 0}
    with pytest.raises(ValidationError):
        AdminIngestRequestIn.model_validate(payload)


def test_week_number_too_large_for_year_is_rejected():
    # 2026 has 52 weeks.
    payload = _base_payload() | {"week_number": 53}
    with pytest.raises(ValidationError):
        AdminIngestRequestIn.model_validate(payload)


def test_extra_fields_forbidden():
    payload = _base_payload() | {"unknown": "x"}
    with pytest.raises(ValidationError):
        AdminIngestRequestIn.model_validate(payload)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_admin_schemas.py -q`
Expected: FAIL — `ImportError: cannot import name 'AdminIngestRequestIn'`.

- [ ] **Step 3: Implement schema**

Append to `src/collector/schemas.py` after `CollectRequestIn`:

```python
from datetime import date as _date

from .saturday_week import weeks_in_year


class AdminIngestRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style_id: StrictInt = Field(gt=0)
    week_year: StrictInt = Field(ge=2000, le=2100)
    week_number: StrictInt = Field(ge=1, le=53)
    period_start: _date | None = None
    period_end: _date | None = None
    bp_token: str = Field(min_length=1)
    search_label_count: StrictInt | None = Field(default=None, ge=1, le=200)

    @field_validator("bp_token")
    @classmethod
    def _normalize_bp_token(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("bp_token is required and must be a non-empty string")
        return normalized

    @model_validator(mode="after")
    def _validate(self) -> "AdminIngestRequestIn":
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError(
                "period_start and period_end must both be present or both absent"
            )
        if self.period_start is not None and self.period_end is not None:
            if self.period_end < self.period_start:
                raise ValueError("period_end must be on or after period_start")
        if self.week_number > weeks_in_year(self.week_year):
            raise ValueError(
                f"week_number {self.week_number} exceeds weeks_in_year"
                f"({self.week_year}) = {weeks_in_year(self.week_year)}"
            )
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_admin_schemas.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/schemas.py tests/unit/test_admin_schemas.py
git commit -m "feat(schemas): add AdminIngestRequestIn"
```

---

### Task 3: Database migration

**Files:**
- Create: `alembic/versions/20260509_16_admin_ingest_runs.py`

- [ ] **Step 1: Find the previous revision id**

Run: `ls alembic/versions/ | sort | tail -1`
Expected: `20260428_15_triage.py` (or later if other branches landed). Note the file's `revision = "20260428_15"`.

- [ ] **Step 2: Write the migration**

```python
# alembic/versions/20260509_16_admin_ingest_runs.py
"""ingest_runs: add Saturday-week + period columns for admin ingest

Revision ID: 20260509_16
Revises: 20260428_15
Create Date: 2026-05-09 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260509_16"
down_revision = "20260428_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("ingest_runs", "iso_year", nullable=True)
    op.alter_column("ingest_runs", "iso_week", nullable=True)
    op.add_column("ingest_runs", sa.Column("week_year", sa.Integer(), nullable=True))
    op.add_column("ingest_runs", sa.Column("week_number", sa.Integer(), nullable=True))
    op.add_column("ingest_runs", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("ingest_runs", sa.Column("period_end", sa.Date(), nullable=True))
    op.add_column(
        "ingest_runs",
        sa.Column(
            "is_custom_range",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "idx_ingest_runs_coverage",
        "ingest_runs",
        ["week_year", "style_id", "week_number"],
    )


def downgrade() -> None:
    op.drop_index("idx_ingest_runs_coverage", table_name="ingest_runs")
    op.drop_column("ingest_runs", "is_custom_range")
    op.drop_column("ingest_runs", "period_end")
    op.drop_column("ingest_runs", "period_start")
    op.drop_column("ingest_runs", "week_number")
    op.drop_column("ingest_runs", "week_year")
    op.alter_column("ingest_runs", "iso_week", nullable=False)
    op.alter_column("ingest_runs", "iso_year", nullable=False)
```

- [ ] **Step 3: Update `db_models.py` to mirror the new shape**

In `src/collector/db_models.py`, change `IngestRun` columns:

```python
class IngestRun(Base):
    __tablename__ = "ingest_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    style_id: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iso_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    week_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    week_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_custom_range: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    raw_s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
```

Add `Boolean`, `Date` to the existing import block at top of file if missing.

- [ ] **Step 4: Run alembic check locally to confirm autogen is clean**

```bash
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head
alembic check
```

Expected: `No new upgrade operations detected.` (Skip if local Postgres not running — CI runs the same.)

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/20260509_16_admin_ingest_runs.py src/collector/db_models.py
git commit -m "feat(db): admin ingest_runs columns (Saturday-week + period)"
```

---

### Task 4: Repository — extend CreateIngestRunCmd + new methods

**Files:**
- Modify: `src/collector/repositories.py`

- [ ] **Step 1: Extend `CreateIngestRunCmd`**

Replace the existing dataclass with:

```python
@dataclass(frozen=True)
class CreateIngestRunCmd:
    run_id: str
    source: str
    style_id: int
    raw_s3_key: str
    status: RunStatus
    item_count: int
    meta: Mapping[str, Any]
    started_at: datetime
    iso_year: int | None = None
    iso_week: int | None = None
    week_year: int | None = None
    week_number: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    is_custom_range: bool = False
```

- [ ] **Step 2: Update `ClouderRepository.create_ingest_run` to write all columns**

Replace the method body:

```python
def create_ingest_run(self, cmd: CreateIngestRunCmd) -> None:
    self._data_api.execute(
        """
        INSERT INTO ingest_runs (
            run_id, source, style_id,
            iso_year, iso_week,
            week_year, week_number,
            period_start, period_end, is_custom_range,
            raw_s3_key,
            status, item_count, processed_count, started_at, meta
        ) VALUES (
            :run_id, :source, :style_id,
            :iso_year, :iso_week,
            :week_year, :week_number,
            :period_start, :period_end, :is_custom_range,
            :raw_s3_key,
            :status, :item_count, 0, :started_at, :meta
        )
        ON CONFLICT (run_id) DO UPDATE SET
            source = EXCLUDED.source,
            style_id = EXCLUDED.style_id,
            iso_year = EXCLUDED.iso_year,
            iso_week = EXCLUDED.iso_week,
            week_year = EXCLUDED.week_year,
            week_number = EXCLUDED.week_number,
            period_start = EXCLUDED.period_start,
            period_end = EXCLUDED.period_end,
            is_custom_range = EXCLUDED.is_custom_range,
            raw_s3_key = EXCLUDED.raw_s3_key,
            status = EXCLUDED.status,
            item_count = EXCLUDED.item_count,
            meta = EXCLUDED.meta,
            error_code = NULL,
            error_message = NULL,
            finished_at = NULL
        """,
        {
            "run_id": cmd.run_id,
            "source": cmd.source,
            "style_id": cmd.style_id,
            "iso_year": cmd.iso_year,
            "iso_week": cmd.iso_week,
            "week_year": cmd.week_year,
            "week_number": cmd.week_number,
            "period_start": cmd.period_start,
            "period_end": cmd.period_end,
            "is_custom_range": cmd.is_custom_range,
            "raw_s3_key": cmd.raw_s3_key,
            "status": cmd.status.value,
            "item_count": cmd.item_count,
            "started_at": cmd.started_at,
            "meta": dict(cmd.meta),
        },
    )
```

- [ ] **Step 3: Add `coverage_for_year` method**

Append to `ClouderRepository`:

```python
def coverage_for_year(self, week_year: int) -> list[dict[str, Any]]:
    return self._data_api.execute(
        """
        SELECT
            cs.id          AS style_id,
            cs.name        AS style_name,
            r.run_id,
            r.week_number,
            r.status,
            r.item_count,
            r.is_custom_range,
            r.period_start,
            r.period_end,
            r.started_at,
            r.finished_at
        FROM clouder_styles cs
        LEFT JOIN LATERAL (
            SELECT *
            FROM ingest_runs ir
            WHERE ir.week_year = :week_year
              AND ir.style_id::text = cs.id::text
            ORDER BY ir.week_number, ir.started_at DESC
        ) r ON TRUE
        WHERE NOT EXISTS (
            SELECT 1
            FROM ingest_runs ir2
            WHERE ir2.week_year = r.week_year
              AND ir2.style_id = r.style_id
              AND ir2.week_number = r.week_number
              AND ir2.started_at > r.started_at
        )
        ORDER BY cs.name ASC, r.week_number ASC NULLS LAST
        """,
        {"week_year": week_year},
    )
```

> **Note:** `clouder_styles.id` is `UUID` while `ingest_runs.style_id` was originally INTEGER (Beatport numeric id). Cast both sides to text for safety. If the existing `style_id` semantics differ in your DB, adjust the join — but do NOT silently change column types here.

- [ ] **Step 4: Add `list_runs_for_cell` method**

```python
def list_runs_for_cell(
    self, style_id: int, week_year: int, week_number: int
) -> list[dict[str, Any]]:
    return self._data_api.execute(
        """
        SELECT
            run_id, status, started_at, finished_at,
            item_count, processed_count,
            error_code, error_message,
            is_custom_range, period_start, period_end
        FROM ingest_runs
        WHERE style_id = :style_id
          AND week_year = :week_year
          AND week_number = :week_number
        ORDER BY started_at DESC
        """,
        {
            "style_id": style_id,
            "week_year": week_year,
            "week_number": week_number,
        },
    )
```

- [ ] **Step 5: Update existing legacy callers to keep `iso_year` / `iso_week`**

Verify `src/collector/handler.py` line ~227 still passes `iso_year=request.iso_year, iso_week=request.iso_week`. The new keyword-arg-with-default signature accepts them unchanged. No edit required here.

- [ ] **Step 6: Commit**

```bash
git add src/collector/repositories.py
git commit -m "feat(repo): extend CreateIngestRunCmd + add admin coverage queries"
```

---

### Task 5: Refactor handler — share `_run_beatport_ingest` helper

**Files:**
- Modify: `src/collector/handler.py`

- [ ] **Step 1: Extract a shared helper**

In `src/collector/handler.py`, replace `_handle_collect` with two pieces. First, the shared helper (place it directly above the current `_handle_collect`):

```python
@dataclass(frozen=True)
class _IngestParams:
    style_id: int
    bp_token: str
    period_start: str  # YYYY-MM-DD
    period_end: str    # YYYY-MM-DD
    search_label_count: int | None
    iso_year: int | None
    iso_week: int | None
    week_year: int | None
    week_number: int | None
    is_custom_range: bool


def _run_beatport_ingest(
    event: Mapping[str, Any],
    context: Any,
    params: _IngestParams,
) -> dict[str, Any]:
    started_at_perf = time.perf_counter()
    api_request_id = _extract_api_request_id(event)
    lambda_request_id = getattr(context, "aws_request_id", "unknown")
    correlation_id = _extract_correlation_id(event)

    log_event(
        "INFO",
        "request_received",
        correlation_id=correlation_id,
        api_request_id=api_request_id,
        lambda_request_id=lambda_request_id,
    )

    settings = _load_api_settings()
    run_id = str(uuid.uuid4())

    log_event(
        "INFO",
        "request_validated",
        correlation_id=correlation_id,
        api_request_id=api_request_id,
        lambda_request_id=lambda_request_id,
        style_id=params.style_id,
        iso_year=params.iso_year,
        iso_week=params.iso_week,
        week_year=params.week_year,
        week_number=params.week_number,
        is_custom_range=params.is_custom_range,
    )

    beatport_client = registry.get_ingest("beatport")
    releases, api_pages_fetched = beatport_client.fetch_weekly_releases(
        bp_token=params.bp_token,
        style_id=params.style_id,
        week_start=params.period_start,
        week_end=params.period_end,
        correlation_id=correlation_id,
    )

    duration_ms = int((time.perf_counter() - started_at_perf) * 1000)
    item_count = len(releases)
    meta = {
        "style_id": params.style_id,
        "iso_year": params.iso_year,
        "iso_week": params.iso_week,
        "week_year": params.week_year,
        "week_number": params.week_number,
        "period_start": params.period_start,
        "period_end": params.period_end,
        "is_custom_range": params.is_custom_range,
        "run_id": run_id,
        "correlation_id": correlation_id,
        "api_request_id": api_request_id,
        "lambda_request_id": lambda_request_id,
        "collected_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "item_count": item_count,
        "api_pages_fetched": api_pages_fetched,
        "duration_ms": duration_ms,
    }

    storage = S3Storage(
        s3_client=create_default_s3_client(),
        bucket_name=settings.raw_bucket_name,
        raw_prefix=settings.raw_prefix,
    )
    releases_key, _ = storage.write_run_artifacts(releases=releases, meta=meta)

    repository = create_clouder_repository_from_env()
    if repository is not None:
        repository.create_ingest_run(
            CreateIngestRunCmd(
                run_id=run_id,
                source="beatport",
                style_id=params.style_id,
                iso_year=params.iso_year,
                iso_week=params.iso_week,
                week_year=params.week_year,
                week_number=params.week_number,
                period_start=date.fromisoformat(params.period_start),
                period_end=date.fromisoformat(params.period_end),
                is_custom_range=params.is_custom_range,
                raw_s3_key=releases_key,
                status=RunStatus.RAW_SAVED,
                item_count=item_count,
                meta=meta,
                started_at=utc_now(),
            )
        )

    enqueue_result = _enqueue_canonicalization(
        run_id=run_id,
        s3_key=releases_key,
        style_id=params.style_id,
        iso_year=params.iso_year or 0,
        iso_week=params.iso_week or 0,
        correlation_id=correlation_id,
        settings=settings,
    )

    search_enqueued = 0
    if params.search_label_count and settings.ai_search_enabled:
        search_enqueued = _enqueue_label_search(
            limit=params.search_label_count,
            settings=settings,
            correlation_id=correlation_id,
        )

    response = {
        "run_id": run_id,
        "correlation_id": correlation_id,
        "api_request_id": api_request_id,
        "lambda_request_id": lambda_request_id,
        "iso_year": params.iso_year,
        "iso_week": params.iso_week,
        "week_year": params.week_year,
        "week_number": params.week_number,
        "period_start": params.period_start,
        "period_end": params.period_end,
        "is_custom_range": params.is_custom_range,
        "s3_object_key": releases_key,
        "item_count": item_count,
        "duration_ms": duration_ms,
        "run_status": RunStatus.RAW_SAVED.value,
        "processing_status": enqueue_result.processing_status.value,
        "processing_outcome": enqueue_result.processing_outcome.value,
        "processing_reason": (
            enqueue_result.processing_reason.value
            if enqueue_result.processing_reason
            else None
        ),
        "search_labels_enqueued": search_enqueued,
    }

    log_event(
        "INFO",
        "collection_completed",
        correlation_id=correlation_id,
        api_request_id=api_request_id,
        lambda_request_id=lambda_request_id,
        run_id=run_id,
        style_id=params.style_id,
        iso_year=params.iso_year,
        iso_week=params.iso_week,
        week_year=params.week_year,
        week_number=params.week_number,
        item_count=item_count,
        api_pages_fetched=api_pages_fetched,
        duration_ms=duration_ms,
        status_code=200,
        processing_status=enqueue_result.processing_status.value,
        processing_outcome=enqueue_result.processing_outcome.value,
    )
    return _json_response(200, response, correlation_id)
```

Add `from datetime import date` to the top imports.

- [ ] **Step 2: Reduce legacy `_handle_collect` to a thin wrapper**

```python
def _handle_collect(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    body = _parse_json_body(event)
    request = _parse_collect_request(body)
    week_start, week_end = compute_iso_week_date_range(
        request.iso_year, request.iso_week
    )
    params = _IngestParams(
        style_id=request.style_id,
        bp_token=request.bp_token,
        period_start=week_start,
        period_end=week_end,
        search_label_count=request.search_label_count,
        iso_year=request.iso_year,
        iso_week=request.iso_week,
        week_year=None,
        week_number=None,
        is_custom_range=False,
    )
    return _run_beatport_ingest(event, context, params)
```

- [ ] **Step 3: Run existing tests to confirm no regressions**

Run: `pytest tests/ -q -k 'collect or handler or ingest'`
Expected: all existing tests pass. Fix only what the refactor broke.

- [ ] **Step 4: Commit**

```bash
git add src/collector/handler.py
git commit -m "refactor(handler): extract _run_beatport_ingest shared helper"
```

---

### Task 6: Admin handler endpoints

**Files:**
- Modify: `src/collector/handler.py`

- [ ] **Step 1: Add `_handle_admin_ingest`**

Append after `_handle_collect`:

```python
def _handle_admin_ingest(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    body = _parse_json_body(event)
    try:
        request = AdminIngestRequestIn.model_validate(body)
    except PydanticValidationError as exc:
        raise ValidationError(validation_error_message(exc))

    from .saturday_week import saturday_week_range

    if request.period_start is None:
        std_start, std_end = saturday_week_range(
            request.week_year, request.week_number
        )
        period_start_iso = std_start.isoformat()
        period_end_iso = std_end.isoformat()
        is_custom = False
    else:
        period_start_iso = request.period_start.isoformat()
        period_end_iso = request.period_end.isoformat()
        is_custom = True

    params = _IngestParams(
        style_id=request.style_id,
        bp_token=request.bp_token,
        period_start=period_start_iso,
        period_end=period_end_iso,
        search_label_count=request.search_label_count,
        iso_year=None,
        iso_week=None,
        week_year=request.week_year,
        week_number=request.week_number,
        is_custom_range=is_custom,
    )
    return _run_beatport_ingest(event, context, params)
```

Add the import at top: `from .schemas import AdminIngestRequestIn` (alongside existing `CollectRequestIn`).

- [ ] **Step 2: Add `_handle_admin_coverage`**

```python
def _handle_admin_coverage(event: Mapping[str, Any]) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)
    qs = event.get("queryStringParameters") or {}
    raw = qs.get("week_year") if isinstance(qs, Mapping) else None
    if not raw or not raw.isdigit():
        raise ValidationError("week_year is required (4-digit year)")
    week_year = int(raw)
    if week_year < 2000 or week_year > 2100:
        raise ValidationError("week_year out of range")

    from .saturday_week import weeks_in_year

    repository = create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )

    rows = repository.coverage_for_year(week_year)

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = str(row["style_id"])
        if sid not in grouped:
            grouped[sid] = {
                "style_id": sid,
                "style_name": row["style_name"],
                "cells": [],
            }
        if row.get("run_id") is None:
            continue
        grouped[sid]["cells"].append(
            {
                "week_number": row["week_number"],
                "status": row["status"],
                "run_id": row["run_id"],
                "item_count": row["item_count"],
                "is_custom_range": bool(row.get("is_custom_range")),
                "period_start": _iso(row.get("period_start")),
                "period_end": _iso(row.get("period_end")),
                "started_at": _iso(row.get("started_at")),
                "finished_at": _iso(row.get("finished_at")),
            }
        )

    return _json_response(
        200,
        {
            "week_year": week_year,
            "weeks_in_year": weeks_in_year(week_year),
            "styles": list(grouped.values()),
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
```

- [ ] **Step 3: Add `_handle_admin_runs`**

```python
def _handle_admin_runs(event: Mapping[str, Any]) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)
    qs = event.get("queryStringParameters") or {}
    qs = qs if isinstance(qs, Mapping) else {}

    def _int_param(name: str) -> int:
        raw = qs.get(name)
        if not isinstance(raw, str) or not raw.lstrip("-").isdigit():
            raise ValidationError(f"{name} is required (integer)")
        return int(raw)

    style_id = _int_param("style_id")
    week_year = _int_param("week_year")
    week_number = _int_param("week_number")

    repository = create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )

    rows = repository.list_runs_for_cell(style_id, week_year, week_number)
    items = [
        {
            "run_id": r["run_id"],
            "status": r["status"],
            "started_at": _iso(r.get("started_at")),
            "finished_at": _iso(r.get("finished_at")),
            "item_count": r.get("item_count"),
            "processed_count": r.get("processed_count"),
            "error_code": r.get("error_code"),
            "error_message": r.get("error_message"),
            "is_custom_range": bool(r.get("is_custom_range")),
            "period_start": _iso(r.get("period_start")),
            "period_end": _iso(r.get("period_end")),
        }
        for r in rows
    ]

    return _json_response(200, {"items": items, "correlation_id": correlation_id}, correlation_id)
```

- [ ] **Step 4: Wire routes in `_route` and extend `_ADMIN_ROUTES`**

Replace `_ADMIN_ROUTES` and update `_route`:

```python
_ADMIN_ROUTES = frozenset({
    "POST /collect_bp_releases",          # legacy, kept for backward compatibility
    "POST /admin/beatport/ingest",
    "GET /admin/coverage",
    "GET /admin/runs",
    "GET /tracks/spotify-not-found",
})


def _route(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    route_key = _extract_route_key(event)
    if route_key in _ADMIN_ROUTES:
        _require_admin(event)
    if route_key == "GET /runs/{run_id}":
        return _handle_get_run(event, context)
    if route_key in ("POST /collect_bp_releases", ""):
        return _handle_collect(event, context)
    if route_key == "POST /admin/beatport/ingest":
        return _handle_admin_ingest(event, context)
    if route_key == "GET /admin/coverage":
        return _handle_admin_coverage(event)
    if route_key == "GET /admin/runs":
        return _handle_admin_runs(event)
    if route_key == "GET /tracks/spotify-not-found":
        return _handle_spotify_not_found(event)
    if route_key in _LIST_ROUTES:
        return _handle_list(event, route_key)
    return _json_response(
        404,
        {"error_code": "not_found", "message": "Route not found"},
        correlation_id,
    )
```

- [ ] **Step 5: Run all backend tests to confirm no regressions**

Run: `pytest -q`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add src/collector/handler.py
git commit -m "feat(api): add /admin/beatport/ingest + /admin/coverage + /admin/runs"
```

---

### Task 7: Integration tests for admin endpoints (TDD around the seam)

**Files:**
- Create: `tests/integration/test_admin_ingest_endpoint.py`
- Create: `tests/integration/test_admin_coverage_endpoint.py`
- Create: `tests/integration/test_admin_runs_endpoint.py`

- [ ] **Step 1: Inspect an existing integration test fixture for shape**

Run: `head -50 tests/integration/test_handler_collect.py`
(Or whichever existing collect-test is closest.) Use the same monkeypatching pattern (`monkeypatch.setenv`, fake repository, fake S3, fake registry).

- [ ] **Step 2: Write `test_admin_ingest_endpoint.py`**

```python
"""Integration tests for POST /admin/beatport/ingest."""

from __future__ import annotations

import json
from typing import Any

import pytest

from collector import handler


@pytest.fixture
def admin_event_factory():
    def _make(body: dict[str, Any], *, is_admin: bool = True) -> dict[str, Any]:
        return {
            "routeKey": "POST /admin/beatport/ingest",
            "rawPath": "/admin/beatport/ingest",
            "body": json.dumps(body),
            "isBase64Encoded": False,
            "headers": {"x-correlation-id": "test-corr"},
            "requestContext": {
                "requestId": "req-1",
                "authorizer": {"lambda": {"is_admin": is_admin}},
            },
        }

    return _make


def test_admin_ingest_rejects_non_admin(admin_event_factory):
    event = admin_event_factory(
        {
            "style_id": 1,
            "week_year": 2026,
            "week_number": 5,
            "bp_token": "tok",
        },
        is_admin=False,
    )
    response = handler.lambda_handler(event, type("Ctx", (), {"aws_request_id": "lr"})())
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "admin_required"


def test_admin_ingest_validation_only_period_start(admin_event_factory, monkeypatch):
    # No backend stubs needed — validation fires before any side-effect.
    event = admin_event_factory(
        {
            "style_id": 1,
            "week_year": 2026,
            "week_number": 5,
            "bp_token": "tok",
            "period_start": "2026-01-31",
        }
    )
    response = handler.lambda_handler(event, type("Ctx", (), {"aws_request_id": "lr"})())
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "validation_error"
```

(Note: full happy-path test requires the same monkeypatching scaffold as the existing collect tests — the new test file should reuse the same helpers. Add a happy-path case mirroring `test_handler_collect::test_handle_collect_persists_run` but submitting the new schema and asserting the response includes `week_year`, `week_number`, `is_custom_range`. Refer to the existing test for the exact stubs.)

- [ ] **Step 3: Write `test_admin_coverage_endpoint.py`**

```python
"""Integration tests for GET /admin/coverage."""

from __future__ import annotations

import json

import pytest

from collector import handler


def _event(qs: dict[str, str] | None, *, is_admin: bool = True):
    return {
        "routeKey": "GET /admin/coverage",
        "rawPath": "/admin/coverage",
        "queryStringParameters": qs,
        "headers": {"x-correlation-id": "c"},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": is_admin}},
            "requestId": "req",
        },
    }


def test_coverage_requires_admin():
    response = handler.lambda_handler(
        _event({"week_year": "2026"}, is_admin=False), type("C", (), {"aws_request_id": "x"})()
    )
    assert response["statusCode"] == 403


def test_coverage_missing_week_year_400():
    response = handler.lambda_handler(
        _event(None), type("C", (), {"aws_request_id": "x"})()
    )
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "validation_error"


def test_coverage_db_not_configured_503(monkeypatch):
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: None
    )
    response = handler.lambda_handler(
        _event({"week_year": "2026"}), type("C", (), {"aws_request_id": "x"})()
    )
    assert response["statusCode"] == 503
    body = json.loads(response["body"])
    assert body["error_code"] == "db_not_configured"


def test_coverage_returns_grouped_styles(monkeypatch):
    rows = [
        {
            "style_id": "s1",
            "style_name": "Tech House",
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
            "style_id": "s1",
            "style_name": "Tech House",
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
        {
            "style_id": "s2",
            "style_name": "Melodic",
            "run_id": "r2",
            "week_number": 4,
            "status": "completed",
            "item_count": 50,
            "is_custom_range": True,
            "period_start": "2026-01-25",
            "period_end": "2026-02-02",
            "started_at": "2026-02-03T10:00:00Z",
            "finished_at": "2026-02-03T10:01:00Z",
        },
    ]

    class FakeRepo:
        def coverage_for_year(self, week_year):
            assert week_year == 2026
            return rows

    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env",
        lambda: FakeRepo(),
    )
    response = handler.lambda_handler(
        _event({"week_year": "2026"}), type("C", (), {"aws_request_id": "x"})()
    )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["week_year"] == 2026
    assert body["weeks_in_year"] == 52
    styles = {s["style_id"]: s for s in body["styles"]}
    assert {"s1", "s2"} == set(styles.keys())
    assert len(styles["s1"]["cells"]) == 1
    assert styles["s1"]["cells"][0]["week_number"] == 1
    assert styles["s2"]["cells"][0]["is_custom_range"] is True
```

- [ ] **Step 4: Write `test_admin_runs_endpoint.py`**

```python
"""Integration tests for GET /admin/runs."""

from __future__ import annotations

import json

import pytest

from collector import handler


def _event(qs: dict[str, str] | None, *, is_admin: bool = True):
    return {
        "routeKey": "GET /admin/runs",
        "rawPath": "/admin/runs",
        "queryStringParameters": qs,
        "headers": {"x-correlation-id": "c"},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": is_admin}},
            "requestId": "req",
        },
    }


def test_admin_runs_requires_admin():
    response = handler.lambda_handler(
        _event({"style_id": "1", "week_year": "2026", "week_number": "5"}, is_admin=False),
        type("C", (), {"aws_request_id": "x"})(),
    )
    assert response["statusCode"] == 403


def test_admin_runs_missing_param_400():
    response = handler.lambda_handler(
        _event({"week_year": "2026", "week_number": "5"}),
        type("C", (), {"aws_request_id": "x"})(),
    )
    assert response["statusCode"] == 400


def test_admin_runs_returns_items_desc(monkeypatch):
    rows = [
        {
            "run_id": "r2",
            "status": "completed",
            "started_at": "2026-02-03T10:00:00Z",
            "finished_at": "2026-02-03T10:01:00Z",
            "item_count": 100,
            "processed_count": 100,
            "error_code": None,
            "error_message": None,
            "is_custom_range": False,
            "period_start": "2026-01-31",
            "period_end": "2026-02-06",
        },
        {
            "run_id": "r1",
            "status": "failed",
            "started_at": "2026-02-02T10:00:00Z",
            "finished_at": "2026-02-02T10:00:30Z",
            "item_count": 0,
            "processed_count": 0,
            "error_code": "bp_token_invalid",
            "error_message": "Beatport token rejected",
            "is_custom_range": False,
            "period_start": "2026-01-31",
            "period_end": "2026-02-06",
        },
    ]

    class FakeRepo:
        def list_runs_for_cell(self, style_id, week_year, week_number):
            assert (style_id, week_year, week_number) == (1, 2026, 5)
            return rows

    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env",
        lambda: FakeRepo(),
    )

    response = handler.lambda_handler(
        _event({"style_id": "1", "week_year": "2026", "week_number": "5"}),
        type("C", (), {"aws_request_id": "x"})(),
    )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert [it["run_id"] for it in body["items"]] == ["r2", "r1"]
    assert body["items"][1]["error_code"] == "bp_token_invalid"
```

- [ ] **Step 5: Run integration tests**

Run: `pytest tests/integration/test_admin_ingest_endpoint.py tests/integration/test_admin_coverage_endpoint.py tests/integration/test_admin_runs_endpoint.py -q`
Expected: all passing (each happy-path may need tweaks; iterate locally).

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_admin_*
git commit -m "test(admin): integration coverage for new endpoints"
```

---

### Task 8: Terraform — register the three new routes

**Files:**
- Modify: `infra/api_gateway.tf`

- [ ] **Step 1: Append routes**

Append to the end of the file (before `aws_apigatewayv2_stage`):

```hcl
resource "aws_apigatewayv2_route" "admin_beatport_ingest" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /admin/beatport/ingest"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "admin_coverage" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /admin/coverage"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "admin_runs" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /admin/runs"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 2: Validate Terraform**

Run: `cd infra && terraform fmt -check && terraform validate`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add infra/api_gateway.tf
git commit -m "feat(infra): register admin API routes in API Gateway"
```

---

### Task 9: Update `scripts/generate_openapi.py` and regenerate spec

**Files:**
- Modify: `scripts/generate_openapi.py`
- Regenerate: `docs/openapi.yaml`

- [ ] **Step 1: Add `AdminIngestRequestIn` to imports**

In `scripts/generate_openapi.py`, change:

```python
from collector.schemas import CollectRequestIn
```

to:

```python
from collector.schemas import CollectRequestIn, AdminIngestRequestIn
```

- [ ] **Step 2: Register it in `_collect_pydantic_schemas`**

In the `for name, model in (...)` tuple, append `("AdminIngestRequestIn", AdminIngestRequestIn),`.

- [ ] **Step 3: Add three route entries to `ROUTES`**

Insert after the existing `/collect_bp_releases` block:

```python
{
    "method": "post",
    "path": "/admin/beatport/ingest",
    "auth": ADMIN,
    "summary": "Admin: trigger Beatport ingest with Saturday-week or custom range.",
    "description": (
        "Saturday-week semantics. If `period_start` and `period_end` are "
        "omitted, the server computes them from `(week_year, week_number)`. "
        "If both are present the run is recorded with `is_custom_range = true`."
    ),
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/AdminIngestRequestIn"},
            }
        },
    },
    "request_example": {
        "style_id": 90,
        "week_year": 2026,
        "week_number": 17,
        "bp_token": "REDACTED",
    },
    "responses": {
        "200": _make_response(
            200,
            "Run created.",
            {"$ref": "#/components/schemas/CollectResponse"},
        ),
        "400": _error(400, "validation_error."),
        **COMMON_AUTH_ERRORS,
        "403": _error(403, "admin_required."),
        "502": _error(502, "beatport_unavailable."),
    },
},
{
    "method": "get",
    "path": "/admin/coverage",
    "auth": ADMIN,
    "summary": "Admin: ingest coverage matrix for one Saturday-year.",
    "parameters": [
        {
            "name": "week_year",
            "in": "query",
            "required": True,
            "schema": {"type": "integer", "minimum": 2000, "maximum": 2100},
        }
    ],
    "responses": {
        "200": _make_response(
            200,
            "Coverage payload.",
            {"type": "object"},
        ),
        "400": _error(400, "validation_error."),
        "503": _error(503, "db_not_configured."),
        **COMMON_AUTH_ERRORS,
        "403": _error(403, "admin_required."),
    },
},
{
    "method": "get",
    "path": "/admin/runs",
    "auth": ADMIN,
    "summary": "Admin: list runs for one (style, week_year, week_number) cell.",
    "parameters": [
        {"name": "style_id", "in": "query", "required": True, "schema": {"type": "integer"}},
        {"name": "week_year", "in": "query", "required": True, "schema": {"type": "integer"}},
        {"name": "week_number", "in": "query", "required": True, "schema": {"type": "integer"}},
    ],
    "responses": {
        "200": _make_response(200, "Runs (DESC by started_at).", {"type": "object"}),
        "400": _error(400, "validation_error."),
        "503": _error(503, "db_not_configured."),
        **COMMON_AUTH_ERRORS,
        "403": _error(403, "admin_required."),
    },
},
```

- [ ] **Step 4: Regenerate `docs/openapi.yaml`**

Run: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`
Expected: `wrote docs/openapi.yaml (...)`.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_openapi.py docs/openapi.yaml
git commit -m "docs(openapi): expose /admin/* routes"
```

---

## Phase 2 — Frontend foundation

### Task 10: Frontend Saturday-week math (TDD)

**Files:**
- Create: `frontend/src/features/admin/lib/saturdayWeek.ts`
- Test: `frontend/src/features/admin/lib/saturdayWeek.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// frontend/src/features/admin/lib/saturdayWeek.test.ts
import { describe, expect, it } from 'vitest';
import {
  firstSaturday,
  saturdayWeekRange,
  weekOfDate,
  weeksInYear,
} from './saturdayWeek';

describe('saturdayWeek', () => {
  it('firstSaturday(2026) = 2026-01-03', () => {
    expect(firstSaturday(2026).toISOString().slice(0, 10)).toBe('2026-01-03');
  });

  it('firstSaturday(2028) = 2028-01-01 (Jan 1 itself is Saturday)', () => {
    expect(firstSaturday(2028).toISOString().slice(0, 10)).toBe('2028-01-01');
  });

  it('saturdayWeekRange(2026,1) = 2026-01-03..2026-01-09', () => {
    const [s, e] = saturdayWeekRange(2026, 1);
    expect(s.toISOString().slice(0, 10)).toBe('2026-01-03');
    expect(e.toISOString().slice(0, 10)).toBe('2026-01-09');
  });

  it('weeksInYear(2026) = 52', () => {
    expect(weeksInYear(2026)).toBe(52);
  });

  it('weeksInYear(2028) = 53', () => {
    expect(weeksInYear(2028)).toBe(53);
  });

  it('weekOfDate(2027-01-01) = (2026,52) — falls before first Saturday of 2027', () => {
    expect(weekOfDate(new Date(Date.UTC(2027, 0, 1)))).toEqual([2026, 52]);
  });

  it('saturdayWeekRange round-trips with weekOfDate for all weeks of 2026', () => {
    for (let n = 1; n <= weeksInYear(2026); n += 1) {
      const [start] = saturdayWeekRange(2026, n);
      expect(weekOfDate(start)).toEqual([2026, n]);
    }
  });

  it('saturdayWeekRange throws on out-of-range', () => {
    expect(() => saturdayWeekRange(2026, 0)).toThrow();
    expect(() => saturdayWeekRange(2026, weeksInYear(2026) + 1)).toThrow();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && pnpm test src/features/admin/lib/saturdayWeek.test.ts -- --run`
Expected: cannot find module.

- [ ] **Step 3: Implement**

```typescript
// frontend/src/features/admin/lib/saturdayWeek.ts
const SATURDAY = 6; // JS getUTCDay(): Sun=0..Sat=6

function utcDate(year: number, month: number, day: number): Date {
  return new Date(Date.UTC(year, month, day));
}

export function firstSaturday(year: number): Date {
  const jan1 = utcDate(year, 0, 1);
  const delta = (SATURDAY - jan1.getUTCDay() + 7) % 7;
  return utcDate(year, 0, 1 + delta);
}

function lastSaturdayOnOrBefore(d: Date): Date {
  const delta = (d.getUTCDay() - SATURDAY + 7) % 7;
  return new Date(d.getTime() - delta * 86_400_000);
}

export function weeksInYear(year: number): number {
  const start = firstSaturday(year);
  const end = lastSaturdayOnOrBefore(utcDate(year, 11, 31));
  return Math.floor((end.getTime() - start.getTime()) / (7 * 86_400_000)) + 1;
}

export function saturdayWeekRange(year: number, week: number): [Date, Date] {
  const max = weeksInYear(year);
  if (week < 1 || week > max) {
    throw new RangeError(`week ${week} out of range for year ${year} (1..${max})`);
  }
  const start = new Date(firstSaturday(year).getTime() + (week - 1) * 7 * 86_400_000);
  const end = new Date(start.getTime() + 6 * 86_400_000);
  return [start, end];
}

export function weekOfDate(d: Date): [number, number] {
  const saturday = lastSaturdayOnOrBefore(d);
  const year = saturday.getUTCFullYear();
  const fs = firstSaturday(year);
  if (saturday.getTime() < fs.getTime()) {
    const prev = year - 1;
    const prevFs = firstSaturday(prev);
    const week = Math.floor((saturday.getTime() - prevFs.getTime()) / (7 * 86_400_000)) + 1;
    return [prev, week];
  }
  const week = Math.floor((saturday.getTime() - fs.getTime()) / (7 * 86_400_000)) + 1;
  return [year, week];
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && pnpm test src/features/admin/lib/saturdayWeek.test.ts -- --run`
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/admin/lib/saturdayWeek.ts frontend/src/features/admin/lib/saturdayWeek.test.ts
git commit -m "feat(admin/fe): add saturdayWeek mirror of BE math"
```

---

### Task 11: requireAdmin loader (TDD)

**Files:**
- Create: `frontend/src/auth/requireAdmin.ts`
- Create: `frontend/src/auth/__tests__/requireAdmin.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// frontend/src/auth/__tests__/requireAdmin.test.ts
import { describe, expect, it, vi } from 'vitest';
import { requireAdmin } from '../requireAdmin';

vi.mock('../bootstrap', () => ({
  bootstrapPromise: () => Promise.resolve(),
}));

const snapMock = vi.hoisted(() => vi.fn());
vi.mock('../AuthProvider', () => ({
  getAuthSnapshot: () => snapMock(),
}));

describe('requireAdmin', () => {
  it('redirects to / when unauthenticated', async () => {
    snapMock.mockReturnValue({ status: 'unauthenticated' });
    await expect(
      requireAdmin({ request: new Request('http://x/admin'), params: {} } as never),
    ).rejects.toMatchObject({ status: 302 });
  });

  it('redirects to / when user has is_admin=false', async () => {
    snapMock.mockReturnValue({
      status: 'authenticated',
      user: { id: 'u', spotify_id: 's', display_name: 'D', is_admin: false },
      expiresAt: 0,
      spotifyAccessToken: null,
    });
    await expect(
      requireAdmin({ request: new Request('http://x/admin'), params: {} } as never),
    ).rejects.toMatchObject({ status: 302 });
  });

  it('returns null when admin', async () => {
    snapMock.mockReturnValue({
      status: 'authenticated',
      user: { id: 'u', spotify_id: 's', display_name: 'D', is_admin: true },
      expiresAt: 0,
      spotifyAccessToken: null,
    });
    const result = await requireAdmin({
      request: new Request('http://x/admin'),
      params: {},
    } as never);
    expect(result).toBeNull();
  });
});
```

- [ ] **Step 2: Run failing test**

Run: `cd frontend && pnpm test src/auth/__tests__/requireAdmin.test.ts -- --run`
Expected: cannot find module.

- [ ] **Step 3: Implement**

```typescript
// frontend/src/auth/requireAdmin.ts
import { redirect, type LoaderFunction } from 'react-router';
import { getAuthSnapshot } from './AuthProvider';
import { bootstrapPromise } from './bootstrap';

export const requireAdmin: LoaderFunction = async () => {
  await bootstrapPromise();
  const snap = getAuthSnapshot();
  if (snap.status !== 'authenticated') throw redirect('/');
  if (!snap.user.is_admin) throw redirect('/');
  return null;
};
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && pnpm test src/auth/__tests__/requireAdmin.test.ts -- --run`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/auth/requireAdmin.ts frontend/src/auth/__tests__/requireAdmin.test.ts
git commit -m "feat(auth/fe): add requireAdmin loader"
```

---

### Task 12: bpTokenStore + useBpToken (TDD)

**Files:**
- Create: `frontend/src/features/admin/lib/bpTokenStore.ts`
- Create: `frontend/src/features/admin/lib/__tests__/bpTokenStore.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// frontend/src/features/admin/lib/__tests__/bpTokenStore.test.ts
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { bpTokenStore, useBpToken } from '../bpTokenStore';

describe('bpTokenStore', () => {
  it('stores, returns, and clears the token', () => {
    bpTokenStore.clear();
    expect(bpTokenStore.get()).toBeNull();
    bpTokenStore.set('abc');
    expect(bpTokenStore.get()).toBe('abc');
    bpTokenStore.clear();
    expect(bpTokenStore.get()).toBeNull();
  });

  it('useBpToken re-renders on changes', () => {
    bpTokenStore.clear();
    const { result } = renderHook(() => useBpToken());
    expect(result.current).toBeNull();
    act(() => bpTokenStore.set('xyz'));
    expect(result.current).toBe('xyz');
    act(() => bpTokenStore.clear());
    expect(result.current).toBeNull();
  });
});
```

- [ ] **Step 2: Run failing tests**

Run: `cd frontend && pnpm test src/features/admin/lib/__tests__/bpTokenStore.test.ts -- --run`
Expected: cannot find module.

- [ ] **Step 3: Implement**

```typescript
// frontend/src/features/admin/lib/bpTokenStore.ts
import { useSyncExternalStore } from 'react';

let value: string | null = null;
const listeners = new Set<() => void>();

export const bpTokenStore = {
  get(): string | null {
    return value;
  },
  set(next: string | null): void {
    if (value === next) return;
    value = next === '' ? null : next;
    listeners.forEach((l) => l());
  },
  clear(): void {
    if (value === null) return;
    value = null;
    listeners.forEach((l) => l());
  },
  subscribe(cb: () => void): () => void {
    listeners.add(cb);
    return () => listeners.delete(cb);
  },
};

export function useBpToken(): string | null {
  return useSyncExternalStore(bpTokenStore.subscribe, bpTokenStore.get, bpTokenStore.get);
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && pnpm test src/features/admin/lib/__tests__/bpTokenStore.test.ts -- --run`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/admin/lib/bpTokenStore.ts frontend/src/features/admin/lib/__tests__/bpTokenStore.test.ts
git commit -m "feat(admin/fe): add bpTokenStore (in-memory)"
```

---

### Task 13: runsTracker (TDD)

**Files:**
- Create: `frontend/src/features/admin/lib/runsTracker.ts`
- Create: `frontend/src/features/admin/lib/__tests__/runsTracker.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// frontend/src/features/admin/lib/__tests__/runsTracker.test.ts
import { describe, expect, it } from 'vitest';
import { runsTrackerStore, type RunMeta } from '../runsTracker';

const meta = (run_id: string): RunMeta => ({
  run_id,
  styleId: 1,
  weekYear: 2026,
  weekNumber: 5,
  startedAt: Date.now(),
});

describe('runsTracker', () => {
  it('add → list → remove', () => {
    runsTrackerStore.getState().clear();
    runsTrackerStore.getState().add(meta('r1'));
    runsTrackerStore.getState().add(meta('r2'));
    expect(runsTrackerStore.getState().runs.size).toBe(2);
    runsTrackerStore.getState().remove('r1');
    expect(runsTrackerStore.getState().runs.has('r1')).toBe(false);
    expect(runsTrackerStore.getState().runs.has('r2')).toBe(true);
  });

  it('isRunning returns true for matching cell', () => {
    runsTrackerStore.getState().clear();
    runsTrackerStore.getState().add(meta('r1'));
    expect(runsTrackerStore.getState().isRunning(1, 2026, 5)).toBe(true);
    expect(runsTrackerStore.getState().isRunning(2, 2026, 5)).toBe(false);
  });
});
```

- [ ] **Step 2: Run failing tests**

Run: `cd frontend && pnpm test src/features/admin/lib/__tests__/runsTracker.test.ts -- --run`

- [ ] **Step 3: Implement**

```typescript
// frontend/src/features/admin/lib/runsTracker.ts
import { create } from 'zustand';

export interface RunMeta {
  run_id: string;
  styleId: number;
  weekYear: number;
  weekNumber: number;
  startedAt: number;
}

interface RunsState {
  runs: Map<string, RunMeta>;
  add: (meta: RunMeta) => void;
  remove: (run_id: string) => void;
  clear: () => void;
  isRunning: (styleId: number, weekYear: number, weekNumber: number) => boolean;
}

export const runsTrackerStore = create<RunsState>((set, get) => ({
  runs: new Map(),
  add: (meta) =>
    set((s) => {
      const next = new Map(s.runs);
      next.set(meta.run_id, meta);
      return { runs: next };
    }),
  remove: (run_id) =>
    set((s) => {
      const next = new Map(s.runs);
      next.delete(run_id);
      return { runs: next };
    }),
  clear: () => set({ runs: new Map() }),
  isRunning: (styleId, weekYear, weekNumber) => {
    for (const meta of get().runs.values()) {
      if (
        meta.styleId === styleId &&
        meta.weekYear === weekYear &&
        meta.weekNumber === weekNumber
      ) {
        return true;
      }
    }
    return false;
  },
}));
```

> **Note:** `zustand` is not yet in the dependency set. Verify with `cd frontend && pnpm list zustand`. If absent, run `cd frontend && pnpm add zustand` and commit `package.json` + `pnpm-lock.yaml` together.

- [ ] **Step 4: Run tests**

Run: `cd frontend && pnpm test src/features/admin/lib/__tests__/runsTracker.test.ts -- --run`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/admin/lib/runsTracker.ts frontend/src/features/admin/lib/__tests__/runsTracker.test.ts frontend/package.json frontend/pnpm-lock.yaml
git commit -m "feat(admin/fe): add runsTracker zustand store"
```

---

### Task 14: cellState helper (TDD)

**Files:**
- Create: `frontend/src/features/admin/lib/cellState.ts`
- Create: `frontend/src/features/admin/lib/__tests__/cellState.test.ts`

- [ ] **Step 1: Write tests**

```typescript
// frontend/src/features/admin/lib/__tests__/cellState.test.ts
import { describe, expect, it } from 'vitest';
import { cellState, type CoverageCell } from '../cellState';

const empty = undefined as CoverageCell | undefined;
const ok: CoverageCell = {
  week_number: 1,
  status: 'completed',
  run_id: 'r',
  item_count: 1,
  is_custom_range: false,
  period_start: '2026-01-03',
  period_end: '2026-01-09',
  started_at: '2026-01-04T09:00:00Z',
  finished_at: '2026-01-04T09:01:00Z',
};

describe('cellState', () => {
  it('empty when no cell + not running', () => {
    expect(cellState(empty, false)).toBe('empty');
  });

  it('running when active in tracker', () => {
    expect(cellState(empty, true)).toBe('running');
    expect(cellState(ok, true)).toBe('running');
  });

  it('loaded for completed standard', () => {
    expect(cellState(ok, false)).toBe('loaded');
  });

  it('loaded-custom for completed + is_custom_range', () => {
    expect(cellState({ ...ok, is_custom_range: true }, false)).toBe('loaded-custom');
  });

  it('failed for failed status', () => {
    expect(cellState({ ...ok, status: 'failed' }, false)).toBe('failed');
  });

  it('running for processing/queued status', () => {
    expect(cellState({ ...ok, status: 'processing' }, false)).toBe('running');
    expect(cellState({ ...ok, status: 'queued' }, false)).toBe('running');
  });
});
```

- [ ] **Step 2: Run failing tests**

Run: `cd frontend && pnpm test src/features/admin/lib/__tests__/cellState.test.ts -- --run`

- [ ] **Step 3: Implement**

```typescript
// frontend/src/features/admin/lib/cellState.ts
export interface CoverageCell {
  week_number: number;
  status: string; // 'completed' | 'failed' | 'queued' | 'processing' | 'raw_saved'
  run_id: string;
  item_count: number;
  is_custom_range: boolean;
  period_start: string;
  period_end: string;
  started_at: string;
  finished_at: string | null;
}

export type CellState =
  | 'empty'
  | 'loaded'
  | 'loaded-custom'
  | 'failed'
  | 'running'
  | 'n/a';

const RUNNING = new Set(['queued', 'processing', 'raw_saved']);

export function cellState(
  cell: CoverageCell | undefined,
  isTrackedRunning: boolean,
): CellState {
  if (isTrackedRunning) return 'running';
  if (!cell) return 'empty';
  if (RUNNING.has(cell.status.toLowerCase())) return 'running';
  if (cell.status.toLowerCase() === 'failed') return 'failed';
  if (cell.status.toLowerCase() === 'completed') {
    return cell.is_custom_range ? 'loaded-custom' : 'loaded';
  }
  return 'empty';
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && pnpm test src/features/admin/lib/__tests__/cellState.test.ts -- --run`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/admin/lib/cellState.ts frontend/src/features/admin/lib/__tests__/cellState.test.ts
git commit -m "feat(admin/fe): add cellState derivation helper"
```

---

### Task 15: Hooks — useCoverage / useCellRuns / useStartIngest / useRunPoller / useSpotifyNotFound

**Files:**
- Create: `frontend/src/features/admin/hooks/useCoverage.ts`
- Create: `frontend/src/features/admin/hooks/useCellRuns.ts`
- Create: `frontend/src/features/admin/hooks/useStartIngest.ts`
- Create: `frontend/src/features/admin/hooks/useRunPoller.ts`
- Create: `frontend/src/features/admin/hooks/useSpotifyNotFound.ts`
- Create: `frontend/src/features/admin/hooks/__tests__/useRunPoller.test.tsx`

- [ ] **Step 1: Write `useCoverage`**

```typescript
// frontend/src/features/admin/hooks/useCoverage.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface CoveragePayload {
  week_year: number;
  weeks_in_year: number;
  styles: Array<{
    style_id: string;
    style_name: string;
    cells: Array<{
      week_number: number;
      status: string;
      run_id: string;
      item_count: number;
      is_custom_range: boolean;
      period_start: string;
      period_end: string;
      started_at: string;
      finished_at: string | null;
    }>;
  }>;
}

export function useCoverage(weekYear: number) {
  return useQuery({
    queryKey: ['admin', 'coverage', weekYear],
    queryFn: () => api<CoveragePayload>(`/admin/coverage?week_year=${weekYear}`),
    staleTime: 30_000,
  });
}
```

- [ ] **Step 2: Write `useCellRuns`**

```typescript
// frontend/src/features/admin/hooks/useCellRuns.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface CellRun {
  run_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  item_count: number | null;
  processed_count: number | null;
  error_code: string | null;
  error_message: string | null;
  is_custom_range: boolean;
  period_start: string;
  period_end: string;
}

export function useCellRuns(args: {
  styleId: number;
  weekYear: number;
  weekNumber: number;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: ['admin', 'runs', args.styleId, args.weekYear, args.weekNumber],
    queryFn: () =>
      api<{ items: CellRun[] }>(
        `/admin/runs?style_id=${args.styleId}&week_year=${args.weekYear}&week_number=${args.weekNumber}`,
      ),
    enabled: args.enabled ?? true,
  });
}
```

- [ ] **Step 3: Write `useStartIngest`**

```typescript
// frontend/src/features/admin/hooks/useStartIngest.ts
import { useMutation } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { runsTrackerStore } from '../lib/runsTracker';

export interface IngestInput {
  style_id: number;
  week_year: number;
  week_number: number;
  bp_token: string;
  period_start?: string;
  period_end?: string;
  search_label_count?: number;
}

export interface IngestResponse {
  run_id: string;
  run_status: string;
  processing_status: string;
  is_custom_range: boolean;
}

export function useStartIngest() {
  return useMutation({
    mutationFn: (input: IngestInput) =>
      api<IngestResponse>('/admin/beatport/ingest', {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    onSuccess: (data, vars) => {
      runsTrackerStore.getState().add({
        run_id: data.run_id,
        styleId: vars.style_id,
        weekYear: vars.week_year,
        weekNumber: vars.week_number,
        startedAt: Date.now(),
      });
    },
  });
}
```

- [ ] **Step 4: Write `useRunPoller`**

```typescript
// frontend/src/features/admin/hooks/useRunPoller.ts
import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { runsTrackerStore } from '../lib/runsTracker';

interface RunPayload {
  run_id: string;
  status: string;
}

const TERMINAL = new Set(['completed', 'failed']);

export function useRunPoller(
  run_id: string | null,
  args: { styleId: number; weekYear: number; weekNumber: number } | null,
) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ['runs', run_id],
    queryFn: () => api<RunPayload>(`/runs/${run_id}`),
    enabled: !!run_id,
    refetchInterval: (q) => {
      const data = q.state.data as RunPayload | undefined;
      if (!data) return 2000;
      return TERMINAL.has(data.status.toLowerCase()) ? false : 2000;
    },
  });

  useEffect(() => {
    if (!query.data || !run_id || !args) return;
    if (!TERMINAL.has(query.data.status.toLowerCase())) return;
    runsTrackerStore.getState().remove(run_id);
    void qc.invalidateQueries({ queryKey: ['admin', 'coverage', args.weekYear] });
    void qc.invalidateQueries({
      queryKey: ['admin', 'runs', args.styleId, args.weekYear, args.weekNumber],
    });
  }, [query.data, run_id, args, qc]);

  return query;
}
```

- [ ] **Step 5: Write a focused test for `useRunPoller`**

```typescript
// frontend/src/features/admin/hooks/__tests__/useRunPoller.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { useRunPoller } from '../useRunPoller';
import { runsTrackerStore } from '../../lib/runsTracker';

const server = setupServer();
beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  runsTrackerStore.getState().clear();
});
afterAll(() => server.close());

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useRunPoller', () => {
  it('removes run from tracker on terminal status', async () => {
    runsTrackerStore.getState().add({
      run_id: 'r1',
      styleId: 1,
      weekYear: 2026,
      weekNumber: 5,
      startedAt: 0,
    });
    server.use(
      http.get('http://localhost/runs/r1', () =>
        HttpResponse.json({ run_id: 'r1', status: 'completed' }),
      ),
    );

    renderHook(
      () => useRunPoller('r1', { styleId: 1, weekYear: 2026, weekNumber: 5 }),
      { wrapper: wrapper() },
    );

    await waitFor(() =>
      expect(runsTrackerStore.getState().runs.has('r1')).toBe(false),
    );
  });
});
```

- [ ] **Step 6: Write `useSpotifyNotFound`**

```typescript
// frontend/src/features/admin/hooks/useSpotifyNotFound.ts
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface SpotifyNotFoundItem {
  track_id: string;
  title: string;
  artists: string[];
  album?: string | null;
  label?: string | null;
  style?: string | null;
  isrc?: string | null;
  last_seen_at?: string | null;
}

export function useSpotifyNotFound(args: {
  limit: number;
  offset: number;
  search: string;
}) {
  const params = new URLSearchParams({
    limit: String(args.limit),
    offset: String(args.offset),
  });
  if (args.search) params.set('search', args.search);
  return useQuery({
    queryKey: ['admin', 'spotifyNotFound', args.limit, args.offset, args.search],
    queryFn: () =>
      api<{ items: SpotifyNotFoundItem[]; total: number; limit: number; offset: number }>(
        `/tracks/spotify-not-found?${params.toString()}`,
      ),
    placeholderData: keepPreviousData,
  });
}
```

- [ ] **Step 7: Run hook tests**

Run: `cd frontend && pnpm test src/features/admin/hooks -- --run`
Expected: passes.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/admin/hooks
git commit -m "feat(admin/fe): add coverage/runs/ingest/poller/spotify hooks"
```

---

## Phase 3 — Frontend UI components

### Task 16: YearNavigator

**Files:**
- Create: `frontend/src/features/admin/components/YearNavigator.tsx`
- Create: `frontend/src/features/admin/components/__tests__/YearNavigator.test.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/admin/components/YearNavigator.tsx
import { ActionIcon, Group, Select, Text } from '@mantine/core';
import { weeksInYear } from '../lib/saturdayWeek';

interface Props {
  year: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
}

export function YearNavigator({ year, onChange, min = 2024, max = 2030 }: Props) {
  const years = [];
  for (let y = min; y <= max; y += 1) years.push(String(y));
  return (
    <Group gap="xs" align="center">
      <ActionIcon
        variant="default"
        aria-label="Previous year"
        disabled={year <= min}
        onClick={() => onChange(year - 1)}
      >
        ‹
      </ActionIcon>
      <Select
        data={years}
        value={String(year)}
        onChange={(v) => v && onChange(Number(v))}
        w={110}
        aria-label="Year"
      />
      <ActionIcon
        variant="default"
        aria-label="Next year"
        disabled={year >= max}
        onClick={() => onChange(year + 1)}
      >
        ›
      </ActionIcon>
      <Text size="sm" c="dimmed">
        {weeksInYear(year)} weeks
      </Text>
    </Group>
  );
}
```

- [ ] **Step 2: Test**

```tsx
// frontend/src/features/admin/components/__tests__/YearNavigator.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { YearNavigator } from '../YearNavigator';

function ui(props: React.ComponentProps<typeof YearNavigator>) {
  return (
    <MantineProvider theme={testTheme}>
      <YearNavigator {...props} />
    </MantineProvider>
  );
}

describe('YearNavigator', () => {
  it('decrements via prev button', async () => {
    const onChange = vi.fn();
    render(ui({ year: 2026, onChange }));
    await userEvent.click(screen.getByLabelText('Previous year'));
    expect(onChange).toHaveBeenCalledWith(2025);
  });

  it('increments via next button', async () => {
    const onChange = vi.fn();
    render(ui({ year: 2026, onChange }));
    await userEvent.click(screen.getByLabelText('Next year'));
    expect(onChange).toHaveBeenCalledWith(2027);
  });

  it('disables prev at min', () => {
    render(ui({ year: 2024, onChange: vi.fn() }));
    expect(screen.getByLabelText('Previous year')).toBeDisabled();
  });
});
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && pnpm test src/features/admin/components/__tests__/YearNavigator.test.tsx -- --run`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/admin/components/YearNavigator.tsx frontend/src/features/admin/components/__tests__/YearNavigator.test.tsx
git commit -m "feat(admin/fe): add YearNavigator"
```

---

### Task 17: CoverageMatrix + cell

**Files:**
- Create: `frontend/src/features/admin/components/CoverageMatrix.tsx`
- Create: `frontend/src/features/admin/components/CoverageMatrixCell.tsx`
- Create: `frontend/src/features/admin/components/__tests__/CoverageMatrix.test.tsx`

- [ ] **Step 1: Implement `CoverageMatrixCell`**

```tsx
// frontend/src/features/admin/components/CoverageMatrixCell.tsx
import { Box, Tooltip } from '@mantine/core';
import { memo } from 'react';
import type { CellState } from '../lib/cellState';

interface Props {
  styleId: number;
  styleName: string;
  weekNumber: number;
  state: CellState;
  tooltip: string;
  onClick: (styleId: number, weekNumber: number) => void;
}

const COLORS: Record<CellState, string> = {
  empty: 'var(--mantine-color-dark-6)',
  loaded: 'var(--mantine-color-green-7)',
  'loaded-custom': 'var(--mantine-color-green-7)',
  failed: 'var(--mantine-color-red-7)',
  running: 'var(--mantine-color-yellow-5)',
  'n/a': 'var(--mantine-color-dark-8)',
};

function CoverageMatrixCellInner({
  styleId,
  styleName,
  weekNumber,
  state,
  tooltip,
  onClick,
}: Props) {
  return (
    <Tooltip label={tooltip} withArrow disabled={!tooltip}>
      <Box
        component="button"
        type="button"
        aria-label={`${styleName} week ${weekNumber} ${state}`}
        onClick={() => onClick(styleId, weekNumber)}
        data-state={state}
        style={{
          width: 24,
          height: 24,
          borderRadius: 4,
          border: 'none',
          padding: 0,
          background: COLORS[state],
          outline:
            state === 'loaded-custom'
              ? '1px solid var(--mantine-color-yellow-5)'
              : undefined,
          cursor: state === 'n/a' ? 'default' : 'pointer',
          opacity: state === 'n/a' ? 0.4 : 1,
          animation: state === 'running' ? 'admin-pulse 1.4s infinite' : undefined,
        }}
      />
    </Tooltip>
  );
}

export const CoverageMatrixCell = memo(CoverageMatrixCellInner);
```

- [ ] **Step 2: Add the keyframe in a CSS module (or global)**

Create `frontend/src/features/admin/components/CoverageMatrix.module.css`:

```css
@keyframes admin-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
```

Import via `import './CoverageMatrix.module.css'` in `CoverageMatrix.tsx`.

- [ ] **Step 3: Implement `CoverageMatrix`**

```tsx
// frontend/src/features/admin/components/CoverageMatrix.tsx
import { Box, ScrollArea, Text } from '@mantine/core';
import './CoverageMatrix.module.css';
import { useMemo } from 'react';
import { useStore } from 'zustand';
import { runsTrackerStore } from '../lib/runsTracker';
import type { CoveragePayload } from '../hooks/useCoverage';
import { cellState, type CoverageCell } from '../lib/cellState';
import { CoverageMatrixCell } from './CoverageMatrixCell';

interface Props {
  data: CoveragePayload;
  onCellClick: (styleId: number, weekNumber: number) => void;
}

export function CoverageMatrix({ data, onCellClick }: Props) {
  const tracker = useStore(runsTrackerStore);
  const weeks = useMemo(
    () => Array.from({ length: data.weeks_in_year }, (_, i) => i + 1),
    [data.weeks_in_year],
  );

  return (
    <ScrollArea offsetScrollbars>
      <Box
        style={{
          display: 'grid',
          gridTemplateColumns: `160px repeat(${data.weeks_in_year}, 24px)`,
          gap: 4,
          alignItems: 'center',
        }}
      >
        <Box style={{ position: 'sticky', left: 0, background: 'var(--mantine-color-body)' }} />
        {weeks.map((w) => (
          <Text key={w} size="xs" ta="center" c="dimmed">
            {w}
          </Text>
        ))}
        {data.styles.map((style) => {
          const byWeek = new Map<number, CoverageCell>();
          for (const c of style.cells) byWeek.set(c.week_number, c);
          return (
            <Row
              key={style.style_id}
              styleIdNum={Number(style.style_id) || 0}
              styleName={style.style_name}
              weeks={weeks}
              byWeek={byWeek}
              tracker={tracker}
              onCellClick={onCellClick}
            />
          );
        })}
      </Box>
    </ScrollArea>
  );
}

function Row({
  styleIdNum,
  styleName,
  weeks,
  byWeek,
  tracker,
  onCellClick,
}: {
  styleIdNum: number;
  styleName: string;
  weeks: number[];
  byWeek: Map<number, CoverageCell>;
  tracker: ReturnType<typeof runsTrackerStore.getState>;
  onCellClick: (styleId: number, weekNumber: number) => void;
}) {
  return (
    <>
      <Text
        size="sm"
        truncate
        style={{
          position: 'sticky',
          left: 0,
          background: 'var(--mantine-color-body)',
          paddingRight: 8,
        }}
      >
        {styleName}
      </Text>
      {weeks.map((w) => {
        const cell = byWeek.get(w);
        const running = tracker.runs.size > 0 && tracker.isRunning(styleIdNum, 0, w);
        // weekYear is implicit in the parent — we cannot pass it here without lifting; the
        // parent already invalidates by year so passing 0 is safe for tracker-id matching.
        const tooltip = cell
          ? `Wk ${w} · ${cell.period_start} – ${cell.period_end} · ${cell.item_count} items${
              cell.is_custom_range ? ' · custom range' : ''
            }`
          : `Wk ${w} · empty`;
        return (
          <CoverageMatrixCell
            key={w}
            styleId={styleIdNum}
            styleName={styleName}
            weekNumber={w}
            state={cellState(cell, running)}
            tooltip={tooltip}
            onClick={onCellClick}
          />
        );
      })}
    </>
  );
}
```

> **Refinement note:** `tracker.isRunning` was specified to take `weekYear` too. Lift `weekYear` from `CoverageMatrix`'s `data.week_year` and pass it through `Row` so the predicate is exact. Adjust the call: `tracker.isRunning(styleIdNum, data.week_year, w)`.

Apply that adjustment now — pass `weekYear={data.week_year}` to `Row` and use it in the running check.

- [ ] **Step 4: Test (smoke)**

```tsx
// frontend/src/features/admin/components/__tests__/CoverageMatrix.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { CoverageMatrix } from '../CoverageMatrix';
import type { CoveragePayload } from '../../hooks/useCoverage';

const sample: CoveragePayload = {
  week_year: 2026,
  weeks_in_year: 52,
  styles: [
    {
      style_id: '1',
      style_name: 'Tech House',
      cells: [
        {
          week_number: 1,
          status: 'completed',
          run_id: 'r',
          item_count: 10,
          is_custom_range: false,
          period_start: '2026-01-03',
          period_end: '2026-01-09',
          started_at: '2026-01-04T09:00:00Z',
          finished_at: '2026-01-04T09:01:00Z',
        },
      ],
    },
  ],
};

function ui(props: React.ComponentProps<typeof CoverageMatrix>) {
  return (
    <MantineProvider theme={testTheme}>
      <CoverageMatrix {...props} />
    </MantineProvider>
  );
}

describe('CoverageMatrix', () => {
  it('renders one row per style and week-1 cell loaded', () => {
    render(ui({ data: sample, onCellClick: vi.fn() }));
    expect(screen.getByText('Tech House')).toBeInTheDocument();
    expect(
      screen.getByLabelText('Tech House week 1 loaded'),
    ).toBeInTheDocument();
  });

  it('fires onCellClick with style_id+week', async () => {
    const onClick = vi.fn();
    render(ui({ data: sample, onCellClick: onClick }));
    await userEvent.click(screen.getByLabelText('Tech House week 1 loaded'));
    expect(onClick).toHaveBeenCalledWith(1, 1);
  });

  it('renders empty cells for missing weeks', () => {
    render(ui({ data: sample, onCellClick: vi.fn() }));
    expect(
      screen.getByLabelText('Tech House week 5 empty'),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Run tests**

Run: `cd frontend && pnpm test src/features/admin/components/__tests__/CoverageMatrix.test.tsx -- --run`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/admin/components/CoverageMatrix.tsx frontend/src/features/admin/components/CoverageMatrixCell.tsx frontend/src/features/admin/components/CoverageMatrix.module.css frontend/src/features/admin/components/__tests__/CoverageMatrix.test.tsx
git commit -m "feat(admin/fe): add CoverageMatrix grid + cell"
```

---

### Task 18: BpTokenInput

**Files:**
- Create: `frontend/src/features/admin/components/BpTokenInput.tsx`
- Create: `frontend/src/features/admin/components/__tests__/BpTokenInput.test.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/admin/components/BpTokenInput.tsx
import { Anchor, Group, PasswordInput, Text } from '@mantine/core';
import { bpTokenStore, useBpToken } from '../lib/bpTokenStore';

export function BpTokenInput() {
  const token = useBpToken();
  if (token) {
    return (
      <Group justify="space-between">
        <Text size="sm">Beatport token loaded</Text>
        <Anchor size="sm" component="button" type="button" onClick={() => bpTokenStore.clear()}>
          Reset
        </Anchor>
      </Group>
    );
  }
  return (
    <PasswordInput
      label="Beatport token"
      placeholder="Paste bp_token"
      onChange={(e) => bpTokenStore.set(e.currentTarget.value || null)}
      autoComplete="off"
      data-testid="bp-token-input"
    />
  );
}
```

- [ ] **Step 2: Test**

```tsx
// frontend/src/features/admin/components/__tests__/BpTokenInput.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { BpTokenInput } from '../BpTokenInput';
import { bpTokenStore } from '../../lib/bpTokenStore';

function ui() {
  return (
    <MantineProvider theme={testTheme}>
      <BpTokenInput />
    </MantineProvider>
  );
}

describe('BpTokenInput', () => {
  it('captures input into store and switches to loaded state', async () => {
    bpTokenStore.clear();
    const { rerender } = render(ui());
    await userEvent.type(screen.getByTestId('bp-token-input'), 'abc');
    expect(bpTokenStore.get()).toBe('abc');
    rerender(ui());
    expect(screen.getByText('Beatport token loaded')).toBeInTheDocument();
  });

  it('reset clears the store and re-shows the input', async () => {
    bpTokenStore.set('abc');
    render(ui());
    await userEvent.click(screen.getByText('Reset'));
    expect(bpTokenStore.get()).toBeNull();
    expect(screen.getByTestId('bp-token-input')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run tests + commit**

```bash
cd frontend && pnpm test src/features/admin/components/__tests__/BpTokenInput.test.tsx -- --run
git add frontend/src/features/admin/components/BpTokenInput.tsx frontend/src/features/admin/components/__tests__/BpTokenInput.test.tsx
git commit -m "feat(admin/fe): add BpTokenInput"
```

---

### Task 19: IngestForm

**Files:**
- Create: `frontend/src/features/admin/components/IngestForm.tsx`
- Create: `frontend/src/features/admin/components/__tests__/IngestForm.test.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/admin/components/IngestForm.tsx
import { Alert, Button, Collapse, Group, NumberInput, Stack, Switch, Text } from '@mantine/core';
import { useState } from 'react';
import { saturdayWeekRange } from '../lib/saturdayWeek';
import { bpTokenStore, useBpToken } from '../lib/bpTokenStore';
import { useStartIngest } from '../hooks/useStartIngest';
import { BpTokenInput } from './BpTokenInput';

interface Props {
  styleId: number;
  styleName: string;
  weekYear: number;
  weekNumber: number;
  onStarted: (run_id: string) => void;
}

function fmt(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function IngestForm({ styleId, weekYear, weekNumber, onStarted }: Props) {
  const [override, setOverride] = useState(false);
  const [stdStart, stdEnd] = saturdayWeekRange(weekYear, weekNumber);
  const [start, setStart] = useState(fmt(stdStart));
  const [end, setEnd] = useState(fmt(stdEnd));
  const [advanced, setAdvanced] = useState(false);
  const [labelCount, setLabelCount] = useState<number | ''>('');
  const token = useBpToken();
  const mutation = useStartIngest();

  const submit = () => {
    if (!token) return;
    if (override && new Date(end) < new Date(start)) {
      mutation.reset();
      return;
    }
    const payload = {
      style_id: styleId,
      week_year: weekYear,
      week_number: weekNumber,
      bp_token: token,
      ...(override ? { period_start: start, period_end: end } : {}),
      ...(typeof labelCount === 'number' ? { search_label_count: labelCount } : {}),
    };
    mutation.mutate(payload, {
      onSuccess: (data) => onStarted(data.run_id),
    });
  };

  return (
    <Stack gap="sm">
      <BpTokenInput />
      <Switch
        label="Override date range"
        checked={override}
        onChange={(e) => setOverride(e.currentTarget.checked)}
      />
      <Collapse in={override}>
        <Group grow>
          <Text size="xs" c="dimmed">
            Standard week: {fmt(stdStart)} – {fmt(stdEnd)}
          </Text>
        </Group>
        <Group grow>
          <input
            type="date"
            aria-label="period_start"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
          <input
            type="date"
            aria-label="period_end"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </Group>
      </Collapse>
      <Anchor advanced advancedOpen={advanced} onToggle={setAdvanced} labelCount={labelCount} setLabelCount={setLabelCount} />
      {mutation.isError && (
        <Alert color="red" title="Ingest failed">
          {(mutation.error as Error)?.message ?? 'Unknown error'}
        </Alert>
      )}
      <Button
        onClick={submit}
        loading={mutation.isPending}
        disabled={!token}
      >
        Start ingest
      </Button>
    </Stack>
  );
}

function Anchor({
  advanced,
  advancedOpen,
  onToggle,
  labelCount,
  setLabelCount,
}: {
  advanced: boolean;
  advancedOpen: boolean;
  onToggle: (next: boolean) => void;
  labelCount: number | '';
  setLabelCount: (v: number | '') => void;
}) {
  return (
    <Stack gap={2}>
      <Switch
        size="xs"
        label="Advanced"
        checked={advancedOpen}
        onChange={(e) => onToggle(e.currentTarget.checked)}
      />
      <Collapse in={advancedOpen}>
        <NumberInput
          label="search_label_count"
          min={1}
          max={200}
          value={labelCount}
          onChange={(v) => setLabelCount(typeof v === 'number' ? v : '')}
        />
      </Collapse>
    </Stack>
  );
}
```

> **Note:** the `Anchor` helper above is a private sub-component to keep the main form readable. The Mantine `<Anchor>` component is not used here; rename if it shadows imports in your editor.

- [ ] **Step 2: Test**

```tsx
// frontend/src/features/admin/components/__tests__/IngestForm.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { IngestForm } from '../IngestForm';
import { bpTokenStore } from '../../lib/bpTokenStore';

const server = setupServer();
beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  bpTokenStore.clear();
});
afterAll(() => server.close());

function ui(props: React.ComponentProps<typeof IngestForm>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <IngestForm {...props} />
      </MantineProvider>
    </QueryClientProvider>
  );
}

describe('IngestForm', () => {
  it('disables submit when no token', () => {
    render(
      ui({
        styleId: 1,
        styleName: 'Tech',
        weekYear: 2026,
        weekNumber: 5,
        onStarted: vi.fn(),
      }),
    );
    expect(screen.getByRole('button', { name: 'Start ingest' })).toBeDisabled();
  });

  it('submits standard range when override off', async () => {
    bpTokenStore.set('tok');
    let captured: unknown = null;
    server.use(
      http.post('http://localhost/admin/beatport/ingest', async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          run_id: 'r1',
          run_status: 'RAW_SAVED',
          processing_status: 'QUEUED',
          is_custom_range: false,
        });
      }),
    );
    const onStarted = vi.fn();
    render(
      ui({ styleId: 1, styleName: 'Tech', weekYear: 2026, weekNumber: 5, onStarted }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Start ingest' }));
    await vi.waitFor(() => expect(onStarted).toHaveBeenCalledWith('r1'));
    expect(captured).toMatchObject({
      style_id: 1,
      week_year: 2026,
      week_number: 5,
      bp_token: 'tok',
    });
    expect(captured).not.toHaveProperty('period_start');
  });

  it('submits override range when toggled', async () => {
    bpTokenStore.set('tok');
    let captured: unknown = null;
    server.use(
      http.post('http://localhost/admin/beatport/ingest', async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json({
          run_id: 'r1',
          run_status: 'RAW_SAVED',
          processing_status: 'QUEUED',
          is_custom_range: true,
        });
      }),
    );
    render(
      ui({ styleId: 1, styleName: 'Tech', weekYear: 2026, weekNumber: 5, onStarted: vi.fn() }),
    );
    await userEvent.click(screen.getByLabelText('Override date range'));
    await userEvent.clear(screen.getByLabelText('period_end'));
    await userEvent.type(screen.getByLabelText('period_end'), '2026-02-10');
    await userEvent.click(screen.getByRole('button', { name: 'Start ingest' }));
    await vi.waitFor(() =>
      expect((captured as { period_end?: string })?.period_end).toBe('2026-02-10'),
    );
  });
});
```

- [ ] **Step 3: Run tests + commit**

```bash
cd frontend && pnpm test src/features/admin/components/__tests__/IngestForm.test.tsx -- --run
git add frontend/src/features/admin/components/IngestForm.tsx frontend/src/features/admin/components/__tests__/IngestForm.test.tsx
git commit -m "feat(admin/fe): add IngestForm"
```

---

### Task 20: RunDetails + RunHistoryList

**Files:**
- Create: `frontend/src/features/admin/components/RunDetails.tsx`
- Create: `frontend/src/features/admin/components/RunHistoryList.tsx`

- [ ] **Step 1: Implement RunDetails**

```tsx
// frontend/src/features/admin/components/RunDetails.tsx
import { Alert, Badge, Group, Stack, Text } from '@mantine/core';
import type { CoverageCell } from '../lib/cellState';

interface Props {
  cell: CoverageCell;
  errorCode?: string | null;
  errorMessage?: string | null;
}

export function RunDetails({ cell, errorCode, errorMessage }: Props) {
  return (
    <Stack gap="xs">
      <Group gap="xs">
        <Text fw={600}>{cell.period_start} – {cell.period_end}</Text>
        {cell.is_custom_range && <Badge color="yellow">custom range</Badge>}
      </Group>
      <Text size="sm" c="dimmed">
        Started {cell.started_at}
        {cell.finished_at ? ` · finished ${cell.finished_at}` : ''}
      </Text>
      <Text size="sm">
        {cell.item_count} items · status <code>{cell.status}</code>
      </Text>
      {errorCode && (
        <Alert color="red" title={errorCode}>
          {errorMessage}
        </Alert>
      )}
    </Stack>
  );
}
```

- [ ] **Step 2: Implement RunHistoryList**

```tsx
// frontend/src/features/admin/components/RunHistoryList.tsx
import { Stack, Text } from '@mantine/core';
import { useCellRuns, type CellRun } from '../hooks/useCellRuns';

interface Props {
  styleId: number;
  weekYear: number;
  weekNumber: number;
  excludeRunId?: string;
}

export function RunHistoryList({ styleId, weekYear, weekNumber, excludeRunId }: Props) {
  const q = useCellRuns({ styleId, weekYear, weekNumber });
  if (q.isLoading) return <Text size="sm" c="dimmed">Loading history…</Text>;
  if (q.isError) return <Text size="sm" c="red">Failed to load history.</Text>;
  const items = (q.data?.items ?? []).filter((r) => r.run_id !== excludeRunId);
  if (items.length === 0) return null;
  return (
    <Stack gap={4}>
      <Text fw={600} size="sm">Previous runs</Text>
      {items.map((r) => (
        <RunRow key={r.run_id} run={r} />
      ))}
    </Stack>
  );
}

function RunRow({ run }: { run: CellRun }) {
  return (
    <Text size="xs" c="dimmed">
      {run.started_at} · {run.status}{' '}
      {run.error_code ? `(${run.error_code})` : `${run.item_count ?? 0} items`}
    </Text>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/admin/components/RunDetails.tsx frontend/src/features/admin/components/RunHistoryList.tsx
git commit -m "feat(admin/fe): add RunDetails + RunHistoryList"
```

---

### Task 21: CellDetailDrawer

**Files:**
- Create: `frontend/src/features/admin/components/CellDetailDrawer.tsx`
- Create: `frontend/src/features/admin/components/__tests__/CellDetailDrawer.test.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/admin/components/CellDetailDrawer.tsx
import { Button, Drawer, Stack, Text } from '@mantine/core';
import { useState } from 'react';
import { saturdayWeekRange } from '../lib/saturdayWeek';
import { useRunPoller } from '../hooks/useRunPoller';
import { IngestForm } from './IngestForm';
import { RunDetails } from './RunDetails';
import { RunHistoryList } from './RunHistoryList';
import type { CellState } from '../lib/cellState';
import type { CoverageCell } from '../lib/cellState';

interface Props {
  open: boolean;
  onClose: () => void;
  styleId: number | null;
  styleName: string | null;
  weekYear: number;
  weekNumber: number | null;
  state: CellState;
  cell: CoverageCell | null;
}

export function CellDetailDrawer({
  open,
  onClose,
  styleId,
  styleName,
  weekYear,
  weekNumber,
  state,
  cell,
}: Props) {
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const polling = useRunPoller(
    activeRunId,
    activeRunId && styleId !== null && weekNumber !== null
      ? { styleId, weekYear, weekNumber }
      : null,
  );
  const [reingest, setReingest] = useState(false);

  if (styleId === null || styleName === null || weekNumber === null) return null;

  const [stdStart, stdEnd] = saturdayWeekRange(weekYear, weekNumber);
  const title = `${styleName} · Wk ${weekNumber} · ${stdStart.toISOString().slice(0, 10)} – ${stdEnd
    .toISOString()
    .slice(0, 10)}`;

  return (
    <Drawer opened={open} onClose={onClose} position="right" size="md" title={title}>
      <Stack gap="md">
        {state === 'empty' && (
          <IngestForm
            styleId={styleId}
            styleName={styleName}
            weekYear={weekYear}
            weekNumber={weekNumber}
            onStarted={setActiveRunId}
          />
        )}
        {state === 'failed' && cell && (
          <>
            <RunDetails
              cell={cell}
              errorCode={'see history'}
              errorMessage={'Latest run failed; retry below.'}
            />
            <IngestForm
              styleId={styleId}
              styleName={styleName}
              weekYear={weekYear}
              weekNumber={weekNumber}
              onStarted={setActiveRunId}
            />
          </>
        )}
        {(state === 'loaded' || state === 'loaded-custom') && cell && (
          <>
            <RunDetails cell={cell} />
            {!reingest ? (
              <Button variant="light" onClick={() => setReingest(true)}>
                Re-ingest
              </Button>
            ) : (
              <IngestForm
                styleId={styleId}
                styleName={styleName}
                weekYear={weekYear}
                weekNumber={weekNumber}
                onStarted={setActiveRunId}
              />
            )}
          </>
        )}
        {state === 'running' && (
          <Text size="sm">
            Run in progress {activeRunId ? `(${polling.data?.status ?? 'queued'})` : '…'}
          </Text>
        )}
        <RunHistoryList
          styleId={styleId}
          weekYear={weekYear}
          weekNumber={weekNumber}
          excludeRunId={cell?.run_id}
        />
      </Stack>
    </Drawer>
  );
}
```

- [ ] **Step 2: Smoke test (state machine)**

```tsx
// frontend/src/features/admin/components/__tests__/CellDetailDrawer.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MantineProvider } from '@mantine/core';
import { testTheme } from '../../../../test/theme';
import { CellDetailDrawer } from '../CellDetailDrawer';

function ui(props: React.ComponentProps<typeof CellDetailDrawer>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <CellDetailDrawer {...props} />
      </MantineProvider>
    </QueryClientProvider>
  );
}

describe('CellDetailDrawer', () => {
  it('renders ingest form on empty', () => {
    render(
      ui({
        open: true,
        onClose: vi.fn(),
        styleId: 1,
        styleName: 'Tech',
        weekYear: 2026,
        weekNumber: 5,
        state: 'empty',
        cell: null,
      }),
    );
    expect(screen.getByRole('button', { name: 'Start ingest' })).toBeInTheDocument();
  });

  it('renders run details on loaded', () => {
    render(
      ui({
        open: true,
        onClose: vi.fn(),
        styleId: 1,
        styleName: 'Tech',
        weekYear: 2026,
        weekNumber: 5,
        state: 'loaded',
        cell: {
          week_number: 5,
          status: 'completed',
          run_id: 'r',
          item_count: 42,
          is_custom_range: false,
          period_start: '2026-01-31',
          period_end: '2026-02-06',
          started_at: '2026-02-07T00:00:00Z',
          finished_at: '2026-02-07T00:01:00Z',
        },
      }),
    );
    expect(screen.getByText('2026-01-31 – 2026-02-06')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Re-ingest' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run tests + commit**

```bash
cd frontend && pnpm test src/features/admin/components/__tests__/CellDetailDrawer.test.tsx -- --run
git add frontend/src/features/admin/components/CellDetailDrawer.tsx frontend/src/features/admin/components/__tests__/CellDetailDrawer.test.tsx
git commit -m "feat(admin/fe): add CellDetailDrawer state machine"
```

---

### Task 22: RunProgressToast

**Files:**
- Create: `frontend/src/features/admin/components/RunProgressToast.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/src/features/admin/components/RunProgressToast.tsx
import { useEffect, useRef } from 'react';
import { notifications } from '@mantine/notifications';
import { useStore } from 'zustand';
import { runsTrackerStore, type RunMeta } from '../lib/runsTracker';

export function RunProgressToast() {
  const tracker = useStore(runsTrackerStore);
  const toastIds = useRef(new Map<string, string>());

  useEffect(() => {
    // Add toasts for new runs.
    for (const meta of tracker.runs.values()) {
      if (toastIds.current.has(meta.run_id)) continue;
      const id = notifications.show({
        loading: true,
        title: 'Beatport ingest',
        message: `style ${meta.styleId} · Wk ${meta.weekNumber} · running…`,
        autoClose: false,
        withCloseButton: false,
      });
      toastIds.current.set(meta.run_id, id);
    }
    // Settle removed runs.
    for (const [runId, id] of toastIds.current.entries()) {
      if (tracker.runs.has(runId)) continue;
      notifications.update({
        id,
        title: 'Beatport ingest',
        message: 'completed',
        color: 'green',
        loading: false,
        autoClose: 4000,
      });
      toastIds.current.delete(runId);
    }
  }, [tracker.runs]);

  return null;
}

export type { RunMeta };
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/admin/components/RunProgressToast.tsx
git commit -m "feat(admin/fe): add RunProgressToast"
```

---

### Task 23: SpotifyNotFoundTable + AdminSpotifyNotFoundPage

**Files:**
- Create: `frontend/src/features/admin/components/SpotifyNotFoundTable.tsx`
- Create: `frontend/src/features/admin/routes/AdminSpotifyNotFoundPage.tsx`

- [ ] **Step 1: Implement Table**

```tsx
// frontend/src/features/admin/components/SpotifyNotFoundTable.tsx
import { Pagination, Skeleton, Stack, Table, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useState } from 'react';
import { useSpotifyNotFound } from '../hooks/useSpotifyNotFound';

const LIMIT = 50;

export function SpotifyNotFoundTable() {
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(search, 300);
  const [page, setPage] = useState(1);
  const offset = (page - 1) * LIMIT;
  const q = useSpotifyNotFound({ limit: LIMIT, offset, search: debouncedSearch });

  if (q.isLoading) return <Skeleton h={400} />;
  if (q.isError) return <Text c="red">Failed to load tracks.</Text>;
  if (!q.data) return null;

  const totalPages = Math.max(1, Math.ceil(q.data.total / LIMIT));

  return (
    <Stack>
      <TextInput
        placeholder="Search title or artist…"
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
      />
      <Text size="sm" c="dimmed">
        {q.data.total} tracks pending Spotify enrichment
      </Text>
      <Table striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Title</Table.Th>
            <Table.Th>Artists</Table.Th>
            <Table.Th>ISRC</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {q.data.items.map((t) => (
            <Table.Tr key={t.track_id}>
              <Table.Td>{t.title}</Table.Td>
              <Table.Td>{t.artists.join(', ')}</Table.Td>
              <Table.Td>{t.isrc ?? '—'}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Pagination value={page} onChange={setPage} total={totalPages} />
    </Stack>
  );
}
```

- [ ] **Step 2: Implement page**

```tsx
// frontend/src/features/admin/routes/AdminSpotifyNotFoundPage.tsx
import { Stack, Title } from '@mantine/core';
import { SpotifyNotFoundTable } from '../components/SpotifyNotFoundTable';

export function AdminSpotifyNotFoundPage() {
  return (
    <Stack>
      <Title order={2}>Tracks not on Spotify</Title>
      <SpotifyNotFoundTable />
    </Stack>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/admin/components/SpotifyNotFoundTable.tsx frontend/src/features/admin/routes/AdminSpotifyNotFoundPage.tsx
git commit -m "feat(admin/fe): add Spotify-not-found page + table"
```

---

### Task 24: AdminLayout + AdminCoveragePage

**Files:**
- Create: `frontend/src/features/admin/routes/AdminLayout.tsx`
- Create: `frontend/src/features/admin/routes/AdminCoveragePage.tsx`

- [ ] **Step 1: Implement AdminLayout**

```tsx
// frontend/src/features/admin/routes/AdminLayout.tsx
import { Tabs } from '@mantine/core';
import { Outlet, useLocation, useNavigate } from 'react-router';
import { RunProgressToast } from '../components/RunProgressToast';

const TABS = [
  { value: '/admin/coverage', label: 'Coverage' },
  { value: '/admin/spotify-not-found', label: 'Tracks not on Spotify' },
];

export function AdminLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const active = TABS.find((t) => location.pathname.startsWith(t.value))?.value ?? TABS[0].value;
  return (
    <>
      <Tabs value={active} onChange={(v) => v && navigate(v)} keepMounted={false}>
        <Tabs.List>
          {TABS.map((t) => (
            <Tabs.Tab key={t.value} value={t.value}>
              {t.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      <Outlet />
      <RunProgressToast />
    </>
  );
}
```

- [ ] **Step 2: Implement AdminCoveragePage**

```tsx
// frontend/src/features/admin/routes/AdminCoveragePage.tsx
import { Alert, Stack, Title } from '@mantine/core';
import { useState } from 'react';
import { useCoverage } from '../hooks/useCoverage';
import { weekOfDate } from '../lib/saturdayWeek';
import { CoverageMatrix } from '../components/CoverageMatrix';
import { CellDetailDrawer } from '../components/CellDetailDrawer';
import { YearNavigator } from '../components/YearNavigator';
import { cellState, type CoverageCell } from '../lib/cellState';
import { runsTrackerStore } from '../lib/runsTracker';

export function AdminCoveragePage() {
  const [year, setYear] = useState(() => weekOfDate(new Date())[0]);
  const q = useCoverage(year);
  const [active, setActive] = useState<{ styleId: number; weekNumber: number } | null>(null);

  const styleMap = new Map<number, { name: string; cells: Map<number, CoverageCell> }>();
  for (const s of q.data?.styles ?? []) {
    const sid = Number(s.style_id) || 0;
    const cells = new Map<number, CoverageCell>();
    for (const c of s.cells) cells.set(c.week_number, c);
    styleMap.set(sid, { name: s.style_name, cells });
  }
  const activeStyle = active ? styleMap.get(active.styleId) : null;
  const activeCell = active && activeStyle ? activeStyle.cells.get(active.weekNumber) ?? null : null;
  const isRunning =
    active &&
    runsTrackerStore.getState().isRunning(active.styleId, year, active.weekNumber);
  const state = activeCell ? cellState(activeCell, !!isRunning) : 'empty';

  return (
    <Stack>
      <Title order={2}>Coverage</Title>
      <YearNavigator year={year} onChange={setYear} />
      {q.isError && <Alert color="red">Failed to load coverage.</Alert>}
      {q.data && (
        <CoverageMatrix
          data={q.data}
          onCellClick={(styleId, weekNumber) => setActive({ styleId, weekNumber })}
        />
      )}
      <CellDetailDrawer
        open={active !== null}
        onClose={() => setActive(null)}
        styleId={active?.styleId ?? null}
        styleName={activeStyle?.name ?? null}
        weekYear={year}
        weekNumber={active?.weekNumber ?? null}
        state={state}
        cell={activeCell}
      />
    </Stack>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/admin/routes/AdminLayout.tsx frontend/src/features/admin/routes/AdminCoveragePage.tsx
git commit -m "feat(admin/fe): add AdminLayout + AdminCoveragePage"
```

---

## Phase 4 — Wiring

### Task 25: Router registration

**Files:**
- Modify: `frontend/src/routes/router.tsx`

- [ ] **Step 1: Add `/admin/*` subtree**

```tsx
// at top:
import { requireAdmin } from '../auth/requireAdmin';
import { AdminLayout } from '../features/admin/routes/AdminLayout';
import { AdminCoveragePage } from '../features/admin/routes/AdminCoveragePage';
import { AdminSpotifyNotFoundPage } from '../features/admin/routes/AdminSpotifyNotFoundPage';
import { Navigate } from 'react-router';
```

Inside the existing AppShell `children` array, after `{ path: 'profile', element: <ProfilePage /> }`, append:

```tsx
{
  path: 'admin',
  element: <AdminLayout />,
  loader: requireAdmin,
  children: [
    { index: true, element: <Navigate to="/admin/coverage" replace /> },
    { path: 'coverage', element: <AdminCoveragePage /> },
    { path: 'spotify-not-found', element: <AdminSpotifyNotFoundPage /> },
  ],
},
```

- [ ] **Step 2: Run tests**

Run: `cd frontend && pnpm test -- --run`
Expected: existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/router.tsx
git commit -m "feat(routes): register /admin namespace"
```

---

### Task 26: Conditional admin nav item

**Files:**
- Modify: `frontend/src/components/icons.ts`
- Modify: `frontend/src/routes/_layout.tsx`
- Modify: `frontend/src/routes/__tests__/_layout.test.tsx`

- [ ] **Step 1: Add IconShield re-export**

In `frontend/src/components/icons.ts`, add `IconShield` next to the existing icon re-exports (the file already re-exports `IconHome` etc. from `@tabler/icons-react`). Mirror that pattern:

```ts
export { IconShield } from '@tabler/icons-react';
```

- [ ] **Step 2: Conditionally append admin nav item**

In `frontend/src/routes/_layout.tsx`, change `AppShellInner` to read auth state and append the admin entry. Add the imports:

```ts
import { useContext, useMemo } from 'react';
import { AuthContext } from '../auth/AuthProvider';
import { IconShield } from '../components/icons';
```

Inside `AppShellInner` (replacing the use of the static `NAV_ITEMS`):

```ts
const auth = useContext(AuthContext);
const isAdmin =
  auth?.state.status === 'authenticated' && auth.state.user.is_admin === true;

const navItems = useMemo<NavItem[]>(
  () =>
    isAdmin
      ? [...NAV_ITEMS, { path: '/admin', labelKey: 'appshell.admin', Icon: IconShield }]
      : NAV_ITEMS,
  [isAdmin],
);
```

Use `navItems` everywhere `NAV_ITEMS` is currently mapped.

- [ ] **Step 3: Add i18n key**

In `frontend/src/i18n/en.json`, under the `appshell` block, add:

```json
"admin": "Admin"
```

- [ ] **Step 4: Update layout test**

In `frontend/src/routes/__tests__/_layout.test.tsx`, add a test that mounts the layout with `is_admin: true` and asserts the `Admin` link is present, and another with `false` asserting it is absent. Use the existing `renderApp` helper as a template; copy its setup.

- [ ] **Step 5: Run tests + commit**

```bash
cd frontend && pnpm test src/routes/__tests__/_layout.test.tsx -- --run
git add frontend/src/components/icons.ts frontend/src/routes/_layout.tsx frontend/src/i18n/en.json frontend/src/routes/__tests__/_layout.test.tsx
git commit -m "feat(layout): conditional Admin nav item for is_admin users"
```

---

### Task 27: UserMenu — Reset Beatport token item

**Files:**
- Modify: `frontend/src/components/UserMenu.tsx`
- Modify: `frontend/src/components/__tests__/UserMenu.test.tsx`

- [ ] **Step 1: Inspect existing menu structure**

Run: `cat frontend/src/components/UserMenu.tsx`. Note where it renders Mantine `<Menu.Item>`s and how it reads `auth.state.user`.

- [ ] **Step 2: Add the conditional item**

Inside `UserMenu`, before the existing `Sign out` item:

```tsx
import { bpTokenStore, useBpToken } from '../features/admin/lib/bpTokenStore';

// inside the component:
const isAdmin =
  auth?.state.status === 'authenticated' && auth.state.user.is_admin === true;
const token = useBpToken();

// inside the menu, conditional:
{isAdmin && token && (
  <Menu.Item
    color="orange"
    onClick={() => bpTokenStore.clear()}
  >
    Reset Beatport token
  </Menu.Item>
)}
```

> Wire up `auth` and the i18n key (`usermenu.resetBpToken`) consistently with the existing items.

- [ ] **Step 3: Test**

Add to `UserMenu.test.tsx`:

```tsx
it('shows Reset Beatport token only for admin with token loaded', async () => {
  // 1. non-admin: hidden.
  // 2. admin no token: hidden.
  // 3. admin with token: visible; click clears the store.
});
```

Use the existing fixture for renderingUserMenu; mock `bpTokenStore.get` via `set/clear` calls before render.

- [ ] **Step 4: Run tests + commit**

```bash
cd frontend && pnpm test src/components/__tests__/UserMenu.test.tsx -- --run
git add frontend/src/components/UserMenu.tsx frontend/src/components/__tests__/UserMenu.test.tsx frontend/src/i18n/en.json
git commit -m "feat(usermenu): admin-only Reset Beatport token item"
```

---

### Task 28: i18n keys for admin namespace

**Files:**
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Add `admin` namespace**

Append (under the root JSON object):

```json
"admin": {
  "coverage": {
    "title": "Coverage",
    "year": "Year",
    "weeksLabel": "{{count}} weeks"
  },
  "spotifyNotFound": {
    "title": "Tracks not on Spotify",
    "search": "Search title or artist…",
    "totalLabel": "{{count}} tracks pending Spotify enrichment",
    "empty": "No tracks awaiting Spotify match"
  },
  "ingest": {
    "start": "Start ingest",
    "override": "Override date range",
    "advanced": "Advanced",
    "tokenLoaded": "Beatport token loaded",
    "reset": "Reset",
    "tokenLabel": "Beatport token",
    "tokenPlaceholder": "Paste bp_token"
  },
  "errors": {
    "validation": "Request was invalid.",
    "bpTokenInvalid": "Beatport token rejected. Check or regenerate.",
    "dbNotConfigured": "Database is unavailable. Try again.",
    "internal": "Unexpected error.",
    "adminRequired": "Admin access required."
  }
}
```

- [ ] **Step 2: Wire keys into the components**

Replace the hardcoded strings in `IngestForm`, `BpTokenInput`, `AdminCoveragePage`, `AdminSpotifyNotFoundPage`, `SpotifyNotFoundTable` with `t('admin.ingest.*')` etc. via `useTranslation`. Verify each rendered page matches.

- [ ] **Step 3: Run tests + commit**

```bash
cd frontend && pnpm test -- --run
git add frontend/src/i18n/en.json frontend/src/features/admin
git commit -m "feat(i18n): admin namespace + wire components to t()"
```

---

### Task 29: MSW handlers for new endpoints

**Files:**
- Modify: `frontend/src/test/handlers.ts`

- [ ] **Step 1: Add default handlers**

Inside the existing `handlers` array, add:

```ts
http.get('http://localhost/admin/coverage', ({ request }) => {
  const url = new URL(request.url);
  const year = Number(url.searchParams.get('week_year') ?? '0');
  return HttpResponse.json({
    week_year: year,
    weeks_in_year: 52,
    styles: [],
    correlation_id: 'test',
  });
}),
http.get('http://localhost/admin/runs', () =>
  HttpResponse.json({ items: [] }),
),
http.post('http://localhost/admin/beatport/ingest', async () =>
  HttpResponse.json({
    run_id: 'test-run',
    run_status: 'RAW_SAVED',
    processing_status: 'QUEUED',
    is_custom_range: false,
  }),
),
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/test/handlers.ts
git commit -m "test(admin/fe): default MSW handlers for admin endpoints"
```

---

## Phase 5 — Wrap-up

### Task 30: Update CLAUDE.md gotchas

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add lines under Gotchas**

Append four bullets near the existing backend gotchas (immediately before the `**Frontend …**` block):

```
- **Saturday-week convention is admin-only.** `src/collector/saturday_week.py` is the BE source of truth; `frontend/src/features/admin/lib/saturdayWeek.ts` mirrors it. Week N runs Saturday-to-Friday; week 1 begins on the first Saturday on/after Jan 1. Days before the first Saturday belong to the previous year.
- **`POST /collect_bp_releases` is deprecated.** Admin UI uses `POST /admin/beatport/ingest`. Both share `_run_beatport_ingest` in `handler.py`. Don't add new ISO-week entry points; new ingests must be Saturday-week with optional `period_start`/`period_end` override.
- **`bp_token` lives in browser memory only.** `frontend/src/features/admin/lib/bpTokenStore.ts` is a module-scoped singleton; it survives soft navigations but is wiped on tab close or hard reload. Never persist it (no localStorage/sessionStorage/cookies). UserMenu has a "Reset Beatport token" item visible to admins only.
- **`/admin/*` is gated client-side too.** `requireAdmin` loader (`frontend/src/auth/requireAdmin.ts`) bounces non-admins to `/`. The AppShell `Admin` nav item is rendered conditionally on `auth.state.user.is_admin`.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude.md): admin-page gotchas"
```

---

### Task 31: End-to-end smoke

**Files:** none — runs the full suite.

- [ ] **Step 1: Backend tests**

Run: `pytest -q`
Expected: all passing.

- [ ] **Step 2: Frontend tests**

Run: `cd frontend && pnpm test -- --run`
Expected: all passing.

- [ ] **Step 3: Frontend typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Local dev visual check**

Run (in two shells):
```bash
# Shell 1
cd frontend && pnpm dev
# Shell 2 — open http://127.0.0.1:5173 in a browser, log in as an admin user.
```

Verify manually:
- `Admin` nav item appears in the sidebar.
- `/admin` redirects to `/admin/coverage`.
- Year navigator works; matrix renders empty grid for an unloaded year.
- Click a cell → drawer with `Start ingest` (token input shown if not yet set).
- Tab `Tracks not on Spotify` lists data when DB has any.

If anything is off, fix in a small follow-up commit.

- [ ] **Step 5: No commit needed unless fixes were applied.**

---

## Self-Review

**Spec coverage:**
- §1 Goals — Tasks 1–31.
- §2 Saturday-week — Tasks 1, 10.
- §3.1 Migration — Task 3.
- §3.2 New endpoints — Tasks 2, 5, 6.
- §3.3 Reused endpoints — Task 23 reuses /tracks/spotify-not-found; existing GET /runs/{run_id} reused in Task 15.
- §3.4 Auth — Task 6 extends `_ADMIN_ROUTES`.
- §3.5 API Gateway — Task 8.
- §3.6 OpenAPI — Task 9.
- §4.1 Folder layout — Tasks 10–24.
- §4.2 Routing — Task 25.
- §4.3 Nav — Task 26.
- §4.4 AdminLayout — Task 24.
- §4.5 Coverage page — Task 24.
- §4.6 Drawer behavior — Task 21.
- §4.7 IngestForm — Task 19.
- §4.8 Run details/history — Task 20.
- §4.9 Polling — Task 15 (`useRunPoller`) + Task 22.
- §4.10 bp_token — Tasks 12, 27.
- §4.11 Spotify-not-found — Task 23.
- §4.12 i18n errors — Task 28.
- §5 Data flow — exercised by Tasks 19–22 + Task 31 manual verification.
- §6 Tests — Tasks 1, 2, 7, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 23 (per-component), 26, 27, 31.
- §8 Out of scope — respected.

**Type consistency:** `CoverageCell` shape in `cellState.ts` matches `CoveragePayload.styles[].cells[]` in `useCoverage.ts`. `RunMeta` matches in `runsTracker.ts` and `useStartIngest.ts`. `_IngestParams` in handler matches the column set written in `repositories.create_ingest_run`.

**Placeholder scan:** none.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-09-admin-page.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
