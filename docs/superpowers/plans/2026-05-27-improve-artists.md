# Improve Artists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show artist + label info uniformly in all four track players, and give admins a one-click "search now" button on label/artist detail pages that reuses the registered auto-search settings.

**Architecture:** Frontend changes reuse the existing `ArtistTile`/`LabelTile`/`ArtistsPanel` components; `LabelTile` gains a linkless mode so it works in the playlist player (no `styleId`). Backend adds two thin admin endpoints that read `auto_enrich_config` and enqueue a single-entity run through the existing run-creation + SQS path.

**Tech Stack:** React 19 + Mantine 9 + TanStack Query + vitest/MSW (frontend); Python Lambda + Aurora Data API + SQS + pytest (backend); Terraform + generated OpenAPI.

---

## Spec

`docs/superpowers/specs/2026-05-27-improve-artists-design.md`

## File Structure

Frontend:
- `frontend/src/features/library/components/LabelTile.tsx` — make `styleId` optional, plain-text name when absent (mirrors `ArtistTile`).
- `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx` — render linkless `LabelTile`.
- `frontend/src/features/curate/components/CurateSession.tsx` — render `ArtistsPanel` next to the existing `LabelTile`.
- `frontend/src/features/library/hooks/useEnrichLabelAuto.ts` — new mutation hook.
- `frontend/src/features/library/hooks/useEnrichArtistAuto.ts` — new mutation hook.
- `frontend/src/features/library/components/LabelDetailHeader.tsx` — admin "search now" button.
- `frontend/src/features/library/components/ArtistDetailHeader.tsx` — admin "search now" button.
- `frontend/src/i18n/en.json` — new `library.detail.*` keys.
- `frontend/src/api/schema.d.ts` — regenerated.

Backend / infra:
- `src/collector/label_enrichment/routes.py` — `handle_post_enrich_auto`.
- `src/collector/artist_enrichment/routes.py` — `handle_post_enrich_auto`.
- `src/collector/handler.py` — register + dispatch two new routes.
- `infra/api_gateway.tf` — two new routes.
- `scripts/generate_openapi.py` — two new ROUTES entries.
- `docs/api/openapi.yaml` — regenerated.

Tests:
- `frontend/src/features/library/components/__tests__/LabelTile.test.tsx` — extend.
- `frontend/src/features/curate/components/__tests__/CurateSession.artists.test.tsx` — new.
- `frontend/src/features/playlists/components/__tests__/PlaylistPlayerPanel.test.tsx` — extend.
- `frontend/src/features/library/hooks/__tests__/useEnrichLabelAuto.test.tsx` — new.
- `frontend/src/features/library/hooks/__tests__/useEnrichArtistAuto.test.tsx` — new.
- `tests/unit/test_label_enrichment_enrich_auto.py` — new.
- `tests/unit/test_artist_enrichment_enrich_auto.py` — new.

## Conventions (read before starting)

- In a worktree the `.venv` lives at the **main repo root**, not the worktree. Call `pytest` and `.venv/bin/python` by absolute main-repo path. `pytest.ini` sets `PYTHONPATH=src`; for `scripts/*` export `PYTHONPATH=src`.
- Frontend commands run from `frontend/`. `pnpm test` is jsdom (no CSS); `pnpm test:browser` is Playwright (run locally for visual checks).
- Commits go through `caveman:caveman-commit`, then `git commit`. Conventional Commits. No AI-attribution trailer.

---

## Part A — Frontend player parity (gaps 1 & 2)

### Task A1: `LabelTile` linkless mode

**Files:**
- Modify: `frontend/src/features/library/components/LabelTile.tsx`
- Test: `frontend/src/features/library/components/__tests__/LabelTile.test.tsx`

- [ ] **Step 1: Add a failing test for the linkless render**

Append to `LabelTile.test.tsx` (the existing `renderTile` always passes `styleId="dnb"`; add a variant without it):

