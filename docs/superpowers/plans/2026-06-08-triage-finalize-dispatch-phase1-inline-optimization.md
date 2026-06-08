# Triage-Finalize Dispatch — Phase 1: Inline Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make triage-block auto-enrichment dispatch fast enough that both the label pass and the artist pass complete inside the 30s curation Lambda timeout, fixing the silent drop of artist auto-search.

**Architecture:** Replace the per-item RDS Data API round-trip loops (`claim_*`, resolve, `attach_run`) in both the label and artist auto-dispatch paths with set-based statements using the codebase's parametric `IN (:t0, …)` placeholder pattern (chunked at 500), and replace the per-message `sqs.send_message` loop with `sqs.send_message_batch` (≤10 entries). Add the missing dispatch-count log fields so the dispatch is observable.

**Tech Stack:** Python 3.12, RDS Data API (`DataAPIClient.execute`), boto3 SQS, pytest. Runtime DB is the Data API — never psycopg.

**Scope note:** This plan is independently shippable and fully fixes the production bug. Phase 2 (async dispatch worker) is a separate follow-up plan and reuses the optimized code from this plan.

**Run tests with** (worktree `.venv` lives at the MAIN repo root):
`/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest`

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/collector/logging_utils.py` | Structured-log field allowlist | Add dispatch-count fields |
| `src/collector/artist_enrichment/repository.py` | Artist canonical reads/writes | Add `get_artists_by_ids` (set-based resolve) |
| `src/collector/label_enrichment/repository.py` | Label canonical reads/writes | Add `get_labels_by_ids` + `derive_styles_for_labels` (set-based resolve) |
| `src/collector/artist_enrichment/auto_repository.py` | Artist claim/attach state | Set-based `claim_artists` + `attach_run` |
| `src/collector/label_enrichment/auto_repository.py` | Label claim/attach state | Set-based `claim_labels` + `attach_run` |
| `src/collector/artist_enrichment/auto_dispatch.py` | Artist fan-out | Set-based resolve + batched SQS + `started` log |
| `src/collector/label_enrichment/auto_dispatch.py` | Label fan-out | Set-based resolve + batched SQS + `started` log |
| `tests/unit/test_*` | Unit coverage | New + updated tests per task |

Shared conventions introduced:
- `_IN_CHUNK = 500` (max ids per `IN (...)` statement — Data API cannot bind arrays/`ANY()`).
- `_SQS_BATCH = 10` (SQS `send_message_batch` hard limit).
- Placeholder build: `", ".join(f":t{i}" for i in range(len(chunk)))` + `params = {f"t{i}": v for i, v in enumerate(chunk)}` — the established pattern (`repositories.py:846`, `playlists_repository.py:85`).

---

## Task 1: Observability — log dispatch counts + a `started` marker

**Files:**
- Modify: `src/collector/logging_utils.py` (the `ALLOWED_LOG_FIELDS` set)
- Modify: `src/collector/artist_enrichment/auto_dispatch.py:54-117`
- Modify: `src/collector/label_enrichment/auto_dispatch.py:54-119`
- Test: `tests/unit/test_logging_utils_dispatch_fields.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_logging_utils_dispatch_fields.py`:

```python
from collector.logging_utils import ALLOWED_LOG_FIELDS


def test_dispatch_count_fields_are_allowed():
    for field in (
        "claimed",
        "skipped",
        "candidate_labels",
        "candidate_artists",
        "source_hint",
    ):
        assert field in ALLOWED_LOG_FIELDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_logging_utils_dispatch_fields.py -q`
Expected: FAIL — these fields are not yet in the allowlist.

- [ ] **Step 3: Add the fields to the allowlist**

In `src/collector/logging_utils.py`, inside the `ALLOWED_LOG_FIELDS` set, add the five new keys (place them near the existing `run_id` / `result_count` entries):

```python
    "claimed",
    "skipped",
    "candidate_labels",
    "candidate_artists",
    "source_hint",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_logging_utils_dispatch_fields.py -q`
Expected: PASS

- [ ] **Step 5: Add a `*_dispatch_started` marker in both dispatch functions**

In `src/collector/artist_enrichment/auto_dispatch.py`, at the very top of `_dispatch_artists` (right after `if not artist_ids: return`), add:

```python
    log_event(
        "INFO", "auto_enrich_artists_dispatch_started",
        source_hint=source_hint, candidate_artists=len(artist_ids),
    )
