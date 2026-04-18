# Vendor-Sync Plan 4 — Vendor Match Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a SQS-triggered Lambda that matches a canonical track to an external vendor (Spotify, YT Music, Deezer, Apple, Tidal) via ISRC or fuzzy metadata, caching hits in `vendor_track_map` and routing low-confidence misses to `match_review_queue`.

**Architecture:** On each SQS message `{clouder_track_id, vendor, isrc?, artist, title, duration_ms, album}`, the worker first checks cache (`vendor_track_map`). On miss, calls `LookupProvider.lookup_by_isrc` then fuzzy metadata search. Confidence ≥ 0.92 writes cache; below threshold routes top candidates to `match_review_queue` for manual review. Idempotent on the PK `(clouder_track_id, vendor)`.

**Tech Stack:** Python 3.12, boto3 (SQS/Lambda/CloudWatch), pydantic v2, existing retry patterns from `data_api_retry.py`.

**Spec:** [docs/superpowers/specs/2026-04-18-vendor-sync-readiness-design.md](../specs/2026-04-18-vendor-sync-readiness-design.md) §5.1 (tables), §7.1 (match workflow), §8.4 partial (error classes).

**Prereqs:** Plans 1, 2, 3 merged. Provider registry + `VendorTrackRef` + `VendorDisabledError` available.

---

## File Structure

New files:
- `alembic/versions/20260421_10_vendor_match_tables.py` — `vendor_track_map`, `match_review_queue` tables.
- `src/collector/providers/vendor_errors.py` — `VendorUnavailableError`, `VendorAuthError`, `VendorQuotaError`, `MatchFailedError`, `UserTokenMissingError` (OR inline in `errors.py`; see decision).
- `src/collector/vendor_match/__init__.py`
- `src/collector/vendor_match/scorer.py` — fuzzy scoring functions.
- `src/collector/vendor_match/retry.py` — `retry_vendor` decorator (jitter, 3 retries on transient).
- `src/collector/vendor_match_handler.py` — Lambda handler.
- `src/collector/schemas.py` — add `VendorMatchMessage` pydantic model.
- `tests/unit/test_migration_10_sql.py`
- `tests/unit/test_vendor_match_scorer.py`
- `tests/unit/test_vendor_match_retry.py`
- `tests/unit/test_vendor_match_handler.py`
- `tests/integration/test_vendor_match_flow.py`

Modified files:
- `src/collector/db_models.py` — SQLAlchemy models for new tables.
- `src/collector/repositories.py` — methods `get_vendor_match`, `upsert_vendor_match`, `insert_review_candidate`.
- `src/collector/errors.py` — add 5 new error classes (decision: put here, not in separate file).
- `infra/sqs.tf` — new queue + DLQ.
- `infra/iam.tf` — extend Lambda role with new SQS permissions.
- `infra/lambda.tf` — new `aws_lambda_function.vendor_match_worker` + event source mapping.
- `infra/outputs.tf` — add function name output.
- `infra/variables.tf` — queue visibility / worker timeout / max receive count.
- `infra/logging.tf` — CloudWatch log group + DLQ alarm.
- `src/collector/settings.py` — `FUZZY_MATCH_THRESHOLD` (default 0.92), `FUZZY_DURATION_TOLERANCE_MS` (default 3000).

---

## Task 1: Alembic migration — `vendor_track_map` + `match_review_queue`

**Files:**
- Create: `alembic/versions/20260421_10_vendor_match_tables.py`
- Test: `tests/unit/test_migration_10_sql.py`

- [ ] **Step 1: Test**

