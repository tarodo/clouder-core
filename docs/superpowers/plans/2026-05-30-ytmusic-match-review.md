# YT Music Match Review (user-facing) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user resolve `needs_review` YT Music matches inline from the playlist badge — accept a top-5 candidate, paste a YT Music link, or mark the track not-on-YT — writing the canonical result to `vendor_track_map`.

**Architecture:** Two new per-user curation routes (`GET .../match-candidates`, `POST .../match-resolve`) reuse the existing `match_review_queue` + `vendor_track_map`. The `needs_review` badge becomes a Mantine `Popover` that lazily fetches candidates and resolves via an optimistic react-query mutation. No new tables — `match_review_queue.status` gains a `'resolved'` value (no CHECK constraint, no migration).

**Tech Stack:** Python 3.12 (curation Lambda, RDS Data API, pydantic), pytest; React 19 + Mantine 9 + TanStack Query + Vitest.

**Spec:** `docs/superpowers/specs/2026-05-30-ytmusic-match-review-design.md`

**Conventions (from CLAUDE.md):**
- Run from the worktree root. `.venv` is at the MAIN repo root. Backend tests: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest <args>`.
- Frontend from `frontend/`: `pnpm test -- <pat>` (jsdom), `pnpm test:browser -- <pat>` (Playwright). `node_modules` already installed in the worktree.
- Commits: Conventional Commits, heredoc body, no AI trailer.
- OpenAPI is generated: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`, then `cd frontend && pnpm api:types`.

**Design refinement vs spec:** the `GET match-candidates` response returns ONLY `{vendor, candidates}` — the popover renders the canonical-track header from the `PlaylistTrack` it already has in the playlist row, so the endpoint does not re-send track fields.

---

## File Structure

**Backend — modified:**
- `src/collector/curation/schemas.py` — `ResolveMatchIn` request model + videoId validator + shared `YT_VIDEO_ID_RE`.
- `src/collector/curation/playlists_repository.py` — `ReviewRow` dataclass, `get_open_review`, `resolve_review_accept`, `resolve_review_reject`.
- `src/collector/curation_handler.py` — `_project_candidate`, `_handle_match_candidates`, `_handle_resolve_match`, two `_ROUTE_TABLE` entries.
- `scripts/generate_openapi.py` — the two routes + schemas.

**Frontend — created:**
- `src/features/playlists/lib/parseYtVideoId.ts` (+ test)
- `src/features/playlists/hooks/useMatchCandidates.ts`
- `src/features/playlists/hooks/useResolveMatch.ts` (+ test)
- `src/features/playlists/components/YtMusicReviewPopover.tsx` (+ browser test)

**Frontend — modified:**
- `src/features/playlists/lib/playlistTypes.ts` — candidate/response types.
- `src/features/playlists/components/YtMusicBadge.tsx` — `needs_review` opens the popover.
- `src/api/schema.d.ts` — regenerated.

**Tests — created:**
- `tests/unit/test_curation_resolve_schema.py`
- `tests/unit/test_playlists_repository_review_resolve.py`
- `tests/unit/test_curation_handler_match_review.py`

---

## Task 1: Resolve request schema + videoId validation

**Files:**
- Modify: `src/collector/curation/schemas.py`
- Test: `tests/unit/test_curation_resolve_schema.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_curation_resolve_schema.py
import pytest
from pydantic import ValidationError

from collector.curation.schemas import ResolveMatchIn, YT_VIDEO_ID_RE


def test_accept_requires_valid_video_id():
    m = ResolveMatchIn.model_validate(
        {"vendor": "ytmusic", "action": "accept", "vendor_track_id": "dQw4w9WgXcQ"}
    )
    assert m.action == "accept"
    assert m.vendor_track_id == "dQw4w9WgXcQ"


def test_accept_rejects_bad_video_id():
    with pytest.raises(ValidationError):
        ResolveMatchIn.model_validate(
            {"vendor": "ytmusic", "action": "accept", "vendor_track_id": "too-short"}
        )


def test_accept_requires_video_id_present():
    with pytest.raises(ValidationError):
        ResolveMatchIn.model_validate({"vendor": "ytmusic", "action": "accept"})


def test_reject_needs_no_video_id():
    m = ResolveMatchIn.model_validate({"vendor": "ytmusic", "action": "reject"})
    assert m.action == "reject"
    assert m.vendor_track_id is None


def test_regex_matches_11_char_id():
    assert YT_VIDEO_ID_RE.match("dQw4w9WgXcQ")
    assert not YT_VIDEO_ID_RE.match("dQw4w9WgXc")  # 10 chars
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest tests/unit/test_curation_resolve_schema.py -v`
Expected: FAIL (`ImportError: cannot import name 'ResolveMatchIn'`).

- [ ] **Step 3: Implement**

Add to `src/collector/curation/schemas.py` (the file already imports `BaseModel, ConfigDict, Field, field_validator, model_validator` from pydantic; add `import re` at the top and `from typing import Literal` if not present):

```python
import re

YT_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class ResolveMatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: str = Field(min_length=1)
    action: Literal["accept", "reject"]
    vendor_track_id: str | None = None

    @model_validator(mode="after")
    def _check_accept_has_valid_id(self) -> "ResolveMatchIn":
        if self.action == "accept":
            if not self.vendor_track_id or not YT_VIDEO_ID_RE.match(self.vendor_track_id):
                raise ValueError("accept requires a valid 11-char vendor_track_id")
        return self
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest tests/unit/test_curation_resolve_schema.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/schemas.py tests/unit/test_curation_resolve_schema.py
git commit -m "feat(curation): add ResolveMatchIn schema with videoId validation"
```