```

In `src/collector/label_enrichment/auto_dispatch.py`, at the top of `_dispatch_labels` (right after `if not label_ids: return`), add:

```python
    log_event(
        "INFO", "auto_enrich_dispatch_started",
        source_hint=source_hint, candidate_labels=len(label_ids),
    )
```

- [ ] **Step 6: Run the full dispatch test files to confirm nothing broke**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_auto_dispatch.py tests/unit/test_artist_auto_dispatch.py -q`
Expected: PASS (the `started` log adds no behavior the existing tests assert against).

- [ ] **Step 7: Commit**

```bash
git add src/collector/logging_utils.py src/collector/artist_enrichment/auto_dispatch.py src/collector/label_enrichment/auto_dispatch.py tests/unit/test_logging_utils_dispatch_fields.py
git commit -m "$(cat <<'EOF'
feat(enrich): log auto-dispatch counts and start marker

Dispatch counts were dropped by the log-field allowlist, so the
timeout-killed artist pass left no trace. Allow the count fields and
emit a started marker so a future cut-off shows started-without-done.
EOF
)"
```

---

## Task 2: Set-based artist resolve — `get_artists_by_ids`

**Files:**
- Modify: `src/collector/artist_enrichment/repository.py` (add method near `get_artist_by_id:84`)
- Test: `tests/unit/test_artist_enrichment_repository_reads.py` (add cases)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_artist_enrichment_repository_reads.py`:

```python
def test_get_artists_by_ids_one_query_returns_name_map():
    captured = []

    class FakeDataAPI:
        def execute(self, sql, params=None, transaction_id=None):
            captured.append((sql, params))
            return [
                {"id": "a1", "name": "Artist One"},
                {"id": "a2", "name": "Artist Two"},
            ]

    from collector.artist_enrichment.repository import ArtistEnrichmentRepository
    repo = ArtistEnrichmentRepository(data_api=FakeDataAPI())
    result = repo.get_artists_by_ids(["a1", "a2"])
    assert result == {"a1": "Artist One", "a2": "Artist Two"}
    assert len(captured) == 1  # single round-trip, not one per id
    assert ":t0" in captured[0][0] and ":t1" in captured[0][0]


def test_get_artists_by_ids_empty_input_no_query():
    class FakeDataAPI:
        def execute(self, *a, **k):  # pragma: no cover - must not be called
            raise AssertionError("should not query for empty input")

    from collector.artist_enrichment.repository import ArtistEnrichmentRepository
    assert ArtistEnrichmentRepository(data_api=FakeDataAPI()).get_artists_by_ids([]) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_artist_enrichment_repository_reads.py -q -k get_artists_by_ids`
Expected: FAIL with `AttributeError: 'ArtistEnrichmentRepository' object has no attribute 'get_artists_by_ids'`

- [ ] **Step 3: Implement the method**

In `src/collector/artist_enrichment/repository.py`, add a module-level constant near the top imports:

```python
_IN_CHUNK = 500
```

Add the method to `ArtistEnrichmentRepository` (just below `get_artist_by_id`):

```python
    def get_artists_by_ids(self, artist_ids: list[str]) -> dict[str, str]:
        """Resolve {artist_id: name} for many ids in chunked set-based queries."""
        out: dict[str, str] = {}
        unique = list(dict.fromkeys(artist_ids))
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            placeholders = ", ".join(f":t{i}" for i in range(len(chunk)))
            params = {f"t{i}": v for i, v in enumerate(chunk)}
            rows = self._data_api.execute(
                f"SELECT id, name FROM clouder_artists WHERE id IN ({placeholders})",
                params,
            )
            for r in rows:
                out[r["id"]] = r["name"]
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_artist_enrichment_repository_reads.py -q -k get_artists_by_ids`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/artist_enrichment/repository.py tests/unit/test_artist_enrichment_repository_reads.py
git commit -m "feat(artist-enrich): add set-based get_artists_by_ids"
```

---

## Task 3: Set-based label resolve — `get_labels_by_ids` + `derive_styles_for_labels`

