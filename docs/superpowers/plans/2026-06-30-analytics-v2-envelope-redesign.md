# Analytics v2 — Envelope Redesign Implementation Plan (Plan 1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the dead dbt analytics layer and redesign the raw `bronze_events` envelope from JSON-string `context`/`props` to typed top-level columns plus a `props_extra` JSON tail, and add the missing `removed_from_category` telemetry event.

**Architecture:** Schema-on-write for the hot fields the dashboard queries (flat typed columns), schema-on-read for the rare tail (`props_extra` JSON). The Firehose JSON→Parquet conversion already reads the Glue table schema, so typing the columns is a Glue + handler-emit change with no Firehose restructuring. Event taxonomy (13 `event_name`s, per-event allowlists) is unchanged.

**Tech Stack:** Python 3 / pydantic (telemetry Lambda), Terraform (Glue + Firehose), Vitest + React (frontend instrumentation), pytest.

**Plan series:** This is Plan 1. Plan 2 = sessionization marts (`fact_session`, `mart_user_daily`). Plan 3 = rollup Lambda + GET routes. Plan 4 = frontend dashboard. Plan F (separate, maintenance window) = beatport→clouder rename. Spec: `docs/superpowers/specs/2026-06-30-analytics-v2-user-daily-design.md`.

**Worktree:** already isolated at `.claude/worktrees/correct_reports`, branch `feat/analytics-v2`. `.venv` lives at the MAIN repo root — call `pytest`/`.venv/bin/python` by absolute main-repo path. `PYTHONPATH=src` is required for non-pytest scripts.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `analytics/dbt/`, `analytics/dbt_runner.py`, `analytics/Dockerfile`, `analytics/requirements.txt`, `analytics/state_machine.asl.json`, `analytics/sat_week_mirror.py`, `analytics/playback_terminal_mirror.py` | dead dbt layer | Delete |
| `infra/analytics_dbt.tf`, `infra/analytics_dbt_runner.tf` | dbt Step Function + container Lambda | Delete |
| `src/collector/telemetry_schemas.py` | envelope validation + flat-shape builder | Modify |
| `src/collector/telemetry_handler.py` | NDJSON emit to Firehose | Modify |
| `infra/telemetry.tf` (Glue `bronze_events`, lines 94-119) | typed bronze columns | Modify |
| `tests/unit/test_telemetry_schemas.py` | schema unit tests | Rewrite affected |
| `tests/unit/test_telemetry_handler.py` | handler unit tests | Rewrite affected |
| `frontend/src/features/categories/components/TrackRowActions.tsx` | category-remove user action | Modify (emit) |
| `frontend/src/features/categories/components/TrackRowActions.telemetry.test.tsx` | emit test | Create |

---

### Task 1: Delete the dead dbt analytics layer

**Files:**
- Delete: `analytics/dbt/` (recursive), `analytics/dbt_runner.py`, `analytics/Dockerfile`, `analytics/requirements.txt`, `analytics/state_machine.asl.json`, `analytics/sat_week_mirror.py`, `analytics/playback_terminal_mirror.py`
- Delete: `infra/analytics_dbt.tf`, `infra/analytics_dbt_runner.tf`

- [ ] **Step 1: Confirm nothing imports the deleted Python modules**

Run: `grep -rnE "dbt_runner|sat_week_mirror|playback_terminal_mirror" src tests analytics infra --include='*.py' --include='*.tf' | grep -v '^analytics/'`
Expected: no output (nothing outside `analytics/` references them).

- [ ] **Step 2: Confirm no other Terraform references the deleted resources**

Run: `grep -rnE "analytics_dbt|dbt_runner|aws_sfn_state_machine|analytics-daily" infra --include='*.tf' | grep -vE 'infra/analytics_dbt\.tf|infra/analytics_dbt_runner\.tf'`
Expected: no output. If any line prints, it is a dangling reference — note it; it must be removed in the same commit.

- [ ] **Step 3: Delete the files**

```bash
git rm -r analytics/dbt analytics/dbt_runner.py analytics/Dockerfile \
  analytics/requirements.txt analytics/state_machine.asl.json \
  analytics/sat_week_mirror.py analytics/playback_terminal_mirror.py \
  infra/analytics_dbt.tf infra/analytics_dbt_runner.tf
```