---

## Task 2: Repository review-resolve methods

**Files:**
- Modify: `src/collector/curation/playlists_repository.py`
- Test: `tests/unit/test_playlists_repository_review_resolve.py`

Reuse `ClouderRepository.upsert_vendor_match` for the canonical write inside a shared transaction. `get_open_review` parses the stored candidates JSONB.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_playlists_repository_review_resolve.py
from datetime import datetime, timezone
from decimal import Decimal

from collector.curation.playlists_repository import PlaylistsRepository


class FakeTx:
    def __enter__(self):
        return "tx-1"
    def __exit__(self, *a):
        return False


class FakeDataAPI:
    def __init__(self, review_rows):
        self.review_rows = review_rows
        self.calls = []
    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params, transaction_id))
        if "FROM match_review_queue" in sql and "SELECT" in sql:
            return self.review_rows
        return []
    def transaction(self):
        return FakeTx()


def test_get_open_review_parses_candidates():
    api = FakeDataAPI([{"candidates": [{"ref": {"videoId": "v1"}, "score": 0.9}]}])
    repo = PlaylistsRepository(api)
    row = repo.get_open_review(track_id="t1", vendor="ytmusic")
    assert row is not None
    assert row.candidates[0]["ref"]["videoId"] == "v1"


def test_get_open_review_none_when_absent():
    repo = PlaylistsRepository(FakeDataAPI([]))
    assert repo.get_open_review(track_id="t1", vendor="ytmusic") is None


def test_resolve_accept_upserts_and_resolves():
    api = FakeDataAPI([])
    repo = PlaylistsRepository(api)
    now = datetime(2026, 5, 30, tzinfo=timezone.utc)
    repo.resolve_review_accept(
        clouder_track_id="t1", vendor="ytmusic", vendor_track_id="dQw4w9WgXcQ",
        payload={"videoId": "dQw4w9WgXcQ"}, now=now,
    )
    sqls = " ".join(c[0] for c in api.calls)
    assert "INSERT INTO vendor_track_map" in sqls
    assert "match_review_queue" in sqls and "'resolved'" in sqls
    # both writes ran inside the same transaction id
    txids = {c[2] for c in api.calls if c[2] is not None}
    assert txids == {"tx-1"}


def test_resolve_reject_sets_no_match():
    api = FakeDataAPI([])
    repo = PlaylistsRepository(api)
    now = datetime(2026, 5, 30, tzinfo=timezone.utc)
    repo.resolve_review_reject(clouder_track_id="t1", vendor="ytmusic", now=now)
    sqls = " ".join(c[0] for c in api.calls)
    assert "DELETE FROM match_review_queue" in sqls  # clear any stale no_match
    assert "'no_match'" in sqls
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest tests/unit/test_playlists_repository_review_resolve.py -v`
Expected: FAIL (`AttributeError: 'PlaylistsRepository' object has no attribute 'get_open_review'`).

- [ ] **Step 3: Implement**

Add to `src/collector/curation/playlists_repository.py`. First ensure imports at the top include `json`, `Decimal`, and the dataclass tooling (the file already imports `dataclass`, `Any`, `datetime`, `json`; add `from decimal import Decimal` if absent). Add the dataclass near the others:

```python
@dataclass(frozen=True)
class ReviewRow:
    candidates: list[dict]