**Files:**
- Modify: `src/collector/label_enrichment/repository.py` (near `get_label_by_id:87` and `derive_style_for_label:521`)
- Test: `tests/unit/test_label_enrichment_repository.py` (add cases)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_label_enrichment_repository.py`:

```python
def test_get_labels_by_ids_single_query_name_map():
    captured = []

    class FakeDataAPI:
        def execute(self, sql, params=None, transaction_id=None):
            captured.append(sql)
            return [{"id": "l1", "name": "Label One"}, {"id": "l2", "name": "Label Two"}]

    from collector.label_enrichment.repository import LabelEnrichmentRepository
    repo = LabelEnrichmentRepository(data_api=FakeDataAPI())
    assert repo.get_labels_by_ids(["l1", "l2"]) == {"l1": "Label One", "l2": "Label Two"}
    assert len(captured) == 1


def test_derive_styles_for_labels_top_style_per_label():
    class FakeDataAPI:
        def execute(self, sql, params=None, transaction_id=None):
            return [
                {"label_id": "l1", "style_name": "techno"},
                {"label_id": "l2", "style_name": "house"},
            ]

    from collector.label_enrichment.repository import LabelEnrichmentRepository
    repo = LabelEnrichmentRepository(data_api=FakeDataAPI())
    assert repo.derive_styles_for_labels(["l1", "l2"]) == {"l1": "techno", "l2": "house"}


def test_resolve_helpers_empty_input_no_query():
    class FakeDataAPI:
        def execute(self, *a, **k):  # pragma: no cover
            raise AssertionError("no query for empty input")

    from collector.label_enrichment.repository import LabelEnrichmentRepository
    repo = LabelEnrichmentRepository(data_api=FakeDataAPI())
    assert repo.get_labels_by_ids([]) == {}
    assert repo.derive_styles_for_labels([]) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_label_enrichment_repository.py -q -k "get_labels_by_ids or derive_styles_for_labels or resolve_helpers"`
Expected: FAIL with `AttributeError` on the new methods.

- [ ] **Step 3: Implement the methods**

In `src/collector/label_enrichment/repository.py`, add `_IN_CHUNK = 500` near the top imports (if not already present), then add to `LabelEnrichmentRepository`:

```python
    def get_labels_by_ids(self, label_ids: list[str]) -> dict[str, str]:
        """Resolve {label_id: name} for many ids in chunked set-based queries."""
        out: dict[str, str] = {}
        unique = list(dict.fromkeys(label_ids))
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            placeholders = ", ".join(f":t{i}" for i in range(len(chunk)))
            params = {f"t{i}": v for i, v in enumerate(chunk)}
            rows = self._data_api.execute(
                f"SELECT id, name FROM clouder_labels WHERE id IN ({placeholders})",
                params,
            )
            for r in rows:
                out[r["id"]] = r["name"]
        return out

    def derive_styles_for_labels(self, label_ids: list[str]) -> dict[str, str]:
        """Most common style per label, in one chunked query. Absent => no tracks."""
        out: dict[str, str] = {}
        unique = list(dict.fromkeys(label_ids))
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            placeholders = ", ".join(f":t{i}" for i in range(len(chunk)))
            params = {f"t{i}": v for i, v in enumerate(chunk)}
            rows = self._data_api.execute(
                f"""
                SELECT label_id, style_name FROM (
                    SELECT a.label_id AS label_id,
                           s.name AS style_name,
                           ROW_NUMBER() OVER (
                               PARTITION BY a.label_id
                               ORDER BY COUNT(*) DESC, s.name ASC
                           ) AS rn
                    FROM clouder_styles s
                    JOIN clouder_tracks t ON t.style_id = s.id
                    JOIN clouder_albums a ON a.id = t.album_id
                    WHERE a.label_id IN ({placeholders})
                    GROUP BY a.label_id, s.name
                ) ranked
                WHERE rn = 1
                """,
                params,
            )
            for r in rows:
                if r.get("style_name") is not None:
                    out[r["label_id"]] = r["style_name"]
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_label_enrichment_repository.py -q -k "get_labels_by_ids or derive_styles_for_labels or resolve_helpers"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/repository.py tests/unit/test_label_enrichment_repository.py
git commit -m "feat(label-enrich): add set-based label name + style resolve"
```

---

## Task 4: Set-based `claim_artists` (preserve race-safety semantics)

**Files:**
- Modify: `src/collector/artist_enrichment/auto_repository.py:107-172`
- Test: `tests/unit/test_artist_enrichment_auto_repository.py` (add round-trip-count case)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_artist_enrichment_auto_repository.py`:

```python
def test_claim_artists_uses_two_statements_regardless_of_count():
    calls = []

    class FakeDataAPI:
        def execute(self, sql, params=None, transaction_id=None):
            calls.append(sql.strip().split()[0].upper())  # first keyword
            if sql.strip().upper().startswith("UPDATE"):
                return [{"artist_id": "a1"}]      # reclaim a1
            return [{"artist_id": "a3"}]          # insert a3

    from collector.artist_enrichment.auto_repository import AutoEnrichRepository
    repo = AutoEnrichRepository(data_api=FakeDataAPI())
    claimed = repo.claim_artists(["a1", "a2", "a3"])
    # exactly one UPDATE + one INSERT, not 2 per id
    assert calls.count("UPDATE") == 1
    assert calls.count("INSERT") == 1
    assert set(claimed) == {"a1", "a3"}


def test_claim_artists_empty_returns_empty_no_query():
    class FakeDataAPI:
        def execute(self, *a, **k):  # pragma: no cover
            raise AssertionError("no query for empty input")

    from collector.artist_enrichment.auto_repository import AutoEnrichRepository
    assert AutoEnrichRepository(data_api=FakeDataAPI()).claim_artists([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_artist_enrichment_auto_repository.py -q -k claim_artists`
Expected: FAIL — current loop issues one UPDATE + one INSERT *per id* (`calls.count("UPDATE") == 3`).

- [ ] **Step 3: Rewrite `claim_artists` set-based**

Replace the body of `claim_artists` in `src/collector/artist_enrichment/auto_repository.py` (keep the docstring) with:

```python
        if not artist_ids:
            return []
        now = self._now()
        stale_cutoff = now - timedelta(hours=_STALE_QUEUED_HOURS)
        unique = list(dict.fromkeys(artist_ids))
        claimed: list[str] = []
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            placeholders = ", ".join(f":t{i}" for i in range(len(chunk)))
            id_params = {f"t{i}": v for i, v in enumerate(chunk)}

            reclaimed = self._data_api.execute(
                f"""
                UPDATE artist_auto_enrich_state
                SET attempts = attempts + 1,
                    status = 'queued',
                    last_run_id = NULL,
                    updated_at = :ts
                WHERE artist_id IN ({placeholders})
                  AND attempts < :max_attempts
                  AND (
                        status = 'failed'
                     OR (status = 'queued' AND updated_at < :stale_cutoff)
                  )
                RETURNING artist_id
                """,
                {
                    **id_params,
                    "ts": now,
                    "max_attempts": _MAX_ATTEMPTS,
                    "stale_cutoff": stale_cutoff,
                },
            )

            values = ", ".join(f"(:t{i})" for i in range(len(chunk)))
            inserted = self._data_api.execute(
                f"""
                INSERT INTO artist_auto_enrich_state (
                    artist_id, attempts, status, first_enqueued_at, updated_at
                )
                SELECT v.artist_id, 1, 'queued', :ts, :ts
                FROM (VALUES {values}) AS v(artist_id)
                WHERE NOT EXISTS (
                    SELECT 1 FROM artist_auto_enrich_state s
                    WHERE s.artist_id = v.artist_id
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM clouder_artist_info i
                    WHERE i.artist_id = v.artist_id
                )
                ON CONFLICT (artist_id) DO NOTHING
                RETURNING artist_id
                """,
                {**id_params, "ts": now},
            )
            claimed.extend(r["artist_id"] for r in reclaimed)
            claimed.extend(r["artist_id"] for r in inserted)
        return claimed
```

Note: a reclaimed id now has a `queued` row, so the insert's `NOT EXISTS (state)` excludes it — the two result sets cannot overlap. Semantics (attempt cap, stale-queued reclaim, skip-if-info-row, `ON CONFLICT DO NOTHING`) are preserved.

- [ ] **Step 4: Run test + the full auto-repo suite**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_artist_enrichment_auto_repository.py -q`
Expected: PASS (new round-trip test + all existing claim/state tests).

- [ ] **Step 5: Commit**

```bash
git add src/collector/artist_enrichment/auto_repository.py tests/unit/test_artist_enrichment_auto_repository.py
git commit -m "perf(artist-enrich): claim artists set-based, 2 statements/chunk"
```

---

## Task 5: Set-based `claim_labels` (mirror of Task 4)

**Files:**
- Modify: `src/collector/label_enrichment/auto_repository.py:107-172`
- Test: `tests/unit/test_auto_enrich_repository.py` (add round-trip-count case)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_auto_enrich_repository.py`:

```python
def test_claim_labels_uses_two_statements_regardless_of_count():
    calls = []

    class FakeDataAPI:
        def execute(self, sql, params=None, transaction_id=None):
            calls.append(sql.strip().split()[0].upper())
            if sql.strip().upper().startswith("UPDATE"):
                return [{"label_id": "l1"}]
            return [{"label_id": "l3"}]

    from collector.label_enrichment.auto_repository import AutoEnrichRepository
    repo = AutoEnrichRepository(data_api=FakeDataAPI())
    claimed = repo.claim_labels(["l1", "l2", "l3"])
    assert calls.count("UPDATE") == 1
    assert calls.count("INSERT") == 1
    assert set(claimed) == {"l1", "l3"}


def test_claim_labels_empty_returns_empty_no_query():
    class FakeDataAPI:
        def execute(self, *a, **k):  # pragma: no cover
            raise AssertionError("no query for empty input")

    from collector.label_enrichment.auto_repository import AutoEnrichRepository
    assert AutoEnrichRepository(data_api=FakeDataAPI()).claim_labels([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_auto_enrich_repository.py -q -k claim_labels`
Expected: FAIL — current loop issues UPDATE+INSERT per id.

- [ ] **Step 3: Rewrite `claim_labels` set-based**

In `src/collector/label_enrichment/auto_repository.py`, add `_IN_CHUNK = 500` near the top constants (next to `_MAX_ATTEMPTS`), then replace the body of `claim_labels` (keep docstring) with:

```python
        if not label_ids:
            return []
        now = self._now()
        stale_cutoff = now - timedelta(hours=_STALE_QUEUED_HOURS)
        unique = list(dict.fromkeys(label_ids))
        claimed: list[str] = []
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            placeholders = ", ".join(f":t{i}" for i in range(len(chunk)))
            id_params = {f"t{i}": v for i, v in enumerate(chunk)}

            reclaimed = self._data_api.execute(
                f"""
                UPDATE label_auto_enrich_state
                SET attempts = attempts + 1,
                    status = 'queued',
                    last_run_id = NULL,
                    updated_at = :ts
                WHERE label_id IN ({placeholders})
                  AND attempts < :max_attempts
                  AND (
                        status = 'failed'
                     OR (status = 'queued' AND updated_at < :stale_cutoff)
                  )
                RETURNING label_id
                """,
                {
                    **id_params,
                    "ts": now,
                    "max_attempts": _MAX_ATTEMPTS,
                    "stale_cutoff": stale_cutoff,
                },
            )

            values = ", ".join(f"(:t{i})" for i in range(len(chunk)))
            inserted = self._data_api.execute(
                f"""
                INSERT INTO label_auto_enrich_state (
                    label_id, attempts, status, first_enqueued_at, updated_at
                )
                SELECT v.label_id, 1, 'queued', :ts, :ts
                FROM (VALUES {values}) AS v(label_id)
                WHERE NOT EXISTS (
                    SELECT 1 FROM label_auto_enrich_state s
                    WHERE s.label_id = v.label_id
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM clouder_label_info i
                    WHERE i.label_id = v.label_id
                )
                ON CONFLICT (label_id) DO NOTHING
                RETURNING label_id
                """,
                {**id_params, "ts": now},
            )
            claimed.extend(r["label_id"] for r in reclaimed)
            claimed.extend(r["label_id"] for r in inserted)
        return claimed
```

- [ ] **Step 4: Run test + full label auto-repo suite**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_auto_enrich_repository.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/auto_repository.py tests/unit/test_auto_enrich_repository.py
git commit -m "perf(label-enrich): claim labels set-based, 2 statements/chunk"
```

---

## Task 6: Set-based `attach_run` in both auto-repositories

**Files:**
- Modify: `src/collector/artist_enrichment/auto_repository.py:174-189`
- Modify: `src/collector/label_enrichment/auto_repository.py:174-189`
- Test: `tests/unit/test_artist_enrichment_auto_repository.py`, `tests/unit/test_auto_enrich_repository.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_artist_enrichment_auto_repository.py`:

```python
def test_attach_run_single_update_for_many_ids():
    calls = []

    class FakeDataAPI:
        def execute(self, sql, params=None, transaction_id=None):
            calls.append((sql, params))
            return []

    from collector.artist_enrichment.auto_repository import AutoEnrichRepository
    AutoEnrichRepository(data_api=FakeDataAPI()).attach_run(["a1", "a2", "a3"], "run-9")
    assert len(calls) == 1
    assert calls[0][1]["run_id"] == "run-9"
