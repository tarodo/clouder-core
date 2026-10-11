# Replayable Canonicalization and Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make re-running canonicalization over stored raw data safe, previewable and one command away: replays converge whatever their order, a dry run reports what would change before anything is written, and a Step Functions state machine replays any slice of the raw zone.

**Architecture:** The canonicalizer stamps source rows with the run's observation time (when Beatport was read), not the processing time; an older observation can no longer overwrite a newer one (guarded upsert) and only fills gaps on tracks. Track updates are computed in Python from a read of the current row, so only rows that really change are written and every run reports what it created and changed. A `dry_run` canonicalizer reads the same state and writes nothing. A `backfill` Lambda (plan / replay / summarize) and a Step Functions state machine (Plan → Map over runs, MaxConcurrency 2 → Summarize → data-quality post-check on apply) replay the raw zone.

**Tech Stack:** Python 3.12, RDS Data API, AWS Step Functions (STANDARD, Lambda optimized integration), Lambda, Terraform, PostgreSQL 16 (`tests/db/` stand-in), pytest.

**Spec:** inline — "Spec" section below (source: hiring audit §15.3 "D", rescoped by the measurements in "Before").

## Global Constraints

- Runtime DB access only through the RDS Data API (ADR-0001); no `psycopg` under `src/collector/`.
- The Beatport token never enters the backfill path: no Lambda input, no state-machine input (Step Functions stores every state's input in the execution history).
- `log_event` keeps only `ALLOWED_LOG_FIELDS`; every new field goes there.
- No schema migrations.
- `dry_run` defaults to `true` when the execution input omits it.
- Map `MaxConcurrency` = 2.
- The backfill Lambda gets its own role: own log group, Data API (incl. transactions) on the cluster, the cluster secret, `s3:GetObject` on `${raw_prefix}/*`, `sqs:SendMessage` on the Spotify search queue. The state machine role may only invoke the backfill and data-quality Lambdas.
- No money figures in docs.
- Branch `feat/replayable-backfill` from `origin/main`, worktree `../clouder-core-backfill`; commits and PR text via `caveman:caveman-commit`; `$VENV=<repo>/.venv/bin`; `$SCRATCH` = the session scratchpad directory; real-Postgres tests use `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres` (container `er-pg`, migrated to head); `terraform fmt -check` must pass.

## Spec

**Problem.** The raw zone keeps every Beatport week that was ingested (154 style × week objects, 27.0 MB gzip, S3 versioning on), but nothing can use it:

- Re-running a stored run is unsafe. `observed_at` is the processing time, the source upsert overwrites unconditionally and the track update overwrites any field the replayed payload carries. Replaying an older week after a newer one reverts the newer values (BPM, payload) and rewrites `updated_at` on every track it touches.
- New canonicalization logic reaches history only through hand-written SQL (migration `20260531_30` re-implements key extraction from `source_entities.payload`) or by re-ingesting from Beatport, which needs a user's token, one manual request per style × week, and mixes "logic changed" with "upstream changed".
- There is no way to see what a reprocessing would change before it changes it.

**Measured context (2026-10-07, CloudWatch Logs and S3 only).** 30 days: 89 canonicalizations, 5 failures, all transient (deadlocks and transaction timeouts before ADR-0022), all recovered by the SQS retry; 0 permanent. Ingest download: median 4.8 s, p90 12.5 s, max 16.0 s against the 29 s API Gateway limit. 15 raw objects were overwritten by re-ingests.

**Decisions.**

1. *Event time.* A run's observation time is `ingest_runs.started_at`. Source rows (`source_entities.first_seen_at/last_seen_at`) and identity rows carry it; canonical rows' `created_at/updated_at` stay processing time (row audit).
2. *Guarded source upsert.* `ON CONFLICT DO UPDATE ... WHERE stored.last_run_id = new.last_run_id OR stored.last_seen_at <= new.last_seen_at`. The same run always re-applies (so a replay of the latest run picks up new logic even where old rows carry a later processing-time stamp); another run's older observation does not overwrite.
3. *Stale observation.* "Stale" = the stored source row is from another run and newer. A fresh observation overwrites each track field it carries; a stale one only fills fields that are NULL. Replays of the same set of runs then converge whatever their order (known limit: if the newest observation drops a value an older one had, the older value can return when replayed out of order — per-field observation times would close it).
4. *Changed rows only.* The canonicalizer reads the current track row (after the source upsert, which locks the source row for the transaction), computes the fields that change, and updates only those rows; `updated_at` moves only on a real change. Every run returns counts: entities created per type, tracks created / changed / stale, and changes per field.
5. *Dry run.* `Canonicalizer(repo, dry_run=True)` runs the same code against a read-only view of the repository: reads pass through, every other call is dropped, transactions are not opened; ids that do not exist are reported as "would be created".
6. *Backfill.* One Lambda with three actions — `plan` (the latest run per raw object, filtered by style ids and `period_end` range), `replay` (one run, dry or apply; apply marks a non-completed run completed and enqueues the Spotify search when tracks were created), `summarize` (totals). A STANDARD state machine: Plan → Map (MaxConcurrency 2, retries, a failed run is caught and recorded) → Summarize → fail if any run failed → on apply only, invoke the data-quality Lambda and fail if a check failed.

**Non-goals (rulings, recorded in ADR-0024).** Ingest inside Step Functions (the token would persist in execution history). Asynchronous ingest (max 16 s vs 29 s). A `canonicalizer_version` column (a full replay of the raw zone takes minutes; add when replays get expensive). Diffs of relations and track–artist links (append-only, never removed). Removal counts (canonicalization never deletes).

**Success criteria.** Real-Postgres tests prove: an older replay keeps newer values; same-run replay changes nothing and leaves `updated_at`; out-of-order replays converge; dry run writes nothing and predicts apply's counts; a dry run after apply reports zero. The state machine deploys; `docs/ops/backfill.md` records before and, after the first production runs, the full-replay time, the diff and the zero-change re-run.

## Review Focus

1. **A stale observation carries a value the stored track lacks** → the gap is filled; a value already set is never overwritten. Tests: `test_track_update_stale_only_fills_gaps` (Task 1, unit), `test_out_of_order_replays_converge` (Task 1, PG).
2. **The same run is replayed while its rows carry a later processing-time stamp** (every row written before this change) → treated as fresh, new values applied. Test: `test_same_run_replay_is_fresh_even_if_stamped_later` (Task 1, PG).
3. **The Data API returns dates and ids as strings; Postgres returns native types** → no false "changed". Test: `test_track_update_compares_driver_strings_with_python_values` (Task 1, unit).
4. **A dry run over a week that introduces a new release** → existing tracks that move to it count as changed, nothing is written. Test: `test_dry_run_predicts_what_apply_does` (Task 2, PG) moves a track to a new release.
5. **One replay in the Map fails** → the others still run, the summary names it, the execution ends failed. Tests: `test_replay_failures_are_caught_and_counted` (Task 5, ASL contract), `test_summarize_adds_counts_and_lists_failures` (Task 4).

---

### Task 1: Event-time, replay-safe canonical writes with change counts

**Files:**
- Modify: `src/collector/models.py` (`CanonicalizationResult`)
- Modify: `src/collector/repositories.py` (`TRACK_MERGE_FIELDS`, `TrackState`, `read_track_state`, guarded `batch_upsert_source_entities`)
- Modify: `src/collector/canonicalize.py`
- Modify: `src/collector/logging_utils.py` (`tracks_created`, `tracks_changed`, `tracks_stale`)
- Modify: `tests/unit/test_canonicalize.py`, `tests/unit/test_canonicalize_transactions.py`, `tests/unit/test_worker_handler.py`, `tests/unit/test_worker_handler_partial_failure.py` (fakes gain `read_track_state`)
- Create: `tests/db/test_canonicalize_replay_pg.py`

**Interfaces:**
- Produces:
  - `repositories.TRACK_MERGE_FIELDS: tuple[str, ...] = ("mix_name", "isrc", "bpm", "length_ms", "key_name", "key_camelot", "publish_date", "album_id", "style_id")`
  - `repositories.TrackState(stale: bool, values: Mapping[str, Any])` (frozen dataclass)
  - `ClouderRepository.read_track_state(external_ids: Sequence[str], *, run_id: str, observed_at: datetime, transaction_id: str | None = None) -> dict[str, TrackState]`
  - `canonicalize.track_update(current: Mapping[str, Any], incoming: Mapping[str, Any], *, stale: bool) -> tuple[dict[str, Any], tuple[str, ...]]`
  - `Canonicalizer.process_run(run_id: str, bundle: NormalizedBundle, observed_at: datetime | None = None) -> CanonicalizationResult`
  - `CanonicalizationResult` gains `labels_created, styles_created, artists_created, albums_created, tracks_created, tracks_changed, tracks_stale: int = 0` and `track_field_changes: Mapping[str, int]` (default empty)

- [ ] **Step 0: Record the "before" behaviour on the unchanged code**

Run (from the worktree; old code, nothing implemented yet):

```bash
cd <repo> && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres PYTHONPATH=src:tests/db $VENV/python - <<'EOF'
import copy, os
from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import ClouderRepository
from pg_data_api import PgDataAPIClient, seed_run, truncate_canonical
from synthetic import synthetic_week
pg = PgDataAPIClient(os.environ["TEST_DATABASE_URL"]); truncate_canonical(pg); repo = ClouderRepository(pg)
old = synthetic_week(200); old[0]["bpm"] = 120
new = copy.deepcopy(old); new[0]["bpm"] = 124
for r in ("run-old", "run-new"): seed_run(pg, r)
Canonicalizer(repo).process_run(run_id="run-old", bundle=normalize_tracks(old))
Canonicalizer(repo).process_run(run_id="run-new", bundle=normalize_tracks(new))
stamp = {r["id"]: r["updated_at"] for r in pg.execute("SELECT id, updated_at FROM clouder_tracks")}
Canonicalizer(repo).process_run(run_id="run-old", bundle=normalize_tracks(old))
bpm = pg.execute("SELECT t.bpm FROM clouder_tracks t JOIN identity_map i ON i.clouder_id = t.id WHERE i.entity_type = 'track' AND i.external_id = '1'")[0]["bpm"]
touched = sum(1 for r in pg.execute("SELECT id, updated_at FROM clouder_tracks") if r["updated_at"] != stamp[r["id"]])
print(f"before: replaying the older run sets bpm back to {bpm} (newer run had 124); updated_at rewritten on {touched}/200 tracks")
truncate_canonical(pg); pg.close()
EOF
```

Expected: `before: replaying the older run sets bpm back to 120 (newer run had 124); updated_at rewritten on 200/200 tracks`. Copy the line into the ledger as `Task 1: before-evidence: ...` — it goes into `docs/ops/backfill.md` (Task 6).

- [ ] **Step 1: Write the failing unit tests for `track_update`**

Append to `tests/unit/test_canonicalize.py`:

```python
from datetime import date

from collector.canonicalize import track_update

_FIELDS_NONE = {
    "mix_name": None, "isrc": None, "bpm": None, "length_ms": None, "key_name": None,
    "key_camelot": None, "publish_date": None, "album_id": None, "style_id": None,
}


def test_track_update_fresh_overwrites_with_carried_values() -> None:
    current = {**_FIELDS_NONE, "bpm": 120, "isrc": "A"}
    incoming = {**_FIELDS_NONE, "bpm": 124}

    write, changed = track_update(current, incoming, stale=False)

    assert changed == ("bpm",)
    assert write["bpm"] == 124
    assert write["isrc"] is None  # None = keep the column


def test_track_update_stale_only_fills_gaps() -> None:
    current = {**_FIELDS_NONE, "bpm": 124}
    incoming = {**_FIELDS_NONE, "bpm": 120, "isrc": "QZ1"}

    write, changed = track_update(current, incoming, stale=True)

    assert changed == ("isrc",)
    assert write["bpm"] is None
    assert write["isrc"] == "QZ1"


def test_track_update_compares_driver_strings_with_python_values() -> None:
    # The Data API returns DATE columns as 'YYYY-MM-DD' strings; Postgres as date.
    current = {**_FIELDS_NONE, "publish_date": "2026-09-26", "bpm": 128, "album_id": "a-1"}
    incoming = {**_FIELDS_NONE, "publish_date": date(2026, 9, 26), "bpm": 128, "album_id": "a-1"}

    _, changed = track_update(current, incoming, stale=False)

    assert changed == ()


def test_reused_track_without_changes_is_not_updated() -> None:
    repo = FakeRepo()
    bundle = normalize_tracks(_raw_track())
    Canonicalizer(repo).process_run(run_id="run-1", bundle=bundle)
    track = bundle.tracks[0]
    repo.track_states["1"] = {
        "mix_name": track.mix_name, "isrc": track.isrc, "bpm": track.bpm,
        "length_ms": track.length_ms, "key_name": None, "key_camelot": None,
        "publish_date": track.publish_date,
        "album_id": repo.identities[("beatport", "album", "5654120")].clouder_id,
        "style_id": repo.identities[("beatport", "style", "1")].clouder_id,
    }

    result = Canonicalizer(repo).process_run(run_id="run-2", bundle=bundle)

    assert repo.updated_tracks == []
    assert (result.tracks_created, result.tracks_changed) == (0, 0)
```

In `FakeRepo.__init__` add `self.track_states: dict[str, dict] = {}` and `self.stale: set[str] = set()`, and add the method:

```python
    def read_track_state(self, external_ids, *, run_id, observed_at, transaction_id=None):
        from collector.repositories import TrackState

        self.calls["read_track_state"] += 1
        return {
            ext: TrackState(stale=ext in self.stale, values=self.track_states.get(ext, {}))
            for ext in external_ids
            if ("beatport", "track", ext) in self.identities
        }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd <repo> && $VENV/pytest tests/unit/test_canonicalize.py -q`
Expected: collection error `ImportError: cannot import name 'track_update'`.

- [ ] **Step 3: Write the failing real-Postgres replay tests**

Create `tests/db/test_canonicalize_replay_pg.py`:

```python
"""Replays of stored runs on a real Postgres: event time decides, not processing order."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import ClouderRepository

from pg_data_api import seed_run
from synthetic import synthetic_week

T1 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(days=7)
MERGE_COLUMNS = "mix_name, isrc, bpm, length_ms, key_name, key_camelot, publish_date, album_id, style_id"


def _process(pg, run_id, raw, observed_at):
    seed_run(pg, run_id)
    return Canonicalizer(ClouderRepository(pg)).process_run(
        run_id=run_id, bundle=normalize_tracks(raw), observed_at=observed_at
    )


def _track(pg, external_id: int) -> dict:
    return pg.execute(
        f"""
        SELECT {MERGE_COLUMNS}, t.updated_at, se.payload, se.last_run_id
        FROM clouder_tracks t
        JOIN identity_map i ON i.clouder_id = t.id AND i.entity_type = 'track'
        JOIN source_entities se ON se.source = i.source AND se.entity_type = i.entity_type
                               AND se.external_id = i.external_id
        WHERE i.external_id = :ext
        """,
        {"ext": str(external_id)},
    )[0]


def _merge_snapshot(pg) -> list[tuple]:
    rows = pg.execute(
        f"""
        SELECT i.external_id, {MERGE_COLUMNS}
        FROM clouder_tracks t JOIN identity_map i ON i.clouder_id = t.id AND i.entity_type = 'track'
        ORDER BY i.external_id
        """
    )
    # album/style ids are fresh uuids per database; compare whether they are set
    return [
        tuple(bool(v) if k in ("album_id", "style_id") else v for k, v in row.items())
        for row in rows
    ]


def _weeks():
    old = synthetic_week(60)
    old[0]["bpm"] = 120
    new = copy.deepcopy(old)
    new[0]["bpm"] = 124
    new[1]["isrc"] = None  # newer observation lacks a value the older one had
    return old, new


def test_replaying_an_older_run_keeps_newer_values(pg) -> None:
    old, new = _weeks()
    _process(pg, "run-old", old, T1)
    _process(pg, "run-new", new, T2)

    result = _process(pg, "run-old", old, T1)

    track = _track(pg, 1)
    assert track["bpm"] == 124
    assert track["payload"]["bpm"] == 124
    assert track["last_run_id"] == "run-new"
    assert result.tracks_stale == len(old)
    assert result.tracks_changed == 0


def test_replaying_the_same_run_changes_nothing_and_keeps_updated_at(pg) -> None:
    raw = synthetic_week(60)
    _process(pg, "run-1", raw, T1)
    stamps = pg.execute("SELECT id, updated_at FROM clouder_tracks ORDER BY id")

    result = _process(pg, "run-1", raw, T1)

    assert pg.execute("SELECT id, updated_at FROM clouder_tracks ORDER BY id") == stamps
    assert (result.tracks_created, result.tracks_changed, result.tracks_stale) == (0, 0, 0)
    assert result.artists_created == result.albums_created == result.labels_created == 0


def test_same_run_replay_is_fresh_even_if_stamped_later(pg) -> None:
    raw = synthetic_week(60)
    _process(pg, "run-1", raw, T2)  # rows written before this change carry processing time
    raw[0]["bpm"] = 99  # e.g. a fixed normalizer now reads a different value

    result = _process(pg, "run-1", raw, T1)

    assert _track(pg, 1)["bpm"] == 99
    assert result.tracks_changed == 1
    assert dict(result.track_field_changes) == {"bpm": 1}


def test_out_of_order_replays_converge(pg) -> None:
    old, new = _weeks()
    _process(pg, "run-old", old, T1)
    _process(pg, "run-new", new, T2)
    in_order = _merge_snapshot(pg)

    from pg_data_api import truncate_canonical

    truncate_canonical(pg)
    _process(pg, "run-new", new, T2)
    _process(pg, "run-old", old, T1)

    assert _merge_snapshot(pg) == in_order
    assert _track(pg, 1)["bpm"] == 124
    assert _track(pg, 2)["isrc"] == old[1]["isrc"]
```

- [ ] **Step 4: Run them to verify they fail**

Run: `cd <repo> && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres $VENV/pytest tests/db/test_canonicalize_replay_pg.py -q`
Expected: 4 failed with `TypeError: Canonicalizer.process_run() got an unexpected keyword argument 'observed_at'`.

- [ ] **Step 5: Extend `CanonicalizationResult`**

In `src/collector/models.py` (add `field` to the `dataclasses` import):

```python
@dataclass(frozen=True)
class CanonicalizationResult:
    run_id: str
    tracks_total: int
    tracks_processed: int
    artists_total: int
    labels_total: int
    albums_total: int
    styles_total: int
    labels_created: int = 0
    styles_created: int = 0
    artists_created: int = 0
    albums_created: int = 0
    tracks_created: int = 0
    tracks_changed: int = 0
    tracks_stale: int = 0
    track_field_changes: Mapping[str, int] = field(default_factory=dict)
```

- [ ] **Step 6: Repository — guarded source upsert and `read_track_state`**

In `src/collector/repositories.py`, add after `_LOOKUP_CHUNK`:

```python
# Track columns a Beatport observation may set after creation (conservative merge).
TRACK_MERGE_FIELDS = (
    "mix_name", "isrc", "bpm", "length_ms", "key_name", "key_camelot",
    "publish_date", "album_id", "style_id",
)
```

and next to the other command dataclasses:

```python
@dataclass(frozen=True)
class TrackState:
    """A track's mergeable columns, and whether this run's observation is older
    than the stored one (from another run)."""

    stale: bool
    values: Mapping[str, Any]
```

In `batch_upsert_source_entities`, append to the `ON CONFLICT ... DO UPDATE SET ...` clause (after `last_run_id = EXCLUDED.last_run_id`):

```sql
            WHERE source_entities.last_run_id = EXCLUDED.last_run_id
               OR source_entities.last_seen_at <= EXCLUDED.last_seen_at
```

and extend its docstring (add one if absent):

```python
        """Upsert source rows; an older observation from another run never
        overwrites a newer one, so replays are order-independent (ADR-0024).
        The same run always re-applies: a replay of the latest data must pick up
        new normalization logic even where rows carry a later processing-time stamp."""
```

Add the read after `find_identities`:

```python
    def read_track_state(
        self,
        external_ids: Sequence[str],
        *,
        run_id: str,
        observed_at: datetime,
        transaction_id: str | None = None,
    ) -> dict[str, TrackState]:
        """Mergeable columns of existing Beatport tracks, keyed by external id.

        `stale` is the negation of the guarded source upsert's condition, so it
        reads the same before and after this run's upsert. Called after the
        upsert inside the chunk transaction: the upsert locks the source rows
        (also when its WHERE rejects the update), so no concurrent run can change
        these tracks between this read and the update.
        """
        unique = list(dict.fromkeys(external_ids))
        states: dict[str, TrackState] = {}
        for start in range(0, len(unique), _LOOKUP_CHUNK):
            chunk = unique[start : start + _LOOKUP_CHUNK]
            params: dict[str, Any] = {"run_id": run_id, "observed_at": observed_at}
            params.update({f"id{i}": ext for i, ext in enumerate(chunk)})
            placeholders = ", ".join(f":id{i}" for i in range(len(chunk)))
            rows = self._data_api.execute(
                f"""
                SELECT im.external_id,
                       COALESCE(
                           se.last_run_id <> :run_id AND se.last_seen_at > :observed_at,
                           FALSE
                       ) AS stale,
                       t.mix_name, t.isrc, t.bpm, t.length_ms, t.key_name, t.key_camelot,
                       t.publish_date, t.album_id, t.style_id
                FROM identity_map im
                JOIN clouder_tracks t ON t.id = im.clouder_id
                LEFT JOIN source_entities se
                  ON se.source = im.source
                 AND se.entity_type = im.entity_type
                 AND se.external_id = im.external_id
                WHERE im.source = 'beatport'
                  AND im.entity_type = 'track'
                  AND im.external_id IN ({placeholders})
                """,
                params,
                transaction_id=transaction_id,
            )
            for row in rows:
                states[str(row["external_id"])] = TrackState(
                    stale=bool(row["stale"]),
                    values={f: row[f] for f in TRACK_MERGE_FIELDS},
                )
        return states
```

(`Sequence` and `datetime` are already imported in `repositories.py`; add `Sequence` to the `typing` import if it is not.)

- [ ] **Step 7: Canonicalizer — event time, change computation, counts**

In `src/collector/canonicalize.py`:

1. Imports: add `from collections import Counter`; add `TRACK_MERGE_FIELDS` to the `.repositories` import.
2. Add module-level helpers after the constants:

```python
def track_update(
    current: Mapping[str, Any], incoming: Mapping[str, Any], *, stale: bool
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Values to write (None keeps the column) and the fields that change.

    A fresh observation overwrites each field it carries; a stale one (older than
    the stored observation, from another run) only fills NULLs, so replays of the
    same runs converge whatever their order. The written values come from the
    incoming observation only, never from the read-back row.
    """
    write = {
        f: incoming[f]
        if incoming[f] is not None and (not stale or current.get(f) is None)
        else None
        for f in TRACK_MERGE_FIELDS
    }
    changed = tuple(
        f
        for f in TRACK_MERGE_FIELDS
        if write[f] is not None and _comparable(write[f]) != _comparable(current.get(f))
    )
    return write, changed


def _comparable(value: Any) -> str | None:
    # The Data API returns dates and ids as strings, Postgres as native types.
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
```

3. `process_run(self, run_id: str, bundle: NormalizedBundle, observed_at: datetime | None = None)`: first lines become

```python
        # Observation time (when Beatport was read) stamps source and identity rows
        # and decides which observation wins; `at` is the row-audit time.
        observed_at = observed_at or utc_now()
        at = utc_now()
```

   Pass `at=at` into `_process_named_entities`, `_process_albums`, `_process_tracks`, and use it (instead of `observed_at`) for `CreateNamedEntityCmd.at`, `CreateAlbumCmd.at`, `CreateTrackCmd.at` and `ConservativeUpdateTrackCmd.at`. `_source_entity_cmd(...)` and `_identity_cmd(...)` keep `observed_at`.

4. `_process_named_entities` and `_process_albums` return `(ids, len(created))`; callers unpack (`label_ids, labels_created = ...`).

5. `_process_tracks` returns `(track_ids, counts)` where `counts` is a `Counter` with keys `tracks_created`, `tracks_changed`, `tracks_stale` and a `Counter` `field_changes`. Inside the chunk transaction, after `_resolve_identities(...)`:

```python
                state = self._repository.read_track_state(
                    [str(t.bp_track_id) for t in chunk if str(t.bp_track_id) not in created],
                    run_id=run_id,
                    observed_at=observed_at,
                    transaction_id=transaction_id,
                )
```

   and replace the `else:` branch that builds `ConservativeUpdateTrackCmd` with:

```python
                    else:
                        current = state.get(str(track.bp_track_id))
                        # ponytail: an identity without a track row has nothing to update
                        if current is not None:
                            write, changed = track_update(
                                current.values,
                                {
                                    "mix_name": track.mix_name,
                                    "isrc": track.isrc,
                                    "bpm": track.bpm,
                                    "length_ms": track.length_ms,
                                    "key_name": track.key_name,
                                    "key_camelot": track.key_camelot,
                                    "publish_date": publish_date,
                                    "album_id": album_id,
                                    "style_id": style_id,
                                },
                                stale=current.stale,
                            )
                            counts["tracks_stale"] += current.stale
                            if changed:
                                updates.append(
                                    ConservativeUpdateTrackCmd(
                                        track_id=clouder_track_id, at=at, **write
                                    )
                                )
                                counts["tracks_changed"] += 1
                                field_changes.update(changed)
```

   and count `counts["tracks_created"] += 1` where a `CreateTrackCmd` is appended. `batch_conservative_update_tracks(updates, ...)` stays unconditional (it returns early on an empty list); its SQL is unchanged — `COALESCE(:value, column)` with `None` for "keep" yields exactly `track_update`'s result.

6. Build the result with the new fields and log them:

```python
        result = CanonicalizationResult(
            run_id=run_id,
            tracks_total=len(bundle.tracks),
            tracks_processed=len(track_ids),
            artists_total=len(bundle.artists),
            labels_total=len(bundle.labels),
            albums_total=len(bundle.albums),
            styles_total=len(bundle.styles),
            labels_created=labels_created,
            styles_created=styles_created,
            artists_created=artists_created,
            albums_created=albums_created,
            tracks_created=track_counts["tracks_created"],
            tracks_changed=track_counts["tracks_changed"],
            tracks_stale=track_counts["tracks_stale"],
            track_field_changes=dict(field_changes),
        )
```

   and add `tracks_created=..., tracks_changed=..., tracks_stale=...` to the `canonicalization_process_completed` log call. Add `"tracks_created"`, `"tracks_changed"`, `"tracks_stale"` to `ALLOWED_LOG_FIELDS` in `src/collector/logging_utils.py`.

- [ ] **Step 8: Teach the other fakes the new read**

- `tests/unit/test_canonicalize_transactions.py`: in `_echo_repo()` add `repo.read_track_state.return_value = {}`; add `"read_track_state"` to the `test_every_phase_call_passes_transaction_id` parametrize list.
- `tests/unit/test_worker_handler.py` and `tests/unit/test_worker_handler_partial_failure.py`: add to each `FakeRepo`

```python
    def read_track_state(self, external_ids, *, run_id, observed_at, transaction_id=None):
        return {}
```

- [ ] **Step 9: Run the unit and PG tests**

Run: `cd <repo> && TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres $VENV/pytest tests/unit/test_canonicalize.py tests/unit/test_canonicalize_transactions.py tests/unit/test_worker_handler.py tests/unit/test_worker_handler_partial_failure.py tests/db -q`
Expected: all pass (the existing `tests/db` suites — cold run, warm rerun, concurrency, set-based — included).

- [ ] **Step 10: Full suite and commit**

Run: `$VENV/pytest -q 2>&1 | tail -3` — Expected: all pass.

```bash
git add src/collector/models.py src/collector/repositories.py src/collector/canonicalize.py src/collector/logging_utils.py tests/unit/test_canonicalize.py tests/unit/test_canonicalize_transactions.py tests/unit/test_worker_handler.py tests/unit/test_worker_handler_partial_failure.py tests/db/test_canonicalize_replay_pg.py
git commit -m "<caveman-commit output: feat(canonicalize): event-time, replay-safe writes>"
```

---

### Task 2: Dry-run canonicalization

**Files:**
- Modify: `src/collector/canonicalize.py`
- Test: `tests/unit/test_canonicalize.py`, `tests/db/test_canonicalize_dry_run_pg.py` (create)

**Interfaces:**
- Consumes: `Canonicalizer.process_run(..., observed_at=...)`, `CanonicalizationResult` counts (Task 1).
- Produces: `Canonicalizer(repository, *, dry_run: bool = False)`; the dry run returns the same `CanonicalizationResult` shape and writes nothing.

- [ ] **Step 1: Write the failing unit test**

Append to `tests/unit/test_canonicalize.py`:

```python
class _WriteSpy(FakeRepo):
    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if name.startswith(("batch_", "claim_", "set_", "upsert_")):
            raise AssertionError(f"dry run called {name}")
        return attr


def test_dry_run_reports_creations_and_writes_nothing() -> None:
    repo = _WriteSpy()

    result = Canonicalizer(repo, dry_run=True).process_run(
        run_id="run-dry", bundle=normalize_tracks(_raw_track())
    )

    assert (result.tracks_created, result.artists_created, result.albums_created) == (1, 1, 1)
    assert (result.labels_created, result.styles_created) == (1, 1)
    assert repo.identities == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$VENV/pytest tests/unit/test_canonicalize.py::test_dry_run_reports_creations_and_writes_nothing -q`
Expected: FAIL with `TypeError: Canonicalizer.__init__() got an unexpected keyword argument 'dry_run'`.

- [ ] **Step 3: Write the failing PG tests**

Create `tests/db/test_canonicalize_dry_run_pg.py`:

```python
"""Dry run on a real Postgres: writes nothing, predicts what apply does."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import ClouderRepository

from pg_data_api import CANONICAL_TABLES, count_rows, seed_run
from synthetic import synthetic_week

T1 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(days=7)
COUNTS = (
    "labels_created", "styles_created", "artists_created", "albums_created",
    "tracks_created", "tracks_changed", "tracks_stale",
)


def _fingerprint(pg) -> dict:
    out = {t: count_rows(pg, t) for t in CANONICAL_TABLES}
    out["tracks"] = pg.execute(
        "SELECT id, bpm, album_id, updated_at FROM clouder_tracks ORDER BY id"
    )
    out["sources"] = pg.execute(
        "SELECT external_id, payload_hash, last_run_id, last_seen_at FROM source_entities ORDER BY entity_type, external_id"
    )
    return out


def _counts(result) -> dict:
    return {**{c: getattr(result, c) for c in COUNTS}, "fields": dict(result.track_field_changes)}


def _second_week():
    first = synthetic_week(80)
    second = copy.deepcopy(first)
    second[0]["bpm"] = 99
    second[1]["release"] = {
        "id": 2_999_999, "name": "New Release",
        "label": {"id": 3_999_999, "name": "New Label"},
    }  # an existing track moves to a release that does not exist yet
    second.append({**copy.deepcopy(first[2]), "id": 9_999, "name": "Brand New"})
    return first, second


def test_dry_run_writes_nothing(pg) -> None:
    first, second = _second_week()
    repo = ClouderRepository(pg)
    seed_run(pg, "run-1")
    seed_run(pg, "run-2")
    Canonicalizer(repo).process_run(run_id="run-1", bundle=normalize_tracks(first), observed_at=T1)
    before = _fingerprint(pg)

    Canonicalizer(repo, dry_run=True).process_run(
        run_id="run-2", bundle=normalize_tracks(second), observed_at=T2
    )

    assert _fingerprint(pg) == before


def test_dry_run_predicts_what_apply_does(pg) -> None:
    first, second = _second_week()
    repo = ClouderRepository(pg)
    seed_run(pg, "run-1")
    seed_run(pg, "run-2")
    Canonicalizer(repo).process_run(run_id="run-1", bundle=normalize_tracks(first), observed_at=T1)

    dry = Canonicalizer(repo, dry_run=True).process_run(
        run_id="run-2", bundle=normalize_tracks(second), observed_at=T2
    )
    applied = Canonicalizer(repo).process_run(
        run_id="run-2", bundle=normalize_tracks(second), observed_at=T2
    )

    assert _counts(dry) == _counts(applied)
    assert dry.tracks_created == 1
    assert (dry.albums_created, dry.labels_created) == (1, 1)
    assert dry.track_field_changes == {"bpm": 1, "album_id": 1}


def test_dry_run_after_apply_reports_nothing(pg) -> None:
    first, second = _second_week()
    repo = ClouderRepository(pg)
    seed_run(pg, "run-1")
    seed_run(pg, "run-2")
    Canonicalizer(repo).process_run(run_id="run-1", bundle=normalize_tracks(first), observed_at=T1)
    Canonicalizer(repo).process_run(run_id="run-2", bundle=normalize_tracks(second), observed_at=T2)

    again = Canonicalizer(repo, dry_run=True).process_run(
        run_id="run-2", bundle=normalize_tracks(second), observed_at=T2
    )

    assert _counts(again) == {**{c: 0 for c in COUNTS}, "fields": {}}
```

- [ ] **Step 4: Run them to verify they fail**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres $VENV/pytest tests/db/test_canonicalize_dry_run_pg.py -q`
Expected: 3 failed with `TypeError: ... unexpected keyword argument 'dry_run'`.

- [ ] **Step 5: Implement**

In `src/collector/canonicalize.py` add `from contextlib import nullcontext` and:

```python
class _ReadOnlyRepository:
    """Dry-run view: the reads a run needs pass through, every other call is
    dropped and no transaction is opened, so a dry run cannot write — also through
    a write method added later."""

    _READS = frozenset({"find_identities", "read_track_state"})

    def __init__(self, repository: ClouderRepository) -> None:
        self._repository = repository

    def transaction(self):
        return nullcontext(None)

    def __getattr__(self, name: str) -> Any:
        if name in self._READS:
            return getattr(self._repository, name)
        return lambda *args, **kwargs: None
```

`Canonicalizer.__init__(self, repository, *, dry_run: bool = False)`:

```python
        self._dry_run = dry_run
        self._repository = _ReadOnlyRepository(repository) if dry_run else repository
```

In `_resolve_identities`, replace the `missing` check and `created` computation with:

```python
        missing = candidates.keys() - resolved.keys()
        if missing and not self._dry_run:
            raise RuntimeError(
                f"identity claim did not resolve {len(missing)} {entity_type} ids"
            )
        # Dry run: nothing was claimed, so ids without an identity would be created
        # under the candidate id.
        resolved = {**{ext: candidates[ext] for ext in missing}, **resolved}
        created = {ext for ext, clouder_id in resolved.items() if clouder_id == candidates[ext]}
```

Add `dry_run=self._dry_run` to the `canonicalization_process_started` log call and `"dry_run"` to `ALLOWED_LOG_FIELDS`.

- [ ] **Step 6: Run the tests**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres $VENV/pytest tests/unit/test_canonicalize.py tests/db -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/collector/canonicalize.py src/collector/logging_utils.py tests/unit/test_canonicalize.py tests/db/test_canonicalize_dry_run_pg.py
git commit -m "<caveman-commit output: feat(canonicalize): dry run that predicts changes>"
```

---

### Task 3: Live worker uses the run's observation time

**Files:**
- Modify: `src/collector/repositories.py` (`as_utc_datetime`)
- Modify: `src/collector/worker_handler.py`
- Test: `tests/unit/test_repositories_timestamps.py` (create), `tests/unit/test_worker_handler.py`

**Interfaces:**
- Consumes: `process_run(..., observed_at=)` (Task 1); `ClouderRepository.get_run(run_id) -> dict | None` (existing; `started_at` is a Data API string such as `"2026-10-07 11:08:49.563"`).
- Produces: `repositories.as_utc_datetime(value: str | datetime | None) -> datetime | None` (timezone-aware UTC).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_repositories_timestamps.py`:

```python
from datetime import datetime, timezone

import pytest

from collector.repositories import as_utc_datetime

UTC = timezone.utc


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-10-07 11:08:49.563", datetime(2026, 10, 7, 11, 8, 49, 563000, tzinfo=UTC)),
        ("2026-10-07T11:08:49+00:00", datetime(2026, 10, 7, 11, 8, 49, tzinfo=UTC)),
        ("2026-10-07T11:08:49Z", datetime(2026, 10, 7, 11, 8, 49, tzinfo=UTC)),
        (datetime(2026, 10, 7, 11, 8), datetime(2026, 10, 7, 11, 8, tzinfo=UTC)),
        (datetime(2026, 10, 7, 11, 8, tzinfo=UTC), datetime(2026, 10, 7, 11, 8, tzinfo=UTC)),
        (None, None),
    ],
)
def test_as_utc_datetime(value, expected) -> None:
    assert as_utc_datetime(value) == expected