```

Add the methods to `PlaylistsRepository`:

```python
    def get_open_review(self, *, track_id: str, vendor: str) -> "ReviewRow | None":
        rows = self._data_api.execute(
            """
            SELECT candidates
            FROM match_review_queue
            WHERE clouder_track_id = :t AND vendor = :v AND status = 'pending'
            LIMIT 1
            """,
            {"t": track_id, "v": vendor},
        )
        if not rows:
            return None
        raw = rows[0].get("candidates")
        candidates = json.loads(raw) if isinstance(raw, str) else (raw or [])
        return ReviewRow(candidates=list(candidates))

    def resolve_review_accept(
        self, *, clouder_track_id: str, vendor: str, vendor_track_id: str,
        payload: dict, now,
    ) -> None:
        from ..repositories import ClouderRepository, UpsertVendorMatchCmd

        with self._data_api.transaction() as tx:
            ClouderRepository(self._data_api).upsert_vendor_match(
                UpsertVendorMatchCmd(
                    clouder_track_id=clouder_track_id,
                    vendor=vendor,
                    vendor_track_id=vendor_track_id,
                    match_type="manual",
                    confidence=Decimal("1.000"),
                    matched_at=now,
                    payload=payload,
                ),
                transaction_id=tx,
            )
            self._data_api.execute(
                """
                UPDATE match_review_queue
                SET status = 'resolved', resolved_at = :now
                WHERE clouder_track_id = :t AND vendor = :v AND status = 'pending'
                """,
                {"t": clouder_track_id, "v": vendor, "now": now},
                transaction_id=tx,
            )

    def resolve_review_reject(self, *, clouder_track_id: str, vendor: str, now) -> None:
        with self._data_api.transaction() as tx:
            # Drop any stale no_match row so the pending->no_match UPDATE cannot
            # collide with uq_review_no_match.
            self._data_api.execute(
                """
                DELETE FROM match_review_queue
                WHERE clouder_track_id = :t AND vendor = :v AND status = 'no_match'
                """,
                {"t": clouder_track_id, "v": vendor},
                transaction_id=tx,
            )
            self._data_api.execute(
                """
                UPDATE match_review_queue
                SET status = 'no_match', resolved_at = :now
                WHERE clouder_track_id = :t AND vendor = :v AND status = 'pending'
                """,
                {"t": clouder_track_id, "v": vendor, "now": now},
                transaction_id=tx,
            )
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest tests/unit/test_playlists_repository_review_resolve.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/collector/curation/playlists_repository.py tests/unit/test_playlists_repository_review_resolve.py
git commit -m "feat(playlists): add review-resolve repository methods"
```

---

## Task 3: Route handlers + scope checks + projection

**Files:**
- Modify: `src/collector/curation_handler.py`
- Test: `tests/unit/test_curation_handler_match_review.py`

`GET` returns projected candidates; `POST` resolves and returns the resulting ytmusic status. Both check playlist ownership + track scope.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_curation_handler_match_review.py
import json

from collector import curation_handler as ch
from collector.curation.playlists_repository import ReviewRow, YtmusicStatus


def _candidate(vid="dQw4w9WgXcQ", score=0.9):
    return {"ref": {"videoId": vid, "title": "Hold Me", "artists": [{"name": "ARTYS"}],
                    "album": {"name": "EP"}, "duration_seconds": 418}, "score": score}


class Repo:
    def __init__(self, *, in_scope=True, owns=True, review=None, status=None):
        self._in_scope = in_scope
        self._owns = owns
        self._review = review
        self._status = status
        self.accepted = None
        self.rejected = None
    def get(self, *, user_id, playlist_id):
        return object() if self._owns else None
    def validate_tracks_in_scope(self, *, user_id, track_ids):
        return set(track_ids) if self._in_scope else set()
    def get_open_review(self, *, track_id, vendor):
        return self._review
    def resolve_review_accept(self, *, clouder_track_id, vendor, vendor_track_id, payload, now):
        self.accepted = (clouder_track_id, vendor, vendor_track_id, payload)
    def resolve_review_reject(self, *, clouder_track_id, vendor, now):
        self.rejected = (clouder_track_id, vendor)
    def fetch_ytmusic_status(self, track_ids):
        return {t: self._status for t in track_ids}


def _event(pid="pl1", tid="t1", body=None, qs=None):
    e = {"pathParameters": {"id": pid, "track_id": tid}}
    if body is not None:
        e["body"] = json.dumps(body)
    if qs is not None:
        e["queryStringParameters"] = qs
    return e


def test_candidates_projects_top5():
    repo = Repo(review=ReviewRow(candidates=[_candidate()]))
    resp = ch._handle_match_candidates(_event(qs={"vendor": "ytmusic"}), repo, "u1", "c1")
    body = json.loads(resp["body"])
    assert body["vendor"] == "ytmusic"
    c = body["candidates"][0]
    assert c["vendor_track_id"] == "dQw4w9WgXcQ"
    assert c["title"] == "Hold Me"
    assert c["artists"] == ["ARTYS"]
    assert c["album"] == "EP"
    assert c["duration_ms"] == 418_000
    assert c["url"] == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
    assert c["score"] == 0.9


def test_candidates_404_when_no_open_review():
    repo = Repo(review=None)
    try:
        ch._handle_match_candidates(_event(qs={"vendor": "ytmusic"}), repo, "u1", "c1")
        assert False, "expected NotFoundError"
    except ch.NotFoundError:
        pass


def test_resolve_accept_writes_and_returns_status():
    repo = Repo(
        review=ReviewRow(candidates=[_candidate()]),
        status=YtmusicStatus(status="matched", video_id="dQw4w9WgXcQ",
                             url="https://music.youtube.com/watch?v=dQw4w9WgXcQ",
                             confidence=1.0),
    )
    body = {"vendor": "ytmusic", "action": "accept", "vendor_track_id": "dQw4w9WgXcQ"}
    resp = ch._handle_resolve_match(_event(body=body), repo, "u1", "c1")
    assert repo.accepted[0] == "t1" and repo.accepted[2] == "dQw4w9WgXcQ"
    # payload is the matched candidate's ref (provenance kept)
    assert repo.accepted[3]["videoId"] == "dQw4w9WgXcQ"
    assert json.loads(resp["body"])["ytmusic"]["status"] == "matched"


def test_resolve_accept_manual_url_payload():
    repo = Repo(review=ReviewRow(candidates=[_candidate(vid="aaaaaaaaaaa")]),
                status=YtmusicStatus(status="matched"))
    body = {"vendor": "ytmusic", "action": "accept", "vendor_track_id": "bbbbbbbbbbb"}
    ch._handle_resolve_match(_event(body=body), repo, "u1", "c1")
    # videoId not in candidates -> manual payload
    assert repo.accepted[3]["source"] == "manual_url"
    assert repo.accepted[3]["videoId"] == "bbbbbbbbbbb"


def test_resolve_reject_sets_status():
    repo = Repo(status=YtmusicStatus(status="not_found"))
    body = {"vendor": "ytmusic", "action": "reject"}
    resp = ch._handle_resolve_match(_event(body=body), repo, "u1", "c1")
    assert repo.rejected == ("t1", "ytmusic")
    assert json.loads(resp["body"])["ytmusic"]["status"] == "not_found"


def test_resolve_out_of_scope_raises():
    repo = Repo(in_scope=False, status=YtmusicStatus(status="pending"))
    body = {"vendor": "ytmusic", "action": "reject"}
    try:
        ch._handle_resolve_match(_event(body=body), repo, "u1", "c1")
        assert False, "expected TrackNotInUserScopeError"
    except ch.TrackNotInUserScopeError:
        pass
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest tests/unit/test_curation_handler_match_review.py -v`
Expected: FAIL (`AttributeError: module 'collector.curation_handler' has no attribute '_handle_match_candidates'`).

- [ ] **Step 3: Implement**