```tsx
function renderTileNoStyle(labelId: string | null, labelName: string | null = null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter>
            <LabelTile labelId={labelId} labelName={labelName} />
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

it('renders the name as plain text (no link) when styleId is absent', () => {
  renderTileNoStyle('hanging', 'Linkless Label');
  expect(screen.getByText('Linkless Label')).toBeInTheDocument();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^like label$/i })).toBeInTheDocument();
});

it('renders the name as a link when styleId is present', async () => {
  server.use(
    http.get('http://localhost/labels/linked', () =>
      HttpResponse.json({ label_name: 'Linked', my_preference: null }),
    ),
  );
  renderTile('linked', 'fallback');
  await waitFor(() => expect(screen.getByText('Linked')).toBeInTheDocument());
  expect(screen.getByRole('link', { name: 'Linked' })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test, verify it fails**

Run (from `frontend/`): `pnpm test -- LabelTile`
Expected: FAIL — the linkless test finds a `link` role (current code always renders an `<Anchor>`), and the type-check/test errors because `styleId` is required.

- [ ] **Step 3: Make `styleId` optional and branch the name node**

In `LabelTile.tsx`, change the Props interface (line 9-13):

```tsx
interface Props {
  labelId: string | null | undefined;
  labelName?: string | null | undefined;
  /** Present on bucket/category/curate players → name links to detail. Absent on playlists. */
  styleId?: string;
}
```

Change the signature (line 31) and remove the unconditional `detailUrl` (line 38):

```tsx
export function LabelTile({ labelId, labelName, styleId }: Props) {
```

Replace the name `<Anchor>` (lines 70-73) with a `styleId` branch (mirrors `ArtistTile.tsx` lines 67-75):

```tsx
        {styleId ? (
          <Anchor component={Link} to={`/library/${styleId}/labels/${labelId}`} fw={600} size="lg">
            {displayName || labelId}
          </Anchor>
        ) : (
          <Text fw={600} size="lg">
            {displayName || labelId}
          </Text>
        )}
```

Delete the now-unused `const detailUrl = ...;` line.

- [ ] **Step 4: Run the test, verify it passes**

Run (from `frontend/`): `pnpm test -- LabelTile`
Expected: PASS (all LabelTile tests, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/library/components/LabelTile.tsx frontend/src/features/library/components/__tests__/LabelTile.test.tsx
git commit -m "feat(library): support linkless LabelTile without styleId"
```

---

### Task A2: Playlist player renders a linkless `LabelTile`

**Files:**
- Modify: `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx`
- Test: `frontend/src/features/playlists/components/__tests__/PlaylistPlayerPanel.test.tsx`

- [ ] **Step 1: Add a failing test**

Open the existing `PlaylistPlayerPanel.test.tsx` and reuse its render harness (it already mounts the panel with a playing track via mocked playback). Add a test that a track carrying a label renders the label name. Use the same `items` fixture shape the existing tests use (a `PlaylistTrack` with `label: { id, name }`). Add:

```tsx
it('renders the label tile (linkless) for the playing track', async () => {
  // Arrange the same way the existing "renders label/BPM" test does:
  // mount with a current track whose items entry has label { id, name }.
  renderPanelWithPlayingTrack({
    track_id: 't1',
    label: { id: 'lbl-1', name: 'Fokuz Recordings' },
    artists: [{ id: 'a1', name: 'Joja' }],
    // ...other PlaylistTrack fields as in the existing fixtures
  });
  expect(await screen.findByText('Fokuz Recordings')).toBeInTheDocument();
  // Linkless: the label name is not a router link.
  expect(screen.queryByRole('link', { name: 'Fokuz Recordings' })).not.toBeInTheDocument();
});
```

> Use the existing file's helper (e.g. `renderPanelWithPlayingTrack` / the test's own setup) and fixture fields verbatim — do not invent a new harness. The only new assertions are the two `expect(...)` lines above.

- [ ] **Step 2: Run the test, verify it fails**

Run (from `frontend/`): `pnpm test -- PlaylistPlayerPanel`
Expected: FAIL — `Fokuz Recordings` not found (panel renders the label only inside the `PlayerCard` meta row text, which the existing fixture may not populate; the dedicated `LabelTile` is absent).

- [ ] **Step 3: Render the `LabelTile`**

In `PlaylistPlayerPanel.tsx`, add the import (top of file, near line 13):

```tsx
import { LabelTile } from '../../library/components/LabelTile';
```

Replace the "No LabelTile here" comment block (lines 231-235) with:

```tsx
      <LabelTile
        labelId={effectiveRich?.label?.id ?? null}
        labelName={effectiveRich?.label?.name ?? null}
      />
```

(`ArtistsPanel` on line 236 stays exactly as is — no `styleId`, so artist names remain plain text, matching the label tile.)

- [ ] **Step 4: Run the test, verify it passes**

Run (from `frontend/`): `pnpm test -- PlaylistPlayerPanel`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx frontend/src/features/playlists/components/__tests__/PlaylistPlayerPanel.test.tsx
git commit -m "feat(playlists): show label tile in the playlist player"
```

---

### Task A3: Curate player renders an `ArtistsPanel`

**Files:**
- Modify: `frontend/src/features/curate/components/CurateSession.tsx`
- Test: `frontend/src/features/curate/components/__tests__/CurateSession.artists.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Mirror the existing analog `frontend/src/features/triage/components/__tests__/BucketPlayerPanel.artists.test.tsx` (it mounts a player and asserts the artist tile) and the harness in `frontend/src/features/curate/components/__tests__/CurateSession.test.tsx` (for how `CurateSession` is rendered with a mocked `useCurateSession`). Create `CurateSession.artists.test.tsx`:

```tsx
// Reuse the exact provider wrapper + useCurateSession mock from CurateSession.test.tsx.
// The mocked session's currentTrack must include:
//   artists: [{ id: 'a1', name: 'Joja', role: 'main' }]
// Then assert the artist tile renders the name + a like button.
it('renders the artist tile for the current track', async () => {
  renderCurateSessionWithTrack({
    // ...currentTrack fields as in CurateSession.test.tsx, plus:
    artists: [{ id: 'a1', name: 'Joja', role: 'main' }],
    label_id: null,
    label_name: null,
  });
  expect(await screen.findByText('Joja')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^like artist$/i })).toBeInTheDocument();
});
```