- [ ] **Step 4: Validate Terraform still parses**

Run: `cd infra && terraform fmt -check && terraform validate`
Expected: `Success! The configuration is valid.` (run `terraform init` first if the backend is not initialized in this worktree). If validate fails on a dangling reference, remove that reference and re-run.

- [ ] **Step 5: Run the unit suite to confirm nothing broke**

Run: `cd /Users/roman/Projects/clouder-projects/clouder-core && pytest -q`
Expected: PASS (telemetry tests still green — they do not touch dbt).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(analytics): delete dbt star-schema layer

Replaced by the raw-layer rollup (analytics v2). Deleting the dbt
silver that read the JSON-string bronze contract unlocks the
envelope redesign in the next commit.
EOF
)"
```

---

### Task 2: Flatten `validate_event` to the typed-hybrid shape

**Files:**
- Modify: `src/collector/telemetry_schemas.py`
- Test: `tests/unit/test_telemetry_schemas.py`

- [ ] **Step 1: Rewrite the affected tests to assert the flat shape**

Replace the body of `tests/unit/test_telemetry_schemas.py` from `def test_valid_event_stamps_user_and_ts` through `def test_props_returned_as_dict_not_stringified` (lines 25-35) with:

```python
def test_valid_event_flattens_context_and_hot_props():
    out = validate_event(_envelope(), user_id="u-1", ts_server=TS_SERVER)
    # context is flattened to typed top-level columns
    assert out["user_id"] == "u-1"
    assert out["device"] == "desktop"
    assert out["route"] == "/curate/:id"
    # envelope unchanged
    assert out["ts_server"] == TS_SERVER
    assert out["event_name"] == "track_view"
    # hot props promoted to top level (no nested "props"/"context" keys)
    assert out["track_id"] == "t1"
    assert out["dwell_ms"] == 1200
    assert "props" not in out
    assert "context" not in out


def test_tail_props_go_to_props_extra():
    ev = _envelope(
        event_name="playback_seek",
        props={"track_id": "t", "from_position_ms": 1, "to_position_ms": 9},
    )
    out = validate_event(ev, user_id="u-1", ts_server=TS_SERVER)
    # track_id is hot -> top level; from/to_position_ms are tail -> props_extra dict
    assert out["track_id"] == "t"
    assert out["props_extra"] == {"from_position_ms": 1, "to_position_ms": 9}


def test_no_props_extra_key_when_tail_empty():
    out = validate_event(_envelope(), user_id="u-1", ts_server=TS_SERVER)
    assert "props_extra" not in out
```

Update `test_client_user_id_in_context_is_ignored_and_server_stamps` (lines 41-45) to read the flat key:

```python
def test_client_user_id_in_context_is_ignored_and_server_stamps():
    ev = _envelope(context={"user_id": "EVIL", "device": "mobile"})
    out = validate_event(ev, user_id="u-real", ts_server=TS_SERVER)
    assert out["user_id"] == "u-real"
    assert "EVIL" not in json.dumps(out)
```

Update `test_secret_and_unknown_props_dropped` (lines 47-51) — props are now flattened, so assert on the flat keys:

```python
def test_secret_and_unknown_props_dropped():
    ev = _envelope(props={"track_id": "t1", "dwell_ms": 5, "access_token": "x", "junk": 1})
    out = validate_event(ev, user_id="u-1", ts_server=TS_SERVER)
    assert out["track_id"] == "t1"
    assert out["dwell_ms"] == 5
    assert "access_token" not in json.dumps(out)
    assert "junk" not in out
```

Update the parametrized `test_each_event_accepts_its_allowlisted_props` (lines 81-86) to assert flattening rather than a `props` dict:

```python
from collector.telemetry_schemas import HOT_PROPS