```

In `tests/unit/test_worker_handler.py`, add to `FakeRepo.__init__`: `self.source_commands: list = []` and `self.run_started_at = "2026-10-01 10:00:00.250"`; change `batch_upsert_source_entities` to `self.source_commands.extend(commands)`; add

```python
    def get_run(self, run_id):
        return {"run_id": run_id, "started_at": self.run_started_at} if self.run_started_at else None
```

and append the tests (reuse the module's existing happy-path event/S3 helpers — use the same `event`/`s3_data` the existing happy-path test passes to `lambda_handler`):

```python
def test_worker_stamps_sources_with_the_run_start(monkeypatch) -> None:
    repo = _setup_worker(monkeypatch, s3_data=_happy_s3_data())
    lambda_handler(_happy_event(), None)

    stamps = {cmd.observed_at for cmd in repo.source_commands}
    assert stamps == {datetime(2026, 10, 1, 10, 0, 0, 250000, tzinfo=timezone.utc)}


def test_worker_falls_back_to_now_without_a_run_row(monkeypatch) -> None:
    repo = FakeRepo()
    repo.run_started_at = None
    _setup_worker(monkeypatch, repo=repo, s3_data=_happy_s3_data())

    assert lambda_handler(_happy_event(), None) == {"processed": 1}