> Copy the provider wrapper and `useCurateSession` mock verbatim from `CurateSession.test.tsx`. `ArtistsPanel` is desktop-only here; if that test renders mobile by default, set the viewport to desktop the same way `BucketPlayerPanel.artists.test.tsx` does (it exercises the same desktop side panel).

- [ ] **Step 2: Run the test, verify it fails**

Run (from `frontend/`): `pnpm test -- CurateSession.artists`
Expected: FAIL — `Joja` not found; `CurateSession` renders no artist tile today.

- [ ] **Step 3: Render the `ArtistsPanel`**

In `CurateSession.tsx`, add the import near the existing `LabelTile` import:

```tsx
import { ArtistsPanel } from '../../library/components/ArtistsPanel';
```

In the desktop-only side panel (the `!isMobile` block, lines 327-342), add the panel directly below the existing `<LabelTile ... />` (still inside the same `<div>`):

```tsx
        <ArtistsPanel
          artists={session.currentTrack?.artists ?? []}
          styleId={styleId}
        />
```

- [ ] **Step 4: Run the test, verify it passes**

Run (from `frontend/`): `pnpm test -- CurateSession`
Expected: PASS (the new artists test and the existing `CurateSession.test.tsx`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/curate/components/CurateSession.tsx frontend/src/features/curate/components/__tests__/CurateSession.artists.test.tsx
git commit -m "feat(curate): show artist tile in the curate player"
```

---

## Part B — Admin "search now" backend (gap 3)

### Task B1: Label `handle_post_enrich_auto`

**Files:**
- Modify: `src/collector/label_enrichment/routes.py`
- Test: `tests/unit/test_label_enrichment_enrich_auto.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_label_enrichment_enrich_auto.py` (mirrors `tests/unit/test_label_enrichment_api.py`):

```python
import json
from unittest.mock import MagicMock

import pytest

from collector.handler import lambda_handler

_ROUTE = "POST /admin/labels/{label_id}/enrich-auto"


def _admin_event(label_id: str) -> dict:
    return {
        "routeKey": _ROUTE,
        "body": None,
        "pathParameters": {"label_id": label_id},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True, "user_id": "user-1"}}},
    }


_CONFIG = {
    "kind": "labels",
    "enabled": False,
    "vendors": ["gemini", "openai", "tavily_deepseek"],
    "models": {
        "gemini": "gemini-3-flash-preview",
        "openai": "gpt-5.4-mini",
        "tavily_deepseek": "deepseek-v4-flash",
    },
    "prompt_slug": "label_v3_app_fields",
    "prompt_version": "v1",
    "merge_vendor": "deepseek",
    "merge_model": "deepseek-v4-flash",
}


@pytest.fixture
def patched(monkeypatch):
    repo = MagicMock()
    repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Fokuz"}
    repo.derive_style_for_label.return_value = "dnb"
    repo.create_run.return_value = "run-1"
    auto = MagicMock()
    auto.get_config.return_value = dict(_CONFIG)
    sqs = MagicMock()
    monkeypatch.setattr("collector.label_enrichment.routes._build_repository", lambda: repo)
    monkeypatch.setattr("collector.label_enrichment.routes._build_auto_repository", lambda: auto)
    monkeypatch.setattr("collector.label_enrichment.routes._build_sqs_client", lambda: sqs)
    monkeypatch.setenv("LABEL_ENRICHMENT_QUEUE_URL", "https://sqs.example/q")
    yield repo, auto, sqs


def test_enrich_auto_enqueues_with_config_settings(patched):
    repo, auto, sqs = patched
    resp = lambda_handler(_admin_event("lbl-1"), None)
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body == {"run_id": "run-1", "queued_labels": 1}
    auto.get_config.assert_called_once_with("labels")
    spec = repo.create_run.call_args[0][0]
    assert spec.vendors == _CONFIG["vendors"]
    assert spec.prompt_slug == "label_v3_app_fields"
    assert spec.requested_labels == 1
    assert spec.created_by_user_id == "user-1"
    sqs.send_message.assert_called_once()
    msg = json.loads(sqs.send_message.call_args.kwargs["MessageBody"])
    assert msg == {"run_id": "run-1", "label_id": "lbl-1", "label_name": "Fokuz", "style": "dnb"}


def test_enrich_auto_404_when_label_missing(patched):
    repo, _auto, _sqs = patched
    repo.get_label_by_id.return_value = None
    resp = lambda_handler(_admin_event("nope"), None)
    assert resp["statusCode"] == 404


def test_enrich_auto_409_when_no_config(patched):
    _repo, auto, _sqs = patched
    auto.get_config.return_value = None
    resp = lambda_handler(_admin_event("lbl-1"), None)
    assert resp["statusCode"] == 409