@pytest.mark.parametrize("event_name", sorted(EVENT_NAMES))
def test_each_event_flattens_into_hot_and_tail(event_name):
    sent = dict(_VALID_PROPS[event_name])
    out = validate_event(
        _envelope(event_name=event_name, props=sent), user_id="u-1", ts_server=TS_SERVER
    )
    extra = out.get("props_extra", {})
    for key, value in sent.items():
        if value is None:
            continue  # None-valued allowlisted props are emitted as absent
        if key in HOT_PROPS:
            assert out[key] == value
        else:
            assert extra[key] == value
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/roman/Projects/clouder-projects/clouder-core && pytest tests/unit/test_telemetry_schemas.py -q`
Expected: FAIL — `ImportError: cannot import name 'HOT_PROPS'` and `KeyError`/assertion errors on the flat keys.

- [ ] **Step 3: Implement the flat shape in `telemetry_schemas.py`**

Add `HOT_PROPS` after `_SECRET_KEYS` (line 72):

```python
# Props promoted to typed top-level Glue columns (queried by the dashboard).
# Everything else allowlisted lands in the props_extra JSON tail.
HOT_PROPS: frozenset[str] = frozenset(
    {
        "track_id",
        "source",
        "action",
        "category_key",
        "surface",
        "decision_ms",
        "dwell_ms",
        "position_ms",
        "duration_ms",
        "listen_through_ratio",
        "seek_count",
        "playlist_id",
        "track_count",
        "source_category_id",
        "session_ms",
    }
)
```

Replace the `return { ... }` block of `validate_event` (lines 115-128) with:

```python
    clean = {
        k: v for k, v in _strip_secrets(env.props).items() if k in allowed
    }
    out: dict[str, Any] = {
        "event_name": env.event_name,
        "event_id": env.event_id,
        "session_id": env.session_id,
        "ts_client": env.ts_client,
        "ts_server": ts_server,
        "user_id": user_id,  # SERVER-STAMPED; client value ignored
        "device": env.context.device,
        "route": env.context.route,
        "app_version": env.context.app_version,
    }
    extra: dict[str, Any] = {}
    for k, v in clean.items():
        if k in HOT_PROPS:
            out[k] = v
        else:
            extra[k] = v
    if extra:
        out["props_extra"] = extra
    return out
```

(Delete the now-dead intermediate `clean_props` assignment at lines 112-114.) Update the module docstring's mention of `props` being serialized to "a JSON string" → "`props_extra` is the only JSON-string column; hot props are typed top-level columns".

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/roman/Projects/clouder-projects/clouder-core && pytest tests/unit/test_telemetry_schemas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/telemetry_schemas.py tests/unit/test_telemetry_schemas.py
git commit -m "$(cat <<'EOF'
refactor(telemetry): flatten envelope to typed hybrid

validate_event now returns flat typed top-level fields (envelope +
context + hot props) plus a props_extra dict for the rare tail,
replacing the nested context/props JSON contract.
EOF
)"
```

---

### Task 3: Emit the flat shape from the handler

**Files:**
- Modify: `src/collector/telemetry_handler.py:104-117`
- Test: `tests/unit/test_telemetry_handler.py`

- [ ] **Step 1: Rewrite the shape-dependent handler tests**

Replace `test_props_serialized_as_json_string_for_glue_column` (lines 76-91) with:

```python
def test_emits_flat_typed_shape_no_nested_context_or_props():
    # bronze_events columns are now typed top-level; only props_extra is a
    # JSON string. track_view has no tail, so no props_extra key.
    fh = _ok_firehose()
    telemetry_handler.lambda_handler(_event([_track_view("a")]), _ctx(), firehose_client=fh)
    line = fh.put_record_batch.call_args.kwargs["Records"][0]["Data"].decode("utf-8")
    record = json.loads(line)
    assert record["track_id"] == "a"
    assert record["dwell_ms"] == 900
    assert record["user_id"] == "u-1"
    assert record["device"] == "desktop"
    assert "props" not in record
    assert "context" not in record
    assert "props_extra" not in record
    # partition + envelope scalars stay top-level
    assert isinstance(record["event_name"], str)
    assert isinstance(record["ts_server"], str)


def test_props_extra_emitted_as_json_string():
    # playback_seek's from/to_position_ms are tail props -> props_extra string.
    fh = _ok_firehose()
    seek = {
        "event_name": "playback_seek",
        "event_id": "ev-seek",
        "session_id": "s1",
        "ts_client": "2026-06-27T10:00:00.000Z",
        "context": {"device": "desktop", "route": "/curate/:id"},
        "props": {"track_id": "t", "from_position_ms": 1, "to_position_ms": 9},
    }
    telemetry_handler.lambda_handler(_event([seek]), _ctx(), firehose_client=fh)
    line = fh.put_record_batch.call_args.kwargs["Records"][0]["Data"].decode("utf-8")
    record = json.loads(line)
    assert record["track_id"] == "t"
    assert isinstance(record["props_extra"], str)
    assert json.loads(record["props_extra"]) == {"from_position_ms": 1, "to_position_ms": 9}
```