```

Add to `tests/unit/test_auto_enrich_repository.py`:

```python
def test_attach_run_single_update_for_many_ids():
    calls = []

    class FakeDataAPI:
        def execute(self, sql, params=None, transaction_id=None):
            calls.append((sql, params))
            return []

    from collector.label_enrichment.auto_repository import AutoEnrichRepository
    AutoEnrichRepository(data_api=FakeDataAPI()).attach_run(["l1", "l2"], "run-7")
    assert len(calls) == 1
    assert calls[0][1]["run_id"] == "run-7"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_artist_enrichment_auto_repository.py tests/unit/test_auto_enrich_repository.py -q -k attach_run_single_update`
Expected: FAIL — current loop issues one UPDATE per id (`len(calls) == 3` / `2`).

- [ ] **Step 3: Rewrite both `attach_run` set-based**

In `src/collector/artist_enrichment/auto_repository.py`, replace the body of `attach_run` (keep docstring) with:

```python
        if not artist_ids:
            return
        ts = self._now()
        unique = list(dict.fromkeys(artist_ids))
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            placeholders = ", ".join(f":t{i}" for i in range(len(chunk)))
            id_params = {f"t{i}": v for i, v in enumerate(chunk)}
            self._data_api.execute(
                f"""
                UPDATE artist_auto_enrich_state
                SET last_run_id = :run_id, updated_at = :ts
                WHERE artist_id IN ({placeholders})
                """,
                {**id_params, "run_id": run_id, "ts": ts},
            )