def test_enrich_auto_rejects_non_admin(patched):
    event = _admin_event("lbl-1")
    event["requestContext"]["authorizer"]["lambda"]["is_admin"] = False
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 403
```

- [ ] **Step 2: Run the test, verify it fails**

Run (absolute main-repo path): `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_label_enrichment_enrich_auto.py -q`
Expected: FAIL — route is unknown (`404`/no dispatch) and `_build_auto_repository` does not exist yet.

- [ ] **Step 3: Add the helper + handler**

In `src/collector/label_enrichment/routes.py`, add the import (near line 21):

```python
from .auto_repository import AutoEnrichRepository
```

Add a builder beside `_build_repository` (after line 33):

```python
def _build_auto_repository() -> AutoEnrichRepository:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return AutoEnrichRepository(data_api=client)
```

Add the handler (after `handle_post_enrich`, near line 126):

```python
def handle_post_enrich_auto(event: Mapping[str, Any]) -> tuple[int, dict]:
    """Admin: enqueue one label using the registered auto-search settings."""
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")

    repo = _build_repository()
    row = repo.get_label_by_id(label_id)
    if row is None:
        return 404, {"error_code": "label_not_found", "message": "label not found"}

    cfg = _build_auto_repository().get_config("labels")
    if not cfg or not cfg.get("vendors") or not cfg.get("prompt_slug") \
            or not cfg.get("prompt_version") or not cfg.get("merge_vendor") \
            or not cfg.get("merge_model"):
        return 409, {
            "error_code": "auto_config_missing",
            "message": "auto-enrich config is not set up",
        }

    spec = RunSpec(
        prompt_slug=cfg["prompt_slug"],
        prompt_version=cfg["prompt_version"],
        vendors=list(cfg["vendors"]),
        models=dict(cfg.get("models") or {}),
        merge_vendor=cfg["merge_vendor"],
        merge_model=cfg["merge_model"],
        requested_labels=1,
        created_by_user_id=_extract_user_id(event),
    )
    run_id = repo.create_run(spec)

    style = repo.derive_style_for_label(label_id) or "music"
    sqs = _build_sqs_client()
    sqs.send_message(
        QueueUrl=_queue_url(),
        MessageBody=json.dumps({
            "run_id": run_id,
            "label_id": label_id,
            "label_name": row["name"],
            "style": style,
        }),
    )
    return 202, {"run_id": run_id, "queued_labels": 1}
```

> Note: the route is not wired into the dispatcher yet (Task B3). Steps 4 below run after B3. Proceed to B2 and B3, then return here to verify, or run the verify command at the end of B3. To keep TDD tight, the simplest order is B1 (code) → B2 (code) → B3 (wire + run B1/B2 tests). The checkbox for "verify pass" lives in B3.

- [ ] **Step 4: Commit (code only; tests verified in B3)**

```bash
git add src/collector/label_enrichment/routes.py tests/unit/test_label_enrichment_enrich_auto.py
git commit -m "feat(enrichment): add label enrich-auto handler"
```

---

### Task B2: Artist `handle_post_enrich_auto`

**Files:**
- Modify: `src/collector/artist_enrichment/routes.py`
- Test: `tests/unit/test_artist_enrichment_enrich_auto.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_artist_enrichment_enrich_auto.py`:

```python
import json
from unittest.mock import MagicMock

import pytest

from collector.handler import lambda_handler

_ROUTE = "POST /admin/artists/{artist_id}/enrich-auto"


def _admin_event(artist_id: str) -> dict:
    return {
        "routeKey": _ROUTE,
        "body": None,
        "pathParameters": {"artist_id": artist_id},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True, "user_id": "user-1"}}},
    }


_CONFIG = {
    "kind": "artists",
    "enabled": False,
    "vendors": ["gemini", "openai", "tavily_deepseek"],
    "models": {
        "gemini": "gemini-3-flash-preview",
        "openai": "gpt-5.4-mini",
        "tavily_deepseek": "deepseek-v4-flash",
    },
    "prompt_slug": "artist_v1_facts",
    "prompt_version": "v1",
    "merge_vendor": "deepseek",
    "merge_model": "deepseek-v4-flash",
}


@pytest.fixture
def patched(monkeypatch):
    repo = MagicMock()
    repo.get_artist_by_id.return_value = {"id": "art-1", "name": "Joja"}
    repo.create_run.return_value = "run-1"
    auto = MagicMock()
    auto.get_config.return_value = dict(_CONFIG)
    sqs = MagicMock()
    monkeypatch.setattr("collector.artist_enrichment.routes._build_repository", lambda: repo)
    monkeypatch.setattr("collector.artist_enrichment.routes._build_auto_repository", lambda: auto)
    monkeypatch.setattr("collector.artist_enrichment.routes._build_sqs_client", lambda: sqs)
    monkeypatch.setenv("ARTIST_ENRICHMENT_QUEUE_URL", "https://sqs.example/q")
    yield repo, auto, sqs