Replace `test_user_id_stamped_from_authorizer_not_client` (lines 114-124) with:

```python
def test_user_id_stamped_from_authorizer_not_client():
    fh = _ok_firehose()
    ev = _track_view("a")
    ev["context"]["user_id"] = "CLIENT_SPOOF"
    telemetry_handler.lambda_handler(
        _event([ev], user_id="u-real"), _ctx(), firehose_client=fh
    )
    line = fh.put_record_batch.call_args.kwargs["Records"][0]["Data"].decode("utf-8")
    record = json.loads(line)
    assert record["user_id"] == "u-real"
    assert "CLIENT_SPOOF" not in line
```

(`test_bp_token_never_reaches_firehose` at lines 162-169 stays as-is — it asserts absence, shape-agnostic.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/roman/Projects/clouder-projects/clouder-core && pytest tests/unit/test_telemetry_handler.py -q`
Expected: FAIL — `record["props"]` no longer a string (KeyError) and `record["user_id"]` missing because the handler still emits nested `context`/`props`.

- [ ] **Step 3: Update the handler emit loop**

Replace the per-event body (lines 110-116) of `lambda_handler` with:

```python
        # Hot props are typed top-level columns the OpenX JSON SerDe maps
        # directly; props_extra is the only `string`-typed JSON column.
        if "props_extra" in clean:
            clean["props_extra"] = json.dumps(
                clean["props_extra"], separators=(",", ":")
            )
        line = (json.dumps(clean, separators=(",", ":")) + "\n").encode("utf-8")
        records.append({"Data": line})
```

- [ ] **Step 4: Run the full telemetry suite to verify it passes**

Run: `cd /Users/roman/Projects/clouder-projects/clouder-core && pytest tests/unit/test_telemetry_handler.py tests/unit/test_telemetry_schemas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/telemetry_handler.py tests/unit/test_telemetry_handler.py
git commit -m "$(cat <<'EOF'
feat(telemetry): emit flat typed envelope to firehose

Hot props land on typed bronze columns; only props_extra stays a
JSON string. Drops the nested context/props serialization.
EOF
)"
```

---

### Task 4: Retype the `bronze_events` Glue table

**Files:**
- Modify: `infra/telemetry.tf:94-119`

- [ ] **Step 1: Replace the column definitions**

Replace the six `columns { ... }` blocks (lines 94-119, `event_id` through `props`) with:

```hcl
    columns {
      name = "event_id"
      type = "string"
    }
    columns {
      name = "session_id"
      type = "string"
    }
    columns {
      name = "ts_client"
      type = "string"
    }
    columns {
      name = "ts_server"
      type = "string"
    }
    # flattened context (user_id server-stamped)
    columns {
      name = "user_id"
      type = "string"
    }
    columns {
      name = "device"
      type = "string"
    }
    columns {
      name = "route"
      type = "string"
    }
    columns {
      name = "app_version"
      type = "string"
    }
    # hot props: typed, nullable. Absent keys deserialize to null.
    columns {
      name = "track_id"
      type = "string"
    }
    columns {
      name = "source"
      type = "string"
    }
    columns {
      name = "action"
      type = "string"
    }
    columns {
      name = "category_key"
      type = "string"
    }
    columns {
      name = "surface"
      type = "string"
    }
    columns {
      name = "decision_ms"
      type = "bigint"
    }
    columns {
      name = "dwell_ms"
      type = "bigint"
    }
    columns {
      name = "position_ms"
      type = "bigint"
    }
    columns {
      name = "duration_ms"
      type = "bigint"
    }
    columns {
      name = "listen_through_ratio"
      type = "double"
    }
    columns {
      name = "seek_count"
      type = "int"
    }
    columns {
      name = "playlist_id"
      type = "string"
    }
    columns {
      name = "track_count"
      type = "int"
    }
    columns {
      name = "source_category_id"
      type = "string"
    }
    columns {
      name = "session_ms"
      type = "bigint"
    }
    # ponytail: props_extra is the only JSON-string column. Rare/per-event
    # props live here so adding one needs no Glue migration.
    columns {
      name = "props_extra"
      type = "string"
    }