In `src/collector/curation_handler.py`:

(a) Ensure `ReviewRow` is importable — it is exported from `playlists_repository`; the handler already imports from that module (`PlaylistsRepository, create_default_playlists_repository`). Extend that import to include `ReviewRow` is NOT required (handlers receive `repo`), but the helpers below use `result_to_ref` — add this import near the top imports:

```python
from .providers.ytmusic.normalize import result_to_ref
```

(b) Add the projection helper + two handlers (place after `_playlist_track_response`):

```python
def _project_candidate(c: dict) -> dict[str, Any]:
    ref = c.get("ref") or {}
    vt = result_to_ref(ref)
    vid = vt.vendor_track_id if vt else str(ref.get("videoId") or "")
    return {
        "vendor_track_id": vid,
        "title": vt.title if vt else str(ref.get("title") or ""),
        "artists": list(vt.artist_names) if vt else [],
        "album": vt.album_name if vt else None,
        "duration_ms": vt.duration_ms if vt else None,
        "url": f"https://music.youtube.com/watch?v={vid}",
        "score": c.get("score"),
    }


def _vendor_from_query(event) -> str:
    qp = event.get("queryStringParameters") or {}
    return (qp.get("vendor") or "ytmusic").strip() or "ytmusic"


def _scope_check(repo, user_id, pid, track_id):
    if repo.get(user_id=user_id, playlist_id=pid) is None:
        raise PlaylistNotFoundError("Playlist not found")
    visible = repo.validate_tracks_in_scope(user_id=user_id, track_ids=[track_id])
    if track_id not in visible:
        raise TrackNotInUserScopeError("Track not accessible to the user", [track_id])


def _handle_match_candidates(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    pid, track_id = pp.get("id"), pp.get("track_id")
    if not pid or not track_id:
        raise ValidationError("id and track_id are required in path")
    vendor = _vendor_from_query(event)
    _scope_check(repo, user_id, pid, track_id)
    review = repo.get_open_review(track_id=track_id, vendor=vendor)
    if review is None:
        raise NotFoundError("No open review for this track")
    return _json_response(
        200,
        {"vendor": vendor,
         "candidates": [_project_candidate(c) for c in review.candidates]},
        correlation_id,
    )


def _ytmusic_status_dict(status) -> dict[str, Any] | None:
    if status is None:
        return None
    return {"status": status.status, "video_id": status.video_id,
            "url": status.url, "confidence": status.confidence}


def _handle_resolve_match(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    pid, track_id = pp.get("id"), pp.get("track_id")
    if not pid or not track_id:
        raise ValidationError("id and track_id are required in path")
    body = ResolveMatchIn.model_validate(_parse_body(event))
    _scope_check(repo, user_id, pid, track_id)

    if body.action == "accept":
        review = repo.get_open_review(track_id=track_id, vendor=body.vendor)
        payload: dict[str, Any] = {
            "videoId": body.vendor_track_id,
            "url": f"https://music.youtube.com/watch?v={body.vendor_track_id}",
            "source": "manual_url",
        }
        if review is not None:
            for c in review.candidates:
                ref = c.get("ref") or {}
                if str(ref.get("videoId") or "") == body.vendor_track_id:
                    payload = ref
                    break
        repo.resolve_review_accept(
            clouder_track_id=track_id, vendor=body.vendor,
            vendor_track_id=body.vendor_track_id, payload=payload, now=utc_now(),
        )
    else:
        repo.resolve_review_reject(
            clouder_track_id=track_id, vendor=body.vendor, now=utc_now(),
        )

    status = repo.fetch_ytmusic_status([track_id]).get(track_id)
    log_event(
        "INFO", "match_review_resolved",
        correlation_id=correlation_id, user_id=user_id,
        track_id=track_id, vendor=body.vendor, action=body.action,
    )
    return _json_response(200, {"ytmusic": _ytmusic_status_dict(status)}, correlation_id)
```

(c) Import `ResolveMatchIn` — find the existing import block from `.curation.schemas` (or wherever `AddTracksIn` is imported in `curation_handler.py`) and add `ResolveMatchIn` to it. Confirm `NotFoundError`, `PlaylistNotFoundError`, `TrackNotInUserScopeError`, `ValidationError` are already imported at the top of `curation_handler.py` (they are — used by sibling handlers).

(d) Register the routes in `_ROUTE_TABLE` (next to the other `/playlists/{id}/tracks/...` entries):

```python
    "GET /playlists/{id}/tracks/{track_id}/match-candidates": (
        _handle_match_candidates, _playlists_factory),
    "POST /playlists/{id}/tracks/{track_id}/match-resolve": (
        _handle_resolve_match, _playlists_factory),
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest tests/unit/test_curation_handler_match_review.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the existing curation suites for no regression**

Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest tests/unit/test_curation_handler_enqueue.py tests/integration/test_curation_handler.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/collector/curation_handler.py tests/unit/test_curation_handler_match_review.py
git commit -m "feat(curation): add match-candidates and match-resolve routes"
```

---

## Task 4: OpenAPI + schema regen