```

If the module has no `_happy_event()` / `_happy_s3_data()` helpers, extract them from the existing happy-path test body (same values) in this step — record it as a ruling only if the existing test changes behaviour.

- [ ] **Step 2: Run them to verify they fail**

Run: `$VENV/pytest tests/unit/test_repositories_timestamps.py tests/unit/test_worker_handler.py -q`
Expected: `ImportError: cannot import name 'as_utc_datetime'` (first file); the worker tests fail on the stamp assertion.

- [ ] **Step 3: Implement**

`src/collector/repositories.py`, next to `utc_now`:

```python
def as_utc_datetime(value: str | datetime | None) -> datetime | None:
    """A timestamp from the Data API ('YYYY-MM-DD HH:MM:SS[.fff]', UTC) or the
    driver, as an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
```

`src/collector/worker_handler.py`: import `as_utc_datetime`; before `phase = "canonicalize"`:

```python
            run_row = repository.get_run(run_id)
            # Event time: when Beatport was read, so replays and retries are
            # ordered by observation, not by processing (ADR-0024).
            observed_at = as_utc_datetime(run_row.get("started_at")) if run_row else None
```

pass `observed_at=observed_at` to `process_run`, and add `tracks_created=result.tracks_created, tracks_changed=result.tracks_changed, tracks_stale=result.tracks_stale` to the `canonicalization_completed` log call.

- [ ] **Step 4: Run the tests**

Run: `$VENV/pytest tests/unit/test_repositories_timestamps.py tests/unit/test_worker_handler.py tests/unit/test_worker_handler_partial_failure.py -q`
Expected: all pass (add `get_run` returning `None` to the partial-failure `FakeRepo` if it lacks one).

- [ ] **Step 5: Commit**

```bash
git add src/collector/repositories.py src/collector/worker_handler.py tests/unit/test_repositories_timestamps.py tests/unit/test_worker_handler.py tests/unit/test_worker_handler_partial_failure.py
git commit -m "<caveman-commit output: feat(worker): stamp sources with run start time>"
```

---

### Task 4: Backfill Lambda (plan / replay / summarize)

**Files:**
- Modify: `src/collector/repositories.py` (`list_replayable_runs`)
- Create: `src/collector/backfill_handler.py`
- Modify: `src/collector/logging_utils.py` (`runs_failed`)
- Test: `tests/unit/test_backfill_handler.py` (create), `tests/db/test_backfill_plan_pg.py` (create)

**Interfaces:**
- Consumes: `Canonicalizer(repo, dry_run=)`, `process_run(..., observed_at=)`, `CanonicalizationResult` counts (Tasks 1–2); `as_utc_datetime` (Task 3); `worker_handler._enqueue_spotify_search_after_canonicalization(settings, correlation_id)`; `S3Storage.read_releases(key)`; `ClouderRepository.set_run_completed(run_id, processed_count, finished_at)`.
- Produces:
  - `ClouderRepository.list_replayable_runs(*, style_ids: Sequence[int] | None = None, since: date | None = None, until: date | None = None) -> list[dict]` with keys `run_id, raw_s3_key, started_at, status, style_id, period_end`
  - `backfill_handler.lambda_handler(event, context)`; events: `{"action": "plan", "input": {...}}` → `{"dry_run": bool, "runs": [run]}`; `{"action": "replay", "run": run, "dry_run": bool}` → replay result; `{"action": "summarize", "dry_run": bool, "results": [...]}` → summary
  - run item: `{"run_id", "s3_key", "observed_at" (ISO), "status", "style_id", "period_end" (ISO or None)}`
  - replay result: `{"run_id", "style_id", "period_end", "dry_run", <COUNT_FIELDS>, "track_field_changes", "duration_ms"}`; a failed item (from the state machine) is `{"run_id", "failed": true, "error"}`
  - summary: `{"dry_run", "runs", "runs_failed", "failed_run_ids" (≤ 20), <COUNT_FIELDS>, "track_field_changes"}`
  - `COUNT_FIELDS = ("tracks_total", "labels_created", "styles_created", "artists_created", "albums_created", "tracks_created", "tracks_changed", "tracks_stale")`

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_backfill_handler.py`:

```python
from __future__ import annotations

import pytest

from collector import backfill_handler
from collector.backfill_handler import lambda_handler, plan, replay, summarize
from collector.models import CanonicalizationResult


class PlanRepo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def list_replayable_runs(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


ROW = {
    "run_id": "r-1",
    "raw_s3_key": "raw/bp/releases/style_id=1/year=2026/week=38/releases.json.gz",
    "started_at": "2026-09-20 09:15:00.5",  # Data API string
    "status": "COMPLETED",
    "style_id": 1,
    "period_end": "2026-09-18",
}


def test_plan_defaults_to_dry_run_and_shapes_runs() -> None:
    repo = PlanRepo([ROW])

    out = plan({}, repo)

    assert out["dry_run"] is True
    assert out["runs"] == [
        {
            "run_id": "r-1",
            "s3_key": ROW["raw_s3_key"],
            "observed_at": "2026-09-20T09:15:00.500000+00:00",
            "status": "COMPLETED",
            "style_id": 1,
            "period_end": "2026-09-18",
        }
    ]
    assert repo.calls == [{"style_ids": None, "since": None, "until": None}]


def test_plan_passes_filters() -> None:
    repo = PlanRepo([])

    plan({"dry_run": False, "style_ids": [1, 13], "since": "2026-08-01", "until": "2026-09-30"}, repo)

    from datetime import date

    assert repo.calls == [
        {"style_ids": [1, 13], "since": date(2026, 8, 1), "until": date(2026, 9, 30)}
    ]


@pytest.mark.parametrize(
    "params",
    [{"dry_run": "yes"}, {"style_ids": "1"}, {"style_ids": [True]}, {"since": "2026-13-01"}],
)
def test_plan_rejects_bad_input(params) -> None:
    with pytest.raises(ValueError):
        plan(params, PlanRepo([]))


class RunRepo:
    def __init__(self):
        self.completed = []

    def set_run_completed(self, run_id, processed_count, finished_at):
        self.completed.append((run_id, processed_count))


class Storage:
    def read_releases(self, key):
        return [{"id": 1, "name": "T", "artists": []}]


def _stub_canonicalizer(monkeypatch, created: int):
    seen = {}

    class Stub:
        def __init__(self, repository, *, dry_run=False):
            seen["dry_run"] = dry_run

        def process_run(self, run_id, bundle, observed_at=None):
            seen["observed_at"] = observed_at
            return CanonicalizationResult(
                run_id=run_id, tracks_total=1, tracks_processed=1, artists_total=0,
                labels_total=0, albums_total=0, styles_total=0,
                tracks_created=created, tracks_changed=2, track_field_changes={"bpm": 2},
            )

    monkeypatch.setattr(backfill_handler, "Canonicalizer", Stub)
    enqueued = []
    monkeypatch.setattr(
        backfill_handler,
        "_enqueue_spotify_search_after_canonicalization",
        lambda settings, correlation_id: enqueued.append(correlation_id),
    )
    monkeypatch.setattr(backfill_handler, "get_worker_settings", lambda: object())
    return seen, enqueued


RUN = {
    "run_id": "r-1", "s3_key": "k", "observed_at": "2026-09-20T09:15:00+00:00",
    "status": "FAILED", "style_id": 1, "period_end": "2026-09-18",
}


def test_replay_dry_run_neither_marks_nor_enqueues(monkeypatch) -> None:
    seen, enqueued = _stub_canonicalizer(monkeypatch, created=1)
    repo = RunRepo()

    out = replay(RUN, dry_run=True, repository=repo, storage=Storage())

    assert seen["dry_run"] is True
    assert seen["observed_at"].isoformat() == "2026-09-20T09:15:00+00:00"
    assert (repo.completed, enqueued) == ([], [])
    assert (out["tracks_created"], out["tracks_changed"]) == (1, 2)
    assert out["track_field_changes"] == {"bpm": 2}


def test_replay_apply_recovers_unfinished_runs_and_enqueues_search(monkeypatch) -> None:
    _, enqueued = _stub_canonicalizer(monkeypatch, created=1)
    repo = RunRepo()

    replay(RUN, dry_run=False, repository=repo, storage=Storage())

    assert repo.completed == [("r-1", 1)]
    assert enqueued == ["r-1"]


def test_replay_apply_keeps_completed_run_history(monkeypatch) -> None:
    _, enqueued = _stub_canonicalizer(monkeypatch, created=0)
    repo = RunRepo()

    replay({**RUN, "status": "COMPLETED"}, dry_run=False, repository=repo, storage=Storage())

    assert (repo.completed, enqueued) == ([], [])


def test_summarize_adds_counts_and_lists_failures() -> None:
    ok = {"run_id": "a", "tracks_total": 10, "tracks_changed": 2, "track_field_changes": {"bpm": 2}}
    ok2 = {"run_id": "b", "tracks_total": 5, "tracks_created": 1, "track_field_changes": {"bpm": 1, "isrc": 1}}
    bad = {"run_id": "c", "failed": True, "error": "RuntimeError"}

    out = summarize([ok, ok2, bad], dry_run=True)

    assert out["runs"] == 3
    assert (out["runs_failed"], out["failed_run_ids"]) == (1, ["c"])
    assert (out["tracks_total"], out["tracks_changed"], out["tracks_created"]) == (15, 2, 1)
    assert out["track_field_changes"] == {"bpm": 3, "isrc": 1}


def test_lambda_handler_rejects_unknown_action() -> None:
    with pytest.raises(ValueError):
        lambda_handler({"action": "drop"}, None)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$VENV/pytest tests/unit/test_backfill_handler.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'collector.backfill_handler'`.

- [ ] **Step 3: Write the failing PG test for the planner**

Create `tests/db/test_backfill_plan_pg.py`:

```python
"""The planner replays the run behind each raw object — the latest one written to its key."""

from __future__ import annotations

from datetime import date

from collector.repositories import ClouderRepository


def _run(pg, run_id, key, started_at, style_id, period_end, status="COMPLETED"):
    pg.execute(
        """
        INSERT INTO ingest_runs (run_id, source, style_id, raw_s3_key, status, started_at, period_end)
        VALUES (:run_id, 'beatport', :style_id, :key, :status, CAST(:started_at AS TIMESTAMPTZ),
                CAST(:period_end AS DATE))
        """,
        {
            "run_id": run_id, "style_id": style_id, "key": key, "status": status,
            "started_at": started_at, "period_end": period_end,
        },
    )


def test_list_replayable_runs_picks_latest_run_per_raw_object(pg) -> None:
    _run(pg, "a-old", "k/a", "2026-09-01 10:00+00", 1, "2026-08-28")
    _run(pg, "a-new", "k/a", "2026-09-05 10:00+00", 1, "2026-08-28", status="FAILED")
    _run(pg, "b", "k/b", "2026-09-10 10:00+00", 13, "2026-09-04")
    _run(pg, "c", "k/c", "2026-09-20 10:00+00", 1, "2026-09-18")
    repo = ClouderRepository(pg)

    assert [r["run_id"] for r in repo.list_replayable_runs()] == ["a-new", "b", "c"]
    assert [r["run_id"] for r in repo.list_replayable_runs(style_ids=[1])] == ["a-new", "c"]
    assert [
        r["run_id"]
        for r in repo.list_replayable_runs(since=date(2026, 9, 1), until=date(2026, 9, 10))
    ] == ["b"]
```

- [ ] **Step 4: Run it to verify it fails**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres $VENV/pytest tests/db/test_backfill_plan_pg.py -q`
Expected: FAIL with `AttributeError: 'ClouderRepository' object has no attribute 'list_replayable_runs'`.

- [ ] **Step 5: Implement the planner query**

`src/collector/repositories.py`, after `get_run`:

```python
    def list_replayable_runs(
        self,
        *,
        style_ids: Sequence[int] | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> list[dict[str, Any]]:
        """The run behind each raw object — the latest one written to its key.

        Re-ingesting a week overwrites its raw object, so older runs of the same
        key no longer have data of their own to replay. Filters apply to the
        latest run, by style and by the period's end date.
        """
        filters: list[str] = []
        params: dict[str, Any] = {}
        if style_ids:
            filters.append(
                "style_id IN (" + ", ".join(f":style{i}" for i in range(len(style_ids))) + ")"
            )
            params.update({f"style{i}": int(s) for i, s in enumerate(style_ids)})
        if since:
            filters.append("period_end >= :since")
            params["since"] = since
        if until:
            filters.append("period_end <= :until")
            params["until"] = until
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        return self._data_api.execute(
            f"""
            SELECT run_id, raw_s3_key, started_at, status, style_id, period_end
            FROM (
                SELECT DISTINCT ON (raw_s3_key)
                       run_id, raw_s3_key, started_at, status, style_id, period_end
                FROM ingest_runs
                WHERE source = 'beatport' AND raw_s3_key IS NOT NULL
                ORDER BY raw_s3_key, started_at DESC
            ) latest
            {where}
            ORDER BY period_end, style_id, run_id
            """,
            params,
        )
```

- [ ] **Step 6: Implement the handler**

Create `src/collector/backfill_handler.py`:

```python
"""Task Lambda behind the backfill state machine (docs/ops/backfill.md).