```

- [ ] **Step 2: Update the stale comment above the block**

Replace the comment at lines 110-111 (`# ponytail: context MUST be string per locked contract...`) — it is removed by Step 1's replacement; confirm no `context`/`props` column comment remains in the table resource.

Run: `grep -nE '"context"|"props"' infra/telemetry.tf`
Expected: no output (the only remaining `props`-prefixed name is `props_extra`).

- [ ] **Step 3: Validate Terraform**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 4: Commit**

```bash
git add infra/telemetry.tf
git commit -m "$(cat <<'EOF'
feat(infra): retype bronze_events to typed hybrid columns

Flat typed columns for envelope/context/hot-props + a single
props_extra JSON-string column, matching the new handler emit.
EOF
)"
```

---

### Task 5: Instrument `removed_from_category` on the frontend

**Files:**
- Modify: `frontend/src/features/categories/components/TrackRowActions.tsx`
- Create: `frontend/src/features/categories/components/TrackRowActions.telemetry.test.tsx`

- [ ] **Step 1: Write the failing emit test**

Create `frontend/src/features/categories/components/TrackRowActions.telemetry.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const track = vi.fn();
vi.mock('../../../lib/telemetry/hooks', () => ({
  useTelemetry: () => ({ track }),
}));

const removeAsync = vi.fn().mockResolvedValue(undefined);
vi.mock('../hooks/useRemoveTrackOptimistic', () => ({
  useRemoveTrackOptimistic: () => ({ mutateAsync: removeAsync }),
}));
vi.mock('../hooks/useAddTrackToCategory', () => ({
  useAddTrackToCategory: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock('../hooks/useMoveTrackBetweenCategories', () => ({
  useMoveTrackBetweenCategories: () => ({ mutateAsync: vi.fn() }),
  MovePartialError: class extends Error {},
}));
vi.mock('../hooks/useCategoriesByStyle', () => ({
  useCategoriesByStyle: () => ({ data: { items: [] } }),
}));

import { renderWithProviders } from '../../../test/renderWithProviders';
import { TrackRowActions } from './TrackRowActions';

describe('TrackRowActions telemetry', () => {
  beforeEach(() => {
    track.mockClear();
    removeAsync.mockClear();
  });

  it('emits removed_from_category on remove', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <TrackRowActions
        track={{ id: 'trk-1' } as never}
        currentCategoryId="cat-9"
        styleId="sty-1"
      />,
    );
    await user.click(screen.getByLabelText(/trigger_aria|actions/i));
    await user.click(await screen.findByText(/remove/i));

    await waitFor(() => expect(removeAsync).toHaveBeenCalled());
    expect(track).toHaveBeenCalledWith('track_categorized', {
      track_id: 'trk-1',
      category_key: 'cat-9',
      action: 'removed_from_category',
    });
  });
});
```

> Note: if `renderWithProviders` does not exist at that path, use the project's standard test wrapper (grep `frontend/src/test` for the helper that wires `MantineProvider` + i18n + `QueryClientProvider`) and adjust the import. The aria label string comes from `t('categories.row_actions.trigger_aria')`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test TrackRowActions.telemetry`
Expected: FAIL — `track` was not called with `removed_from_category` (no emit exists yet).

- [ ] **Step 3: Add the emit to `handleRemove`**

Add the telemetry hook import near the other imports in `TrackRowActions.tsx`:

```tsx
import { useTelemetry } from '../../../lib/telemetry/hooks';
```

Inside the component, near the other hooks (after `const removeMut = useRemoveTrackOptimistic();`, line 36):