def test_enrich_auto_enqueues_with_config_settings(patched):
    repo, auto, sqs = patched
    resp = lambda_handler(_admin_event("art-1"), None)
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body == {"run_id": "run-1", "queued_artists": 1}
    auto.get_config.assert_called_once_with("artists")
    spec = repo.create_run.call_args[0][0]
    assert spec.requested_artists == 1
    assert spec.created_by_user_id == "user-1"
    msg = json.loads(sqs.send_message.call_args.kwargs["MessageBody"])
    assert msg == {"run_id": "run-1", "artist_id": "art-1", "artist_name": "Joja"}


def test_enrich_auto_404_when_artist_missing(patched):
    repo, _auto, _sqs = patched
    repo.get_artist_by_id.return_value = None
    resp = lambda_handler(_admin_event("nope"), None)
    assert resp["statusCode"] == 404


def test_enrich_auto_409_when_no_config(patched):
    _repo, auto, _sqs = patched
    auto.get_config.return_value = None
    resp = lambda_handler(_admin_event("art-1"), None)
    assert resp["statusCode"] == 409
```

> Confirm the real artist prompt slug from `src/collector/artist_enrichment/prompts/` and use it in `_CONFIG["prompt_slug"]` if `artist_v1_facts` is not the actual slug. The handler does not validate the slug against the prompt registry (unlike the manual enrich), so any non-empty string passes; the test value only needs to be non-empty.

- [ ] **Step 2: Run the test, verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_artist_enrichment_enrich_auto.py -q`
Expected: FAIL — route unknown and `_build_auto_repository` missing.

- [ ] **Step 3: Add the helper + handler**

In `src/collector/artist_enrichment/routes.py`, add the import (near line 21):

```python
from .auto_repository import AutoEnrichRepository
```

Add the builder (after line 33):

```python
def _build_auto_repository() -> AutoEnrichRepository:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return AutoEnrichRepository(data_api=client)
```

Add the handler (after `handle_post_enrich`, near line 117):

```python
def handle_post_enrich_auto(event: Mapping[str, Any]) -> tuple[int, dict]:
    """Admin: enqueue one artist using the registered auto-search settings."""
    path = event.get("pathParameters") or {}
    artist_id = (path.get("artist_id") or "").strip()
    if not artist_id:
        raise ValidationError("artist_id is required")

    repo = _build_repository()
    row = repo.get_artist_by_id(artist_id)
    if row is None:
        return 404, {"error_code": "artist_not_found", "message": "artist not found"}

    cfg = _build_auto_repository().get_config("artists")
    if not cfg or not cfg.get("vendors") or not cfg.get("prompt_slug") \
            or not cfg.get("prompt_version") or not cfg.get("merge_vendor") \
            or not cfg.get("merge_model"):
        return 409, {
            "error_code": "auto_config_missing",
            "message": "auto-enrich config is not set up",
        }

    spec = RunSpec(
        prompt_slug=cfg["prompt_slug"],
        prompt_version=cfg["prompt_version"],
        vendors=list(cfg["vendors"]),
        models=dict(cfg.get("models") or {}),
        merge_vendor=cfg["merge_vendor"],
        merge_model=cfg["merge_model"],
        requested_artists=1,
        created_by_user_id=_extract_user_id(event),
    )
    run_id = repo.create_run(spec)

    sqs = _build_sqs_client()
    sqs.send_message(
        QueueUrl=_queue_url(),
        MessageBody=json.dumps({
            "run_id": run_id,
            "artist_id": artist_id,
            "artist_name": row["name"],
        }),
    )
    return 202, {"run_id": run_id, "queued_artists": 1}
```

- [ ] **Step 4: Commit (code only; tests verified in B3)**

```bash
git add src/collector/artist_enrichment/routes.py tests/unit/test_artist_enrichment_enrich_auto.py
git commit -m "feat(enrichment): add artist enrich-auto handler"
```

---

### Task B3: Register + dispatch the two routes

**Files:**
- Modify: `src/collector/handler.py`

- [ ] **Step 1: Add the route keys to `_ADMIN_ROUTES`**

In `src/collector/handler.py`, inside the `_ADMIN_ROUTES` frozenset (lines 60-84), add two members:

```python
    "POST /admin/labels/{label_id}/enrich-auto",
    "POST /admin/artists/{artist_id}/enrich-auto",
```

(Place the label one near line 66 with the other label routes and the artist one near line 75 with the artist routes — ordering inside a frozenset is irrelevant, but keep it readable.)

- [ ] **Step 2: Add dispatch blocks**

After the `POST /admin/labels/enrich` dispatch block (lines 170-173), add:

```python
    if route_key == "POST /admin/labels/{label_id}/enrich-auto":
        from .label_enrichment.routes import handle_post_enrich_auto
        status, body = handle_post_enrich_auto(event)
        return _json_response(status, body, correlation_id)
```

After the `POST /admin/artists/enrich` dispatch block (lines 234-237), add:

```python
    if route_key == "POST /admin/artists/{artist_id}/enrich-auto":
        from .artist_enrichment.routes import handle_post_enrich_auto
        status, body = handle_post_enrich_auto(event)
        return _json_response(status, body, correlation_id)
```