```python
# tests/unit/test_migration_10_sql.py
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration(filename: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("m", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_migration_10_revision_chain() -> None:
    m = _load_migration("20260421_10_vendor_match_tables.py")
    assert m.revision == "20260421_10"
    assert m.down_revision == "20260420_09"


def test_migration_10_creates_tables() -> None:
    text = (Path(__file__).resolve().parents[2]
            / "alembic/versions/20260421_10_vendor_match_tables.py").read_text()
    for token in [
        "vendor_track_map", "match_review_queue",
        "clouder_track_id", "vendor_track_id", "match_type", "confidence",
        "candidates", "status", "pending",
    ]:
        assert token in text, f"expected {token!r} in migration"
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Migration file**

```python
# alembic/versions/20260421_10_vendor_match_tables.py
"""vendor_track_map + match_review_queue

Revision ID: 20260421_10
Revises: 20260420_09
Create Date: 2026-04-21 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "20260421_10"
down_revision = "20260420_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_track_map",
        sa.Column("clouder_track_id", sa.String(36), sa.ForeignKey("clouder_tracks.id"), nullable=False),
        sa.Column("vendor", sa.String(32), nullable=False),
        sa.Column("vendor_track_id", sa.String(128), nullable=False),
        sa.Column("match_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("clouder_track_id", "vendor", name="pk_vendor_track_map"),
    )
    op.create_index(
        "idx_vtm_vendor_track", "vendor_track_map",
        ["vendor", "clouder_track_id"],
    )

    op.create_table(
        "match_review_queue",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("clouder_track_id", sa.String(36), sa.ForeignKey("clouder_tracks.id"), nullable=False),
        sa.Column("vendor", sa.String(32), nullable=False),
        sa.Column("candidates", JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_review_pending", "match_review_queue",
        ["clouder_track_id", "vendor"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_review_pending", table_name="match_review_queue")
    op.drop_table("match_review_queue")
    op.drop_index("idx_vtm_vendor_track", table_name="vendor_track_map")
    op.drop_table("vendor_track_map")
```

- [ ] **Step 4: PASS + local alembic upgrade/downgrade smoke**

- [ ] **Step 5: Add SQLAlchemy models to `db_models.py`**

```python
class VendorTrackMap(Base):
    __tablename__ = "vendor_track_map"
    __table_args__ = (
        PrimaryKeyConstraint("clouder_track_id", "vendor"),
        Index("idx_vtm_vendor_track", "vendor", "clouder_track_id"),
    )

    clouder_track_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clouder_tracks.id"), nullable=False,
    )
    vendor: Mapped[str] = mapped_column(String(32), nullable=False)
    vendor_track_id: Mapped[str] = mapped_column(String(128), nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class MatchReviewQueue(Base):
    __tablename__ = "match_review_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    clouder_track_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clouder_tracks.id"), nullable=False,
    )
    vendor: Mapped[str] = mapped_column(String(32), nullable=False)
    candidates: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 6: Commit**

---

## Task 2: Error classes

**Files:**
- Modify: `src/collector/errors.py`
- Test: `tests/unit/test_vendor_errors.py`

- [ ] **Step 1: Test**

```python
# tests/unit/test_vendor_errors.py
import pytest
from collector.errors import (
    VendorUnavailableError, VendorAuthError, VendorQuotaError,
    MatchFailedError, UserTokenMissingError,
)


def test_vendor_unavailable_error_code() -> None:
    e = VendorUnavailableError("spotify", "timeout")
    assert e.status_code == 502
    assert e.error_code == "vendor_unavailable"
    assert "spotify" in str(e)


def test_vendor_auth_error_code() -> None:
    assert VendorAuthError("ytmusic").status_code == 403
    assert VendorAuthError("ytmusic").error_code == "vendor_auth_failed"


def test_vendor_quota_error_includes_retry_after() -> None:
    e = VendorQuotaError("deezer", retry_after=60)
    assert e.status_code == 429
    assert e.retry_after == 60


def test_match_failed_error_non_http() -> None:
    e = MatchFailedError("apple", "low_confidence")
    assert e.error_code == "match_failed"
    # no HTTP status required — worker-internal


def test_user_token_missing_error() -> None:
    e = UserTokenMissingError("user-1", "spotify")
    assert e.status_code == 400
    assert e.error_code == "user_token_missing"
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implementation in `src/collector/errors.py`**

```python
class VendorUnavailableError(AppError):
    status_code = 502
    error_code = "vendor_unavailable"

    def __init__(self, vendor: str, reason: str = ""):
        super().__init__(f"vendor {vendor} unavailable: {reason}")
        self.vendor = vendor
        self.reason = reason


class VendorAuthError(AppError):
    status_code = 403
    error_code = "vendor_auth_failed"

    def __init__(self, vendor: str):
        super().__init__(f"vendor {vendor} auth failed")
        self.vendor = vendor


class VendorQuotaError(AppError):
    status_code = 429
    error_code = "vendor_quota"

    def __init__(self, vendor: str, retry_after: int | None = None):
        super().__init__(f"vendor {vendor} quota exceeded")
        self.vendor = vendor
        self.retry_after = retry_after


class MatchFailedError(Exception):
    """Worker-internal non-fatal: trigger review queue routing."""

    error_code = "match_failed"

    def __init__(self, vendor: str, reason: str):
        super().__init__(f"match failed for {vendor}: {reason}")
        self.vendor = vendor
        self.reason = reason


class UserTokenMissingError(AppError):
    status_code = 400
    error_code = "user_token_missing"

    def __init__(self, user_id: str, vendor: str):
        super().__init__(f"user {user_id} has no token for vendor {vendor}")
        self.user_id = user_id
        self.vendor = vendor
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

---

## Task 3: `retry_vendor` decorator

**Files:**
- Create: `src/collector/vendor_match/__init__.py`
- Create: `src/collector/vendor_match/retry.py`
- Test: `tests/unit/test_vendor_match_retry.py`

- [ ] **Step 1: Test**

```python
# tests/unit/test_vendor_match_retry.py
from __future__ import annotations

import pytest

from collector.errors import VendorUnavailableError, VendorAuthError, VendorQuotaError
from collector.vendor_match.retry import retry_vendor


def test_retry_on_unavailable_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = {"n": 0}

    @retry_vendor(max_retries=3)
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise VendorUnavailableError("spotify", "timeout")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_honours_quota_retry_after(monkeypatch) -> None:
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    calls = {"n": 0}

    @retry_vendor(max_retries=3)
    def limited():
        calls["n"] += 1
        if calls["n"] == 1:
            raise VendorQuotaError("spotify", retry_after=5)
        return "ok"

    assert limited() == "ok"
    # Retry-After=5 should dominate jitter backoff
    assert slept and slept[0] >= 5


def test_no_retry_on_auth_error(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = {"n": 0}

    @retry_vendor(max_retries=3)
    def unauth():
        calls["n"] += 1
        raise VendorAuthError("spotify")

    with pytest.raises(VendorAuthError):
        unauth()
    assert calls["n"] == 1


def test_raises_after_exhausting_retries(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)

    @retry_vendor(max_retries=3)
    def always_fail():
        raise VendorUnavailableError("x", "down")

    with pytest.raises(VendorUnavailableError):
        always_fail()
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implementation**

```python
# src/collector/vendor_match/retry.py
from __future__ import annotations

import functools
import random
import time

from ..errors import VendorUnavailableError, VendorQuotaError


_TRANSIENT = (VendorUnavailableError, VendorQuotaError)


def retry_vendor(max_retries: int = 3, base_delay: float = 0.5, max_delay: float = 8.0):
    """Full-jitter retry on VendorUnavailableError / VendorQuotaError.

    VendorQuotaError.retry_after takes precedence over jitter when set.
    Non-transient errors (VendorAuthError, VendorDisabledError, etc.) propagate immediately.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except _TRANSIENT as exc:
                    last_exc = exc
                    if attempt == max_retries - 1:
                        break
                    delay = random.uniform(0, min(max_delay, base_delay * (2 ** attempt)))
                    if isinstance(exc, VendorQuotaError) and exc.retry_after:
                        delay = max(delay, float(exc.retry_after))
                    time.sleep(delay)
            assert last_exc is not None
            raise last_exc
        return wrapper
    return decorator
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