```tsx
  const telemetry = useTelemetry();
```

In `handleRemove` (lines 145-165), emit immediately after the successful `mutateAsync` (line 150), before `fireUndoToast`:

```tsx
      await removeMut.mutateAsync({
        categoryId: currentCategoryId,
        trackId: track.id,
      });
      telemetry.track('track_categorized', {
        track_id: track.id,
        category_key: currentCategoryId,
        action: 'removed_from_category',
      });
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm test TrackRowActions.telemetry`
Expected: PASS.

- [ ] **Step 5: Run frontend CI gates**

Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm test TrackRowActions`
Expected: all PASS (vitest alone misses tsc/eslint — both run in CI).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/categories/components/TrackRowActions.tsx \
  frontend/src/features/categories/components/TrackRowActions.telemetry.test.tsx
git commit -m "$(cat <<'EOF'
feat(telemetry): emit removed_from_category on track remove

Instruments the category-remove action so the analytics rollup can
count category deletions (no backend allowlist change: action is an
already-allowed key, values are schema-on-read).
EOF
)"
```

---

### Task 6: Refresh the graphify graph and verify the increment

**Files:** none (regenerates `graphify-out/`)

- [ ] **Step 1: Run the full backend suite**

Run: `cd /Users/roman/Projects/clouder-projects/clouder-core && pytest -q`
Expected: PASS.

- [ ] **Step 2: Confirm no `beatport`-prefixed assumptions were touched**

Run: `grep -rnE "context\[|\"props\"|json_extract" src/collector --include='*.py'`
Expected: no output in the telemetry path (the JSON-string contract is fully gone from the handler).

- [ ] **Step 3: Refresh graphify so the graph reflects the new envelope**

Run: `graphify . --update`
Expected: re-extracts only the changed files (`telemetry_schemas.py`, `telemetry_handler.py`, `TrackRowActions.tsx`). A stale graph mis-answers later queries.

- [ ] **Step 4: Sanity-check the graph picked up the change**

Run: `graphify query "what shape does telemetry validate_event return"`
Expected: the answer references the flat typed fields / `props_extra`, not nested `context`/`props`.

- [ ] **Step 5: Commit the refreshed graph**

```bash
git add graphify-out
git commit -m "$(cat <<'EOF'
chore(graphify): refresh graph after envelope redesign
EOF
)"
```

---

## Self-Review

**Spec coverage (Part A + Part B of the spec):**
- Delete dbt layer → Task 1. ✓ (Frontend old-dashboard deletion is deferred to Plan 4, which replaces it; infra `analytics_dbt*.tf` deleted here.)
- Typed hybrid envelope (flat context + hot props + `props_extra`) → Tasks 2, 3, 4. ✓
- Event taxonomy unchanged → no `EVENT_NAMES`/`PROP_ALLOWLIST` edits. ✓
- `removed_from_category` instrumentation, no backend allowlist change → Task 5. ✓ (`action` already allowlisted for `track_categorized`; values unvalidated.)
- graphify refresh → Task 6. ✓

**Out of scope here (correctly deferred):** sessionization SQL, marts, rollup Lambda, GET routes, dashboard (Plans 2-4); beatport→clouder rename (Plan F). The `_env` fixture's `beatport-prod-telemetry` stream name is left untouched — it is renamed in Plan F.

**Type consistency:** `HOT_PROPS` defined in Task 2 is imported by the Task 2 test and referenced by the same set of keys in the Task 4 Glue columns (`track_id`, `source`, `action`, `category_key`, `surface`, `decision_ms`, `dwell_ms`, `position_ms`, `duration_ms`, `listen_through_ratio`, `seek_count`, `playlist_id`, `track_count`, `source_category_id`, `session_ms`) plus `props_extra`. The handler (Task 3) only special-cases `props_extra` serialization — consistent with the schema builder putting tail keys there.

**Risk note:** `bronze_events` is reset by this schema change (old JSON-string partitions become unreadable under the new typed schema). This is the explicitly-accepted analytics/raw data loss — no migration. Glue partition projection range (`2026-01-01,NOW`) is unchanged, so new typed data lands and reads forward.