**Files:**
- Modify: `scripts/generate_openapi.py`
- Generated: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`

- [ ] **Step 1: Locate the playlist routes block**

Run: `grep -n '"/playlists/{id}/tracks' scripts/generate_openapi.py`
Expected: the path entries for playlist tracks. You will add two sibling paths.

- [ ] **Step 2: Add the two paths**

In `scripts/generate_openapi.py`, add to the paths dict (match the file's existing structure for an admin/curation path with `parameters`, `responses`, `security`). Use this shape:

```python
    "/playlists/{id}/tracks/{track_id}/match-candidates": {
        "get": {
            "summary": "List YT Music match candidates for a track under review",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string"}},
                {"name": "vendor", "in": "query", "required": False,
                 "schema": {"type": "string", "default": "ytmusic"}},
            ],
            "responses": {
                "200": {
                    "description": "Top-5 candidates",
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["vendor", "candidates"],
                        "properties": {
                            "vendor": {"type": "string"},
                            "candidates": {"type": "array", "items": {
                                "type": "object",
                                "required": ["vendor_track_id", "title", "artists", "url"],
                                "properties": {
                                    "vendor_track_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "artists": {"type": "array", "items": {"type": "string"}},
                                    "album": {"type": "string", "nullable": True},
                                    "duration_ms": {"type": "integer", "nullable": True},
                                    "url": {"type": "string"},
                                    "score": {"type": "number", "nullable": True},
                                },
                            }},
                        },
                    }}},
                },
                "404": {"description": "No open review for this track"},
            },
        },
    },
    "/playlists/{id}/tracks/{track_id}/match-resolve": {
        "post": {
            "summary": "Resolve a YT Music match (accept candidate/link or reject)",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string"}},
            ],
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["vendor", "action"],
                "properties": {
                    "vendor": {"type": "string"},
                    "action": {"type": "string", "enum": ["accept", "reject"]},
                    "vendor_track_id": {"type": "string", "nullable": True},
                },
            }}}},
            "responses": {
                "200": {
                    "description": "Resulting match status",
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "required": ["ytmusic"],
                        "properties": {"ytmusic": {
                            "type": "object",
                            "nullable": True,
                            "properties": {
                                "status": {"type": "string",
                                           "enum": ["matched", "pending", "needs_review", "not_found"]},
                                "video_id": {"type": "string", "nullable": True},
                                "url": {"type": "string", "nullable": True},
                                "confidence": {"type": "number", "nullable": True},
                            },
                        }},
                    }}},
                },
                "400": {"description": "Invalid body / videoId"},
                "403": {"description": "Track not in user scope"},
            },
        },
    },
```

Match the existing indentation and, if the file wraps each path with `**_auth()` / security helpers, mirror that for these two (check a neighboring playlist path and copy its `security`/auth decoration).

- [ ] **Step 3: Regenerate**

```bash
PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python scripts/generate_openapi.py
cd frontend && pnpm api:types && cd ..
grep -n "match-candidates\|match-resolve" docs/api/openapi.yaml | head
grep -n "match-candidates\|match-resolve" frontend/src/api/schema.d.ts | head
```
Expected: both paths present in both files.

- [ ] **Step 4: Commit**

```bash
git add scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts
git commit -m "docs(api): add match-candidates and match-resolve routes"
```

---

## Task 5: Frontend videoId parser

**Files:**
- Create: `frontend/src/features/playlists/lib/parseYtVideoId.ts`
- Create test: `frontend/src/features/playlists/lib/__tests__/parseYtVideoId.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/playlists/lib/__tests__/parseYtVideoId.test.ts
import { describe, it, expect } from 'vitest';
import { parseYtVideoId } from '../parseYtVideoId';