---

## Task 4: Fuzzy scorer

**Files:**
- Create: `src/collector/vendor_match/scorer.py`
- Test: `tests/unit/test_vendor_match_scorer.py`

- [ ] **Step 1: Test**

```python
from __future__ import annotations

from collector.vendor_match.scorer import score_candidate, FuzzyScore
from collector.providers.base import VendorTrackRef


def _candidate(**overrides) -> VendorTrackRef:
    base = dict(
        vendor="spotify", vendor_track_id="x", isrc=None,
        artist_names=("Foo",), title="Bar", duration_ms=200_000,
        album_name="Baz", raw_payload={},
    )
    base.update(overrides)
    return VendorTrackRef(**base)


def test_perfect_match() -> None:
    cand = _candidate()
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert s.total >= 0.95


def test_title_differs_slightly() -> None:
    cand = _candidate(title="Bar (Remix)")
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert 0.6 <= s.total < 0.95


def test_duration_outside_tolerance_penalises() -> None:
    cand = _candidate(duration_ms=250_000)  # +50s
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert not s.duration_ok


def test_artist_mismatch() -> None:
    cand = _candidate(artist_names=("Different",))
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert s.artist_sim < 0.5


def test_score_fields_accessible() -> None:
    cand = _candidate()
    s = score_candidate(
        candidate=cand, artist="Foo", title="Bar",
        duration_ms=200_000, album="Baz",
    )
    assert hasattr(s, "title_sim") and hasattr(s, "artist_sim")
    assert hasattr(s, "duration_ok") and hasattr(s, "album_bonus")
    assert hasattr(s, "total")
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implementation**

```python
# src/collector/vendor_match/scorer.py
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from ..providers.base import VendorTrackRef
from ..settings import get_ingestion_settings  # re-use or add fuzzy settings