- [ ] **Step 3: Run the B1 + B2 tests, verify they pass**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_label_enrichment_enrich_auto.py tests/unit/test_artist_enrichment_enrich_auto.py -q`
Expected: PASS (all cases — 202, 404, 409, 403).

- [ ] **Step 4: Run the full backend suite**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/collector/handler.py
git commit -m "feat(api): route admin label/artist enrich-auto endpoints"
```

---

### Task B4: Terraform routes + OpenAPI + regenerate

**Files:**
- Modify: `infra/api_gateway.tf`
- Modify: `scripts/generate_openapi.py`
- Regenerate: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`

- [ ] **Step 1: Add the two API Gateway routes**

In `infra/api_gateway.tf`, after the `labels_enrich_post` resource (lines 113-119) add:

```hcl
resource "aws_apigatewayv2_route" "labels_enrich_auto_post" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /admin/labels/{label_id}/enrich-auto"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

After the `artists_enrich_post` resource (lines 217-223) add:

```hcl
resource "aws_apigatewayv2_route" "artists_enrich_auto_post" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /admin/artists/{artist_id}/enrich-auto"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 2: Add the two OpenAPI ROUTES entries**

In `scripts/generate_openapi.py`, after the `/admin/labels/enrich` entry (ends line 1453) add:

```python
    {
        "method": "post",
        "path": "/admin/labels/{label_id}/enrich-auto",
        "auth": ADMIN,
        "summary": "Admin: enqueue one label using saved auto-search settings.",
        "description": (
            "Reads the registered auto-enrich config for labels, creates a run, "
            "and enqueues this label onto the label-enrichment SQS queue. Returns "
            "202 with the run id. 409 if no auto-enrich config is set up."
        ),
        "responses": {
            "202": _make_response(
                202,
                "Enrichment run accepted and queued.",
                LABEL_ENRICH_ACCEPTED_RESPONSE,
            ),
            "404": _error(404, "label_not_found."),
            "409": _error(409, "auto_config_missing."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
```

After the `/admin/artists/enrich` entry (the block using `ARTIST_ENRICH_ACCEPTED_RESPONSE`, near line 2913) add:

```python
    {
        "method": "post",
        "path": "/admin/artists/{artist_id}/enrich-auto",
        "auth": ADMIN,
        "summary": "Admin: enqueue one artist using saved auto-search settings.",
        "description": (
            "Reads the registered auto-enrich config for artists, creates a run, "
            "and enqueues this artist onto the artist-enrichment SQS queue. Returns "
            "202 with the run id. 409 if no auto-enrich config is set up."
        ),
        "responses": {
            "202": _make_response(
                202,
                "Enrichment run accepted and queued.",
                ARTIST_ENRICH_ACCEPTED_RESPONSE,
            ),
            "404": _error(404, "artist_not_found."),
            "409": _error(409, "auto_config_missing."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
```

- [ ] **Step 3: Regenerate the OpenAPI doc**

Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python scripts/generate_openapi.py`
Expected: `docs/api/openapi.yaml` updated; `git diff --stat` shows the two new paths.

- [ ] **Step 4: Regenerate the frontend schema types**

Run (from `frontend/`): `pnpm run gen:api` (or the script in `frontend/package.json` that produces `src/api/schema.d.ts` from `docs/api/openapi.yaml`).
Expected: `frontend/src/api/schema.d.ts` updated with the two new operations. (If unsure of the script name, check `frontend/package.json` "scripts".)

- [ ] **Step 5: Commit**

```bash
git add infra/api_gateway.tf scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts
git commit -m "feat(api): expose label/artist enrich-auto in gateway + openapi"
```

---

## Part C — Admin "search now" frontend (gap 3)

### Task C1: Mutation hooks

**Files:**
- Create: `frontend/src/features/library/hooks/useEnrichLabelAuto.ts`
- Create: `frontend/src/features/library/hooks/useEnrichArtistAuto.ts`
- Test: `frontend/src/features/library/hooks/__tests__/useEnrichLabelAuto.test.tsx` (new)
- Test: `frontend/src/features/library/hooks/__tests__/useEnrichArtistAuto.test.tsx` (new)

- [ ] **Step 1: Write the failing test for the label hook**

Create `useEnrichLabelAuto.test.tsx` (mirror the harness in `useSetLabelPreference.test.tsx`, which wraps `renderHook` with a `QueryClientProvider` and uses MSW):

```tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useEnrichLabelAuto } from '../useEnrichLabelAuto';

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </I18nextProvider>
  );
}

describe('useEnrichLabelAuto', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs to the enrich-auto endpoint and resolves with the run id', async () => {
    let hit = '';
    server.use(
      http.post('http://localhost/admin/labels/:id/enrich-auto', ({ params }) => {
        hit = String(params.id);
        return HttpResponse.json({ run_id: 'run-1', queued_labels: 1 }, { status: 202 });
      }),
    );
    const { result } = renderHook(() => useEnrichLabelAuto(), { wrapper });
    result.current.mutate({ labelId: 'lbl-1' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(hit).toBe('lbl-1');
    expect(result.current.data).toEqual({ run_id: 'run-1', queued_labels: 1 });
  });
});
```

- [ ] **Step 2: Run it, verify it fails**

Run (from `frontend/`): `pnpm test -- useEnrichLabelAuto`
Expected: FAIL — module `useEnrichLabelAuto` does not exist.

- [ ] **Step 3: Implement both hooks**

Create `frontend/src/features/library/hooks/useEnrichLabelAuto.ts`:

```ts
import { useMutation } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';

interface Accepted {
  run_id: string;
  queued_labels: number;
}

export function useEnrichLabelAuto() {
  const { t } = useTranslation();
  return useMutation<Accepted, Error, { labelId: string }>({
    mutationFn: ({ labelId }) =>
      api<Accepted>(`/admin/labels/${labelId}/enrich-auto`, { method: 'POST' }),
    onSuccess: () => {
      notifications.show({ message: t('library.detail.admin_search_queued') });
    },
    onError: (err) => {
      const msg =
        err instanceof ApiError && err.status === 409
          ? t('library.detail.admin_search_not_configured')
          : t('library.detail.admin_search_failed');
      notifications.show({ color: 'red', message: msg });
    },
  });
}
```

Create `frontend/src/features/library/hooks/useEnrichArtistAuto.ts`:

```ts
import { useMutation } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';

interface Accepted {
  run_id: string;
  queued_artists: number;
}

export function useEnrichArtistAuto() {
  const { t } = useTranslation();
  return useMutation<Accepted, Error, { artistId: string }>({
    mutationFn: ({ artistId }) =>
      api<Accepted>(`/admin/artists/${artistId}/enrich-auto`, { method: 'POST' }),
    onSuccess: () => {
      notifications.show({ message: t('library.detail.admin_search_queued') });
    },
    onError: (err) => {
      const msg =
        err instanceof ApiError && err.status === 409
          ? t('library.detail.admin_search_not_configured')
          : t('library.detail.admin_search_failed');
      notifications.show({ color: 'red', message: msg });
    },
  });
}
```

- [ ] **Step 4: Add the artist-hook test, run both, verify pass**

Create `useEnrichArtistAuto.test.tsx` identical to the label test but POSTing to `http://localhost/admin/artists/:id/enrich-auto`, returning `{ run_id: 'run-1', queued_artists: 1 }`, calling `result.current.mutate({ artistId: 'art-1' })`, asserting `result.current.data` equals `{ run_id: 'run-1', queued_artists: 1 }`.

Run (from `frontend/`): `pnpm test -- useEnrichLabelAuto useEnrichArtistAuto`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/library/hooks/useEnrichLabelAuto.ts frontend/src/features/library/hooks/useEnrichArtistAuto.ts frontend/src/features/library/hooks/__tests__/useEnrichLabelAuto.test.tsx frontend/src/features/library/hooks/__tests__/useEnrichArtistAuto.test.tsx
git commit -m "feat(library): add enrich-auto mutation hooks"
```

---

### Task C2: Admin button in detail headers + i18n

**Files:**
- Modify: `frontend/src/i18n/en.json`
- Modify: `frontend/src/features/library/components/LabelDetailHeader.tsx`
- Modify: `frontend/src/features/library/components/ArtistDetailHeader.tsx`
- Test: extend `frontend/src/features/library/routes/__tests__/ArtistDetailPage.test.tsx` (or a new header test)

- [ ] **Step 1: Add i18n keys**

In `frontend/src/i18n/en.json`, inside the `library.detail` object (after line 889, before the closing brace at 890) add:

```json
      "ai_reasoning_missing": "No reasoning available.",
      "admin_search_now": "Search now",
      "admin_search_queued": "Search queued.",
      "admin_search_failed": "Could not start the search.",
      "admin_search_not_configured": "Auto-search is not configured yet."
```

(The first line already exists — replace its trailing comma situation accordingly: the existing `"ai_reasoning_missing"` is the last key, so change its line to end with a comma and append the four new keys.)

- [ ] **Step 2: Write a failing test for the admin button**

Add to `ArtistDetailPage.test.tsx` (it already renders the detail page with auth + MSW). Add two cases — button hidden for non-admin, present + clickable for admin. Reuse the file's existing auth setup helper (it controls `is_admin`):

```tsx
it('shows no "Search now" button for non-admins', async () => {
  renderArtistDetail({ isAdmin: false }); // use the file's existing render+auth helper
  await screen.findByRole('heading', { level: 2 });
  expect(screen.queryByRole('button', { name: /search now/i })).not.toBeInTheDocument();
});

it('shows a working "Search now" button for admins', async () => {
  let posted = false;
  server.use(
    http.post('http://localhost/admin/artists/:id/enrich-auto', () => {
      posted = true;
      return HttpResponse.json({ run_id: 'run-1', queued_artists: 1 }, { status: 202 });
    }),
  );
  renderArtistDetail({ isAdmin: true });
  const btn = await screen.findByRole('button', { name: /search now/i });
  await userEvent.click(btn);
  await waitFor(() => expect(posted).toBe(true));
});
```

> Use the file's existing render helper and the way it injects `is_admin` (via the auth provider / `getAuthSnapshot`). If the file mounts with a fixed admin state, add a small param to toggle `is_admin` the same way other auth-dependent tests in the repo do.

- [ ] **Step 3: Run it, verify it fails**

Run (from `frontend/`): `pnpm test -- ArtistDetailPage`
Expected: FAIL — no "Search now" button exists.

- [ ] **Step 4: Add the button to `ArtistDetailHeader`**

In `ArtistDetailHeader.tsx`, add imports:

```tsx
import { Button } from '@mantine/core';
import { useAuth } from '../../../auth/useAuth';
import { useEnrichArtistAuto } from '../hooks/useEnrichArtistAuto';
```

Inside the component, after `const { t } = useTranslation();` (line 16):

```tsx
  const { state } = useAuth();
  const isAdmin = state.status === 'authenticated' && state.user.is_admin;
  const enrich = useEnrichArtistAuto();
```

In the title `Group` (lines 35-39), after `<ArtistPreferenceButtons .../>` add:

```tsx
        {isAdmin && (
          <Button
            size="xs"
            variant="light"
            loading={enrich.isPending}
            onClick={() => enrich.mutate({ artistId })}
          >
            {t('library.detail.admin_search_now')}
          </Button>
        )}
```

- [ ] **Step 5: Add the button to `LabelDetailHeader`**

In `LabelDetailHeader.tsx`, add the same imports (use `useEnrichLabelAuto`):

```tsx
import { Button } from '@mantine/core';
import { useAuth } from '../../../auth/useAuth';
import { useEnrichLabelAuto } from '../hooks/useEnrichLabelAuto';
```

After `const { t } = useTranslation();` (line 26):

```tsx
  const { state } = useAuth();
  const isAdmin = state.status === 'authenticated' && state.user.is_admin;
  const enrich = useEnrichLabelAuto();
```

In the title `Group` (lines 73-77), after `<LabelPreferenceButtons .../>` add:

```tsx
        {isAdmin && (
          <Button
            size="xs"
            variant="light"
            loading={enrich.isPending}
            onClick={() => enrich.mutate({ labelId })}
          >
            {t('library.detail.admin_search_now')}
          </Button>
        )}
```

Note: `Button` must be added to the `@mantine/core` import on line 1.

- [ ] **Step 6: Run tests, verify pass**

Run (from `frontend/`): `pnpm test -- ArtistDetailPage LabelDetailHeader ArtistDetailHeader`
Expected: PASS. (If `LabelDetailHeader`/`ArtistDetailHeader` have no own test files, that's fine — the `ArtistDetailPage` test covers the wiring; add an equivalent label-page case if a `LabelDetailPage.test.tsx` exists.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/i18n/en.json frontend/src/features/library/components/LabelDetailHeader.tsx frontend/src/features/library/components/ArtistDetailHeader.tsx frontend/src/features/library/routes/__tests__/ArtistDetailPage.test.tsx
git commit -m "feat(library): admin search-now button on detail pages"
```

---

## Final verification

- [ ] **Backend suite**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q`
Expected: PASS.

- [ ] **Frontend unit suite + typecheck + lint**

Run (from `frontend/`): `pnpm test && pnpm typecheck && pnpm lint`
Expected: PASS. (Use the actual script names in `frontend/package.json` if they differ, e.g. `pnpm run build` for type-checking.)

- [ ] **OpenAPI / schema drift check**

Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python scripts/generate_openapi.py` then `git diff --exit-code docs/api/openapi.yaml`
Expected: no diff (already regenerated in B4). The frontend CI diff-checks `schema.d.ts` against `openapi.yaml` — ensure both were regenerated together.

- [ ] **Visual check (local, optional but recommended)**

Per `CLAUDE.md` gotcha 11, jsdom applies no CSS. Verify the new playlist `LabelTile` and curate `ArtistsPanel` layouts in a real browser:
Run (from `frontend/`): `pnpm test:browser` (if you add `*.browser.test.tsx`) or `pnpm dev` and click through `/playlists/:id` and `/curate`.

---

## Self-review notes (for the implementer)

- **Spec coverage:** Part A covers gaps 1 (curate artist tile, A3) & 2 (playlist label tile A2 + the linkless `LabelTile` A1; triage/categories already comply). Parts B+C cover gap 3 (label A1/B1, artist B2, routing B3, infra/openapi B4, frontend hooks C1, button C2).
- **Type/name consistency:** `handle_post_enrich_auto` is the handler name in both `routes.py`. Route keys use `{label_id}` / `{artist_id}` (matching repo path-param conventions and `get_*_by_id`). Hooks: `useEnrichLabelAuto({ labelId })` returns `{ run_id, queued_labels }`; `useEnrichArtistAuto({ artistId })` returns `{ run_id, queued_artists }`.
- **No requestBody** on the new endpoints — the only input is the path id; settings come from `auto_enrich_config`.
- **`enabled` flag is intentionally ignored** by the manual button (it governs auto-dispatch only); the handler validates only that the settings fields are present, returning 409 otherwise.
</content>