Replays stored raw Beatport runs through the canonicalizer: `plan` lists the run
behind each raw object, `replay` canonicalizes one (dry run or apply), `summarize`
adds the results up. The Beatport token never reaches this path.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import date
from typing import Any, Mapping, Sequence

from .canonicalize import Canonicalizer
from .logging_utils import log_event
from .models import RunStatus
from .normalize import normalize_tracks
from .repositories import as_utc_datetime, create_clouder_repository_from_env, utc_now
from .settings import get_worker_settings
from .storage import S3Storage, create_default_s3_client
from .worker_handler import _enqueue_spotify_search_after_canonicalization

COUNT_FIELDS = (
    "tracks_total",
    "labels_created",
    "styles_created",
    "artists_created",
    "albums_created",
    "tracks_created",
    "tracks_changed",
    "tracks_stale",
)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    action = event.get("action")
    if action == "plan":
        return plan(event.get("input") or {}, _repository())
    if action == "replay":
        return replay(
            event["run"],
            dry_run=bool(event["dry_run"]),
            repository=_repository(),
            storage=_storage(),
        )
    if action == "summarize":
        return summarize(event.get("results") or [], dry_run=bool(event.get("dry_run", True)))
    raise ValueError(f"unknown backfill action: {action!r}")


def plan(params: Mapping[str, Any], repository: Any) -> dict[str, Any]:
    dry_run = params.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be true or false")
    style_ids = params.get("style_ids") or None
    if style_ids is not None and not (
        isinstance(style_ids, list)
        and all(isinstance(s, int) and not isinstance(s, bool) for s in style_ids)
    ):
        raise ValueError("style_ids must be a list of integers")
    rows = repository.list_replayable_runs(
        style_ids=style_ids,
        since=_date(params.get("since"), "since"),
        until=_date(params.get("until"), "until"),
    )
    runs = [
        {
            "run_id": str(row["run_id"]),
            "s3_key": str(row["raw_s3_key"]),
            "observed_at": as_utc_datetime(row["started_at"]).isoformat(),
            "status": str(row["status"]),
            "style_id": row["style_id"],
            "period_end": _iso(row["period_end"]),
        }
        for row in rows
    ]
    log_event("INFO", "backfill_planned", dry_run=dry_run, count=len(runs))
    return {"dry_run": dry_run, "runs": runs}