@dataclass(frozen=True)
class FuzzyScore:
    title_sim: float
    artist_sim: float
    duration_ok: bool
    album_bonus: float
    total: float


def _normalize(s: str) -> str:
    return " ".join(s.lower().split())


def _string_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _best_artist_sim(candidate_artists: tuple[str, ...], query_artist: str) -> float:
    if not candidate_artists:
        return 0.0
    # Split query by " & " or "," to handle "Artist1 & Artist2"
    parts = [p.strip() for p in query_artist.replace("&", ",").split(",") if p.strip()]
    if not parts:
        parts = [query_artist]
    best = 0.0
    for cand in candidate_artists:
        for q in parts:
            best = max(best, _string_sim(cand, q))
    return best


def score_candidate(
    *,
    candidate: VendorTrackRef,
    artist: str,
    title: str,
    duration_ms: int | None,
    album: str | None,
) -> FuzzyScore:
    title_sim = _string_sim(candidate.title, title)
    artist_sim = _best_artist_sim(candidate.artist_names, artist)

    tolerance = 3000  # default; override via settings
    duration_ok = False
    if duration_ms is not None and candidate.duration_ms is not None:
        duration_ok = abs(candidate.duration_ms - duration_ms) <= tolerance

    album_bonus = 0.0
    if album and candidate.album_name:
        if _normalize(album) == _normalize(candidate.album_name):
            album_bonus = 0.05

    duration_contribution = 0.05 if duration_ok else 0.0
    total = (
        0.5 * title_sim
        + 0.4 * artist_sim
        + duration_contribution
        + album_bonus
    )
    total = min(1.0, total)

    return FuzzyScore(
        title_sim=title_sim,
        artist_sim=artist_sim,
        duration_ok=duration_ok,
        album_bonus=album_bonus,
        total=round(total, 3),
    )
```

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

---

## Task 5: Repository methods for match + review queue

**Files:**
- Modify: `src/collector/repositories.py`
- Test: `tests/unit/test_repositories_vendor_match.py`

- [ ] **Step 1: Test**

```python
# tests/unit/test_repositories_vendor_match.py
# Use existing repo fake pattern, assert SQL shape via fake executor.
# Test upsert behavior, get_vendor_match returns None / dataclass, insert_review_candidate shape.
```

- [ ] **Step 2: Implementation**

In `repositories.py`:

```python
@dataclass(frozen=True)
class VendorTrackMatch:
    clouder_track_id: str
    vendor: str
    vendor_track_id: str
    match_type: str
    confidence: Decimal
    matched_at: datetime
    payload: dict


@dataclass(frozen=True)
class UpsertVendorMatchCmd:
    clouder_track_id: str
    vendor: str
    vendor_track_id: str
    match_type: str          # "isrc" | "fuzzy" | "manual"
    confidence: Decimal
    matched_at: datetime
    payload: dict