describe('parseYtVideoId', () => {
  it('parses music.youtube.com watch url', () => {
    expect(parseYtVideoId('https://music.youtube.com/watch?v=dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ');
  });
  it('parses youtube.com watch url with extra params', () => {
    expect(parseYtVideoId('https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=x')).toBe('dQw4w9WgXcQ');
  });
  it('parses youtu.be short url', () => {
    expect(parseYtVideoId('https://youtu.be/dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ');
  });
  it('accepts a bare 11-char id', () => {
    expect(parseYtVideoId('dQw4w9WgXcQ')).toBe('dQw4w9WgXcQ');
  });
  it('returns null for junk', () => {
    expect(parseYtVideoId('not a link')).toBeNull();
    expect(parseYtVideoId('https://music.youtube.com/playlist?list=x')).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && pnpm test -- parseYtVideoId 2>&1 | tail -15 ; cd ..`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

```ts
// frontend/src/features/playlists/lib/parseYtVideoId.ts
const ID_RE = /^[A-Za-z0-9_-]{11}$/;

/** Extract an 11-char YT video id from a URL or a bare id; null if none. */
export function parseYtVideoId(input: string): string | null {
  const s = input.trim();
  if (ID_RE.test(s)) return s;
  try {
    const u = new URL(s);
    const host = u.hostname.replace(/^www\./, '');
    if (host === 'youtu.be') {
      const id = u.pathname.slice(1);
      return ID_RE.test(id) ? id : null;
    }
    if (host === 'youtube.com' || host === 'music.youtube.com' || host === 'm.youtube.com') {
      const v = u.searchParams.get('v');
      return v && ID_RE.test(v) ? v : null;
    }
  } catch {
    return null;
  }
  return null;
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && pnpm test -- parseYtVideoId 2>&1 | tail -15 ; cd ..`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/playlists/lib/parseYtVideoId.ts frontend/src/features/playlists/lib/__tests__/parseYtVideoId.test.ts
git commit -m "feat(playlists): add YT videoId parser util"
```

---

## Task 6: Frontend types + candidates/resolve hooks

**Files:**
- Modify: `frontend/src/features/playlists/lib/playlistTypes.ts`
- Create: `frontend/src/features/playlists/hooks/useMatchCandidates.ts`
- Create: `frontend/src/features/playlists/hooks/useResolveMatch.ts`
- Create test: `frontend/src/features/playlists/hooks/__tests__/useResolveMatch.test.tsx`

- [ ] **Step 1: Add types**

In `frontend/src/features/playlists/lib/playlistTypes.ts`, add:

```ts
export interface YtMusicCandidate {
  vendor_track_id: string;
  title: string;
  artists: string[];
  album?: string | null;
  duration_ms?: number | null;
  url: string;
  score?: number | null;
}

export interface MatchCandidatesResponse {
  vendor: string;
  candidates: YtMusicCandidate[];
}

export type ResolveMatchVars =
  | { action: 'accept'; vendorTrackId: string }
  | { action: 'reject' };
```

- [ ] **Step 2: Write the failing hook test**

```tsx
// frontend/src/features/playlists/hooks/__tests__/useResolveMatch.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useResolveMatch } from '../useResolveMatch';
import { playlistTracksKey } from '../../lib/queryKeys';
import type { PaginatedPlaylistTracks } from '../../lib/playlistTypes';

vi.mock('../../../../api/client', () => ({
  api: vi.fn(async () => ({ ytmusic: { status: 'matched', video_id: 'dQw4w9WgXcQ',
    url: 'https://music.youtube.com/watch?v=dQw4w9WgXcQ', confidence: 1 } })),
}));

function wrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useResolveMatch', () => {
  let qc: QueryClient;
  beforeEach(() => {
    qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const seed: PaginatedPlaylistTracks = {
      items: [{ track_id: 't1', position: 0, added_at: '', title: 'X', spotify_id: null,
        isrc: null, length_ms: null, origin: 'beatport', mix_name: null, artists: [],
        label: null, bpm: null, spotify_release_date: null, is_ai_suspected: false, tags: [],
        ytmusic: { status: 'needs_review' } }] as any,
      total: 1, limit: 200, offset: 0,
    };
    qc.setQueryData(playlistTracksKey('pl1'), seed);
  });

  it('optimistically flips the track to matched on accept', async () => {
    const { result } = renderHook(() => useResolveMatch('pl1', 't1'), { wrapper: wrapper(qc) });
    result.current.mutate({ action: 'accept', vendorTrackId: 'dQw4w9WgXcQ' });
    await waitFor(() => {
      const data = qc.getQueryData<PaginatedPlaylistTracks>(playlistTracksKey('pl1'));
      expect(data!.items[0].ytmusic!.status).toBe('matched');
    });
  });
});
```

- [ ] **Step 3: Run to verify failure**

Run: `cd frontend && pnpm test -- useResolveMatch 2>&1 | tail -15 ; cd ..`
Expected: FAIL (module not found).

- [ ] **Step 4: Implement both hooks**

```ts
// frontend/src/features/playlists/hooks/useMatchCandidates.ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { MatchCandidatesResponse } from '../lib/playlistTypes';

export function matchCandidatesKey(playlistId: string, trackId: string) {
  return ['match-candidates', playlistId, trackId] as const;
}

export function useMatchCandidates(
  playlistId: string,
  trackId: string,
  enabled: boolean,
): UseQueryResult<MatchCandidatesResponse> {
  return useQuery({
    queryKey: matchCandidatesKey(playlistId, trackId),
    queryFn: () =>
      api<MatchCandidatesResponse>(
        `/playlists/${playlistId}/tracks/${trackId}/match-candidates?vendor=ytmusic`,
      ),
    enabled,
    staleTime: 0,
  });
}
```

```ts
// frontend/src/features/playlists/hooks/useResolveMatch.ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { playlistTracksKey } from '../lib/queryKeys';
import type {
  PaginatedPlaylistTracks, ResolveMatchVars, YtMusicMatch,
} from '../lib/playlistTypes';

interface ResolveResponse { ytmusic: YtMusicMatch | null }
interface Ctx { prev?: PaginatedPlaylistTracks }

function setStatus(
  data: PaginatedPlaylistTracks | undefined,
  trackId: string,
  ytmusic: YtMusicMatch,
): PaginatedPlaylistTracks | undefined {
  if (!data) return data;
  return {
    ...data,
    items: data.items.map((it) => (it.track_id === trackId ? { ...it, ytmusic } : it)),
  };
}

export function useResolveMatch(
  playlistId: string,
  trackId: string,
): UseMutationResult<ResolveResponse, Error, ResolveMatchVars, Ctx> {
  const qc = useQueryClient();
  const key = playlistTracksKey(playlistId);
  return useMutation<ResolveResponse, Error, ResolveMatchVars, Ctx>({
    mutationFn: (vars) => {
      const body =
        vars.action === 'accept'
          ? { vendor: 'ytmusic', action: 'accept', vendor_track_id: vars.vendorTrackId }
          : { vendor: 'ytmusic', action: 'reject' };
      return api<ResolveResponse>(
        `/playlists/${playlistId}/tracks/${trackId}/match-resolve`,
        { method: 'POST', body: JSON.stringify(body) },
      );
    },
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<PaginatedPlaylistTracks>(key);
      const optimistic: YtMusicMatch =
        vars.action === 'accept'
          ? { status: 'matched', video_id: vars.vendorTrackId,
              url: `https://music.youtube.com/watch?v=${vars.vendorTrackId}` }
          : { status: 'not_found' };
      qc.setQueryData<PaginatedPlaylistTracks>(key, (old) => setStatus(old, trackId, optimistic));
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(key, ctx.prev); },
    onSuccess: (data) => {
      if (data?.ytmusic) {
        qc.setQueryData<PaginatedPlaylistTracks>(key, (old) =>
          setStatus(old, trackId, data.ytmusic!));
      }
    },
    onSettled: () => { qc.invalidateQueries({ queryKey: key }); },
  });
}
```

- [ ] **Step 5: Run to verify pass**

Run: `cd frontend && pnpm test -- useResolveMatch 2>&1 | tail -15 ; cd ..`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/playlists/lib/playlistTypes.ts frontend/src/features/playlists/hooks/useMatchCandidates.ts frontend/src/features/playlists/hooks/useResolveMatch.ts frontend/src/features/playlists/hooks/__tests__/useResolveMatch.test.tsx
git commit -m "feat(playlists): add match candidates + resolve hooks"
```

---

## Task 7: Review popover + clickable badge

**Files:**
- Create: `frontend/src/features/playlists/components/YtMusicReviewPopover.tsx`
- Create browser test: `frontend/src/features/playlists/components/__tests__/YtMusicReviewPopover.browser.test.tsx`
- Modify: `frontend/src/features/playlists/components/YtMusicBadge.tsx`

- [ ] **Step 1: Write the failing browser test**

Model imports/wrappers on the existing `YtMusicBadge.browser.test.tsx` (MantineProvider + i18n + a QueryClientProvider; copy its exact render helper). The test:

```tsx
// frontend/src/features/playlists/components/__tests__/YtMusicReviewPopover.browser.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import '../../../../i18n';
import { YtMusicReviewPopover } from '../YtMusicReviewPopover';

vi.mock('../../../../api/client', () => ({
  api: vi.fn(async (path: string) =>
    path.includes('match-candidates')
      ? { vendor: 'ytmusic', candidates: [
          { vendor_track_id: 'dQw4w9WgXcQ', title: 'Hold Me', artists: ['ARTYS'],
            album: 'EP', duration_ms: 418000,
            url: 'https://music.youtube.com/watch?v=dQw4w9WgXcQ', score: 0.9 }] }
      : { ytmusic: { status: 'matched', video_id: 'dQw4w9WgXcQ',
          url: 'https://music.youtube.com/watch?v=dQw4w9WgXcQ', confidence: 1 } }),
}));

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <YtMusicReviewPopover playlistId="pl1" trackId="t1"
          track={{ title: 'Hold Me In Heaven', artists: [{ id: 'a', name: 'ARTYS' }] } as any} />
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe('YtMusicReviewPopover', () => {
  it('opens, lists a candidate, and accepts it', async () => {
    setup();
    await userEvent.click(screen.getByRole('button', { name: /review/i }));
    await waitFor(() => expect(screen.getByText('Hold Me')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /accept/i }));
    // mutation fired; no throw — candidate accept path exercised
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && pnpm test:browser -- YtMusicReviewPopover 2>&1 | tail -20 ; cd ..`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the popover**

```tsx
// frontend/src/features/playlists/components/YtMusicReviewPopover.tsx
import { useState } from 'react';
import {
  ActionIcon, Anchor, Button, Group, Popover, Stack, Text, TextInput, Tooltip,
} from '@mantine/core';
import { IconHelpCircle, IconExternalLink } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { PlaylistTrack } from '../lib/playlistTypes';
import { useMatchCandidates } from '../hooks/useMatchCandidates';
import { useResolveMatch } from '../hooks/useResolveMatch';
import { parseYtVideoId } from '../lib/parseYtVideoId';

export interface YtMusicReviewPopoverProps {
  playlistId: string;
  trackId: string;
  track: Pick<PlaylistTrack, 'title' | 'artists'>;
}

export function YtMusicReviewPopover({ playlistId, trackId, track }: YtMusicReviewPopoverProps) {
  const { t } = useTranslation();
  const [opened, setOpened] = useState(false);
  const [link, setLink] = useState('');
  const [linkError, setLinkError] = useState<string | null>(null);
  const candidates = useMatchCandidates(playlistId, trackId, opened);
  const resolve = useResolveMatch(playlistId, trackId);

  const accept = (vendorTrackId: string) =>
    resolve.mutate({ action: 'accept', vendorTrackId }, { onSuccess: () => setOpened(false) });

  const acceptLink = () => {
    const id = parseYtVideoId(link);
    if (!id) { setLinkError(t('playlists.ytmusic.badLink', 'Invalid YT Music link')); return; }
    setLinkError(null);
    accept(id);
  };

  return (
    <Popover opened={opened} onChange={setOpened} width={360} position="bottom-end" withArrow>
      <Popover.Target>
        <Tooltip label={t('playlists.ytmusic.needsReview', 'Needs review')}>
          <ActionIcon variant="subtle" color="yellow"
            aria-label={t('playlists.ytmusic.review', 'Review YT Music match')}
            onClick={() => setOpened((o) => !o)}>
            <IconHelpCircle size={18} />
          </ActionIcon>
        </Tooltip>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <Text fw={600} size="sm">{track.title}</Text>
          <Text c="dimmed" size="xs">{track.artists.map((a) => a.name).join(', ')}</Text>

          {candidates.isLoading && <Text size="xs" c="dimmed">{t('common.loading', 'Loading…')}</Text>}
          {candidates.data?.candidates.map((c) => (
            <Group key={c.vendor_track_id} justify="space-between" wrap="nowrap" gap="xs">
              <Stack gap={0} style={{ minWidth: 0 }}>
                <Text size="sm" truncate>{c.title}</Text>
                <Text size="xs" c="dimmed" truncate>
                  {c.artists.join(', ')}{c.score != null ? ` · ${c.score.toFixed(2)}` : ''}
                </Text>
              </Stack>
              <Group gap={4} wrap="nowrap">
                <Anchor href={c.url} target="_blank" rel="noopener noreferrer" aria-label="open">
                  <IconExternalLink size={16} />
                </Anchor>
                <Button size="compact-xs" onClick={() => accept(c.vendor_track_id)}>
                  {t('common.accept', 'Accept')}
                </Button>
              </Group>
            </Group>
          ))}

          <TextInput size="xs" placeholder="https://music.youtube.com/watch?v=…"
            value={link} error={linkError ?? undefined}
            onChange={(e) => setLink(e.currentTarget.value)} />
          <Group justify="space-between">
            <Button size="compact-xs" variant="light" onClick={acceptLink} disabled={!link.trim()}>
              {t('playlists.ytmusic.useLink', 'Use link')}
            </Button>
            <Button size="compact-xs" variant="subtle" color="gray"
              onClick={() => resolve.mutate({ action: 'reject' }, { onSuccess: () => setOpened(false) })}>
              {t('playlists.ytmusic.notOnYt', 'Not on YT')}
            </Button>
          </Group>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
```

- [ ] **Step 4: Wire the badge to the popover**

In `frontend/src/features/playlists/components/YtMusicBadge.tsx`, the `needs_review` branch currently renders a static `<Text>` icon. The badge needs the playlist + track context to open the popover, so extend its props. Change the `YtMusicBadgeProps` to also accept `playlistId`, `trackId`, and `track`:

```tsx
import { YtMusicReviewPopover } from './YtMusicReviewPopover';
import type { PlaylistTrack } from '../lib/playlistTypes';

export interface YtMusicBadgeProps {
  match: YtMusicMatch | null | undefined;
  playlistId: string;
  trackId: string;
  track: Pick<PlaylistTrack, 'title' | 'artists'>;
}
```

In the component body, replace the `needs_review` arm of the status switch so it returns the popover instead of the static text icon:

```tsx
  if (match.status === 'needs_review') {
    return <YtMusicReviewPopover playlistId={playlistId} trackId={trackId} track={track} />;
  }
```

Keep `matched` / `pending` / `not_found` exactly as they are.

- [ ] **Step 5: Update the badge's call site**

In `frontend/src/features/playlists/components/PlaylistTrackRow.tsx`, the existing `<YtMusicBadge match={track.ytmusic} />` now needs the new props. The component has `track` and the playlist id is available where the row is rendered. Update to:

```tsx
<YtMusicBadge match={track.ytmusic} playlistId={playlistId} trackId={track.track_id} track={track} />
```

If `PlaylistTrackRowView` does not already receive `playlistId`, thread it through from `PlaylistTracksList` (the parent that holds the playlist id) as a prop on `PlaylistTrackRowProps`. Read `PlaylistTracksList.tsx` to find where the id lives and pass it down. Keep the change minimal — one prop added through the existing props chain.

- [ ] **Step 6: Run the browser test + the existing badge/row tests**

```bash
cd frontend && pnpm test:browser -- YtMusicReviewPopover 2>&1 | tail -20 ; cd ..
cd frontend && pnpm test:browser -- YtMusicBadge 2>&1 | tail -10 ; cd ..
cd frontend && pnpm test -- PlaylistTrackRow 2>&1 | tail -10 ; cd ..
```
Expected: all PASS. If existing `YtMusicBadge`/`PlaylistTrackRow` tests now fail to compile because the badge requires new props, update those test render call sites to pass `playlistId="pl1"`, `trackId`, and a minimal `track` — report which you changed.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/playlists/components/YtMusicReviewPopover.tsx frontend/src/features/playlists/components/__tests__/YtMusicReviewPopover.browser.test.tsx frontend/src/features/playlists/components/YtMusicBadge.tsx frontend/src/features/playlists/components/PlaylistTrackRow.tsx frontend/src/features/playlists/components/PlaylistTracksList.tsx
git commit -m "feat(playlists): inline YT Music match review popover"
```

---

## Task 8: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Backend suite**

Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest -q`
Expected: all green. If an integration test asserts the exact set of curation routes, add the two new `routeKey`s to its expected list — report what you changed.

- [ ] **Step 2: Frontend suites**

```bash
cd frontend && pnpm test 2>&1 | tail -6 ; cd ..
cd frontend && pnpm test:browser 2>&1 | tail -6 ; cd ..
```
Expected: all green.

- [ ] **Step 3: Final commit (only if a fixture needed updating in Step 1/2)**

```bash
git add -A
git commit -m "test(curation): cover new match-review routes in fixtures"
```

---

## Self-Review Notes

- **Spec coverage:** §3 flow → Tasks 2,3,6,7; §4 backend routes → Tasks 1,2,3 (GET candidates, POST resolve, scope, videoId validation, canonical upsert via `upsert_vendor_match`, `resolved`/`no_match` transitions); §5 frontend → Tasks 5,6,7 (clickable badge, popover, hooks, parser); §6 error handling → Task 5 (bad link), Task 3 (404/403/400 via schema + scope), Task 6 (onError rollback); §7 testing → every task + Task 8; OpenAPI → Task 4.
- **Status transitions:** `accept`→`vendor_track_map` + row `resolved`; `reject`→row `no_match`; both keep `fetch_ytmusic_status` correct (matched wins; no_match→not_found; no fallback to pending). Verified against the Task 9 read logic from the prior feature.
- **Type consistency:** `ReviewRow` (Task 2) consumed in Task 3; `ResolveMatchIn` (Task 1) used in Task 3; `YtMusicCandidate`/`MatchCandidatesResponse`/`ResolveMatchVars` (Task 6) consumed in Tasks 6,7; `useResolveMatch`/`useMatchCandidates` signatures identical across Tasks 6,7; `_project_candidate` reuses `result_to_ref` from the shipped `providers/ytmusic/normalize.py`.
- **No migration:** `'resolved'` reuses the existing free-form `status` column; partial indexes unaffected.