def replay(
    run: Mapping[str, Any], *, dry_run: bool, repository: Any, storage: Any
) -> dict[str, Any]:
    started = time.perf_counter()
    bundle = normalize_tracks(storage.read_releases(run["s3_key"]))
    result = Canonicalizer(repository, dry_run=dry_run).process_run(
        run_id=run["run_id"], bundle=bundle, observed_at=as_utc_datetime(run["observed_at"])
    )
    if not dry_run:
        # A replay recovers a run that never completed; completed runs keep their history.
        if run["status"] != RunStatus.COMPLETED.value:
            repository.set_run_completed(
                run_id=run["run_id"],
                processed_count=result.tracks_processed,
                finished_at=utc_now(),
            )
        if result.tracks_created:
            _enqueue_spotify_search_after_canonicalization(
                settings=get_worker_settings(), correlation_id=run["run_id"]
            )
    out = {
        "run_id": run["run_id"],
        "style_id": run.get("style_id"),
        "period_end": run.get("period_end"),
        "dry_run": dry_run,
        **{f: getattr(result, f) for f in COUNT_FIELDS},
        "track_field_changes": dict(result.track_field_changes),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    log_event(
        "INFO",
        "backfill_run_replayed",
        run_id=run["run_id"],
        dry_run=dry_run,
        tracks_total=result.tracks_total,
        tracks_created=result.tracks_created,
        tracks_changed=result.tracks_changed,
        tracks_stale=result.tracks_stale,
        duration_ms=out["duration_ms"],
    )
    return out


def summarize(results: Sequence[Mapping[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    field_changes: Counter[str] = Counter()
    failed: list[str] = []
    for item in results:
        if item.get("failed"):
            failed.append(str(item.get("run_id")))
            continue
        totals.update({f: int(item.get(f) or 0) for f in COUNT_FIELDS})
        field_changes.update(item.get("track_field_changes") or {})
    summary = {
        "dry_run": dry_run,
        "runs": len(results),
        "runs_failed": len(failed),
        "failed_run_ids": failed[:20],
        **{f: totals[f] for f in COUNT_FIELDS},
        "track_field_changes": dict(field_changes),
    }
    log_event(
        "INFO",
        "backfill_summary",
        dry_run=dry_run,
        count=len(results),
        runs_failed=len(failed),
        tracks_total=totals["tracks_total"],
        tracks_created=totals["tracks_created"],
        tracks_changed=totals["tracks_changed"],
        tracks_stale=totals["tracks_stale"],
    )
    return summary


def _date(value: Any, name: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date (YYYY-MM-DD)") from exc


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _repository():
    repository = create_clouder_repository_from_env()
    if repository is None:
        raise RuntimeError("AURORA Data API configuration is required for backfill")
    return repository


def _storage() -> S3Storage:
    settings = get_worker_settings()
    return S3Storage(
        s3_client=create_default_s3_client(),
        bucket_name=settings.raw_bucket_name,
        raw_prefix=settings.raw_prefix,
    )
```

Add `"runs_failed"` to `ALLOWED_LOG_FIELDS`.

- [ ] **Step 7: Run the tests**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres $VENV/pytest tests/unit/test_backfill_handler.py tests/db/test_backfill_plan_pg.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/collector/repositories.py src/collector/backfill_handler.py src/collector/logging_utils.py tests/unit/test_backfill_handler.py tests/db/test_backfill_plan_pg.py
git commit -m "<caveman-commit output: feat(backfill): plan, replay and summarize raw runs>"
```

---

### Task 5: State machine and Lambda in Terraform

**Files:**
- Create: `infra/backfill.asl.json`, `infra/backfill.tf`
- Modify: `infra/outputs.tf`
- Test: `tests/unit/test_backfill_state_machine.py` (create)

**Interfaces:**
- Consumes: handler actions and item shapes (Task 4): Plan sends `{"action": "plan", "input": <execution input>}`; Map items `{"action": "replay", "run": <item>, "dry_run": <plan.dry_run>}`; failed items `{"run_id", "failed": true, "error"}`; Summarize `{"action": "summarize", "dry_run", "results"}` returning `runs_failed`; the data-quality Lambda returns `{"failed_checks": int, ...}`.
- Produces: state machine `clouder-prod-backfill`; output `backfill_state_machine_arn`.

- [ ] **Step 1: Write the failing contract test**

Create `tests/unit/test_backfill_state_machine.py`:

```python
"""The state machine sends what backfill_handler dispatches on (infra/backfill.asl.json)."""

from __future__ import annotations

import json
from pathlib import Path

ASL = Path(__file__).resolve().parents[2] / "infra" / "backfill.asl.json"


def _definition() -> dict:
    text = (
        ASL.read_text()
        .replace("${backfill_function_arn}", "arn:aws:lambda:eu-central-1:1:function:backfill")
        .replace("${data_quality_function_arn}", "arn:aws:lambda:eu-central-1:1:function:dq")
    )
    assert "${" not in text
    return json.loads(text)


def _states(definition: dict):
    for name, state in definition["States"].items():
        yield name, state, definition["States"]
        if state["Type"] == "Map":
            yield from _states(state["ItemProcessor"])


def test_every_transition_points_at_a_state() -> None:
    for name, state, scope in _states(_definition()):
        targets = [state.get("Next"), state.get("Default")]
        targets += [c["Next"] for c in state.get("Choices", [])]
        targets += [c["Next"] for c in state.get("Catch", [])]
        for target in filter(None, targets):
            assert target in scope, f"{name} -> {target}"


def test_tasks_send_the_actions_the_handler_dispatches() -> None:
    states = _definition()["States"]
    assert states["Plan"]["Parameters"]["Payload"] == {"action": "plan", "input.$": "$"}
    assert states["Replay"]["ItemSelector"] == {
        "action": "replay",
        "run.$": "$$.Map.Item.Value",
        "dry_run.$": "$.plan.dry_run",
    }
    assert states["Summarize"]["Parameters"]["Payload"] == {
        "action": "summarize",
        "dry_run.$": "$.plan.dry_run",
        "results.$": "$.results",
    }


def test_replay_failures_are_caught_and_counted() -> None:
    replay = _definition()["States"]["Replay"]
    assert replay["MaxConcurrency"] == 2
    inner = replay["ItemProcessor"]["States"]
    assert inner["ReplayRun"]["Catch"][0]["ErrorEquals"] == ["States.ALL"]
    failed = inner[inner["ReplayRun"]["Catch"][0]["Next"]]
    assert failed["Parameters"]["failed"] is True
    assert failed["Parameters"]["run_id.$"] == "$.run.run_id"
    choice = _definition()["States"]["AnyRunFailed"]["Choices"][0]
    assert choice["Variable"] == "$.report.summary.runs_failed"


def test_quality_gate_runs_only_after_an_apply() -> None:
    states = _definition()["States"]
    assert states["IsDryRun"]["Choices"][0] == {
        "Variable": "$.plan.dry_run", "BooleanEquals": True, "Next": "Done",
    }
    assert states["IsDryRun"]["Default"] == "QualityGate"
    assert "${data_quality_function_arn}" in ASL.read_text()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$VENV/pytest tests/unit/test_backfill_state_machine.py -q`
Expected: 4 failed with `FileNotFoundError` for `infra/backfill.asl.json`.

- [ ] **Step 3: Write the state machine definition**

Create `infra/backfill.asl.json`:

```json
{
  "Comment": "Replay stored raw Beatport runs through the canonicalizer. docs/ops/backfill.md",
  "StartAt": "Plan",
  "States": {
    "Plan": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${backfill_function_arn}",
        "Payload": {"action": "plan", "input.$": "$"}
      },
      "ResultSelector": {"dry_run.$": "$.Payload.dry_run", "runs.$": "$.Payload.runs"},
      "ResultPath": "$.plan",
      "Retry": [
        {
          "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"],
          "IntervalSeconds": 2, "MaxAttempts": 6, "BackoffRate": 2
        }
      ],
      "Next": "Replay"
    },
    "Replay": {
      "Type": "Map",
      "ItemsPath": "$.plan.runs",
      "MaxConcurrency": 2,
      "ItemSelector": {
        "action": "replay",
        "run.$": "$$.Map.Item.Value",
        "dry_run.$": "$.plan.dry_run"
      },
      "ItemProcessor": {
        "ProcessorConfig": {"Mode": "INLINE"},
        "StartAt": "ReplayRun",
        "States": {
          "ReplayRun": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {"FunctionName": "${backfill_function_arn}", "Payload.$": "$"},
            "OutputPath": "$.Payload",
            "Retry": [
              {
                "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"],
                "IntervalSeconds": 2, "MaxAttempts": 6, "BackoffRate": 2
              },
              {"ErrorEquals": ["States.TaskFailed"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2}
            ],
            "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "RunFailed"}],
            "End": true
          },
          "RunFailed": {
            "Type": "Pass",
            "Parameters": {"run_id.$": "$.run.run_id", "failed": true, "error.$": "$.error.Error"},
            "End": true
          }
        }
      },
      "ResultPath": "$.results",
      "Next": "Summarize"
    },
    "Summarize": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${backfill_function_arn}",
        "Payload": {"action": "summarize", "dry_run.$": "$.plan.dry_run", "results.$": "$.results"}
      },
      "ResultSelector": {"summary.$": "$.Payload"},
      "ResultPath": "$.report",
      "Retry": [
        {
          "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"],
          "IntervalSeconds": 2, "MaxAttempts": 6, "BackoffRate": 2
        }
      ],
      "Next": "AnyRunFailed"
    },
    "AnyRunFailed": {
      "Type": "Choice",
      "Choices": [{"Variable": "$.report.summary.runs_failed", "NumericGreaterThan": 0, "Next": "ReplayFailed"}],
      "Default": "IsDryRun"
    },
    "ReplayFailed": {
      "Type": "Fail",
      "Error": "ReplayFailed",
      "Cause": "At least one run failed to replay; the Replay map results name it."
    },
    "IsDryRun": {
      "Type": "Choice",
      "Choices": [{"Variable": "$.plan.dry_run", "BooleanEquals": true, "Next": "Done"}],
      "Default": "QualityGate"
    },
    "QualityGate": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {"FunctionName": "${data_quality_function_arn}", "Payload": {}},
      "ResultSelector": {"failed_checks.$": "$.Payload.failed_checks"},
      "ResultPath": "$.quality",
      "Retry": [
        {
          "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"],
          "IntervalSeconds": 2, "MaxAttempts": 6, "BackoffRate": 2
        }
      ],
      "Next": "QualityPassed"
    },
    "QualityPassed": {
      "Type": "Choice",
      "Choices": [{"Variable": "$.quality.failed_checks", "NumericGreaterThan": 0, "Next": "DataQualityGateFailed"}],
      "Default": "Done"
    },
    "DataQualityGateFailed": {
      "Type": "Fail",
      "Error": "DataQualityGateFailed",
      "Cause": "A data-quality check failed after the backfill; the data-quality Lambda logs name it."
    },
    "Done": {
      "Type": "Pass",
      "Parameters": {"summary.$": "$.report.summary"},
      "End": true
    }
  }
}
```

- [ ] **Step 4: Run the contract test**

Run: `$VENV/pytest tests/unit/test_backfill_state_machine.py -q`
Expected: 4 passed.

- [ ] **Step 5: Validate the definition with AWS (read-only API)**

Run:

```bash
cd <repo> && sed -e 's#${backfill_function_arn}#arn:aws:lambda:eu-central-1:000000000000:function:x#' -e 's#${data_quality_function_arn}#arn:aws:lambda:eu-central-1:000000000000:function:y#' infra/backfill.asl.json > "$SCRATCH/asl.json" && aws stepfunctions validate-state-machine-definition --definition "file://$SCRATCH/asl.json" --type STANDARD --query result --output text
```

Expected: `OK`. If the call is not permitted, record `Task 5: Ruling: ASL validated by the contract test only` and rely on `terraform apply` in deploy.

- [ ] **Step 6: Terraform**

Create `infra/backfill.tf`:

```hcl
# ── Backfill: replay stored raw Beatport runs through the canonicalizer ──
# Started by hand (docs/ops/backfill.md). Ingest stays outside: Step Functions
# keeps every state's input in the execution history, and the Beatport token
# must never be persisted (ADR-0024).

locals {
  backfill_lambda_name = "${local.name_prefix}-backfill"
}

resource "aws_cloudwatch_log_group" "backfill" {
  name              = "/aws/lambda/${local.backfill_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "backfill" {
  name               = "${local.name_prefix}-backfill-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "backfill" {
  statement {
    sid       = "AllowOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.backfill.arn}:*"]
  }
  statement {
    sid    = "AllowRdsDataApi"
    effect = "Allow"
    actions = [
      "rds-data:BeginTransaction",
      "rds-data:CommitTransaction",
      "rds-data:RollbackTransaction",
      "rds-data:ExecuteStatement",
      "rds-data:BatchExecuteStatement",
    ]
    resources = [aws_rds_cluster.aurora.arn]
  }
  statement {
    sid       = "AllowReadDatabaseSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "*")]
  }
  statement {
    sid       = "AllowReadRawReleases"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.raw.arn}/${var.raw_prefix}/*"]
  }
  statement {
    sid       = "AllowEnqueueSpotifySearch"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.spotify_search.arn]
  }
}

resource "aws_iam_role_policy" "backfill" {
  name   = "${local.name_prefix}-backfill-policy"
  role   = aws_iam_role.backfill.id
  policy = data.aws_iam_policy_document.backfill.json
}

resource "aws_lambda_function" "backfill" {
  function_name    = local.backfill_lambda_name
  role             = aws_iam_role.backfill.arn
  runtime          = "python3.12"
  handler          = "collector.backfill_handler.lambda_handler"
  filename         = local.lambda_zip_file
  timeout          = 900
  memory_size      = var.canonicalization_worker_lambda_memory_mb
  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      RAW_BUCKET_NAME          = aws_s3_bucket.raw.bucket
      RAW_PREFIX               = var.raw_prefix
      SPOTIFY_SEARCH_QUEUE_URL = aws_sqs_queue.spotify_search.url
      AURORA_CLUSTER_ARN       = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN        = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE          = var.aurora_database_name
      LOG_LEVEL                = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.backfill]
}

data "aws_iam_policy_document" "states_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "backfill_state_machine" {
  name               = "${local.name_prefix}-backfill-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.states_assume.json
}

data "aws_iam_policy_document" "backfill_state_machine" {
  statement {
    sid     = "AllowInvokeTaskLambdas"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.backfill.arn,
      "${aws_lambda_function.backfill.arn}:*",
      aws_lambda_function.data_quality.arn,
      "${aws_lambda_function.data_quality.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "backfill_state_machine" {
  name   = "${local.name_prefix}-backfill-sfn-policy"
  role   = aws_iam_role.backfill_state_machine.id
  policy = data.aws_iam_policy_document.backfill_state_machine.json
}

resource "aws_sfn_state_machine" "backfill" {
  name     = "${local.name_prefix}-backfill"
  role_arn = aws_iam_role.backfill_state_machine.arn
  definition = templatefile("${path.module}/backfill.asl.json", {
    backfill_function_arn     = aws_lambda_function.backfill.arn
    data_quality_function_arn = aws_lambda_function.data_quality.arn
  })
}
```

Append to `infra/outputs.tf`:

```hcl
output "backfill_state_machine_arn" {
  description = "Backfill state machine (docs/ops/backfill.md)."
  value       = aws_sfn_state_machine.backfill.arn
}
```

Check the raw bucket's encryption first (`grep -n "sse\|kms" infra/*.tf`): with a customer KMS key the Lambda role also needs `kms:Decrypt` on it; with SSE-S3 nothing is added.

- [ ] **Step 7: Format check and commit**

Run: `terraform -chdir=infra fmt -check && echo "terraform fmt -check: clean"`
Expected: `terraform fmt -check: clean` (run `terraform -chdir=infra fmt` first if it lists files, then re-check).

```bash
git add infra/backfill.asl.json infra/backfill.tf infra/outputs.tf tests/unit/test_backfill_state_machine.py
git commit -m "<caveman-commit output: feat(infra): backfill state machine and Lambda>"
```

---

### Task 6: Docs — backfill guide, ADR-0024, canonicalization, runbook

**Files:**
- Create: `docs/ops/backfill.md`, `docs/adr/0024-replayable-canonicalization-backfill.md`
- Modify: `docs/adr/README.md`, `docs/data/canonicalization.md`, `docs/ops/runbook.md`, `docs/architecture.md`, `CLAUDE.md` ("Where things are": add backfill to the Lambda list)

- [ ] **Step 1: Write the failing doc check**

Run:

```bash
cd <repo> && for f in docs/ops/backfill.md docs/adr/0024-replayable-canonicalization-backfill.md; do test -f $f || echo "missing $f"; done; grep -c "0024" docs/adr/README.md; grep -c "observation time\|observed_at" docs/data/canonicalization.md; grep -c "backfill" docs/ops/runbook.md
```

Expected (before): two `missing` lines and three `0`.

- [ ] **Step 2: Write `docs/ops/backfill.md`**

Sections, in this order (no money figures):

1. **Why** — the raw zone holds every ingested week, but re-running it was unsafe (Before), so logic changes reached history only through hand-written SQL or a re-ingest that needs a user's Beatport token per style × week. Backfill makes "re-run the pipeline over what we already have" a safe, previewable command.
2. **Before (2026-10-07)** — table: raw zone 154 Beatport partitions (11 styles, 27.0 MB gzip, 15 overwritten by re-ingests); replay behaviour = the Task 1 before-evidence line (older replay reverts BPM to the older value; same-run replay rewrites `updated_at` on 200/200 tracks); logic changes to history = SQL in migrations (`20260531_30`) or re-ingest; preview = none; 30-day canonicalization = 89 runs, 5 transient failures all recovered by SQS retry, 0 permanent; ingest download max 16.0 s vs the 29 s limit.
3. **What changed** — observation time (`ingest_runs.started_at`) on source/identity rows; guarded source upsert; stale observations fill gaps only; only changed rows written and counted; dry run; backfill Lambda + state machine (ASCII diagram: `Plan → Replay (Map, 2 at a time) → Summarize → [any failed? → ReplayFailed] → [dry run? → Done] → QualityGate → Done | DataQualityGateFailed`).
4. **How to run** — commands:

```bash
SM=$(cd infra && terraform output -raw backfill_state_machine_arn)
# preview everything (dry_run defaults to true)
aws stepfunctions start-execution --state-machine-arn "$SM" --name "dry-$(date +%Y%m%d-%H%M)" --input '{}'
# one style, a date range, applied
aws stepfunctions start-execution --state-machine-arn "$SM" --name "apply-$(date +%Y%m%d-%H%M)" \
  --input '{"dry_run": false, "style_ids": [1], "since": "2026-08-01", "until": "2026-09-30"}'
aws stepfunctions describe-execution --execution-arn <arn> --query '{status:status,start:startDate,stop:stopDate,output:output}'
```

   Input fields: `dry_run` (default `true`), `style_ids`, `since`/`until` (ISO dates on the period end). Output: `summary` with runs, runs_failed, failed_run_ids, tracks_total, *_created, tracks_changed, tracks_stale, track_field_changes. Recovery of a run that never completed: run with `dry_run: false` and its style/week — the replay marks it completed and enqueues the Spotify search.
5. **After** — "Filled from the first production runs": full dry run (duration, counts), apply (duration), dry run again (expected all zero). Leave the table with the three rows and the note "pending first production run".
6. **What it buys** — new logic reaches all history with one command and a preview; no Beatport token or upstream re-fetch needed; order-independent, idempotent replays (tests named); every live run now logs created/changed/stale counts; failed runs recoverable from raw.
7. **Not done, and why** — ingest in Step Functions (token in execution history), asynchronous ingest (max 16 s vs 29 s), version column (full replay is minutes), relation/link diffs (append-only), removals (never deletes); known limit of gap filling (decision 3).

- [ ] **Step 3: Write ADR-0024**

`docs/adr/0024-replayable-canonicalization-backfill.md`, in the format of ADR-0023 (Status: Accepted, Date: 2026-10-07; Context — the Before facts; Options — re-ingest from Beatport / SQL backfills in migrations / replay from the raw zone with event-time writes, and for orchestration: a script / SQS fan-out / Step Functions; Decision — decisions 1–6 of the Spec, Step Functions because a backfill is a bounded, inspectable batch with per-item retries, a concurrency limit and a visible history, and ingest stays out of it because of the token; Consequences — event-time semantics and the gap-filling limit, `updated_at` now means "changed", +1 Data API read per track chunk, a dry run reads as much as an apply, the DQ step is a post-check not a rollback). Add the row `| 0024 | [Replayable canonicalization and Step Functions backfill](0024-replayable-canonicalization-backfill.md) |` to `docs/adr/README.md`.

- [ ] **Step 4: Update the existing docs**

- `docs/data/canonicalization.md`: in "Phase 2 — canonicalize" replace step 3 of the identity list with the new track path (read current row after the source upsert, `track_update`, stale = older observation from another run, gap-fill only, changed rows only, counts); add a "Replays and dry runs" subsection: observation time = `ingest_runs.started_at`, guarded upsert condition verbatim, `Canonicalizer(repo, dry_run=True)`, link to `docs/ops/backfill.md` and ADR-0024.
- `docs/ops/runbook.md`: new section "Reprocess raw data (backfill)" — symptom (logic change needs history; a run stuck in FAILED/RAW_SAVED), fix = dry run then apply via `docs/ops/backfill.md`.
- `docs/architecture.md`: add the backfill Lambda + state machine where the Lambdas/flows are listed (one line, link to `docs/ops/backfill.md`).
- `CLAUDE.md`: add `backfill` to the Lambda list in "Where things are".

- [ ] **Step 5: Verify docs**

Run the Step 1 command again. Expected: no `missing`, three non-zero counts. Then:

```bash
grep -nE '\$[0-9]|USD|руб|cost[s]? \$' docs/ops/backfill.md docs/adr/0024-replayable-canonicalization-backfill.md | wc -l
```

Expected: `0`.

- [ ] **Step 6: Full suite, graph refresh, commit**

Run: `$VENV/pytest -q 2>&1 | tail -3` — Expected: all pass.

```bash
git add docs CLAUDE.md
git commit -m "<caveman-commit output: docs(backfill): guide, ADR-0024, canonicalization replay>"
graphify update . && git add graphify-out && git commit -m "chore(graphify): refresh graph after replayable backfill"
```

---

## After merge (not a task — loop follow-up)

1. Wait for the deploy; verify `aws stepfunctions describe-state-machine --state-machine-arn <arn> --query status` = `ACTIVE` and the `clouder-prod-backfill` Lambda exists.
2. Full dry run (`--input '{}'`), then `describe-execution`: duration (stop − start) and `summary`.
3. Apply (`{"dry_run": false}`) — production writes: if the agent is not permitted, this is an owner checkpoint with the exact command.
4. Dry run again: expected all counts zero (idempotency on production data).
5. Fill "After" in `docs/ops/backfill.md` (docs PR) and the audit status (no money figures).