class ClouderRepository:
    # ... existing methods ...

    def get_vendor_match(
        self, clouder_track_id: str, vendor: str, tx_id: str | None = None
    ) -> VendorTrackMatch | None:
        rows = self._execute(
            """
            SELECT vendor_track_id, match_type, confidence, matched_at, payload
            FROM vendor_track_map
            WHERE clouder_track_id = :tid AND vendor = :v
            """,
            [
                {"name": "tid", "value": {"stringValue": clouder_track_id}},
                {"name": "v", "value": {"stringValue": vendor}},
            ],
            tx_id=tx_id,
        )
        if not rows:
            return None
        r = rows[0]
        return VendorTrackMatch(
            clouder_track_id=clouder_track_id,
            vendor=vendor,
            vendor_track_id=r["vendor_track_id"],
            match_type=r["match_type"],
            confidence=Decimal(r["confidence"]),
            matched_at=r["matched_at"],
            payload=r["payload"],
        )

    def upsert_vendor_match(self, cmd: UpsertVendorMatchCmd, tx_id: str | None = None) -> None:
        self._execute(
            """
            INSERT INTO vendor_track_map (
              clouder_track_id, vendor, vendor_track_id, match_type,
              confidence, matched_at, payload
            ) VALUES (:tid, :v, :vtid, :mt, :conf, :at, :payload::jsonb)
            ON CONFLICT (clouder_track_id, vendor) DO UPDATE SET
              vendor_track_id = EXCLUDED.vendor_track_id,
              match_type      = EXCLUDED.match_type,
              confidence      = EXCLUDED.confidence,
              matched_at      = EXCLUDED.matched_at,
              payload         = EXCLUDED.payload
            """,
            [
                {"name": "tid", "value": {"stringValue": cmd.clouder_track_id}},
                {"name": "v",   "value": {"stringValue": cmd.vendor}},
                {"name": "vtid", "value": {"stringValue": cmd.vendor_track_id}},
                {"name": "mt",  "value": {"stringValue": cmd.match_type}},
                {"name": "conf", "value": {"doubleValue": float(cmd.confidence)}},
                {"name": "at",  "value": {"stringValue": cmd.matched_at.isoformat()}},
                {"name": "payload", "value": {"stringValue": json.dumps(cmd.payload)}},
            ],
            tx_id=tx_id,
        )

    def insert_review_candidate(
        self, *, review_id: str, clouder_track_id: str, vendor: str,
        candidates: list[dict], created_at: datetime, tx_id: str | None = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO match_review_queue (
              id, clouder_track_id, vendor, candidates, status, created_at
            ) VALUES (:id, :tid, :v, :cands::jsonb, 'pending', :at)
            ON CONFLICT (clouder_track_id, vendor)
              WHERE status = 'pending'
              DO NOTHING
            """,
            [
                {"name": "id", "value": {"stringValue": review_id}},
                {"name": "tid", "value": {"stringValue": clouder_track_id}},
                {"name": "v", "value": {"stringValue": vendor}},
                {"name": "cands", "value": {"stringValue": json.dumps(candidates)}},
                {"name": "at", "value": {"stringValue": created_at.isoformat()}},
            ],
            tx_id=tx_id,
        )
```

Adjust parameter handling to existing Data API client conventions.

- [ ] **Step 3: PASS**

- [ ] **Step 4: Commit**

---

## Task 6: `VendorMatchMessage` schema

**Files:**
- Modify: `src/collector/schemas.py`

- [ ] Add pydantic model and coerce function (if needed):

```python
class VendorMatchMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    clouder_track_id: str
    vendor: str
    isrc: str | None = None
    artist: str
    title: str
    duration_ms: int | None = None
    album: str | None = None
    attempt: int = Field(default=1, ge=1)

    @field_validator("clouder_track_id", "vendor", "artist", "title")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v2 = v.strip()
        if not v2:
            raise ValueError("field must be non-empty")
        return v2
```

Tests for field validation mirroring `EntitySearchMessage` tests.

Commit.

---

## Task 7: Vendor match handler

**Files:**
- Create: `src/collector/vendor_match_handler.py`
- Test: `tests/unit/test_vendor_match_handler.py`

**Behaviour:**
1. Parse SQS record → `VendorMatchMessage`.
2. `repository.get_vendor_match(clouder_track_id, vendor)` → if hit, log `vendor_match_cache_hit`, return.
3. `lookup = registry.get_lookup(vendor)`.
4. If `isrc`, wrap `lookup.lookup_by_isrc(isrc)` with `retry_vendor`. On hit → upsert with `match_type="isrc"`, `confidence=1.000`.
5. Else, `lookup.lookup_by_metadata(...)` → rank with `score_candidate` → top score ≥ 0.92 writes cache, else `insert_review_candidate` with top 5 candidates.
6. Log events: `vendor_match_started`, `vendor_match_cached`, `vendor_match_review_queued`, `vendor_match_failed`.

- [ ] **Step 1: Test harness**

```python
# tests/unit/test_vendor_match_handler.py
# Fake LookupProvider, fake repository — drive cache-hit / isrc-match / fuzzy-match / review-queue paths.
```

- [ ] **Step 2: Implementation**

```python
# src/collector/vendor_match_handler.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from .logging_utils import log_event
from .providers import registry
from .providers.base import VendorTrackRef
from .repositories import create_clouder_repository_from_env, UpsertVendorMatchCmd
from .schemas import VendorMatchMessage, validation_error_message
from .settings import get_ingestion_settings
from .vendor_match.retry import retry_vendor
from .vendor_match.scorer import score_candidate
from .errors import VendorDisabledError


FUZZY_THRESHOLD = 0.92


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records")
    if not isinstance(records, list):
        return {"processed": 0}

    repository = create_clouder_repository_from_env()
    if repository is None:
        raise RuntimeError("AURORA Data API configuration required")

    processed = 0
    for record in records:
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue

        try:
            message = VendorMatchMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event("ERROR", "vendor_match_message_invalid",
                      error_message=validation_error_message(exc))
            continue

        if _process_one(message, repository):
            processed += 1

    return {"processed": processed}


def _process_one(message: VendorMatchMessage, repository) -> bool:
    log_event("INFO", "vendor_match_started",
              track_id=message.clouder_track_id, vendor=message.vendor)

    cached = repository.get_vendor_match(message.clouder_track_id, message.vendor)
    if cached is not None:
        log_event("INFO", "vendor_match_cache_hit", track_id=message.clouder_track_id)
        return True

    try:
        lookup = registry.get_lookup(message.vendor)
    except VendorDisabledError:
        log_event("WARNING", "vendor_match_vendor_disabled", vendor=message.vendor)
        return False

    now = datetime.now(timezone.utc)

    # ISRC first
    if message.isrc:
        ref = _safe_lookup(lambda: lookup.lookup_by_isrc(message.isrc), message.vendor)
        if ref is not None:
            repository.upsert_vendor_match(UpsertVendorMatchCmd(
                clouder_track_id=message.clouder_track_id,
                vendor=message.vendor,
                vendor_track_id=ref.vendor_track_id,
                match_type="isrc",
                confidence=Decimal("1.000"),
                matched_at=now,
                payload=ref.raw_payload,
            ))
            log_event("INFO", "vendor_match_cached",
                      track_id=message.clouder_track_id, match_type="isrc")
            return True

    # Fuzzy fallback
    candidates = _safe_lookup(
        lambda: lookup.lookup_by_metadata(
            message.artist, message.title, message.duration_ms, message.album,
        ),
        message.vendor,
    ) or []

    scored = [
        (c, score_candidate(
            candidate=c, artist=message.artist, title=message.title,
            duration_ms=message.duration_ms, album=message.album,
        ))
        for c in candidates
    ]
    scored.sort(key=lambda t: t[1].total, reverse=True)

    if scored and scored[0][1].total >= FUZZY_THRESHOLD:
        best_cand, best_score = scored[0]
        repository.upsert_vendor_match(UpsertVendorMatchCmd(
            clouder_track_id=message.clouder_track_id,
            vendor=message.vendor,
            vendor_track_id=best_cand.vendor_track_id,
            match_type="fuzzy",
            confidence=Decimal(str(best_score.total)),
            matched_at=now,
            payload=best_cand.raw_payload,
        ))
        log_event("INFO", "vendor_match_cached",
                  track_id=message.clouder_track_id, match_type="fuzzy",
                  confidence=float(best_score.total))
        return True

    # Review queue
    top5 = [
        {"ref": c.raw_payload, "score": s.total,
         "title_sim": s.title_sim, "artist_sim": s.artist_sim,
         "duration_ok": s.duration_ok, "album_bonus": s.album_bonus}
        for c, s in scored[:5]
    ]
    if top5:
        repository.insert_review_candidate(
            review_id=str(uuid4()),
            clouder_track_id=message.clouder_track_id,
            vendor=message.vendor,
            candidates=top5,
            created_at=now,
        )
        log_event("INFO", "vendor_match_review_queued",
                  track_id=message.clouder_track_id, count=len(top5))
    else:
        log_event("WARNING", "vendor_match_no_candidates",
                  track_id=message.clouder_track_id, vendor=message.vendor)
    return True


@retry_vendor(max_retries=3)
def _safe_lookup(fn, vendor: str):
    return fn()
```

- [ ] **Step 3: PASS**

- [ ] **Step 4: Commit**

---

## Task 8: Terraform — SQS queue, Lambda, IAM, alarms

**Files:**
- Modify: `infra/sqs.tf` — add `aws_sqs_queue.vendor_match` + DLQ.
- Modify: `infra/lambda.tf` — add Lambda resource + event source mapping.
- Modify: `infra/iam.tf` — extend queue ARNs in `AllowSQSSend`/`AllowSQSConsume`.
- Modify: `infra/outputs.tf` — add `vendor_match_worker_lambda_function_name`.
- Modify: `infra/variables.tf` — `vendor_match_queue_visibility_timeout_seconds`, `vendor_match_worker_lambda_timeout_seconds`, `vendor_match_max_receive_count`.
- Modify: `infra/logging.tf` — DLQ alarm.
- Modify: `infra/main.tf` — local names.

Follow existing canonicalization worker pattern closely — same structure for event source mapping, timeouts, DLQ. Keep queue visibility ≥ worker timeout (as per CLAUDE.md Gotchas).

- [ ] Run `terraform fmt && terraform validate` after changes.
- [ ] Commit.

---

## Task 9: Integration test — end-to-end flow

**Files:**
- Create: `tests/integration/test_vendor_match_flow.py`

Test scenarios using ephemeral Postgres (via `conftest.py` fixtures) and `FakeLookupProvider`:

1. ISRC match — cache hit after first call.
2. Fuzzy match ≥ 0.92 — writes cache.
3. Low confidence — writes to review queue, top 5 candidates present.
4. Cache-hit skip — second invocation with same `(track_id, vendor)` does not call provider.
5. `VendorDisabledError` → skip and log.
6. Permanent error from provider → review queue empty (if scorer returns no candidates).

- [ ] Implement each scenario.
- [ ] Commit.

---

## Task 10: Docs + CLAUDE.md

- Add to `docs/data-model.md`: `vendor_track_map`, `match_review_queue` tables.
- Add to `CLAUDE.md`:
  - Env: `FUZZY_MATCH_THRESHOLD` (default 0.92).
  - Gotchas: "Vendor match cache is PK `(clouder_track_id, vendor)` — idempotent on retry."
  - New Lambda: `vendor_match_worker`.
- Commit.

---

## Execution Order

1. Migration (Task 1)
2. Error classes (Task 2)
3. Retry decorator (Task 3)
4. Scorer (Task 4)
5. Repository methods (Task 5)
6. Schema (Task 6)
7. Handler (Task 7)
8. Terraform (Task 8)
9. Integration (Task 9)
10. Docs (Task 10)

After landing: Plan 5 can call `vendor_match_worker` via SQS (fan-out) OR reuse its matching logic inline from `release_mirror_worker`. Spec currently chooses inline with bounded concurrency — see Plan 5 Task 4.