```

In `src/collector/label_enrichment/auto_repository.py`, replace the body of `attach_run` (keep docstring) with the same shape, using `label_id` / `label_auto_enrich_state`:

```python
        if not label_ids:
            return
        ts = self._now()
        unique = list(dict.fromkeys(label_ids))
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            placeholders = ", ".join(f":t{i}" for i in range(len(chunk)))
            id_params = {f"t{i}": v for i, v in enumerate(chunk)}
            self._data_api.execute(
                f"""
                UPDATE label_auto_enrich_state
                SET last_run_id = :run_id, updated_at = :ts
                WHERE label_id IN ({placeholders})
                """,
                {**id_params, "run_id": run_id, "ts": ts},
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_artist_enrichment_auto_repository.py tests/unit/test_auto_enrich_repository.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/artist_enrichment/auto_repository.py src/collector/label_enrichment/auto_repository.py tests/unit/test_artist_enrichment_auto_repository.py tests/unit/test_auto_enrich_repository.py
git commit -m "perf(enrich): attach_run set-based for label and artist"
```

---

## Task 7: Batched resolve + SQS in the artist dispatch

**Files:**
- Modify: `src/collector/artist_enrichment/auto_dispatch.py:54-117`
- Test: `tests/unit/test_artist_auto_dispatch.py` (update Fakes + assertions)

- [ ] **Step 1: Update the test to expect batch resolve + batch SQS**

In `tests/unit/test_artist_auto_dispatch.py`, replace `FakeArtistRepo` and `FakeSQS` and the happy-path/track assertions:

```python
class FakeArtistRepo:
    def __init__(self): self.created = None
    def get_artists_by_ids(self, ids): return {aid: f"name-{aid}" for aid in ids}
    def create_run(self, spec): self.created = spec; return "run-1"


class FakeSQS:
    def __init__(self): self.batches = []
    def send_message_batch(self, **kw): self.batches.append(kw); \
        return {"Successful": [{"Id": e["Id"]} for e in kw["Entries"]], "Failed": []}

    @property
    def sent(self):
        return [e for b in self.batches for e in b["Entries"]]
```

Update `test_happy_path_creates_run_and_enqueues_per_artist` body assertions:

```python
    assert isinstance(artist_repo.created, RunSpec)
    assert artist_repo.created.requested_artists == 2
    assert artist_repo.created.source == "auto"
    assert auto.attached == (["a1", "a2"], "run-1")
    assert len(sqs.sent) == 2
    msg = json.loads(sqs.sent[0]["MessageBody"])
    assert msg["run_id"] == "run-1" and msg["artist_id"] == "a1" and msg["artist_name"] == "name-a1"
    assert "style" not in msg
```

(`test_track_dispatch_resolves_all_roles` still asserts `len(sqs.sent) == 3`; it now reads through the `sent` property and needs no other change. `test_disabled_config_skips` / `test_no_claim_skips_enqueue` assert `sqs.sent == []` which still holds.)

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_artist_auto_dispatch.py -q`
Expected: FAIL — `_dispatch_artists` still calls `get_artist_by_id` / `send_message`, not the batch APIs.

- [ ] **Step 3: Rewrite the resolve + SQS section of `_dispatch_artists`**

In `src/collector/artist_enrichment/auto_dispatch.py`, add module constant near `_KIND`:

```python
_SQS_BATCH = 10
```

Replace the resolve loop (`resolved: list[...]` through the `for artist_id in claimed:` block) with a single batch resolve:

```python
    ae_repo = _build_artist_repository()
    names = ae_repo.get_artists_by_ids(claimed)
    resolved: list[tuple[str, str]] = [
        (artist_id, names[artist_id]) for artist_id in claimed if artist_id in names
    ]
```

Replace the per-message SQS loop with a batched send:

```python
    sqs = _build_sqs_client()
    queue_url = _queue_url()
    entries = [
        {
            "Id": str(idx),
            "MessageBody": json.dumps(
                {"run_id": run_id, "artist_id": artist_id, "artist_name": name}
            ),
        }
        for idx, (artist_id, name) in enumerate(resolved)
    ]
    failed = 0
    for start in range(0, len(entries), _SQS_BATCH):
        batch = entries[start : start + _SQS_BATCH]
        resp = sqs.send_message_batch(QueueUrl=queue_url, Entries=batch)
        failed += len(resp.get("Failed", []))
    if failed:
        log_event(
            "ERROR", "auto_enrich_artists_enqueue_partial_failure",
            run_id=run_id, error_message=f"{failed} of {len(entries)} sqs entries failed",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_artist_auto_dispatch.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/artist_enrichment/auto_dispatch.py tests/unit/test_artist_auto_dispatch.py
git commit -m "perf(artist-enrich): batch resolve + send_message_batch dispatch"
```

---

## Task 8: Batched resolve + SQS in the label dispatch

**Files:**
- Modify: `src/collector/label_enrichment/auto_dispatch.py:54-119`
- Test: `tests/unit/test_auto_dispatch.py` (update assertions)

- [ ] **Step 1: Update the test to expect batch resolve + batch SQS**

In `tests/unit/test_auto_dispatch.py`, in `test_dispatch_claims_creates_run_and_enqueues`, replace the `le_repo` resolve stubs and the SQS assertions:

```python
    le_repo = MagicMock()
    le_repo.get_labels_by_ids.return_value = {"lbl-1": "name-lbl-1", "lbl-2": "name-lbl-2"}
    le_repo.derive_styles_for_labels.return_value = {"lbl-1": "techno", "lbl-2": "techno"}
    le_repo.create_run.return_value = "run-1"
    sqs = MagicMock()
    sqs.send_message_batch.return_value = {"Successful": [], "Failed": []}
    with _patch_clients(auto_repo, le_repo, sqs):
        auto_dispatch._dispatch_labels(
            label_ids=["lbl-1", "lbl-2"], source_hint="triage", user_id="u1",
        )
    spec = le_repo.create_run.call_args[0][0]
    assert spec.source == "auto"
    assert spec.requested_labels == 2
    assert spec.vendors == ["gemini"]
    auto_repo.attach_run.assert_called_once_with(["lbl-1", "lbl-2"], "run-1")
    assert sqs.send_message_batch.call_count == 1
    entries = sqs.send_message_batch.call_args.kwargs["Entries"]
    assert len(entries) == 2
    body = json.loads(entries[0]["MessageBody"])
    assert body["run_id"] == "run-1"
    assert body["label_id"] == "lbl-1"
    assert body["style"] == "techno"
```

In `test_dispatch_no_claims_skips_run` and `test_dispatch_disabled_does_nothing`, replace `sqs.send_message.assert_not_called()` with `sqs.send_message_batch.assert_not_called()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_auto_dispatch.py -q`
Expected: FAIL — `_dispatch_labels` still uses `get_label_by_id` / `derive_style_for_label` / `send_message`.

- [ ] **Step 3: Rewrite the resolve + SQS section of `_dispatch_labels`**

In `src/collector/label_enrichment/auto_dispatch.py`, add `_SQS_BATCH = 10` near `_KIND`. Replace the resolve loop (`resolved: list[...]` through the `for label_id in claimed:` block) with:

```python
    le_repo = _build_label_repository()
    names = le_repo.get_labels_by_ids(claimed)
    styles = le_repo.derive_styles_for_labels(claimed)
    resolved: list[tuple[str, str, str]] = [
        (label_id, names[label_id], styles.get(label_id) or "music")
        for label_id in claimed
        if label_id in names
    ]
```

Replace the per-message SQS loop with:

```python
    sqs = _build_sqs_client()
    queue_url = _queue_url()
    entries = [
        {
            "Id": str(idx),
            "MessageBody": json.dumps(
                {"run_id": run_id, "label_id": label_id, "label_name": name, "style": style}
            ),
        }
        for idx, (label_id, name, style) in enumerate(resolved)
    ]
    failed = 0
    for start in range(0, len(entries), _SQS_BATCH):
        batch = entries[start : start + _SQS_BATCH]
        resp = sqs.send_message_batch(QueueUrl=queue_url, Entries=batch)
        failed += len(resp.get("Failed", []))
    if failed:
        log_event(
            "ERROR", "auto_enrich_enqueue_partial_failure",
            run_id=run_id, error_message=f"{failed} of {len(entries)} sqs entries failed",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_auto_dispatch.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/label_enrichment/auto_dispatch.py tests/unit/test_auto_dispatch.py
git commit -m "perf(label-enrich): batch resolve + send_message_batch dispatch"
```

---

## Task 9: Full-suite verification + manual prod check note

**Files:** none (verification only)

- [ ] **Step 1: Run the entire unit suite**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q`
Expected: PASS (no regressions across the collector test suite).

- [ ] **Step 2: Grep for stragglers — no remaining per-item resolve/send in dispatch**

Run: `grep -n "get_label_by_id\|get_artist_by_id\|derive_style_for_label\|send_message(" src/collector/label_enrichment/auto_dispatch.py src/collector/artist_enrichment/auto_dispatch.py`
Expected: no matches (the old single-item methods may remain in the repositories for the single-track path, but the dispatch fan-out must not call them).

> Note: `label_id_for_track` / `artist_ids_for_track` (single-track path) and the single-item `get_*_by_id` repository methods stay — they are still used by `try_dispatch_*_for_track` and are already cheap. Do not remove them.

- [ ] **Step 3: Commit any incidental fixes, then post-deploy manual verification**

After this branch is deployed, finalize a real triage block and confirm in
`/aws/lambda/beatport-prod-curation` that a single request now logs **both**
`auto_enrich_dispatched` **and** `auto_enrich_artists_dispatched` with non-zero `claimed`,
and that the request `REPORT` duration is well under 30000 ms (no `Status: timeout`).

---

## Self-Review

**Spec coverage:**
- Phase 1 "Resolve set-based" → Tasks 2, 3, 7, 8. ✔
- Phase 1 "Claim set-based" → Tasks 4, 5. ✔
- Phase 1 "`attach_run` set-based" → Task 6. ✔
- Phase 1 "Batch SQS" → Tasks 7, 8. ✔
- Observability fix (allowlist + started marker) → Task 1. ✔
- Phase 2 (async worker/infra) → separate plan (`...-phase2-async-worker.md`). ✔

**Type consistency:** New method names used consistently — `get_artists_by_ids`, `get_labels_by_ids`, `derive_styles_for_labels` (defined Tasks 2-3, consumed Tasks 7-8); `_IN_CHUNK`, `_SQS_BATCH` constants; `send_message_batch(QueueUrl=, Entries=[{Id, MessageBody}])` shape consistent across artist + label.

**Placeholder scan:** No TBD/TODO; every code step shows complete code and the exact run command + expected result.
