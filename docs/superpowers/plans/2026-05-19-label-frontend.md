# Label Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship three frontend surfaces (Library browser, Admin enrichment dashboard, Curate/Categories label tile) consuming the label-enrichment backend, plus the 7 backend prerequisites that feed them.

**Architecture:** Backend gains 5 new read endpoints + 1 expansion + 1 track-payload field, all under existing routing in `src/collector/handler.py` (admin gate via `_ADMIN_ROUTES`). Frontend adds a new `features/library/` feature folder, extends `features/admin/` with an enrichment subsection, and mounts a reusable `LabelTile` into existing curate + categories players. Single OpenAPI regeneration produces all TypeScript types.

**Tech Stack:** Python 3.12 + AWS Lambda + RDS Data API (backend); React 19 + TypeScript + Vite + Mantine 9 + TanStack Query 5 + React Router 7 (frontend); Vitest + MSW + RTL (frontend tests); pytest (backend tests).

**Branch:** `docs/label-frontend-spec` — rename to `feat/label-frontend` in Task 0.1 once first commit lands.

**Spec:** `docs/superpowers/specs/2026-05-19-label-frontend-design.md` (commit a1173cd).

**Deliberate deviation from spec:** the spec proposes a generic `<EntityDetailLayout>` shell to be reused by artists in v2. This plan composes `LabelDetailPage` directly (header + tabs + sidebar Grid) without extracting the shell — YAGNI. Extracting the shell when artists actually land is a small refactor with concrete requirements; doing it now would be speculative.

---

## Phase 0 — Setup

### Task 0.1: Rename branch to `feat/label-frontend`

**Files:** none (git operation only).

- [ ] **Step 1: Rename current branch**

```bash
git branch -m docs/label-frontend-spec feat/label-frontend
git status
```

Expected: `On branch feat/label-frontend`.

- [ ] **Step 2: Verify baseline tests pass before changes**

```bash
PYTHONPATH=src python -m pytest tests/unit -q --no-header 2>&1 | tail -5
```

Expected: all tests pass. If failing, fix or document existing failures before proceeding.

- [ ] **Step 3: Verify frontend baseline**

```bash
cd frontend && pnpm test --run 2>&1 | tail -5 && cd ..
```

Expected: all tests pass.

---

## Phase 1 — Backend prerequisites

Order: B1 → B2 → B3 → B4 → B5 → B6 → B7. Each adds an endpoint or payload field with TDD: failing test → implementation → passing test → commit. ROUTES table updates and OpenAPI regen happen once at the end of Phase 1 (Tasks 1.8 + 1.9) to batch the openapi diff.

### Task 1.1 (B1): Add `label_id` to triage `BucketTrack` payload

**Files:**
- Modify: `src/collector/repositories.py` — find the bucket-tracks query and add the join
- Modify: `src/collector/handler.py` — find the bucket-tracks list response shaping
- Test: `tests/unit/test_handler_triage.py` (existing) OR new `tests/unit/test_bucket_tracks_label_id.py`

- [ ] **Step 1: Locate the bucket-tracks read path**

```bash
grep -rn "buckets.*tracks\|bucket_tracks\|find_bucket_tracks\|/triage/blocks" src/collector/ | head -20
```

Use grep output to identify the exact function/file. The handler exposes `GET /triage/blocks/{block_id}/buckets/{bucket_id}/tracks`.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_bucket_tracks_label_id.py`:

```python
"""Triage bucket tracks must expose label_id (FE label tile prerequisite)."""

from unittest.mock import MagicMock
import json


def test_bucket_tracks_response_includes_label_id(monkeypatch):
    """The track row returned by GET /triage/blocks/{}/buckets/{}/tracks must include label_id."""
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.find_bucket_tracks.return_value = [
        {
            "track_id": "t-1",
            "title": "Drift",
            "mix_name": None,
            "isrc": None,
            "bpm": 174,
            "length_ms": 360_000,
            "publish_date": "2026-04-01",
            "spotify_release_date": "2026-04-01",
            "spotify_id": None,
            "release_type": "single",
            "is_ai_suspected": False,
            "artists": ["Artist A"],
            "label_name": "Cool Label",
            "label_id": "lbl-1",
            "added_at": "2026-04-01T08:00:00Z",
        }
    ]
    fake_repo.count_bucket_tracks.return_value = 1
    monkeypatch.setattr(handler, "_build_repository", lambda: fake_repo)

    event = {
        "routeKey": "GET /triage/blocks/{block_id}/buckets/{bucket_id}/tracks",
        "pathParameters": {"block_id": "b-1", "bucket_id": "bk-1"},
        "queryStringParameters": {"limit": "50", "offset": "0"},
        "requestContext": {"authorizer": {"lambda": {"is_admin": False, "user_id": "u-1"}}},
    }
    resp = handler.lambda_handler(event, None)
    body = json.loads(resp["body"])
    assert body["items"][0]["label_id"] == "lbl-1"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_bucket_tracks_label_id.py -v
```

Expected: FAIL — either route shape differs OR `label_id` missing from response shaping. Read the failure to confirm WHICH layer drops the field.

- [ ] **Step 4: Add `label_id` to the SQL query and row mapping**

Open `src/collector/repositories.py`, find `find_bucket_tracks` (or analogue identified in Step 1). The SQL likely selects `l.name AS label_name LEFT JOIN clouder_labels l ON l.id = a.label_id`. Add `l.id AS label_id` to the SELECT and the resulting dict.

Example shape (adjust to match the existing function):

```python
"""Find tracks in a bucket; include label_id for FE tile fetch."""
rows = self._data_api.execute(
    """
    SELECT t.id AS track_id, t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
           a.publish_date, a.spotify_release_date, t.spotify_id,
           a.release_type, t.is_ai_suspected,
           l.id AS label_id,
           l.name AS label_name,
           ...
    FROM clouder_tracks t
    LEFT JOIN clouder_albums a ON a.id = t.album_id
    LEFT JOIN clouder_labels l ON l.id = a.label_id
    WHERE ...
    """,
    {...},
)
```

If the handler does any explicit allow-list of fields, also add `"label_id"` there.

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_bucket_tracks_label_id.py -v
```

Expected: PASS.

- [ ] **Step 6: Run wider triage tests to verify no regression**

```bash
PYTHONPATH=src python -m pytest tests/unit -q -k triage 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_bucket_tracks_label_id.py src/collector/repositories.py src/collector/handler.py
git commit -m "$(cat <<'EOF'
feat(backend): expose label_id on triage bucket tracks

Frontend label tile (curate + categories players) needs label_id to
fetch enriched label info. The list endpoint already returns label_name;
add label_id alongside it via JOIN with clouder_labels.
EOF
)"
```

---

### Task 1.2 (B2): `GET /labels` user-facing list endpoint

**Files:**
- Create: `tests/unit/test_handler_labels_list.py`
- Modify: `src/collector/label_enrichment/repository.py` — add `list_labels` method
- Modify: `src/collector/label_enrichment/routes.py` — add `handle_get_labels_list`
- Modify: `src/collector/handler.py` — register `GET /labels` route (not admin)

- [ ] **Step 1: Write the failing test**

```python
"""GET /labels returns paginated label list with style/q/sort filters."""

import json
from unittest.mock import MagicMock


def _user_event(qs: dict) -> dict:
    return {
        "routeKey": "GET /labels",
        "queryStringParameters": qs,
        "pathParameters": {},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "u-1"}}
        },
    }


def test_list_labels_returns_items_and_next_cursor(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_labels.return_value = (
        [
            {
                "id": "lbl-1",
                "name": "Fokuz",
                "style": "drum-and-bass",
                "status": "completed",
                "info": {
                    "tagline": "soulful d&b",
                    "country": "NL",
                    "primary_styles": ["liquid"],
                    "activity": "steady",
                    "updated_at": "2026-05-19T00:00:00Z",
                },
            }
        ],
        "cursor-2",
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )

    resp = handler.lambda_handler(
        _user_event({"style": "drum-and-bass", "limit": "50"}),
        None,
    )
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["items"][0]["id"] == "lbl-1"
    assert body["items"][0]["info"]["tagline"] == "soulful d&b"
    assert body["next_cursor"] == "cursor-2"
    fake_repo.list_labels.assert_called_once_with(
        style="drum-and-bass", q=None, sort="name", cursor=None, limit=50,
    )


def test_list_labels_passes_q_and_sort(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_labels.return_value = ([], None)
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )

    handler.lambda_handler(
        _user_event({"style": "techno", "q": "fok", "sort": "recent", "cursor": "abc"}),
        None,
    )
    fake_repo.list_labels.assert_called_once_with(
        style="techno", q="fok", sort="recent", cursor="abc", limit=50,
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_labels_list.py -v
```

Expected: FAIL — route not found / `list_labels` not defined.

- [ ] **Step 3: Implement `list_labels` repository method**

Add to `src/collector/label_enrichment/repository.py` (place after `get_label_by_id`):

```python
def list_labels(
    self,
    *,
    style: str | None,
    q: str | None,
    sort: str,
    cursor: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    """User-facing label list with cursor pagination.

    Cursor format: opaque base64 of "<name>|<id>" for stable sort.
    Returns (items, next_cursor or None).
    """
    import base64

    where = ["1=1"]
    params: dict[str, Any] = {"lim": limit + 1}
    if style:
        where.append(
            "EXISTS (SELECT 1 FROM clouder_albums a "
            "JOIN clouder_tracks t ON t.album_id = a.id "
            "JOIN clouder_styles s ON s.id = t.style_id "
            "WHERE a.label_id = lbl.id AND s.name = :style)"
        )
        params["style"] = style
    if q:
        where.append("LOWER(lbl.name) LIKE :q")
        params["q"] = f"{q.lower()}%"
    if cursor:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            last_name, last_id = decoded.rsplit("|", 1)
        except Exception:
            last_name, last_id = "", ""
        if sort == "recent":
            # cursor is updated_at|id
            where.append("(li.updated_at, lbl.id) < (:cur_ts, :cur_id)")
            params["cur_ts"] = last_name
            params["cur_id"] = last_id
        else:
            where.append("(lbl.name, lbl.id) > (:cur_name, :cur_id)")
            params["cur_name"] = last_name
            params["cur_id"] = last_id

    order_by = "li.updated_at DESC, lbl.id DESC" if sort == "recent" else "lbl.name ASC, lbl.id ASC"

    rows = self._data_api.execute(
        f"""
        SELECT lbl.id, lbl.name,
               COALESCE(li.status, 'none') AS status,
               li.tagline, li.country, li.primary_styles, li.activity, li.updated_at,
               (
                 SELECT s.name FROM clouder_styles s
                 JOIN clouder_tracks t ON t.style_id = s.id
                 JOIN clouder_albums a ON a.id = t.album_id
                 WHERE a.label_id = lbl.id
                 GROUP BY s.name ORDER BY COUNT(*) DESC LIMIT 1
               ) AS dominant_style
        FROM clouder_labels lbl
        LEFT JOIN clouder_label_info li ON li.label_id = lbl.id
        WHERE {' AND '.join(where)}
        ORDER BY {order_by}
        LIMIT :lim
        """,
        params,
    )

    has_more = len(rows) > limit
    page = rows[:limit]

    items = []
    for r in page:
        info = None
        if r.get("status") == "completed":
            primary = r.get("primary_styles")
            if isinstance(primary, str):
                primary = json.loads(primary)
            info = {
                "tagline": r.get("tagline"),
                "country": r.get("country"),
                "primary_styles": primary or [],
                "activity": r.get("activity") or "unknown",
                "updated_at": r.get("updated_at"),
            }
        items.append({
            "id": r["id"],
            "name": r["name"],
            "style": r.get("dominant_style") or "music",
            "status": r.get("status") or "none",
            "info": info,
        })

    next_cursor = None
    if has_more and page:
        last = page[-1]
        if sort == "recent":
            raw = f"{last.get('updated_at')}|{last['id']}"
        else:
            raw = f"{last['name']}|{last['id']}"
        next_cursor = base64.urlsafe_b64encode(raw.encode()).decode()

    return items, next_cursor
```

- [ ] **Step 4: Implement `handle_get_labels_list` route handler**

Add to `src/collector/label_enrichment/routes.py`:

```python
def handle_get_labels_list(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    style = (qs.get("style") or "").strip() or None
    q = (qs.get("q") or "").strip() or None
    sort = (qs.get("sort") or "name").strip()
    if sort not in ("name", "recent"):
        raise ValidationError("sort must be 'name' or 'recent'")
    cursor = (qs.get("cursor") or "").strip() or None
    try:
        limit = int(qs.get("limit") or "50")
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")

    repo = _build_repository()
    items, next_cursor = repo.list_labels(
        style=style, q=q, sort=sort, cursor=cursor, limit=limit,
    )
    return 200, {"items": items, "next_cursor": next_cursor}
```

- [ ] **Step 5: Register the route in `src/collector/handler.py`**

Inside `_route`, **before** the `_ADMIN_ROUTES` check (so non-admin reaches it), or simply outside admin set — add:

```python
if route_key == "GET /labels":
    from .label_enrichment.routes import handle_get_labels_list
    status, body = handle_get_labels_list(event)
    return _json_response(status, body, correlation_id)
```

Add the route key to authentication allow-list if there is one. (Search `_extract_route_key` callers for any allowlist.) Do NOT add it to `_ADMIN_ROUTES` — user-facing.

- [ ] **Step 6: Run test to verify it passes**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_labels_list.py -v
```

Expected: PASS both tests.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_handler_labels_list.py src/collector/label_enrichment/repository.py src/collector/label_enrichment/routes.py src/collector/handler.py
git commit -m "$(cat <<'EOF'
feat(backend): add GET /labels user-facing list endpoint

Paginated list of labels with cursor + filters (style, q prefix on name,
sort by name|recent). Joins clouder_label_info to attach a compact
"info" object for completed enrichments; null otherwise. Not admin-gated.
EOF
)"
```

---

### Task 1.3 (B3): `GET /labels/{label_id}` user-facing detail

**Files:**
- Create: `tests/unit/test_handler_labels_detail.py`
- Modify: `src/collector/label_enrichment/routes.py` — add `handle_get_label_user`
- Modify: `src/collector/handler.py` — register `GET /labels/{label_id}` route

- [ ] **Step 1: Write the failing test**

```python
"""GET /labels/{id} returns sanitized LabelInfo for completed labels."""

import json
from unittest.mock import MagicMock


def _user_event(label_id: str) -> dict:
    return {
        "routeKey": "GET /labels/{label_id}",
        "pathParameters": {"label_id": label_id},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "u-1"}}
        },
    }


def test_get_label_user_returns_sanitized_payload(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_info_for_user.return_value = {
        "label_name": "Fokuz",
        "country": "NL",
        "tagline": "soulful d&b",
        "summary": "Rotterdam liquid label.",
        "primary_styles": ["liquid"],
        "website": "https://fokuzrecordings.com",
        "ai_content": "none_detected",
        "ai_reasoning": "no signals",
    }
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_user_event("lbl-1"), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["label_name"] == "Fokuz"
    # Admin-only fields must not leak
    for forbidden in ("run_id", "prompt_version", "token_cost", "provenance"):
        assert forbidden not in body, f"{forbidden} leaked to user-facing endpoint"


def test_get_label_user_returns_404_when_not_completed(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_label_info_for_user.return_value = None
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_user_event("lbl-x"), None)
    assert resp["statusCode"] == 404
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_labels_detail.py -v
```

Expected: FAIL.

- [ ] **Step 3: Add `get_label_info_for_user` to repository**

Add to `src/collector/label_enrichment/repository.py`:

```python
# Admin-only fields stripped from user-facing responses.
_USER_FACING_FORBIDDEN = frozenset({
    "run_id", "prompt_slug", "prompt_version",
    "vendors_used", "merged_at_run_id",
    "token_cost", "cost_usd", "provenance",
})


def get_label_info_for_user(self, label_id: str) -> dict[str, Any] | None:
    """Return label_info for a user-facing detail page, or None if not completed."""
    rows = self._data_api.execute(
        """
        SELECT li.*
        FROM clouder_label_info li
        WHERE li.label_id = :id AND li.status = 'completed'
        LIMIT 1
        """,
        {"id": label_id},
    )
    if not rows:
        return None
    row = dict(rows[0])
    # Parse JSONB columns (Data API returns them as strings).
    for json_col in ("notable_artists", "primary_styles", "secondary_styles",
                     "ai_signals", "sublabels", "aliases", "sources"):
        v = row.get(json_col)
        if isinstance(v, str):
            row[json_col] = json.loads(v)
    return {k: v for k, v in row.items() if k not in _USER_FACING_FORBIDDEN}
```

- [ ] **Step 4: Add `handle_get_label_user` route handler**

In `src/collector/label_enrichment/routes.py`:

```python
def handle_get_label_user(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    label_id = (path.get("label_id") or "").strip()
    if not label_id:
        raise ValidationError("label_id is required")
    repo = _build_repository()
    row = repo.get_label_info_for_user(label_id)
    if row is None:
        return 404, {"error_code": "label_not_found", "message": "label info not available"}
    return 200, row
```

- [ ] **Step 5: Register route in `src/collector/handler.py`**

Inside `_route`:

```python
if route_key == "GET /labels/{label_id}":
    from .label_enrichment.routes import handle_get_label_user
    status, body = handle_get_label_user(event)
    return _json_response(status, body, correlation_id)
```

Not in `_ADMIN_ROUTES` — user-facing.

- [ ] **Step 6: Run test to verify it passes**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_labels_detail.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_handler_labels_detail.py src/collector/label_enrichment/repository.py src/collector/label_enrichment/routes.py src/collector/handler.py
git commit -m "$(cat <<'EOF'
feat(backend): add GET /labels/{label_id} user-facing detail endpoint

Returns sanitized LabelInfo from clouder_label_info for completed
enrichments. Strips admin-only fields (run_id, prompt_version, cost,
provenance). 404 when status != 'completed'.
EOF
)"
```

---

### Task 1.4 (B4): `GET /admin/labels/backlog`

**Files:**
- Create: `tests/unit/test_handler_labels_backlog.py`
- Modify: `src/collector/label_enrichment/repository.py` — add `list_backlog`
- Modify: `src/collector/label_enrichment/routes.py` — add `handle_get_backlog`
- Modify: `src/collector/handler.py` — register admin route

- [ ] **Step 1: Write the failing test**

```python
"""GET /admin/labels/backlog lists labels without (current) enrichment."""

import json
from unittest.mock import MagicMock


def _admin_event(qs: dict) -> dict:
    return {
        "routeKey": "GET /admin/labels/backlog",
        "queryStringParameters": qs,
        "pathParameters": {},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True}}},
    }


def test_backlog_returns_items_and_total_estimate(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_backlog.return_value = (
        [
            {"id": "lbl-1", "name": "VIM", "style": "drum-and-bass",
             "status": "failed", "track_count": 12,
             "last_attempted_at": "2026-05-12T10:00:00Z"},
            {"id": "lbl-2", "name": "Fokuz", "style": "drum-and-bass",
             "status": "none", "track_count": 142, "last_attempted_at": None},
        ],
        None,
        142,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )

    resp = handler.lambda_handler(_admin_event({"style": "drum-and-bass"}), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert len(body["items"]) == 2
    assert body["items"][0]["status"] == "failed"
    assert body["total_estimate"] == 142
    assert body["next_cursor"] is None


def test_backlog_requires_admin(monkeypatch):
    from collector import handler

    event = _admin_event({})
    event["requestContext"]["authorizer"]["lambda"]["is_admin"] = False
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 403
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_labels_backlog.py -v
```

Expected: FAIL.

- [ ] **Step 3: Add `list_backlog` to repository**

In `src/collector/label_enrichment/repository.py`:

```python
def list_backlog(
    self,
    *,
    style: str | None,
    status: str | None,
    cursor: str | None,
    limit: int,
    staleness_days: int = 180,
) -> tuple[list[dict[str, Any]], str | None, int]:
    """Labels with status in {none, failed, outdated}. Returns (items, next_cursor, total_estimate)."""
    import base64

    where = [
        "(li.status IS NULL OR li.status = 'failed' "
        "OR (li.status = 'completed' AND li.updated_at < NOW() - INTERVAL '" + str(int(staleness_days)) + " days'))"
    ]
    params: dict[str, Any] = {"lim": limit + 1}
    if style:
        where.append(
            "EXISTS (SELECT 1 FROM clouder_albums a "
            "JOIN clouder_tracks t ON t.album_id = a.id "
            "JOIN clouder_styles s ON s.id = t.style_id "
            "WHERE a.label_id = lbl.id AND s.name = :style)"
        )
        params["style"] = style
    if status:
        if status == "none":
            where.append("li.status IS NULL")
        elif status == "failed":
            where.append("li.status = 'failed'")
        elif status == "outdated":
            where.append(
                "li.status = 'completed' AND li.updated_at < NOW() - INTERVAL '"
                + str(int(staleness_days)) + " days'"
            )

    if cursor:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            last_count, last_id = decoded.rsplit("|", 1)
            params["cur_count"] = int(last_count)
            params["cur_id"] = last_id
            where.append("(track_count, lbl.id) < (:cur_count, :cur_id)")
        except Exception:
            pass

    rows = self._data_api.execute(
        f"""
        SELECT lbl.id, lbl.name,
               (
                 SELECT s.name FROM clouder_styles s
                 JOIN clouder_tracks t ON t.style_id = s.id
                 JOIN clouder_albums a ON a.id = t.album_id
                 WHERE a.label_id = lbl.id
                 GROUP BY s.name ORDER BY COUNT(*) DESC LIMIT 1
               ) AS style,
               COALESCE(
                 (SELECT COUNT(*) FROM clouder_albums a2
                  JOIN clouder_tracks t2 ON t2.album_id = a2.id
                  WHERE a2.label_id = lbl.id), 0
               ) AS track_count,
               CASE
                 WHEN li.status IS NULL THEN 'none'
                 WHEN li.status = 'failed' THEN 'failed'
                 WHEN li.status = 'completed' THEN 'outdated'
                 ELSE li.status
               END AS status,
               li.updated_at AS last_attempted_at
        FROM clouder_labels lbl
        LEFT JOIN clouder_label_info li ON li.label_id = lbl.id
        WHERE {' AND '.join(where)}
        ORDER BY track_count DESC, lbl.id DESC
        LIMIT :lim
        """,
        params,
    )

    has_more = len(rows) > limit
    page = rows[:limit]

    items = [
        {
            "id": r["id"],
            "name": r["name"],
            "style": r.get("style") or "music",
            "status": r["status"],
            "track_count": int(r.get("track_count") or 0),
            "last_attempted_at": r.get("last_attempted_at"),
        }
        for r in page
    ]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        raw = f"{last['track_count']}|{last['id']}"
        next_cursor = base64.urlsafe_b64encode(raw.encode()).decode()

    total_rows = self._data_api.execute(
        f"SELECT COUNT(*) AS c FROM clouder_labels lbl "
        f"LEFT JOIN clouder_label_info li ON li.label_id = lbl.id "
        f"WHERE {' AND '.join(where[:1] + ([w for w in where if 'cur_' not in w][1:]))}",
        {k: v for k, v in params.items() if not k.startswith("cur_")},
    )
    total_estimate = int(total_rows[0]["c"]) if total_rows else 0

    return items, next_cursor, total_estimate
```

- [ ] **Step 4: Add `handle_get_backlog` route handler**

In `routes.py`:

```python
def handle_get_backlog(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    style = (qs.get("style") or "").strip() or None
    status = (qs.get("status") or "").strip() or None
    if status and status not in ("none", "failed", "outdated"):
        raise ValidationError("status must be one of: none, failed, outdated")
    cursor = (qs.get("cursor") or "").strip() or None
    try:
        limit = int(qs.get("limit") or "100")
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")

    repo = _build_repository()
    items, next_cursor, total = repo.list_backlog(
        style=style, status=status, cursor=cursor, limit=limit,
    )
    return 200, {"items": items, "next_cursor": next_cursor, "total_estimate": total}
```

- [ ] **Step 5: Register admin route in `handler.py`**

Add `"GET /admin/labels/backlog"` to `_ADMIN_ROUTES`. Add to `_route`:

```python
if route_key == "GET /admin/labels/backlog":
    from .label_enrichment.routes import handle_get_backlog
    status, body = handle_get_backlog(event)
    return _json_response(status, body, correlation_id)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_labels_backlog.py -v
```

Expected: PASS both tests.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_handler_labels_backlog.py src/collector/label_enrichment/repository.py src/collector/label_enrichment/routes.py src/collector/handler.py
git commit -m "$(cat <<'EOF'
feat(backend): add GET /admin/labels/backlog endpoint

Lists labels with no enrichment, failed enrichment, or completed-but-stale
(>180 days). Admin-only. Returns items ordered by track count (priority
hint for batch enqueue), cursor-paginated, plus a total_estimate header.
EOF
)"
```

---

### Task 1.5 (B5): `GET /admin/labels/enrich-runs` (list)

**Files:**
- Create: `tests/unit/test_handler_labels_runs_list.py`
- Modify: `src/collector/label_enrichment/repository.py` — add `list_runs`
- Modify: `src/collector/label_enrichment/routes.py` — add `handle_get_runs_list`
- Modify: `src/collector/handler.py` — register admin route

- [ ] **Step 1: Write the failing test**

```python
"""GET /admin/labels/enrich-runs paginates enrichment runs."""

import json
from unittest.mock import MagicMock


def _admin_event(qs: dict) -> dict:
    return {
        "routeKey": "GET /admin/labels/enrich-runs",
        "queryStringParameters": qs,
        "pathParameters": {},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True}}},
    }


def test_list_runs_returns_items_sorted_by_created_at_desc(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.list_runs.return_value = (
        [
            {"id": "r-1", "status": "completed", "created_at": "2026-05-19T14:00:00Z",
             "cells_total": 3, "cells_ok": 3, "cells_error": 0, "cost_usd": 0.015,
             "prompt_slug": "label_v3_app_fields", "prompt_version": "v1",
             "vendors": ["gemini", "openai", "tavily_deepseek"]},
        ],
        None,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_admin_event({"limit": "50"}), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["items"][0]["id"] == "r-1"
    assert body["next_cursor"] is None
    fake_repo.list_runs.assert_called_once_with(status=None, cursor=None, limit=50)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_labels_runs_list.py -v
```

Expected: FAIL.

- [ ] **Step 3: Add `list_runs` to repository**

```python
def list_runs(
    self,
    *,
    status: str | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    """Admin runs list, sorted by created_at DESC."""
    import base64

    where = ["1=1"]
    params: dict[str, Any] = {"lim": limit + 1}
    if status:
        where.append("status = :status")
        params["status"] = status
    if cursor:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            last_ts, last_id = decoded.rsplit("|", 1)
            where.append("(created_at, id) < (:cur_ts::timestamptz, :cur_id)")
            params["cur_ts"] = last_ts
            params["cur_id"] = last_id
        except Exception:
            pass

    rows = self._data_api.execute(
        f"""
        SELECT id, status, prompt_slug, prompt_version, vendors, models,
               merge_vendor, merge_model, requested_labels, cells_total,
               cells_ok, cells_error, cost_usd, created_at, started_at, finished_at
        FROM clouder_label_enrichment_runs
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC, id DESC
        LIMIT :lim
        """,
        params,
    )

    has_more = len(rows) > limit
    page = rows[:limit]

    items = []
    for r in page:
        row = dict(r)
        for json_col in ("vendors", "models"):
            v = row.get(json_col)
            if isinstance(v, str):
                row[json_col] = json.loads(v)
        cost = row.get("cost_usd")
        if isinstance(cost, Decimal):
            row["cost_usd"] = float(cost)
        items.append(row)

    next_cursor = None
    if has_more and page:
        last = page[-1]
        raw = f"{last['created_at']}|{last['id']}"
        next_cursor = base64.urlsafe_b64encode(raw.encode()).decode()

    return items, next_cursor
```

- [ ] **Step 4: Add `handle_get_runs_list` route handler**

```python
def handle_get_runs_list(event: Mapping[str, Any]) -> tuple[int, dict]:
    qs = event.get("queryStringParameters") or {}
    status = (qs.get("status") or "").strip() or None
    if status and status not in ("queued", "running", "completed", "failed"):
        raise ValidationError("invalid status filter")
    cursor = (qs.get("cursor") or "").strip() or None
    try:
        limit = int(qs.get("limit") or "50")
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")
    repo = _build_repository()
    items, next_cursor = repo.list_runs(status=status, cursor=cursor, limit=limit)
    return 200, {"items": items, "next_cursor": next_cursor}
```

- [ ] **Step 5: Register admin route**

Add `"GET /admin/labels/enrich-runs"` to `_ADMIN_ROUTES`. In `_route`:

```python
if route_key == "GET /admin/labels/enrich-runs":
    from .label_enrichment.routes import handle_get_runs_list
    status, body = handle_get_runs_list(event)
    return _json_response(status, body, correlation_id)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_labels_runs_list.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_handler_labels_runs_list.py src/collector/label_enrichment/repository.py src/collector/label_enrichment/routes.py src/collector/handler.py
git commit -m "$(cat <<'EOF'
feat(backend): add GET /admin/labels/enrich-runs list endpoint

Paginated list of enrichment runs sorted by created_at desc, with
optional status filter. Same payload shape as the existing single-run
endpoint minus per-cell expansion. Admin-only.
EOF
)"
```

---

### Task 1.6 (B6): Expand `GET /admin/labels/enrich-runs/{run_id}` with `cells[]`

**Files:**
- Create: `tests/unit/test_handler_run_detail_cells.py`
- Modify: `src/collector/label_enrichment/repository.py` — add `list_cells_for_run`
- Modify: `src/collector/label_enrichment/routes.py` — extend `handle_get_run`

- [ ] **Step 1: Write the failing test**

```python
"""GET /admin/labels/enrich-runs/{run_id} now includes cells[]."""

import json
from unittest.mock import MagicMock


def _admin_event(run_id: str) -> dict:
    return {
        "routeKey": "GET /admin/labels/enrich-runs/{run_id}",
        "pathParameters": {"run_id": run_id},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True}}},
    }


def test_run_detail_includes_cells(monkeypatch):
    from collector import handler

    fake_repo = MagicMock()
    fake_repo.get_run.return_value = {
        "id": "r-1", "status": "completed",
        "cells_total": 3, "cells_ok": 3, "cells_error": 0,
    }
    fake_repo.list_cells_for_run.return_value = [
        {"cell_id": "c-1", "label_id": "l-1", "label_name": "Fokuz",
         "vendor": "gemini", "status": "ok", "latency_ms": 1200,
         "cost_usd": 0.005, "error_message": None},
        {"cell_id": "c-2", "label_id": "l-1", "label_name": "Fokuz",
         "vendor": "openai", "status": "ok", "latency_ms": 2400,
         "cost_usd": 0.006, "error_message": None},
    ]
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: fake_repo,
    )
    resp = handler.lambda_handler(_admin_event("r-1"), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert len(body["cells"]) == 2
    assert body["cells"][0]["vendor"] == "gemini"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_run_detail_cells.py -v
```

Expected: FAIL.

- [ ] **Step 3: Add `list_cells_for_run` to repository**

```python
def list_cells_for_run(self, run_id: str) -> list[dict[str, Any]]:
    rows = self._data_api.execute(
        """
        SELECT c.id AS cell_id, c.label_id, lbl.name AS label_name,
               c.vendor, c.status, c.latency_ms, c.cost_usd, c.error_message
        FROM clouder_label_enrichment_cells c
        JOIN clouder_labels lbl ON lbl.id = c.label_id
        WHERE c.run_id = :run_id
        ORDER BY c.label_id, c.vendor
        """,
        {"run_id": run_id},
    )
    items = []
    for r in rows:
        row = dict(r)
        cost = row.get("cost_usd")
        if isinstance(cost, Decimal):
            row["cost_usd"] = float(cost)
        items.append(row)
    return items
```

- [ ] **Step 4: Extend `handle_get_run` to attach cells**

In `routes.py`, replace:

```python
def handle_get_run(event: Mapping[str, Any]) -> tuple[int, dict]:
    path = event.get("pathParameters") or {}
    run_id = (path.get("run_id") or "").strip()
    if not run_id:
        raise ValidationError("run_id is required")
    repo = _build_repository()
    row = repo.get_run(run_id)
    if row is None:
        return 404, {"error_code": "not_found", "message": "run not found"}
    row["cells"] = repo.list_cells_for_run(run_id)
    return 200, row
```

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_run_detail_cells.py tests/unit/test_label_enrichment_api.py -v
```

Expected: PASS new test; no regression in existing API tests.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_handler_run_detail_cells.py src/collector/label_enrichment/repository.py src/collector/label_enrichment/routes.py
git commit -m "$(cat <<'EOF'
feat(backend): expand run detail with cells[] per-vendor breakdown

Existing GET /admin/labels/enrich-runs/{run_id} gains a `cells` array
populated from clouder_label_enrichment_cells. No pagination — runs are
capped at 100 labels x 4 vendors = 400 cells max.
EOF
)"
```

---

### Task 1.7 (B7): `GET /admin/labels/enrich/options`

**Files:**
- Create: `tests/unit/test_handler_enrich_options.py`
- Modify: `src/collector/label_enrichment/routes.py` — add `handle_get_options`
- Modify: `src/collector/handler.py` — register admin route

- [ ] **Step 1: Write the failing test**

```python
"""GET /admin/labels/enrich/options exposes vendors + prompts for FE form."""

import json


def _admin_event() -> dict:
    return {
        "routeKey": "GET /admin/labels/enrich/options",
        "queryStringParameters": None,
        "pathParameters": {},
        "requestContext": {"authorizer": {"lambda": {"is_admin": True}}},
    }


def test_enrich_options_payload_shape():
    from collector import handler

    resp = handler.lambda_handler(_admin_event(), None)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert "vendors" in body and set(body["vendors"]) <= {"gemini", "openai", "tavily_deepseek"}
    assert "prompt_versions" in body and len(body["prompt_versions"]) >= 1
    assert any(p.get("is_default") for p in body["prompt_versions"])
    assert "default_models" in body
    assert body["merge"]["vendor"] == "deepseek"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_enrich_options.py -v
```

Expected: FAIL.

- [ ] **Step 3: Add `handle_get_options`**

In `routes.py`:

```python
def handle_get_options(event: Mapping[str, Any]) -> tuple[int, dict]:
    """Static config for the admin enqueue form."""
    from .prompts import load_builtin_prompts, list_prompt_versions
    load_builtin_prompts()

    prompt_versions = list_prompt_versions()  # see prompts module
    return 200, {
        "vendors": ["gemini", "openai", "tavily_deepseek"],
        "prompt_versions": prompt_versions,
        "default_models": {
            "gemini": "gemini-2.5-pro",
            "openai": "gpt-5.1",
            "tavily_deepseek": "deepseek-chat",
        },
        "merge": {"vendor": "deepseek", "default_model": "deepseek-chat"},
    }
```

- [ ] **Step 4: Add `list_prompt_versions` helper to prompts module**

In `src/collector/label_enrichment/prompts/__init__.py` (or wherever the registry lives), add:

```python
def list_prompt_versions() -> list[dict[str, Any]]:
    """Return all loaded prompt registry entries as serializable dicts.

    Default selection: prompt with slug == 'label_v3_app_fields'.
    """
    items = []
    for slug, prompt in _registry.items():  # adjust to actual registry handle
        items.append({
            "slug": slug,
            "version": prompt.version,
            "is_default": slug == "label_v3_app_fields",
        })
    return sorted(items, key=lambda p: (not p["is_default"], p["slug"]))
```

If the registry shape differs, adapt. Verify against `src/collector/label_enrichment/prompts/registry.py`.

- [ ] **Step 5: Register admin route**

Add `"GET /admin/labels/enrich/options"` to `_ADMIN_ROUTES`. In `_route`:

```python
if route_key == "GET /admin/labels/enrich/options":
    from .label_enrichment.routes import handle_get_options
    status, body = handle_get_options(event)
    return _json_response(status, body, correlation_id)
```

- [ ] **Step 6: Run test to verify it passes**

```bash
PYTHONPATH=src python -m pytest tests/unit/test_handler_enrich_options.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/unit/test_handler_enrich_options.py src/collector/label_enrichment/routes.py src/collector/label_enrichment/prompts/__init__.py src/collector/handler.py
git commit -m "$(cat <<'EOF'
feat(backend): add GET /admin/labels/enrich/options endpoint

Static config feeding the admin enqueue form: available vendors, prompt
versions with default flag, default models per vendor, and the merge
vendor/model. Removes hardcoded vendor / version lists from FE.
EOF
)"
```

---

### Task 1.8: Regenerate OpenAPI spec

**Files:**
- Modify: `scripts/generate_openapi.py` — add 5 new route entries
- Modify: `docs/api/openapi.yaml` — regenerated artifact

- [ ] **Step 1: Add route entries to `scripts/generate_openapi.py` ROUTES table**

Find the existing label entries (around line 942 onwards). Add after the existing `GET /admin/labels/{label_id}` block, **5 new entries**:

```python
{
    "method": "get",
    "path": "/labels",
    "tags": ["labels"],
    "summary": "List labels for browsing.",
    "description": "Paginated label list. Filters: style (dominant style), q (name prefix), sort (name|recent). Cursor-paginated.",
    "parameters": [
        {"name": "style", "in": "query", "schema": {"type": "string"}},
        {"name": "q", "in": "query", "schema": {"type": "string"}},
        {"name": "sort", "in": "query", "schema": {"type": "string", "enum": ["name", "recent"]}},
        {"name": "cursor", "in": "query", "schema": {"type": "string"}},
        {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}},
    ],
    "responses": {
        "200": {
            "description": "Paginated labels.",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/LabelsListResponse"}}},
        },
        "401": {"$ref": "#/components/responses/Unauthorized"},
    },
},
{
    "method": "get",
    "path": "/labels/{label_id}",
    "tags": ["labels"],
    "summary": "Get user-facing label detail.",
    "description": "Returns sanitized LabelInfo for completed enrichments. 404 when info not available.",
    "parameters": [
        {"name": "label_id", "in": "path", "required": True, "schema": {"type": "string"}},
    ],
    "responses": {
        "200": {"description": "Label info.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/LabelDetail"}}}},
        "404": {"description": "label_not_found.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}},
    },
},
{
    "method": "get",
    "path": "/admin/labels/backlog",
    "tags": ["labels-admin"],
    "summary": "Admin: list labels missing enrichment.",
    "description": "Labels with no info, failed, or completed-but-outdated. Cursor-paginated. Sorted by track_count DESC.",
    "parameters": [
        {"name": "style", "in": "query", "schema": {"type": "string"}},
        {"name": "status", "in": "query", "schema": {"type": "string", "enum": ["none", "failed", "outdated"]}},
        {"name": "cursor", "in": "query", "schema": {"type": "string"}},
        {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100}},
    ],
    "responses": {
        "200": {"description": "Backlog page.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/BacklogResponse"}}}},
        "403": {"$ref": "#/components/responses/AdminRequired"},
    },
},
{
    "method": "get",
    "path": "/admin/labels/enrich-runs",
    "tags": ["labels-admin"],
    "summary": "Admin: list enrichment runs.",
    "parameters": [
        {"name": "status", "in": "query", "schema": {"type": "string", "enum": ["queued", "running", "completed", "failed"]}},
        {"name": "cursor", "in": "query", "schema": {"type": "string"}},
        {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}},
    ],
    "responses": {
        "200": {"description": "Runs list.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/RunsListResponse"}}}},
        "403": {"$ref": "#/components/responses/AdminRequired"},
    },
},
{
    "method": "get",
    "path": "/admin/labels/enrich/options",
    "tags": ["labels-admin"],
    "summary": "Admin: static config for the enqueue form.",
    "responses": {
        "200": {"description": "Form options.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/EnrichmentOptions"}}}},
        "403": {"$ref": "#/components/responses/AdminRequired"},
    },
},
```

Also extend the existing `GET /admin/labels/enrich-runs/{run_id}` response schema to declare the new `cells` array (look for `LABEL_ENRICH_RUN` schema block and add `cells` field).

Add component schemas to the same script (search where `LABEL_ENRICH_REQUEST` is defined; add new schemas below it):

```python
"LabelSummary": {
    "type": "object",
    "required": ["id", "name", "style", "status"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "style": {"type": "string"},
        "status": {"type": "string", "enum": ["none", "queued", "running", "completed", "failed", "outdated"]},
        "info": {
            "type": "object",
            "nullable": True,
            "properties": {
                "tagline": {"type": "string", "nullable": True},
                "country": {"type": "string", "nullable": True},
                "primary_styles": {"type": "array", "items": {"type": "string"}},
                "activity": {"type": "string", "enum": ["unknown", "dormant", "low", "steady", "high", "fire_hose"]},
                "updated_at": {"type": "string", "format": "date-time"},
            },
        },
    },
},
"LabelsListResponse": {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {"type": "array", "items": {"$ref": "#/components/schemas/LabelSummary"}},
        "next_cursor": {"type": "string", "nullable": True},
    },
},
"LabelDetail": {
    "type": "object",
    "description": "Sanitized LabelInfo (admin-only fields stripped).",
    "additionalProperties": True,
},
"BacklogLabel": {
    "type": "object",
    "required": ["id", "name", "style", "status", "track_count"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "style": {"type": "string"},
        "status": {"type": "string", "enum": ["none", "failed", "outdated"]},
        "track_count": {"type": "integer"},
        "last_attempted_at": {"type": "string", "format": "date-time", "nullable": True},
    },
},
"BacklogResponse": {
    "type": "object",
    "required": ["items", "total_estimate"],
    "properties": {
        "items": {"type": "array", "items": {"$ref": "#/components/schemas/BacklogLabel"}},
        "next_cursor": {"type": "string", "nullable": True},
        "total_estimate": {"type": "integer"},
    },
},
"RunsListResponse": {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {"type": "array", "items": {"$ref": "#/components/schemas/LABEL_ENRICH_RUN"}},
        "next_cursor": {"type": "string", "nullable": True},
    },
},
"EnrichmentOptions": {
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
},
```

Also add the `cells` field to the existing `LABEL_ENRICH_RUN` schema (search for it):

```python
"cells": {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["cell_id", "label_id", "label_name", "vendor", "status", "latency_ms", "cost_usd"],
        "properties": {
            "cell_id": {"type": "string"},
            "label_id": {"type": "string"},
            "label_name": {"type": "string"},
            "vendor": {"type": "string"},
            "status": {"type": "string", "enum": ["ok", "error"]},
            "latency_ms": {"type": "integer"},
            "cost_usd": {"type": "number"},
            "error_message": {"type": "string", "nullable": True},
        },
    },
},
```

- [ ] **Step 2: Regenerate openapi.yaml**

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
```

Expected: writes `docs/api/openapi.yaml`. Confirm the 5 new paths appear:

```bash
grep -n "/labels\|/admin/labels/backlog\|/enrich/options\|/enrich-runs:" docs/api/openapi.yaml
```

- [ ] **Step 3: Commit**

```bash
git add scripts/generate_openapi.py docs/api/openapi.yaml
git commit -m "$(cat <<'EOF'
docs(api): regen openapi for new label endpoints

Adds GET /labels, GET /labels/{id}, GET /admin/labels/backlog,
GET /admin/labels/enrich-runs (list), GET /admin/labels/enrich/options.
Extends GET /admin/labels/enrich-runs/{run_id} with cells[].
EOF
)"
```

---

### Task 1.9: Regenerate frontend `schema.d.ts`

**Files:**
- Modify: `frontend/src/api/schema.d.ts` — regenerated artifact

- [ ] **Step 1: Regenerate**

```bash
cd frontend && pnpm api:types && cd ..
```

Expected: `schema.d.ts` updated.

- [ ] **Step 2: Verify new paths present**

```bash
grep -n '"/labels"\|"/admin/labels/backlog"\|"/admin/labels/enrich/options"' frontend/src/api/schema.d.ts
```

Expected: all three paths appear.

- [ ] **Step 3: Confirm frontend still typechecks**

```bash
cd frontend && pnpm typecheck && cd ..
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/schema.d.ts
git commit -m "$(cat <<'EOF'
chore(frontend): regen schema.d.ts after openapi update
EOF
)"
```

---

**END PHASE 1** — Backend now exposes all data the frontend needs. Run full backend test suite:

```bash
PYTHONPATH=src python -m pytest tests/unit -q 2>&1 | tail -3
```

Expected: all pass.

---

## Phase 2 — Shared frontend types + i18n keys

### Task 2.1: Add `frontend/src/api/labels.ts` type re-exports

**Files:**
- Create: `frontend/src/api/labels.ts`

- [ ] **Step 1: Create the file**

```typescript
// frontend/src/api/labels.ts
import type { paths } from './schema';

export type LabelSummary       = paths['/labels']['get']['responses'][200]['content']['application/json']['items'][number];
export type LabelsListResponse = paths['/labels']['get']['responses'][200]['content']['application/json'];
export type LabelDetail        = paths['/labels/{label_id}']['get']['responses'][200]['content']['application/json'];
export type BacklogLabel       = paths['/admin/labels/backlog']['get']['responses'][200]['content']['application/json']['items'][number];
export type BacklogResponse    = paths['/admin/labels/backlog']['get']['responses'][200]['content']['application/json'];
export type RunSummary         = paths['/admin/labels/enrich-runs']['get']['responses'][200]['content']['application/json']['items'][number];
export type RunsListResponse   = paths['/admin/labels/enrich-runs']['get']['responses'][200]['content']['application/json'];
export type RunDetail          = paths['/admin/labels/enrich-runs/{run_id}']['get']['responses'][200]['content']['application/json'];
export type RunCell            = NonNullable<RunDetail['cells']>[number];
export type EnrichmentOptions  = paths['/admin/labels/enrich/options']['get']['responses'][200]['content']['application/json'];
export type EnrichBody         = paths['/admin/labels/enrich']['post']['requestBody']['content']['application/json'];
```

- [ ] **Step 2: Verify it typechecks**

```bash
cd frontend && pnpm typecheck && cd ..
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/labels.ts
git commit -m "$(cat <<'EOF'
feat(frontend): add label type re-exports from generated schema

Single source of truth for label-related shapes consumed by Library,
Admin enrichment, and the triage tile. Any backend rename surfaces as a
TypeScript error.
EOF
)"
```

---

### Task 2.2: Add i18n keys (EN)

**Files:**
- Modify: `frontend/src/i18n/locales/en/translation.json` (or wherever the EN file lives)

- [ ] **Step 1: Locate the EN translation file**

```bash
find frontend/src/i18n -name '*.json' -o -name '*.ts' | head
```

Use the path identified (commonly `frontend/src/i18n/locales/en.json` or similar).

- [ ] **Step 2: Append keys**

Add the following sections to the EN translation object (placement matches existing structure — top-level keys, peer to `admin`, `triage`, etc.):

```json
{
  "library": {
    "page_title": "Library",
    "list": {
      "title": "Labels",
      "empty_filter": "No labels match these filters.",
      "info_pending": "Info pending",
      "search_placeholder": "Search labels...",
      "sort_label": "Sort",
      "sort_name": "Name (A→Z)",
      "sort_recent": "Recently updated",
      "load_more": "Load more"
    },
    "entity_tabs": {
      "labels": "Labels",
      "artists": "Artists",
      "artists_coming_soon": "Coming soon"
    },
    "detail": {
      "back_to_list": "Back to {{style}}",
      "no_info_title": "Information not yet collected",
      "no_info_body": "This label hasn't been enriched yet.",
      "admin_enqueue_cta": "Enqueue enrichment",
      "tab_overview": "Overview",
      "tab_styles": "Styles",
      "tab_links": "Links",
      "founded": "Founded {{year}}",
      "notable_artists": "Notable artists",
      "primary_styles": "Primary styles",
      "secondary_styles": "Secondary styles",
      "ai_content_label": "AI content",
      "ai_reasoning": "Reasoning",
      "ai_reasoning_collapsed": "Show reasoning"
    },
    "tile": {
      "read_more": "Read more →"
    },
    "channels": {
      "website": "Website",
      "bandcamp": "Bandcamp",
      "soundcloud": "SoundCloud",
      "beatport": "Beatport",
      "residentadvisor": "Resident Advisor",
      "discogs": "Discogs",
      "instagram": "Instagram",
      "twitter": "Twitter"
    },
    "activity": {
      "unknown": "Unknown",
      "dormant": "Dormant",
      "low": "Low activity",
      "steady": "Steady",
      "high": "High activity",
      "fire_hose": "Fire hose"
    }
  },
  "admin_enrichment": {
    "tabs": {
      "backlog": "Enrichment backlog",
      "runs": "Enrichment runs"
    },
    "backlog": {
      "title": "Labels missing info",
      "filter_style": "Style",
      "filter_status": "Status",
      "status_none": "No info",
      "status_failed": "Failed",
      "status_outdated": "Outdated",
      "col_name": "Label",
      "col_style": "Style",
      "col_status": "Status",
      "col_tracks": "Tracks",
      "col_last_try": "Last attempt",
      "selected_summary": "Selected: {{count}}",
      "enqueue_button": "Enqueue {{count}} labels",
      "empty": "Caught up! No labels missing info."
    },
    "enqueue_drawer": {
      "title": "Enqueue {{count}} labels for enrichment",
      "vendors_label": "Vendors",
      "prompt_label": "Prompt version",
      "models_label": "Models per vendor",
      "merge_vendor_label": "Merge vendor",
      "merge_model_label": "Merge model",
      "submit": "Enqueue",
      "submit_inflight": "Enqueueing...",
      "success_notification": "Enqueued {{count}} labels. Run: {{run_id}}",
      "error_notification": "Enqueue failed: {{message}}"
    },
    "runs": {
      "title": "Enrichment runs",
      "col_created": "Created",
      "col_id": "Run id",
      "col_status": "Status",
      "col_cells": "Cells (ok/err/total)",
      "col_cost": "Cost",
      "filter_status": "Status",
      "empty": "No runs yet."
    },
    "run_detail": {
      "back_to_runs": "Back to runs",
      "tab_summary": "Summary",
      "tab_cells": "Cells",
      "tab_json": "Raw JSON",
      "counters_total": "Total",
      "counters_ok": "Ok",
      "counters_err": "Errors",
      "vendor_breakdown": "Per-vendor breakdown",
      "copy_json": "Copy JSON",
      "json_copied": "Copied"
    },
    "status": {
      "queued": "Queued",
      "running": "Running",
      "completed": "Completed",
      "failed": "Failed"
    }
  }
}
```

- [ ] **Step 3: Verify JSON is valid**

```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/locales/en.json','utf8'))" || echo "FAIL — adjust path"
```

Expected: silent (no output) means valid. If path differs, adjust the `find` from Step 1.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/locales/en.json
git commit -m "$(cat <<'EOF'
feat(frontend): add EN i18n keys for label features

Three top-level sections (library, admin_enrichment) covering the
Library browser, admin enrichment dashboard, and triage tile copy.
EOF
)"
```

> RU translations are added in Phase 6.

---

## Phase 3 — Library (Surface 1)

### Task 3.1: lib helpers — `channelMeta`, `countryFlag`, `pickTopChannels`, `formatLabel`

**Files:**
- Create: `frontend/src/features/library/lib/channelMeta.ts`
- Create: `frontend/src/features/library/lib/countryFlag.ts`
- Create: `frontend/src/features/library/lib/pickTopChannels.ts`
- Create: `frontend/src/features/library/lib/formatLabel.ts`
- Create: `frontend/src/features/library/lib/__tests__/pickTopChannels.test.ts`
- Create: `frontend/src/features/library/lib/__tests__/countryFlag.test.ts`

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/features/library/lib/__tests__/pickTopChannels.test.ts
import { describe, it, expect } from 'vitest';
import { pickTopChannels } from '../pickTopChannels';

describe('pickTopChannels', () => {
  it('prioritises website > soundcloud > bandcamp', () => {
    const result = pickTopChannels({
      website: 'https://a',
      bandcamp_url: 'https://b',
      soundcloud_url: 'https://c',
    }, 3);
    expect(result.map(c => c.kind)).toEqual(['website', 'soundcloud', 'bandcamp']);
  });

  it('skips null URLs', () => {
    const result = pickTopChannels({
      website: null,
      soundcloud_url: 'https://s',
      bandcamp_url: null,
    }, 3);
    expect(result.map(c => c.kind)).toEqual(['soundcloud']);
  });

  it('respects the limit', () => {
    const result = pickTopChannels({
      website: 'a', soundcloud_url: 'b', bandcamp_url: 'c',
      beatport_url: 'd', instagram_url: 'e',
    }, 2);
    expect(result).toHaveLength(2);
  });
});
```

```typescript
// frontend/src/features/library/lib/__tests__/countryFlag.test.ts
import { describe, it, expect } from 'vitest';
import { countryFlag } from '../countryFlag';

describe('countryFlag', () => {
  it('emits the regional-indicator emoji for ISO-2', () => {
    expect(countryFlag('NL')).toBe('🇳🇱');
    expect(countryFlag('us')).toBe('🇺🇸');
  });
  it('returns empty string for invalid input', () => {
    expect(countryFlag(null)).toBe('');
    expect(countryFlag('XX1')).toBe('');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm vitest run src/features/library/lib --no-coverage 2>&1 | tail -5 && cd ..
```

Expected: FAIL — modules not found.

- [ ] **Step 3: Implement `countryFlag.ts`**

```typescript
// frontend/src/features/library/lib/countryFlag.ts
export function countryFlag(iso2: string | null | undefined): string {
  if (!iso2 || iso2.length !== 2) return '';
  const upper = iso2.toUpperCase();
  if (!/^[A-Z]{2}$/.test(upper)) return '';
  const A = 0x1F1E6;
  return String.fromCodePoint(A + upper.charCodeAt(0) - 65)
       + String.fromCodePoint(A + upper.charCodeAt(1) - 65);
}
```

- [ ] **Step 4: Implement `channelMeta.ts`**

```typescript
// frontend/src/features/library/lib/channelMeta.ts
import type { ComponentType } from 'react';
import {
  IconWorld,
  IconBrandBandcamp,
  IconBrandSoundcloud,
  IconBrandInstagram,
  IconBrandTwitter,
  IconLink,
} from '@tabler/icons-react';

export type ChannelKind =
  | 'website'
  | 'bandcamp'
  | 'soundcloud'
  | 'beatport'
  | 'residentadvisor'
  | 'discogs'
  | 'instagram'
  | 'twitter';

export interface ChannelMeta {
  kind: ChannelKind;
  /** LabelInfo field name where the URL is stored. */
  field:
    | 'website'
    | 'bandcamp_url'
    | 'soundcloud_url'
    | 'beatport_url'
    | 'residentadvisor_url'
    | 'discogs_url'
    | 'instagram_url'
    | 'twitter_url';
  Icon: ComponentType<{ size?: number }>;
  i18nKey: string;
}

/** Iteration order = display order. */
export const CHANNELS: ReadonlyArray<ChannelMeta> = [
  { kind: 'website',          field: 'website',          Icon: IconWorld,            i18nKey: 'library.channels.website' },
  { kind: 'bandcamp',         field: 'bandcamp_url',     Icon: IconBrandBandcamp,    i18nKey: 'library.channels.bandcamp' },
  { kind: 'soundcloud',       field: 'soundcloud_url',   Icon: IconBrandSoundcloud,  i18nKey: 'library.channels.soundcloud' },
  { kind: 'beatport',         field: 'beatport_url',     Icon: IconLink,             i18nKey: 'library.channels.beatport' },
  { kind: 'residentadvisor',  field: 'residentadvisor_url', Icon: IconLink,         i18nKey: 'library.channels.residentadvisor' },
  { kind: 'discogs',          field: 'discogs_url',      Icon: IconLink,             i18nKey: 'library.channels.discogs' },
  { kind: 'instagram',        field: 'instagram_url',    Icon: IconBrandInstagram,   i18nKey: 'library.channels.instagram' },
  { kind: 'twitter',          field: 'twitter_url',      Icon: IconBrandTwitter,     i18nKey: 'library.channels.twitter' },
];
```

If any `@tabler/icons-react` symbol does not exist, substitute with `IconLink` from the same package — verify with `grep -r "IconBrand" frontend/node_modules/@tabler/icons-react/dist 2>/dev/null | head` after the first failed import.

- [ ] **Step 5: Implement `pickTopChannels.ts`**

```typescript
// frontend/src/features/library/lib/pickTopChannels.ts
import { CHANNELS, type ChannelMeta } from './channelMeta';

type ChannelSource = Partial<Record<ChannelMeta['field'], string | null | undefined>>;

export interface PickedChannel extends ChannelMeta {
  url: string;
}

export function pickTopChannels(source: ChannelSource, limit: number): PickedChannel[] {
  const result: PickedChannel[] = [];
  for (const ch of CHANNELS) {
    const url = source[ch.field];
    if (typeof url === 'string' && url.length > 0) {
      result.push({ ...ch, url });
      if (result.length >= limit) break;
    }
  }
  return result;
}
```

- [ ] **Step 6: Implement `formatLabel.ts`**

```typescript
// frontend/src/features/library/lib/formatLabel.ts
export function truncateTagline(tagline: string | null | undefined, maxChars = 120): string {
  if (!tagline) return '';
  if (tagline.length <= maxChars) return tagline;
  return tagline.slice(0, maxChars - 1) + '…';
}
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd frontend && pnpm vitest run src/features/library/lib --no-coverage && cd ..
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/library/
git commit -m "$(cat <<'EOF'
feat(frontend): add library lib helpers

countryFlag (ISO-2 → emoji), channelMeta (display order + icons),
pickTopChannels (priority-ordered URL picker for the tile), and
truncateTagline. Used across Library list, detail, and tile.
EOF
)"
```

---

### Task 3.2: `useLabelsList` hook

**Files:**
- Create: `frontend/src/features/library/hooks/useLabelsList.ts`
- Create: `frontend/src/features/library/hooks/__tests__/useLabelsList.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useLabelsList } from '../useLabelsList';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useLabelsList', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches the first page with style + q + sort params', async () => {
    let received = '';
    server.use(
      http.get('http://localhost/labels', ({ request }) => {
        received = request.url;
        return HttpResponse.json({
          items: [{ id: 'l1', name: 'A', style: 'dnb', status: 'completed', info: null }],
          next_cursor: 'cur2',
        });
      }),
    );
    const { result } = renderHook(
      () => useLabelsList({ styleId: 'dnb', q: 'foo', sort: 'recent' }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(received).toContain('style=dnb');
    expect(received).toContain('q=foo');
    expect(received).toContain('sort=recent');
  });

  it('paginates via next_cursor', async () => {
    server.use(
      http.get('http://localhost/labels', ({ request }) => {
        const url = new URL(request.url);
        const cursor = url.searchParams.get('cursor');
        return HttpResponse.json({
          items: [{ id: cursor ?? 'first', name: 'X', style: 'dnb', status: 'none', info: null }],
          next_cursor: cursor ? null : 'cur2',
        });
      }),
    );
    const { result } = renderHook(
      () => useLabelsList({ styleId: 'dnb', q: '', sort: 'name' }),
      { wrapper: wrap() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await result.current.fetchNextPage();
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
    expect(result.current.data?.pages[1]?.items[0]?.id).toBe('cur2');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm vitest run src/features/library/hooks/__tests__/useLabelsList.test.tsx && cd ..
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement the hook**

```typescript
// frontend/src/features/library/hooks/useLabelsList.ts
import { useInfiniteQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { LabelsListResponse } from '../../../api/labels';

export interface UseLabelsListParams {
  styleId: string;
  q: string;
  sort: 'name' | 'recent';
}

export const labelsListKey = (params: UseLabelsListParams) =>
  ['library', 'labels', params.styleId, params.q, params.sort] as const;

export function useLabelsList(params: UseLabelsListParams) {
  return useInfiniteQuery<LabelsListResponse, Error>({
    queryKey: labelsListKey(params),
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      if (params.styleId) qs.set('style', params.styleId);
      if (params.q) qs.set('q', params.q);
      qs.set('sort', params.sort);
      if (pageParam) qs.set('cursor', String(pageParam));
      return api<LabelsListResponse>(`/labels?${qs.toString()}`);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm vitest run src/features/library/hooks/__tests__/useLabelsList.test.tsx && cd ..
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/library/hooks/
git commit -m "feat(frontend): add useLabelsList hook"
```

---

### Task 3.3: `useLabelDetail` + `useLabelInfo` hooks

**Files:**
- Create: `frontend/src/features/library/hooks/useLabelDetail.ts`
- Create: `frontend/src/features/library/hooks/useLabelInfo.ts`
- Create: `frontend/src/features/library/hooks/__tests__/useLabelDetail.test.tsx`
- Create: `frontend/src/features/library/hooks/__tests__/useLabelInfo.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// useLabelDetail.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useLabelDetail } from '../useLabelDetail';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useLabelDetail', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('does not fetch when labelId is null', () => {
    const { result } = renderHook(() => useLabelDetail(null), { wrapper: wrap() });
    expect(result.current.fetchStatus).toBe('idle');
  });

  it('fetches detail when labelId is present', async () => {
    server.use(
      http.get('http://localhost/labels/abc', () =>
        HttpResponse.json({ label_name: 'Fokuz', country: 'NL' }),
      ),
    );
    const { result } = renderHook(() => useLabelDetail('abc'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.label_name).toBe('Fokuz');
  });
});
```

```tsx
// useLabelInfo.test.tsx — identical except imports from useLabelInfo and tests cache-key separation
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useLabelInfo, labelInfoKey } from '../useLabelInfo';
import { labelDetailKey } from '../useLabelDetail';

describe('useLabelInfo', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('uses a different cache key than useLabelDetail', () => {
    expect(labelInfoKey('x')).not.toEqual(labelDetailKey('x'));
  });

  it('returns null result silently on 404', async () => {
    server.use(
      http.get('http://localhost/labels/x', () =>
        HttpResponse.json({ error_code: 'label_not_found', message: 'nope' }, { status: 404 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useLabelInfo('x'), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm vitest run src/features/library/hooks/__tests__/useLabelDetail.test.tsx src/features/library/hooks/__tests__/useLabelInfo.test.tsx && cd ..
```

Expected: FAIL.

- [ ] **Step 3: Implement `useLabelDetail.ts`**

```typescript
// frontend/src/features/library/hooks/useLabelDetail.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { LabelDetail } from '../../../api/labels';

export const labelDetailKey = (id: string | null) => ['library', 'labelDetail', id] as const;

export function useLabelDetail(labelId: string | null) {
  return useQuery<LabelDetail, Error>({
    queryKey: labelDetailKey(labelId),
    queryFn: () => api<LabelDetail>(`/labels/${labelId}`),
    enabled: !!labelId,
    staleTime: 5 * 60_000,
  });
}
```

- [ ] **Step 4: Implement `useLabelInfo.ts`**

```typescript
// frontend/src/features/library/hooks/useLabelInfo.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import type { LabelDetail } from '../../../api/labels';

export const labelInfoKey = (id: string | null | undefined) => ['labelInfo', id] as const;

export function useLabelInfo(labelId: string | null | undefined) {
  return useQuery<LabelDetail, Error>({
    queryKey: labelInfoKey(labelId),
    queryFn: () => api<LabelDetail>(`/labels/${labelId}`),
    enabled: !!labelId,
    staleTime: 5 * 60_000,
    retry: (count, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return count < 1;
    },
  });
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd frontend && pnpm vitest run src/features/library/hooks/__tests__ && cd ..
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/library/hooks/
git commit -m "$(cat <<'EOF'
feat(frontend): add useLabelDetail and useLabelInfo hooks

Different cache keys so the Library detail page and the triage tile do
not invalidate each other. useLabelInfo skips retry on 404 so missing
data renders nothing silently.
EOF
)"
```

---

### Task 3.4: Library presentational components — `EntityTabs`, `LibraryFilters`, `LabelCard`

**Files:**
- Create: `frontend/src/features/library/components/EntityTabs.tsx`
- Create: `frontend/src/features/library/components/LibraryFilters.tsx`
- Create: `frontend/src/features/library/components/LabelCard.tsx`
- Create: `frontend/src/features/library/components/__tests__/EntityTabs.test.tsx`
- Create: `frontend/src/features/library/components/__tests__/LabelCard.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// EntityTabs.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
import { EntityTabs } from '../EntityTabs';

function renderWith(active: 'labels' | 'artists') {
  return render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter><EntityTabs active={active} styleId="dnb" /></MemoryRouter>
    </I18nextProvider>
  );
}

describe('EntityTabs', () => {
  it('renders Labels and Artists tabs', () => {
    renderWith('labels');
    expect(screen.getByText('Labels')).toBeInTheDocument();
    expect(screen.getByText('Artists')).toBeInTheDocument();
  });
  it('disables the Artists tab', () => {
    renderWith('labels');
    const artistsTab = screen.getByText('Artists').closest('button');
    expect(artistsTab).toHaveAttribute('data-disabled');
  });
});
```

```tsx
// LabelCard.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
import { LabelCard } from '../LabelCard';

const COMPLETED = {
  id: 'l1', name: 'Fokuz', style: 'dnb', status: 'completed' as const,
  info: {
    tagline: 'soulful d&b', country: 'NL',
    primary_styles: ['liquid', 'jazzstep'], activity: 'steady',
    updated_at: '2026-05-19T00:00:00Z',
  },
};

const PENDING = {
  id: 'l2', name: 'Unknown', style: 'dnb', status: 'none' as const, info: null,
};

function renderCard(item: any) {
  return render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter><LabelCard item={item} styleId="dnb" /></MemoryRouter>
    </I18nextProvider>
  );
}

describe('LabelCard', () => {
  it('renders tagline + styles for completed labels', () => {
    renderCard(COMPLETED);
    expect(screen.getByText('Fokuz')).toBeInTheDocument();
    expect(screen.getByText('soulful d&b')).toBeInTheDocument();
    expect(screen.getByText('liquid')).toBeInTheDocument();
  });
  it('renders pending placeholder when no info', () => {
    renderCard(PENDING);
    expect(screen.getByText('Info pending')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm vitest run src/features/library/components/__tests__ && cd ..
```

Expected: FAIL.

- [ ] **Step 3: Implement `EntityTabs.tsx`**

```tsx
// frontend/src/features/library/components/EntityTabs.tsx
import { Tabs, Tooltip } from '@mantine/core';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';

interface Props {
  active: 'labels' | 'artists';
  styleId: string;
}

export function EntityTabs({ active, styleId }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <Tabs
      value={active}
      onChange={(v) => v === 'labels' && navigate(`/library/${styleId}`)}
    >
      <Tabs.List>
        <Tabs.Tab value="labels">{t('library.entity_tabs.labels')}</Tabs.Tab>
        <Tooltip label={t('library.entity_tabs.artists_coming_soon')}>
          <Tabs.Tab value="artists" data-disabled disabled>
            {t('library.entity_tabs.artists')}
          </Tabs.Tab>
        </Tooltip>
      </Tabs.List>
    </Tabs>
  );
}
```

- [ ] **Step 4: Implement `LibraryFilters.tsx`**

```tsx
// frontend/src/features/library/components/LibraryFilters.tsx
import { Group, TextInput, Select } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useState, useEffect } from 'react';

interface Props {
  q: string;
  sort: 'name' | 'recent';
  onQChange: (q: string) => void;
  onSortChange: (sort: 'name' | 'recent') => void;
}

export function LibraryFilters({ q, sort, onQChange, onSortChange }: Props) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(q);

  useEffect(() => setDraft(q), [q]);
  useEffect(() => {
    const id = setTimeout(() => {
      if (draft !== q) onQChange(draft);
    }, 250);
    return () => clearTimeout(id);
  }, [draft, q, onQChange]);

  return (
    <Group gap="sm">
      <TextInput
        placeholder={t('library.list.search_placeholder')}
        value={draft}
        onChange={(e) => setDraft(e.currentTarget.value)}
        style={{ minWidth: 240 }}
      />
      <Select
        label={t('library.list.sort_label')}
        value={sort}
        data={[
          { value: 'name', label: t('library.list.sort_name') },
          { value: 'recent', label: t('library.list.sort_recent') },
        ]}
        onChange={(v) => v && onSortChange(v as 'name' | 'recent')}
      />
    </Group>
  );
}
```

- [ ] **Step 5: Implement `LabelCard.tsx`**

```tsx
// frontend/src/features/library/components/LabelCard.tsx
import { Card, Group, Text, Badge, Stack } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { LabelSummary } from '../../../api/labels';
import { countryFlag } from '../lib/countryFlag';
import { truncateTagline } from '../lib/formatLabel';

interface Props {
  item: LabelSummary;
  styleId: string;
}

export function LabelCard({ item, styleId }: Props) {
  const { t } = useTranslation();
  const hasInfo = item.status === 'completed' && item.info != null;
  const primary = item.info?.primary_styles ?? [];
  const visible = primary.slice(0, 3);
  const overflow = primary.length - visible.length;

  return (
    <Card
      component={Link}
      to={`/library/${styleId}/labels/${item.id}`}
      withBorder
      padding="md"
      style={{ cursor: 'pointer', textDecoration: 'none' }}
    >
      <Group gap="xs">
        {item.info?.country && <Text>{countryFlag(item.info.country)}</Text>}
        <Text fw={600}>{item.name}</Text>
      </Group>
      {hasInfo ? (
        <Stack gap="xs" mt="sm">
          <Text size="sm" lineClamp={2}>
            {truncateTagline(item.info?.tagline)}
          </Text>
          <Group gap={4}>
            {visible.map((s) => <Badge key={s} variant="light">{s}</Badge>)}
            {overflow > 0 && <Badge variant="outline">+{overflow}</Badge>}
          </Group>
        </Stack>
      ) : (
        <Badge color="gray" mt="sm">{t('library.list.info_pending')}</Badge>
      )}
    </Card>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd frontend && pnpm vitest run src/features/library/components/__tests__ && cd ..
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/library/components/
git commit -m "$(cat <<'EOF'
feat(frontend): add EntityTabs, LibraryFilters, LabelCard

Three presentational pieces for the Library list page. EntityTabs keeps
the URL shape future-proof for Artists v2. LabelCard renders both
completed and pending states.
EOF
)"
```

---

### Task 3.5: `LabelListGrid` + `LabelTile` + `LabelTileSkeleton`

**Files:**
- Create: `frontend/src/features/library/components/LabelListGrid.tsx`
- Create: `frontend/src/features/library/components/LabelTile.tsx`
- Create: `frontend/src/features/library/components/LabelTileSkeleton.tsx`
- Create: `frontend/src/features/library/components/__tests__/LabelTile.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// LabelTile.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { LabelTile } from '../LabelTile';

function renderTile(labelId: string | null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <LabelTile labelId={labelId} styleId="dnb" />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>
  );
}

describe('LabelTile', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders null when labelId is null', () => {
    const { container } = renderTile(null);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders null on 404', async () => {
    server.use(
      http.get('http://localhost/labels/missing', () =>
        HttpResponse.json({ error_code: 'label_not_found', message: 'nope' }, { status: 404 }),
      ),
    );
    const { container } = renderTile('missing');
    await waitFor(() => expect(container).toBeEmptyDOMElement(), { timeout: 1500 });
  });

  it('renders the label name when fetch succeeds', async () => {
    server.use(
      http.get('http://localhost/labels/abc', () =>
        HttpResponse.json({
          label_name: 'Fokuz',
          country: 'NL',
          tagline: 'soulful d&b',
          website: 'https://fokuzrecordings.com',
          soundcloud_url: 'https://soundcloud.com/fokuz',
        }),
      ),
    );
    renderTile('abc');
    await waitFor(() => expect(screen.getByText('Fokuz')).toBeInTheDocument());
    expect(screen.getByText('soulful d&b')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm vitest run src/features/library/components/__tests__/LabelTile.test.tsx && cd ..
```

Expected: FAIL.

- [ ] **Step 3: Implement `LabelTileSkeleton.tsx`**

```tsx
// frontend/src/features/library/components/LabelTileSkeleton.tsx
import { Card, Skeleton } from '@mantine/core';

export function LabelTileSkeleton() {
  return (
    <Card withBorder padding="md" w={320}>
      <Skeleton height={20} mb="sm" />
      <Skeleton height={32} mb="sm" />
      <Skeleton height={24} />
    </Card>
  );
}
```

- [ ] **Step 4: Implement `LabelTile.tsx`**

```tsx
// frontend/src/features/library/components/LabelTile.tsx
import { Anchor, ActionIcon, Card, Group, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useLabelInfo } from '../hooks/useLabelInfo';
import { countryFlag } from '../lib/countryFlag';
import { pickTopChannels } from '../lib/pickTopChannels';
import { LabelTileSkeleton } from './LabelTileSkeleton';

interface Props {
  labelId: string | null | undefined;
  styleId: string;
}

export function LabelTile({ labelId, styleId }: Props) {
  const { t } = useTranslation();
  const query = useLabelInfo(labelId);

  if (!labelId) return null;
  if (query.isLoading) return <LabelTileSkeleton />;
  if (query.isError || !query.data) return null;

  const info = query.data;
  const channels = pickTopChannels(info, 3);
  const detailUrl = `/library/${styleId}/labels/${labelId}`;

  return (
    <Card withBorder padding="md" w={320}>
      <Stack gap="xs">
        <Group gap="xs">
          {info.country && <Text>{countryFlag(info.country)}</Text>}
          <Anchor component={Link} to={detailUrl} fw={600}>
            {info.label_name}
          </Anchor>
        </Group>
        <Text size="sm" lineClamp={2}>
          {info.tagline ?? info.summary ?? ''}
        </Text>
        <Group gap={6}>
          {channels.map((ch) => (
            <ActionIcon
              key={ch.kind}
              component="a"
              href={ch.url}
              target="_blank"
              rel="noopener noreferrer"
              variant="subtle"
              aria-label={t(ch.i18nKey)}
            >
              <ch.Icon size={16} />
            </ActionIcon>
          ))}
        </Group>
        <Anchor component={Link} to={detailUrl} size="sm">
          {t('library.tile.read_more')}
        </Anchor>
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 5: Implement `LabelListGrid.tsx`**

```tsx
// frontend/src/features/library/components/LabelListGrid.tsx
import { useEffect, useRef } from 'react';
import { SimpleGrid, Button, Center, Text, Skeleton } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { LabelSummary } from '../../../api/labels';
import { LabelCard } from './LabelCard';

interface Props {
  items: LabelSummary[];
  styleId: string;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  isLoading: boolean;
  onLoadMore: () => void;
}

export function LabelListGrid(props: Props) {
  const { t } = useTranslation();
  const sentinel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!props.hasNextPage) return;
    const el = sentinel.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => entries[0]?.isIntersecting && props.onLoadMore(),
      { rootMargin: '200px' },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [props.hasNextPage, props.onLoadMore]);

  if (props.isLoading) {
    return (
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} height={140} />)}
      </SimpleGrid>
    );
  }

  if (props.items.length === 0) {
    return <Center mt="lg"><Text c="dimmed">{t('library.list.empty_filter')}</Text></Center>;
  }

  return (
    <>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {props.items.map((item) => (
          <LabelCard key={item.id} item={item} styleId={props.styleId} />
        ))}
      </SimpleGrid>
      <div ref={sentinel} />
      {props.hasNextPage && (
        <Center mt="md">
          <Button onClick={props.onLoadMore} loading={props.isFetchingNextPage} variant="default">
            {t('library.list.load_more')}
          </Button>
        </Center>
      )}
    </>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd frontend && pnpm vitest run src/features/library/components/__tests__/LabelTile.test.tsx && cd ..
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/library/components/
git commit -m "$(cat <<'EOF'
feat(frontend): add LabelListGrid + LabelTile + skeleton

LabelTile is reused by curate and categories players in Phase 5.
LabelListGrid uses IntersectionObserver for infinite scroll plus a
"Load more" button fallback for mobile.
EOF
)"
```

---

### Task 3.6: `LabelDetailHeader`, `LabelChannelLinks`, `LabelOverviewTab`, `LabelStylesTab`

**Files:**
- Create: `frontend/src/features/library/components/LabelDetailHeader.tsx`
- Create: `frontend/src/features/library/components/LabelChannelLinks.tsx`
- Create: `frontend/src/features/library/components/LabelOverviewTab.tsx`
- Create: `frontend/src/features/library/components/LabelStylesTab.tsx`

- [ ] **Step 1: Implement `LabelDetailHeader.tsx`**

```tsx
// frontend/src/features/library/components/LabelDetailHeader.tsx
import { Group, Title, Badge, Text, Anchor } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { LabelDetail } from '../../../api/labels';
import { countryFlag } from '../lib/countryFlag';

interface Props {
  info: LabelDetail;
  styleId: string;
}

export function LabelDetailHeader({ info, styleId }: Props) {
  const { t } = useTranslation();
  const status = (info as { status?: string }).status ?? 'unknown';
  return (
    <>
      <Anchor component={Link} to={`/library/${styleId}`} size="sm">
        ← {t('library.detail.back_to_list', { style: styleId })}
      </Anchor>
      <Group gap="md" mt="xs" align="center">
        <Title order={2}>{info.label_name}</Title>
        <Badge color={status === 'active' ? 'green' : 'gray'}>{status}</Badge>
      </Group>
      <Group gap="xs" mt="xs">
        {info.country && <Text>{countryFlag(info.country)} {info.country}</Text>}
        {info.founded_year && (
          <Text c="dimmed">· {t('library.detail.founded', { year: info.founded_year })}</Text>
        )}
      </Group>
    </>
  );
}
```

- [ ] **Step 2: Implement `LabelChannelLinks.tsx`**

```tsx
// frontend/src/features/library/components/LabelChannelLinks.tsx
import { Stack, ActionIcon, Group, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { LabelDetail } from '../../../api/labels';
import { CHANNELS } from '../lib/channelMeta';

export function LabelChannelLinks({ info }: { info: LabelDetail }) {
  const { t } = useTranslation();
  return (
    <Stack gap="xs">
      {CHANNELS.map((ch) => {
        const url = (info as Record<string, unknown>)[ch.field];
        if (typeof url !== 'string' || !url) return null;
        return (
          <Group key={ch.kind} gap="xs">
            <ActionIcon
              component="a"
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              variant="subtle"
              aria-label={t(ch.i18nKey)}
            >
              <ch.Icon size={18} />
            </ActionIcon>
            <Text size="sm">{t(ch.i18nKey)}</Text>
          </Group>
        );
      })}
    </Stack>
  );
}
```

- [ ] **Step 3: Implement `LabelOverviewTab.tsx`**

```tsx
// frontend/src/features/library/components/LabelOverviewTab.tsx
import { Stack, Text, Title, Badge, Group } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { LabelDetail } from '../../../api/labels';

export function LabelOverviewTab({ info }: { info: LabelDetail }) {
  const { t } = useTranslation();
  const notable = (info.notable_artists ?? []) as string[];
  return (
    <Stack gap="md">
      {info.tagline && <Text fw={500}>{info.tagline}</Text>}
      {info.summary && (
        <Text style={{ whiteSpace: 'pre-wrap' }}>{info.summary}</Text>
      )}
      {notable.length > 0 && (
        <>
          <Title order={5}>{t('library.detail.notable_artists')}</Title>
          <Group gap={6}>
            {notable.map((a) => <Badge key={a} variant="outline">{a}</Badge>)}
          </Group>
        </>
      )}
    </Stack>
  );
}
```

- [ ] **Step 4: Implement `LabelStylesTab.tsx`**

```tsx
// frontend/src/features/library/components/LabelStylesTab.tsx
import { Stack, Title, Badge, Group, Text, Collapse, UnstyledButton } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import type { LabelDetail } from '../../../api/labels';

export function LabelStylesTab({ info }: { info: LabelDetail }) {
  const { t } = useTranslation();
  const [opened, { toggle }] = useDisclosure(false);
  const primary = (info.primary_styles ?? []) as string[];
  const secondary = (info.secondary_styles ?? []) as string[];

  return (
    <Stack gap="md">
      {primary.length > 0 && (
        <>
          <Title order={5}>{t('library.detail.primary_styles')}</Title>
          <Group gap={6}>
            {primary.map((s) => <Badge key={s}>{s}</Badge>)}
          </Group>
        </>
      )}
      {secondary.length > 0 && (
        <>
          <Title order={5}>{t('library.detail.secondary_styles')}</Title>
          <Group gap={6}>
            {secondary.map((s) => <Badge key={s} variant="outline">{s}</Badge>)}
          </Group>
        </>
      )}
      {info.ai_content && (
        <Group gap="xs">
          <Text fw={500}>{t('library.detail.ai_content_label')}:</Text>
          <Badge color={info.ai_content === 'none_detected' ? 'green' : 'yellow'}>
            {info.ai_content}
          </Badge>
        </Group>
      )}
      {info.ai_reasoning && (
        <>
          <UnstyledButton onClick={toggle} c="dimmed">
            {opened ? t('library.detail.ai_reasoning') : t('library.detail.ai_reasoning_collapsed')}
          </UnstyledButton>
          <Collapse in={opened}>
            <Text size="sm" c="dimmed">{info.ai_reasoning}</Text>
          </Collapse>
        </>
      )}
    </Stack>
  );
}
```

- [ ] **Step 5: Verify typecheck**

```bash
cd frontend && pnpm typecheck && cd ..
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/library/components/
git commit -m "$(cat <<'EOF'
feat(frontend): add label detail tab components

LabelDetailHeader, LabelChannelLinks, LabelOverviewTab, LabelStylesTab.
Consumed by LabelDetailPage; channel links also re-rendered as the
mobile "Links" tab via the same component.
EOF
)"
```

---

### Task 3.7: Library route pages — `LibraryIndexRedirect`, `LibraryListPage`, `LabelDetailPage`

**Files:**
- Create: `frontend/src/features/library/routes/LibraryIndexRedirect.tsx`
- Create: `frontend/src/features/library/routes/LibraryListPage.tsx`
- Create: `frontend/src/features/library/routes/LabelDetailPage.tsx`
- Create: `frontend/src/features/library/index.ts`

- [ ] **Step 1: Implement `LibraryIndexRedirect.tsx`**

```tsx
// frontend/src/features/library/routes/LibraryIndexRedirect.tsx
import { Navigate } from 'react-router';

const DEFAULT_STYLE = 'drum-and-bass';

export function LibraryIndexRedirect() {
  return <Navigate to={`/library/${DEFAULT_STYLE}`} replace />;
}
```

- [ ] **Step 2: Implement `LibraryListPage.tsx`**

```tsx
// frontend/src/features/library/routes/LibraryListPage.tsx
import { Container, Stack, Title } from '@mantine/core';
import { useParams, useSearchParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useLabelsList } from '../hooks/useLabelsList';
import { EntityTabs } from '../components/EntityTabs';
import { LibraryFilters } from '../components/LibraryFilters';
import { LabelListGrid } from '../components/LabelListGrid';

export function LibraryListPage() {
  const { t } = useTranslation();
  const { styleId } = useParams<{ styleId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  if (!styleId) return <Navigate to="/library" replace />;

  const q = searchParams.get('q') ?? '';
  const rawSort = searchParams.get('sort');
  const sort: 'name' | 'recent' = rawSort === 'recent' ? 'recent' : 'name';

  const query = useLabelsList({ styleId, q, sort });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  };

  return (
    <Container size="lg" py="md">
      <Stack gap="md">
        <Title order={2}>{t('library.list.title')}</Title>
        <EntityTabs active="labels" styleId={styleId} />
        <LibraryFilters
          q={q}
          sort={sort}
          onQChange={(v) => updateParam('q', v)}
          onSortChange={(v) => updateParam('sort', v)}
        />
        <LabelListGrid
          items={items}
          styleId={styleId}
          isLoading={query.isLoading}
          hasNextPage={!!query.hasNextPage}
          isFetchingNextPage={query.isFetchingNextPage}
          onLoadMore={() => query.fetchNextPage()}
        />
      </Stack>
    </Container>
  );
}
```

- [ ] **Step 3: Implement `LabelDetailPage.tsx`**

```tsx
// frontend/src/features/library/routes/LabelDetailPage.tsx
import { Container, Grid, Tabs, Card, Title, Text, Button, Stack } from '@mantine/core';
import { useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { useLabelDetail } from '../hooks/useLabelDetail';
import { LabelDetailHeader } from '../components/LabelDetailHeader';
import { LabelChannelLinks } from '../components/LabelChannelLinks';
import { LabelOverviewTab } from '../components/LabelOverviewTab';
import { LabelStylesTab } from '../components/LabelStylesTab';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { getAuthSnapshot } from '../../../auth/AuthProvider';

export function LabelDetailPage() {
  const { t } = useTranslation();
  const { styleId, labelId } = useParams<{ styleId: string; labelId: string }>();
  if (!styleId || !labelId) return <Navigate to="/library" replace />;

  const query = useLabelDetail(labelId);
  const isAdmin = !!getAuthSnapshot().user?.is_admin;

  if (query.isLoading) return <FullScreenLoader />;
  if (query.isError) {
    const is404 = query.error instanceof ApiError && query.error.status === 404;
    if (is404) {
      return (
        <Container py="md">
          <Stack gap="sm">
            <Title order={3}>{t('library.detail.no_info_title')}</Title>
            <Text c="dimmed">{t('library.detail.no_info_body')}</Text>
            {isAdmin && (
              <Button component="a" href={`/admin/labels/enrich?label_id=${labelId}`}>
                {t('library.detail.admin_enqueue_cta')}
              </Button>
            )}
          </Stack>
        </Container>
      );
    }
    throw query.error;
  }
  if (!query.data) return null;
  const info = query.data;

  return (
    <Container size="lg" py="md">
      <Grid>
        <Grid.Col span={{ base: 12, lg: 9 }}>
          <Stack gap="md">
            <LabelDetailHeader info={info} styleId={styleId} />
            <Tabs defaultValue="overview">
              <Tabs.List>
                <Tabs.Tab value="overview">{t('library.detail.tab_overview')}</Tabs.Tab>
                <Tabs.Tab value="styles">{t('library.detail.tab_styles')}</Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="overview" pt="md">
                <LabelOverviewTab info={info} />
              </Tabs.Panel>
              <Tabs.Panel value="styles" pt="md">
                <LabelStylesTab info={info} />
              </Tabs.Panel>
            </Tabs>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 3 }}>
          <Card withBorder padding="md">
            <Title order={5} mb="sm">{t('library.detail.tab_links')}</Title>
            <LabelChannelLinks info={info} />
          </Card>
        </Grid.Col>
      </Grid>
    </Container>
  );
}
```

- [ ] **Step 4: Add `index.ts` for the feature**

```typescript
// frontend/src/features/library/index.ts
export { LibraryIndexRedirect } from './routes/LibraryIndexRedirect';
export { LibraryListPage } from './routes/LibraryListPage';
export { LabelDetailPage } from './routes/LabelDetailPage';
export { LabelTile } from './components/LabelTile';
```

- [ ] **Step 5: Verify typecheck**

```bash
cd frontend && pnpm typecheck && cd ..
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/library/routes/ frontend/src/features/library/index.ts
git commit -m "$(cat <<'EOF'
feat(frontend): add Library route pages

LibraryIndexRedirect (→ /library/drum-and-bass), LibraryListPage, and
LabelDetailPage. Detail page handles the 404 empty state with an
admin-only enqueue CTA.
EOF
)"
```

---

### Task 3.8: Wire Library routes into router

**Files:**
- Modify: `frontend/src/routes/router.tsx`

- [ ] **Step 1: Add imports + route block**

In `frontend/src/routes/router.tsx`, add imports near the top:

```tsx
import { LibraryIndexRedirect, LibraryListPage, LabelDetailPage } from '../features/library';
```

Then add the `library` route group inside the `AppShellLayout` children array, before `playlists`:

```tsx
{
  path: 'library',
  children: [
    { index: true, element: <LibraryIndexRedirect /> },
    { path: ':styleId', element: <LibraryListPage /> },
    { path: ':styleId/labels/:labelId', element: <LabelDetailPage /> },
  ],
},
```

- [ ] **Step 2: Smoke test routes**

```bash
cd frontend && pnpm test --run -- src/__tests__ 2>&1 | tail -10 && cd ..
```

Existing global smoke tests should still pass. Confirm `pnpm typecheck` clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/router.tsx
git commit -m "feat(frontend): wire library routes"
```

---

## Phase 4 — Admin enrichment dashboard (Surface 2)

### Task 4.1: Admin hooks — `useEnrichmentOptions`, `useLabelBacklog`, `useEnrichmentRuns`, `useEnrichmentRunDetail`, `useEnqueueEnrichment`

**Files:**
- Create: `frontend/src/features/admin/hooks/useEnrichmentOptions.ts`
- Create: `frontend/src/features/admin/hooks/useLabelBacklog.ts`
- Create: `frontend/src/features/admin/hooks/useEnrichmentRuns.ts`
- Create: `frontend/src/features/admin/hooks/useEnrichmentRunDetail.ts`
- Create: `frontend/src/features/admin/hooks/useEnqueueEnrichment.ts`
- Create one test file per hook under `frontend/src/features/admin/hooks/__tests__/`

- [ ] **Step 1: Implement hooks (no new tests for each — covered by component tests + a single MSW-style test below)**

```typescript
// useEnrichmentOptions.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { EnrichmentOptions } from '../../../api/labels';

export function useEnrichmentOptions() {
  return useQuery<EnrichmentOptions, Error>({
    queryKey: ['admin', 'enrichment', 'options'],
    queryFn: () => api<EnrichmentOptions>('/admin/labels/enrich/options'),
    staleTime: 30 * 60_000,
  });
}
```

```typescript
// useLabelBacklog.ts
import { useInfiniteQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { BacklogResponse } from '../../../api/labels';

export interface UseLabelBacklogParams {
  style: string;
  status: 'all' | 'none' | 'failed' | 'outdated';
}

export const labelBacklogKey = (p: UseLabelBacklogParams) =>
  ['admin', 'labelBacklog', p.style, p.status] as const;

export function useLabelBacklog(p: UseLabelBacklogParams) {
  return useInfiniteQuery<BacklogResponse, Error>({
    queryKey: labelBacklogKey(p),
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      if (p.style) qs.set('style', p.style);
      if (p.status !== 'all') qs.set('status', p.status);
      qs.set('limit', '100');
      if (pageParam) qs.set('cursor', String(pageParam));
      return api<BacklogResponse>(`/admin/labels/backlog?${qs.toString()}`);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}
```

```typescript
// useEnrichmentRuns.ts
import { useInfiniteQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { RunsListResponse } from '../../../api/labels';

export interface UseRunsParams {
  status: 'all' | 'queued' | 'running' | 'completed' | 'failed';
}

export function useEnrichmentRuns(p: UseRunsParams) {
  const anyInflight = (data: { pages: RunsListResponse[] } | undefined) =>
    data?.pages.some((page) =>
      page.items.some((r) => r.status === 'queued' || r.status === 'running'),
    ) ?? false;

  return useInfiniteQuery<RunsListResponse, Error>({
    queryKey: ['admin', 'enrichmentRuns', p.status] as const,
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      if (p.status !== 'all') qs.set('status', p.status);
      qs.set('limit', '50');
      if (pageParam) qs.set('cursor', String(pageParam));
      return api<RunsListResponse>(`/admin/labels/enrich-runs?${qs.toString()}`);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    refetchInterval: (qry) => (anyInflight(qry.state.data) ? 5_000 : false),
  });
}
```

```typescript
// useEnrichmentRunDetail.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { RunDetail } from '../../../api/labels';

export function useEnrichmentRunDetail(runId: string | null) {
  return useQuery<RunDetail, Error>({
    queryKey: ['admin', 'enrichmentRun', runId] as const,
    queryFn: () => api<RunDetail>(`/admin/labels/enrich-runs/${runId}`),
    enabled: !!runId,
    refetchInterval: (qry) => {
      const s = qry.state.data?.status;
      return s === 'queued' || s === 'running' ? 5_000 : false;
    },
  });
}
```

```typescript
// useEnqueueEnrichment.ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { EnrichBody } from '../../../api/labels';

interface EnqueueResponse { run_id: string; queued_labels: number; }

export function useEnqueueEnrichment() {
  const qc = useQueryClient();
  return useMutation<EnqueueResponse, Error, EnrichBody>({
    mutationFn: (body) =>
      api<EnqueueResponse>('/admin/labels/enrich', {
        method: 'POST',
        body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'labelBacklog'] });
      qc.invalidateQueries({ queryKey: ['admin', 'enrichmentRuns'] });
    },
  });
}
```

- [ ] **Step 2: Write one MSW test for `useEnqueueEnrichment`**

```tsx
// frontend/src/features/admin/hooks/__tests__/useEnqueueEnrichment.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useEnqueueEnrichment } from '../useEnqueueEnrichment';

describe('useEnqueueEnrichment', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs the enrich body and returns run_id', async () => {
    server.use(
      http.post('http://localhost/admin/labels/enrich', () =>
        HttpResponse.json({ run_id: 'r-1', queued_labels: 3 }, { status: 202 }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useEnqueueEnrichment(), { wrapper });
    const promise = result.current.mutateAsync({
      labels: [{ label_id: 'l1' }],
      vendors: ['gemini'],
      models: { gemini: 'gemini-2.5-pro' },
      prompt_slug: 'label_v3_app_fields',
      prompt_version: 'v1',
      merge_vendor: 'deepseek',
      merge_model: 'deepseek-chat',
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const res = await promise;
    expect(res.run_id).toBe('r-1');
  });
});
```

- [ ] **Step 3: Run tests and typecheck**

```bash
cd frontend && pnpm vitest run src/features/admin/hooks/__tests__ && pnpm typecheck && cd ..
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/admin/hooks/
git commit -m "$(cat <<'EOF'
feat(frontend): add admin enrichment hooks

useEnrichmentOptions (form config), useLabelBacklog (paginated backlog),
useEnrichmentRuns (paginated runs with 5s polling while jobs in-flight),
useEnrichmentRunDetail (run detail with same polling), and
useEnqueueEnrichment (POST mutation invalidating backlog + runs).
EOF
)"
```

---

### Task 4.2: Admin components — backlog (toolbar, table) + status badge

**Files:**
- Create: `frontend/src/features/admin/components/enrichment/RunStatusBadge.tsx`
- Create: `frontend/src/features/admin/components/enrichment/BacklogToolbar.tsx`
- Create: `frontend/src/features/admin/components/enrichment/BacklogTable.tsx`

- [ ] **Step 1: Implement `RunStatusBadge.tsx`**

```tsx
// frontend/src/features/admin/components/enrichment/RunStatusBadge.tsx
import { Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';

const COLORS: Record<string, string> = {
  queued: 'gray', running: 'blue', completed: 'green', failed: 'red',
  none: 'gray', outdated: 'yellow',
};

export function RunStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const key = `admin_enrichment.status.${status}`;
  const label = t(key, { defaultValue: status });
  return <Badge color={COLORS[status] ?? 'gray'}>{label}</Badge>;
}
```

- [ ] **Step 2: Implement `BacklogToolbar.tsx`**

```tsx
// frontend/src/features/admin/components/enrichment/BacklogToolbar.tsx
import { Group, Select, Text, Button } from '@mantine/core';
import { useTranslation } from 'react-i18next';

interface Props {
  style: string;
  onStyleChange: (style: string) => void;
  status: 'all' | 'none' | 'failed' | 'outdated';
  onStatusChange: (s: 'all' | 'none' | 'failed' | 'outdated') => void;
  selectedCount: number;
  onEnqueueClick: () => void;
}

export function BacklogToolbar(p: Props) {
  const { t } = useTranslation();
  return (
    <Group justify="space-between">
      <Group gap="sm">
        <Select
          label={t('admin_enrichment.backlog.filter_style')}
          value={p.style}
          onChange={(v) => v != null && p.onStyleChange(v)}
          data={[
            { value: '', label: 'all' },
            { value: 'drum-and-bass', label: 'drum-and-bass' },
            { value: 'techno', label: 'techno' },
            { value: 'house', label: 'house' },
          ]}
        />
        <Select
          label={t('admin_enrichment.backlog.filter_status')}
          value={p.status}
          onChange={(v) => v && p.onStatusChange(v as Props['status'])}
          data={[
            { value: 'all', label: 'all' },
            { value: 'none', label: t('admin_enrichment.backlog.status_none') },
            { value: 'failed', label: t('admin_enrichment.backlog.status_failed') },
            { value: 'outdated', label: t('admin_enrichment.backlog.status_outdated') },
          ]}
        />
      </Group>
      <Group gap="sm">
        <Text size="sm" c="dimmed">
          {t('admin_enrichment.backlog.selected_summary', { count: p.selectedCount })}
        </Text>
        <Button onClick={p.onEnqueueClick} disabled={p.selectedCount === 0}>
          {t('admin_enrichment.backlog.enqueue_button', { count: p.selectedCount })}
        </Button>
      </Group>
    </Group>
  );
}
```

- [ ] **Step 3: Implement `BacklogTable.tsx`**

```tsx
// frontend/src/features/admin/components/enrichment/BacklogTable.tsx
import { Table, Checkbox, Group, Anchor } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { BacklogLabel } from '../../../../api/labels';
import { RunStatusBadge } from './RunStatusBadge';

interface Props {
  items: BacklogLabel[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (next: boolean) => void;
}

export function BacklogTable(p: Props) {
  const { t } = useTranslation();
  const allSelected = p.items.length > 0 && p.items.every((i) => p.selected.has(i.id));
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>
            <Checkbox
              checked={allSelected}
              onChange={(e) => p.onToggleAll(e.currentTarget.checked)}
              aria-label="select all rows on this page"
            />
          </Table.Th>
          <Table.Th>{t('admin_enrichment.backlog.col_name')}</Table.Th>
          <Table.Th>{t('admin_enrichment.backlog.col_style')}</Table.Th>
          <Table.Th>{t('admin_enrichment.backlog.col_status')}</Table.Th>
          <Table.Th>{t('admin_enrichment.backlog.col_tracks')}</Table.Th>
          <Table.Th>{t('admin_enrichment.backlog.col_last_try')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {p.items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <Checkbox
                checked={p.selected.has(row.id)}
                onChange={() => p.onToggle(row.id)}
                aria-label={`select ${row.name}`}
              />
            </Table.Td>
            <Table.Td>
              <Anchor component={Link} to={`/library/${row.style}/labels/${row.id}`}>
                {row.name}
              </Anchor>
            </Table.Td>
            <Table.Td>{row.style}</Table.Td>
            <Table.Td><RunStatusBadge status={row.status} /></Table.Td>
            <Table.Td>{row.track_count}</Table.Td>
            <Table.Td>{row.last_attempted_at ?? '—'}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
```

- [ ] **Step 4: Verify typecheck**

```bash
cd frontend && pnpm typecheck && cd ..
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/admin/components/enrichment/
git commit -m "$(cat <<'EOF'
feat(frontend): add admin backlog toolbar + table + status badge

BacklogToolbar (style/status filters + enqueue trigger), BacklogTable
(per-page checkbox-select with no surprise select-all-results), and
RunStatusBadge reused across runs and backlog views.
EOF
)"
```

---

### Task 4.3: `EnqueueDrawer` component + test

**Files:**
- Create: `frontend/src/features/admin/components/enrichment/EnqueueDrawer.tsx`
- Create: `frontend/src/features/admin/components/enrichment/__tests__/EnqueueDrawer.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// EnqueueDrawer.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../../i18n';
import { server } from '../../../../../test/setup';
import { tokenStore } from '../../../../../auth/tokenStore';
import { EnqueueDrawer } from '../EnqueueDrawer';

function renderDrawer(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={qc}>
        <EnqueueDrawer
          opened
          onClose={onClose}
          labelIds={['l1', 'l2']}
        />
      </QueryClientProvider>
    </I18nextProvider>
  );
}

describe('EnqueueDrawer', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('loads options and submits an enrich request', async () => {
    server.use(
      http.get('http://localhost/admin/labels/enrich/options', () =>
        HttpResponse.json({
          vendors: ['gemini', 'openai', 'tavily_deepseek'],
          prompt_versions: [{ slug: 'label_v3_app_fields', version: 'v1', is_default: true }],
          default_models: { gemini: 'gem', openai: 'gpt', tavily_deepseek: 'dsk' },
          merge: { vendor: 'deepseek', default_model: 'deepseek-chat' },
        }),
      ),
      http.post('http://localhost/admin/labels/enrich', async ({ request }) => {
        const body = await request.json() as any;
        expect(body.labels).toHaveLength(2);
        expect(body.prompt_slug).toBe('label_v3_app_fields');
        return HttpResponse.json({ run_id: 'r-x', queued_labels: 2 }, { status: 202 });
      }),
    );

    const onClose = vi.fn();
    renderDrawer(onClose);

    await waitFor(() => expect(screen.getByText('Enqueue')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Enqueue'));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm vitest run src/features/admin/components/enrichment/__tests__/EnqueueDrawer.test.tsx && cd ..
```

Expected: FAIL.

- [ ] **Step 3: Implement `EnqueueDrawer.tsx`**

```tsx
// frontend/src/features/admin/components/enrichment/EnqueueDrawer.tsx
import { Drawer, Stack, Title, Checkbox, Select, TextInput, Button, Badge, Group, Skeleton, Alert } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useEffect, useState } from 'react';
import { useEnrichmentOptions } from '../../hooks/useEnrichmentOptions';
import { useEnqueueEnrichment } from '../../hooks/useEnqueueEnrichment';

interface Props {
  opened: boolean;
  onClose: () => void;
  labelIds: string[];
}

export function EnqueueDrawer({ opened, onClose, labelIds }: Props) {
  const { t } = useTranslation();
  const options = useEnrichmentOptions();
  const enqueue = useEnqueueEnrichment();

  const [vendors, setVendors] = useState<string[]>([]);
  const [promptSlug, setPromptSlug] = useState<string>('');
  const [models, setModels] = useState<Record<string, string>>({});
  const [mergeModel, setMergeModel] = useState<string>('');

  useEffect(() => {
    if (!options.data) return;
    setVendors(options.data.vendors);
    const def = options.data.prompt_versions.find((p) => p.is_default) ?? options.data.prompt_versions[0];
    if (def) setPromptSlug(def.slug);
    setModels({ ...options.data.default_models });
    setMergeModel(options.data.merge.default_model);
  }, [options.data]);

  const promptVersion = options.data?.prompt_versions.find((p) => p.slug === promptSlug)?.version ?? '';

  const submit = async () => {
    try {
      const res = await enqueue.mutateAsync({
        labels: labelIds.map((label_id) => ({ label_id })),
        vendors: vendors as ('gemini' | 'openai' | 'tavily_deepseek')[],
        models,
        prompt_slug: promptSlug,
        prompt_version: promptVersion,
        merge_vendor: 'deepseek',
        merge_model: mergeModel,
      });
      notifications.show({
        color: 'green',
        title: t('admin_enrichment.enqueue_drawer.success_notification', {
          count: res.queued_labels, run_id: res.run_id,
        }),
        message: '',
      });
      onClose();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: t('admin_enrichment.enqueue_drawer.error_notification', {
          message: err instanceof Error ? err.message : 'unknown',
        }),
        message: '',
      });
    }
  };

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={<Title order={4}>{t('admin_enrichment.enqueue_drawer.title', { count: labelIds.length })}</Title>}
      position="right"
      size="md"
    >
      {options.isLoading && <Skeleton height={200} />}
      {options.isError && <Alert color="red">{String(options.error)}</Alert>}
      {options.data && (
        <Stack gap="md">
          <Stack gap="xs">
            <Title order={6}>{t('admin_enrichment.enqueue_drawer.vendors_label')}</Title>
            {options.data.vendors.map((v) => (
              <Checkbox
                key={v}
                label={v}
                checked={vendors.includes(v)}
                onChange={(e) =>
                  setVendors((cur) =>
                    e.currentTarget.checked ? [...cur, v] : cur.filter((x) => x !== v),
                  )
                }
              />
            ))}
          </Stack>
          <Select
            label={t('admin_enrichment.enqueue_drawer.prompt_label')}
            value={promptSlug}
            data={options.data.prompt_versions.map((p) => ({ value: p.slug, label: `${p.slug}@${p.version}` }))}
            onChange={(v) => v && setPromptSlug(v)}
          />
          <Stack gap="xs">
            <Title order={6}>{t('admin_enrichment.enqueue_drawer.models_label')}</Title>
            {vendors.map((v) => (
              <TextInput
                key={v}
                label={v}
                value={models[v] ?? ''}
                onChange={(e) =>
                  setModels((cur) => ({ ...cur, [v]: e.currentTarget.value }))
                }
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
              value={mergeModel}
              onChange={(e) => setMergeModel(e.currentTarget.value)}
              style={{ flex: 1 }}
            />
          </Group>
          <Button onClick={submit} loading={enqueue.isPending} disabled={labelIds.length === 0 || vendors.length === 0}>
            {enqueue.isPending
              ? t('admin_enrichment.enqueue_drawer.submit_inflight')
              : t('admin_enrichment.enqueue_drawer.submit')}
          </Button>
        </Stack>
      )}
    </Drawer>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm vitest run src/features/admin/components/enrichment/__tests__/EnqueueDrawer.test.tsx && cd ..
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/admin/components/enrichment/
git commit -m "$(cat <<'EOF'
feat(frontend): add EnqueueDrawer admin component

Drawer fed by useEnrichmentOptions, submits via useEnqueueEnrichment.
Vendor checkboxes, prompt version select, per-vendor model inputs,
readonly merge vendor badge. Notifications on success / failure.
EOF
)"
```

---

### Task 4.4: Runs list + run-detail components

**Files:**
- Create: `frontend/src/features/admin/components/enrichment/RunsTable.tsx`
- Create: `frontend/src/features/admin/components/enrichment/RunDetailHeader.tsx`
- Create: `frontend/src/features/admin/components/enrichment/RunDetailCellsTable.tsx`
- Create: `frontend/src/features/admin/components/enrichment/RunJsonViewer.tsx`
- Create: `frontend/src/features/admin/components/enrichment/__tests__/RunJsonViewer.test.tsx`

- [ ] **Step 1: Write failing test for `RunJsonViewer`**

```tsx
// RunJsonViewer.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { I18nextProvider } from 'react-i18next';
import { MantineProvider } from '@mantine/core';
import i18n from '../../../../../i18n';
import { RunJsonViewer } from '../RunJsonViewer';

function wrap(ui: React.ReactNode) {
  return (
    <MantineProvider>
      <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>
    </MantineProvider>
  );
}

describe('RunJsonViewer', () => {
  it('renders pretty-printed JSON', () => {
    render(wrap(<RunJsonViewer data={{ a: 1 }} />));
    const pre = screen.getByText(/"a": 1/);
    expect(pre).toBeInTheDocument();
  });

  it('copies JSON to clipboard on button click', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(wrap(<RunJsonViewer data={{ a: 1 }} />));
    await userEvent.click(screen.getByText('Copy JSON'));
    expect(writeText).toHaveBeenCalledWith(JSON.stringify({ a: 1 }, null, 2));
  });
});
```

- [ ] **Step 2: Implement `RunJsonViewer.tsx`**

```tsx
// RunJsonViewer.tsx
import { Code, Group, Button, Box } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';

export function RunJsonViewer({ data }: { data: unknown }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(data, null, 2);
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Box pos="relative">
      <Group justify="flex-end" mb="xs">
        <Button size="xs" variant="default" onClick={copy}>
          {copied ? t('admin_enrichment.run_detail.json_copied') : 'Copy JSON'}
        </Button>
      </Group>
      <Code block style={{ whiteSpace: 'pre-wrap' }}>{text}</Code>
    </Box>
  );
}
```

- [ ] **Step 3: Implement `RunsTable.tsx`**

```tsx
// RunsTable.tsx
import { Table, Anchor, Group, Text, CopyButton, ActionIcon } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { IconCopy } from '@tabler/icons-react';
import type { RunSummary } from '../../../../api/labels';
import { RunStatusBadge } from './RunStatusBadge';

export function RunsTable({ items }: { items: RunSummary[] }) {
  const { t } = useTranslation();
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('admin_enrichment.runs.col_created')}</Table.Th>
          <Table.Th>{t('admin_enrichment.runs.col_id')}</Table.Th>
          <Table.Th>{t('admin_enrichment.runs.col_status')}</Table.Th>
          <Table.Th>{t('admin_enrichment.runs.col_cells')}</Table.Th>
          <Table.Th>{t('admin_enrichment.runs.col_cost')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {items.map((r) => (
          <Table.Tr key={r.id}>
            <Table.Td>{r.created_at ?? '—'}</Table.Td>
            <Table.Td>
              <Group gap={4}>
                <Anchor component={Link} to={`/admin/labels/enrich/runs/${r.id}`}>
                  {r.id.slice(0, 8)}
                </Anchor>
                <CopyButton value={r.id}>
                  {({ copy }) => (
                    <ActionIcon variant="subtle" onClick={copy} aria-label="copy id">
                      <IconCopy size={14} />
                    </ActionIcon>
                  )}
                </CopyButton>
              </Group>
            </Table.Td>
            <Table.Td><RunStatusBadge status={r.status} /></Table.Td>
            <Table.Td>{r.cells_ok}/{r.cells_error}/{r.cells_total}</Table.Td>
            <Table.Td>{typeof r.cost_usd === 'number' ? `$${r.cost_usd.toFixed(4)}` : '—'}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
```

- [ ] **Step 4: Implement `RunDetailHeader.tsx`**

```tsx
// RunDetailHeader.tsx
import { Stack, Group, Title, Anchor, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { RunDetail } from '../../../../api/labels';
import { RunStatusBadge } from './RunStatusBadge';

export function RunDetailHeader({ run }: { run: RunDetail }) {
  const { t } = useTranslation();
  return (
    <Stack gap="xs">
      <Anchor component={Link} to="/admin/labels/enrich/runs" size="sm">
        ← {t('admin_enrichment.run_detail.back_to_runs')}
      </Anchor>
      <Group gap="md" align="center">
        <Title order={3}>Run {run.id.slice(0, 8)}…</Title>
        <RunStatusBadge status={run.status} />
      </Group>
      <Group gap="md">
        <Text size="sm">
          {t('admin_enrichment.run_detail.counters_total')}: {run.cells_total}{' '}
          · {t('admin_enrichment.run_detail.counters_ok')}: {run.cells_ok}{' '}
          · {t('admin_enrichment.run_detail.counters_err')}: {run.cells_error}
        </Text>
        {typeof run.cost_usd === 'number' && (
          <Text size="sm">Cost: ${run.cost_usd.toFixed(4)}</Text>
        )}
      </Group>
      <Text size="sm" c="dimmed">
        {run.prompt_slug}@{run.prompt_version} · vendors: {(run.vendors ?? []).join(', ')}
      </Text>
    </Stack>
  );
}
```

- [ ] **Step 5: Implement `RunDetailCellsTable.tsx`**

```tsx
// RunDetailCellsTable.tsx
import { Table, Badge, Tooltip, Text } from '@mantine/core';
import type { RunCell } from '../../../../api/labels';

export function RunDetailCellsTable({ cells }: { cells: RunCell[] }) {
  return (
    <Table>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Label</Table.Th>
          <Table.Th>Vendor</Table.Th>
          <Table.Th>Status</Table.Th>
          <Table.Th>Latency (ms)</Table.Th>
          <Table.Th>Cost</Table.Th>
          <Table.Th>Error</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {cells.map((c) => (
          <Table.Tr key={c.cell_id}>
            <Table.Td>{c.label_name}</Table.Td>
            <Table.Td>{c.vendor}</Table.Td>
            <Table.Td>
              <Badge color={c.status === 'ok' ? 'green' : 'red'}>{c.status}</Badge>
            </Table.Td>
            <Table.Td>{c.latency_ms}</Table.Td>
            <Table.Td>${c.cost_usd.toFixed(4)}</Table.Td>
            <Table.Td>
              {c.error_message ? (
                <Tooltip label={c.error_message}>
                  <Text size="sm" truncate maw={200}>{c.error_message}</Text>
                </Tooltip>
              ) : '—'}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
```

- [ ] **Step 6: Run tests + typecheck**

```bash
cd frontend && pnpm vitest run src/features/admin/components/enrichment/__tests__/RunJsonViewer.test.tsx && pnpm typecheck && cd ..
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/admin/components/enrichment/
git commit -m "$(cat <<'EOF'
feat(frontend): add runs + run-detail components

RunsTable (id truncate + clipboard copy), RunDetailHeader (counters +
prompt info), RunDetailCellsTable (per-cell grid with tooltip on errors),
and RunJsonViewer (raw JSON with copy button).
EOF
)"
```

---

### Task 4.5: Admin enrichment route pages

**Files:**
- Create: `frontend/src/features/admin/routes/AdminEnrichmentBacklogPage.tsx`
- Create: `frontend/src/features/admin/routes/AdminEnrichmentRunsPage.tsx`
- Create: `frontend/src/features/admin/routes/AdminEnrichmentRunDetailPage.tsx`

- [ ] **Step 1: Implement `AdminEnrichmentBacklogPage.tsx`**

```tsx
// AdminEnrichmentBacklogPage.tsx
import { Stack, Title, Button, Center, Text } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLabelBacklog } from '../hooks/useLabelBacklog';
import { BacklogToolbar } from '../components/enrichment/BacklogToolbar';
import { BacklogTable } from '../components/enrichment/BacklogTable';
import { EnqueueDrawer } from '../components/enrichment/EnqueueDrawer';

export function AdminEnrichmentBacklogPage() {
  const { t } = useTranslation();
  const [style, setStyle] = useState<string>('');
  const [status, setStatus] = useState<'all' | 'none' | 'failed' | 'outdated'>('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [drawerOpen, setDrawerOpen] = useState(false);

  const query = useLabelBacklog({ style, status });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  const toggleAll = (next: boolean) =>
    setSelected((cur) => {
      const copy = new Set(cur);
      for (const i of items) {
        if (next) copy.add(i.id);
        else copy.delete(i.id);
      }
      return copy;
    });
  const toggle = (id: string) =>
    setSelected((cur) => {
      const copy = new Set(cur);
      if (copy.has(id)) copy.delete(id);
      else copy.add(id);
      return copy;
    });

  return (
    <Stack gap="md">
      <Title order={3}>{t('admin_enrichment.backlog.title')}</Title>
      <BacklogToolbar
        style={style}
        onStyleChange={setStyle}
        status={status}
        onStatusChange={setStatus}
        selectedCount={selected.size}
        onEnqueueClick={() => setDrawerOpen(true)}
      />
      {items.length === 0 && !query.isLoading ? (
        <Center mt="lg"><Text c="dimmed">{t('admin_enrichment.backlog.empty')}</Text></Center>
      ) : (
        <BacklogTable items={items} selected={selected} onToggle={toggle} onToggleAll={toggleAll} />
      )}
      {query.hasNextPage && (
        <Center mt="md">
          <Button variant="default" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            Load more
          </Button>
        </Center>
      )}
      <EnqueueDrawer
        opened={drawerOpen}
        onClose={() => { setDrawerOpen(false); setSelected(new Set()); }}
        labelIds={Array.from(selected)}
      />
    </Stack>
  );
}
```

- [ ] **Step 2: Implement `AdminEnrichmentRunsPage.tsx`**

```tsx
// AdminEnrichmentRunsPage.tsx
import { Stack, Title, Select, Button, Center } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useEnrichmentRuns } from '../hooks/useEnrichmentRuns';
import { RunsTable } from '../components/enrichment/RunsTable';

export function AdminEnrichmentRunsPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<'all' | 'queued' | 'running' | 'completed' | 'failed'>('all');
  const query = useEnrichmentRuns({ status });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Stack gap="md">
      <Title order={3}>{t('admin_enrichment.runs.title')}</Title>
      <Select
        label={t('admin_enrichment.runs.filter_status')}
        value={status}
        onChange={(v) => v && setStatus(v as typeof status)}
        data={[
          { value: 'all', label: 'all' },
          { value: 'queued', label: t('admin_enrichment.status.queued') },
          { value: 'running', label: t('admin_enrichment.status.running') },
          { value: 'completed', label: t('admin_enrichment.status.completed') },
          { value: 'failed', label: t('admin_enrichment.status.failed') },
        ]}
        maw={240}
      />
      <RunsTable items={items} />
      {query.hasNextPage && (
        <Center mt="md">
          <Button variant="default" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            Load more
          </Button>
        </Center>
      )}
    </Stack>
  );
}
```

- [ ] **Step 3: Implement `AdminEnrichmentRunDetailPage.tsx`**

```tsx
// AdminEnrichmentRunDetailPage.tsx
import { Stack, Tabs, SimpleGrid, Card, Text } from '@mantine/core';
import { useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useEnrichmentRunDetail } from '../hooks/useEnrichmentRunDetail';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { RunDetailHeader } from '../components/enrichment/RunDetailHeader';
import { RunDetailCellsTable } from '../components/enrichment/RunDetailCellsTable';
import { RunJsonViewer } from '../components/enrichment/RunJsonViewer';

export function AdminEnrichmentRunDetailPage() {
  const { t } = useTranslation();
  const { runId } = useParams<{ runId: string }>();
  if (!runId) return <Navigate to="/admin/labels/enrich/runs" replace />;
  const query = useEnrichmentRunDetail(runId);

  if (query.isLoading) return <FullScreenLoader />;
  if (query.isError || !query.data) return <Text c="red">Run not found</Text>;

  const run = query.data;
  const cells = run.cells ?? [];

  return (
    <Stack gap="md">
      <RunDetailHeader run={run} />
      <Tabs defaultValue="summary">
        <Tabs.List>
          <Tabs.Tab value="summary">{t('admin_enrichment.run_detail.tab_summary')}</Tabs.Tab>
          <Tabs.Tab value="cells">{t('admin_enrichment.run_detail.tab_cells')}</Tabs.Tab>
          <Tabs.Tab value="json">{t('admin_enrichment.run_detail.tab_json')}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="summary" pt="md">
          <SimpleGrid cols={3}>
            <Card withBorder><Text size="sm">{t('admin_enrichment.run_detail.counters_total')}</Text><Text fw={700}>{run.cells_total}</Text></Card>
            <Card withBorder><Text size="sm">{t('admin_enrichment.run_detail.counters_ok')}</Text><Text fw={700}>{run.cells_ok}</Text></Card>
            <Card withBorder><Text size="sm">{t('admin_enrichment.run_detail.counters_err')}</Text><Text fw={700}>{run.cells_error}</Text></Card>
          </SimpleGrid>
        </Tabs.Panel>
        <Tabs.Panel value="cells" pt="md">
          <RunDetailCellsTable cells={cells} />
        </Tabs.Panel>
        <Tabs.Panel value="json" pt="md">
          <RunJsonViewer data={run} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
```

- [ ] **Step 4: Verify typecheck**

```bash
cd frontend && pnpm typecheck && cd ..
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/admin/routes/AdminEnrichment*.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): add admin enrichment route pages

Three pages: backlog (filter + table + enqueue drawer), runs list
(filter + paginated table with auto-refresh), run detail (summary +
cells + raw JSON tabs).
EOF
)"
```

---

### Task 4.6: Wire admin routes + extend AdminLayout tabs

**Files:**
- Modify: `frontend/src/features/admin/routes/AdminLayout.tsx`
- Modify: `frontend/src/routes/router.tsx`

- [ ] **Step 1: Update `AdminLayout.tsx`**

Replace `TAB_VALUES` and `TABS`:

```tsx
const TAB_VALUES = [
  '/admin/labels/enrich/runs',  // longest first → startsWith resolves correctly
  '/admin/labels/enrich',
  '/admin/coverage',
  '/admin/spotify-not-found',
] as const;
```

And replace the `TABS` build:

```tsx
const TABS = [
  { value: '/admin/coverage', label: t('admin.tabs.coverage') },
  { value: '/admin/spotify-not-found', label: t('admin.tabs.spotify_not_found') },
  { value: '/admin/labels/enrich', label: t('admin_enrichment.tabs.backlog') },
  { value: '/admin/labels/enrich/runs', label: t('admin_enrichment.tabs.runs') },
];
```

The existing `active` calc already does `find((v) => location.pathname.startsWith(v))` — with `TAB_VALUES` reordered longest-first, the right tab activates.

- [ ] **Step 2: Add routes to router.tsx**

In the admin block (next to `coverage`):

```tsx
import { AdminEnrichmentBacklogPage } from '../features/admin/routes/AdminEnrichmentBacklogPage';
import { AdminEnrichmentRunsPage } from '../features/admin/routes/AdminEnrichmentRunsPage';
import { AdminEnrichmentRunDetailPage } from '../features/admin/routes/AdminEnrichmentRunDetailPage';

// inside admin children:
{ path: 'labels/enrich', element: <AdminEnrichmentBacklogPage /> },
{ path: 'labels/enrich/runs', element: <AdminEnrichmentRunsPage /> },
{ path: 'labels/enrich/runs/:runId', element: <AdminEnrichmentRunDetailPage /> },
```

- [ ] **Step 3: Run full frontend tests**

```bash
cd frontend && pnpm test --run 2>&1 | tail -5 && cd ..
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/admin/routes/AdminLayout.tsx frontend/src/routes/router.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): wire admin enrichment routes and tabs

Adds two new tabs to AdminLayout (Enrichment backlog + Enrichment runs)
and three nested routes under /admin/labels/enrich. TAB_VALUES ordered
longest-first so /admin/labels/enrich/runs matches before /enrich.
EOF
)"
```

---

## Phase 5 — Triage / Curate / Categories label tile (Surface 3)

### Task 5.1: Add `label_id` to `BucketTrack` interface (frontend)

**Files:**
- Modify: `frontend/src/features/triage/hooks/useBucketTracks.ts`

- [ ] **Step 1: Add the field**

In the `BucketTrack` interface, add `label_id: string | null;` next to `label_name`:

```typescript
export interface BucketTrack {
  track_id: string;
  title: string;
  mix_name: string | null;
  isrc: string | null;
  bpm: number | null;
  length_ms: number | null;
  publish_date: string | null;
  spotify_release_date: string | null;
  spotify_id: string | null;
  release_type: string | null;
  is_ai_suspected: boolean;
  artists: string[];
  label_id: string | null;
  label_name: string | null;
  added_at: string;
}
```

- [ ] **Step 2: Update any test fixtures that construct `BucketTrack` literally**

```bash
grep -rln "track_id:" frontend/src/features/triage/ frontend/src/features/curate/ frontend/src/__tests__/ | xargs grep -l "label_name:" | head
```

For each match, add `label_id: null,` next to `label_name`. The TypeScript compiler will flag any miss.

- [ ] **Step 3: Verify typecheck**

```bash
cd frontend && pnpm typecheck && cd ..
```

Fix any "missing property label_id" errors by adding `label_id: null` to the offending object.

- [ ] **Step 4: Run tests**

```bash
cd frontend && pnpm test --run 2>&1 | tail -5 && cd ..
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "$(cat <<'EOF'
feat(frontend): add label_id to BucketTrack interface

Backend B1 exposes label_id on triage track rows. Surface it on the
TypeScript shape so curate + categories players can pass it to the
label tile.
EOF
)"
```

---

### Task 5.2: Mount `LabelTile` in `CurateSession.tsx`

**Files:**
- Modify: `frontend/src/features/curate/components/CurateSession.tsx`

- [ ] **Step 1: Add imports**

```tsx
import { useViewportSize } from '@mantine/hooks';
import { LabelTile } from '../../library/components/LabelTile';
```

- [ ] **Step 2: Wrap existing PlayerCard in a Group with the tile**

Find where `<PlayerCard ... />` is rendered. Wrap it:

```tsx
const { width } = useViewportSize();
// ...
<Group align="flex-start" gap="md">
  <Box style={{ flex: 1 }}>
    <PlayerCard {...existingProps} />
  </Box>
  {width >= 1024 && (
    <LabelTile
      labelId={session.currentTrack?.label_id ?? null}
      styleId={styleId}
    />
  )}
</Group>
```

Import `Group` and `Box` from `@mantine/core` if not already imported.

- [ ] **Step 3: Run curate tests**

```bash
cd frontend && pnpm vitest run src/features/curate src/__tests__ && cd ..
```

Expected: PASS (no regression).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/curate/components/CurateSession.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): mount LabelTile in curate session right rail

Desktop (>=1024px) shows the enriched label tile next to PlayerCard.
Tile silently renders nothing when the track has no label_id or the
label has no info yet. Mobile keeps the existing single-column layout.
EOF
)"
```

---

### Task 5.3: Mount `LabelTile` in `CategoryPlayerPanel.tsx`

**Files:**
- Modify: `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`

- [ ] **Step 1: Add imports and tile mount**

```bash
grep -n "<PlayerCard\|effectiveRich" frontend/src/features/categories/components/CategoryPlayerPanel.tsx | head
```

Identify where `<PlayerCard>` renders. Wrap it the same way:

```tsx
import { useViewportSize } from '@mantine/hooks';
import { Group, Box } from '@mantine/core';
import { LabelTile } from '../../library/components/LabelTile';

// inside the component:
const { width } = useViewportSize();
// ...
<Group align="flex-start" gap="md">
  <Box style={{ flex: 1 }}>
    <PlayerCard {...existingProps} />
  </Box>
  {width >= 1024 && (
    <LabelTile
      labelId={effectiveRich.label?.id ?? null}
      styleId={styleId}
    />
  )}
</Group>
```

- [ ] **Step 2: Run tests + typecheck**

```bash
cd frontend && pnpm vitest run src/features/categories && pnpm typecheck && cd ..
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/categories/components/CategoryPlayerPanel.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): mount LabelTile in categories player right rail

Same tile, symmetric placement next to the categories PlayerCard.
EOF
)"
```

---

## Phase 6 — Russian translations

### Task 6.1: Add RU keys mirroring EN

**Files:**
- Modify: `frontend/src/i18n/locales/ru/...` (matching EN file path)

- [ ] **Step 1: Locate the RU file**

```bash
find frontend/src/i18n/locales/ru -type f | head
```

- [ ] **Step 2: Append the RU translations**

Mirror the EN keys from Task 2.2 with Russian values:

```json
{
  "library": {
    "page_title": "Библиотека",
    "list": {
      "title": "Лейблы",
      "empty_filter": "Лейблы по этим фильтрам не найдены.",
      "info_pending": "Информация скоро",
      "search_placeholder": "Поиск лейблов...",
      "sort_label": "Сортировка",
      "sort_name": "Имя (А→Я)",
      "sort_recent": "Недавно обновлённые",
      "load_more": "Показать ещё"
    },
    "entity_tabs": {
      "labels": "Лейблы",
      "artists": "Артисты",
      "artists_coming_soon": "Скоро"
    },
    "detail": {
      "back_to_list": "Назад к {{style}}",
      "no_info_title": "Информация ещё не собрана",
      "no_info_body": "Этот лейбл ещё не прогружали.",
      "admin_enqueue_cta": "Запустить enrichment",
      "tab_overview": "Обзор",
      "tab_styles": "Стили",
      "tab_links": "Ссылки",
      "founded": "Основан в {{year}}",
      "notable_artists": "Ключевые артисты",
      "primary_styles": "Основные стили",
      "secondary_styles": "Дополнительные стили",
      "ai_content_label": "AI-контент",
      "ai_reasoning": "Обоснование",
      "ai_reasoning_collapsed": "Показать обоснование"
    },
    "tile": { "read_more": "Подробнее →" },
    "channels": {
      "website": "Сайт",
      "bandcamp": "Bandcamp",
      "soundcloud": "SoundCloud",
      "beatport": "Beatport",
      "residentadvisor": "Resident Advisor",
      "discogs": "Discogs",
      "instagram": "Instagram",
      "twitter": "Twitter"
    },
    "activity": {
      "unknown": "Неизвестно",
      "dormant": "Спящий",
      "low": "Низкая",
      "steady": "Стабильная",
      "high": "Высокая",
      "fire_hose": "Очень высокая"
    }
  },
  "admin_enrichment": {
    "tabs": {
      "backlog": "Enrichment бэклог",
      "runs": "Запуски enrichment"
    },
    "backlog": {
      "title": "Лейблы без информации",
      "filter_style": "Стиль",
      "filter_status": "Статус",
      "status_none": "Нет данных",
      "status_failed": "Ошибка",
      "status_outdated": "Устарело",
      "col_name": "Лейбл",
      "col_style": "Стиль",
      "col_status": "Статус",
      "col_tracks": "Треки",
      "col_last_try": "Последняя попытка",
      "selected_summary": "Выбрано: {{count}}",
      "enqueue_button": "Запустить {{count}} лейблов",
      "empty": "Готово! Нет лейблов без информации."
    },
    "enqueue_drawer": {
      "title": "Запустить {{count}} лейблов на enrichment",
      "vendors_label": "Вендоры",
      "prompt_label": "Версия промпта",
      "models_label": "Модели по вендорам",
      "merge_vendor_label": "Merge вендор",
      "merge_model_label": "Merge модель",
      "submit": "Запустить",
      "submit_inflight": "Запускаем...",
      "success_notification": "Запущено {{count}} лейблов. Run: {{run_id}}",
      "error_notification": "Ошибка запуска: {{message}}"
    },
    "runs": {
      "title": "Запуски enrichment",
      "col_created": "Создан",
      "col_id": "Run id",
      "col_status": "Статус",
      "col_cells": "Cells (ok/err/total)",
      "col_cost": "Стоимость",
      "filter_status": "Статус",
      "empty": "Запусков пока нет."
    },
    "run_detail": {
      "back_to_runs": "Назад к запускам",
      "tab_summary": "Сводка",
      "tab_cells": "Cells",
      "tab_json": "Raw JSON",
      "counters_total": "Всего",
      "counters_ok": "Ok",
      "counters_err": "Ошибок",
      "vendor_breakdown": "Разбивка по вендорам",
      "copy_json": "Скопировать JSON",
      "json_copied": "Скопировано"
    },
    "status": {
      "queued": "В очереди",
      "running": "В процессе",
      "completed": "Готово",
      "failed": "Ошибка"
    }
  }
}
```

- [ ] **Step 3: Verify JSON parse**

```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/locales/ru.json','utf8'))" || echo FAIL
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/locales/ru/
git commit -m "feat(frontend): add RU translations for label features"
```

---

## Phase 7 — Final integration check

### Task 7.1: Full test sweep + build

- [ ] **Step 1: Backend tests**

```bash
PYTHONPATH=src python -m pytest tests/unit -q 2>&1 | tail -3
```

Expected: all pass.

- [ ] **Step 2: Frontend unit + integration tests**

```bash
cd frontend && pnpm test --run 2>&1 | tail -5 && cd ..
```

Expected: all pass.

- [ ] **Step 3: Frontend typecheck + lint**

```bash
cd frontend && pnpm typecheck && pnpm lint 2>&1 | tail -5 && cd ..
```

Expected: clean.

- [ ] **Step 4: Production build smoke test**

```bash
cd frontend && pnpm build 2>&1 | tail -10 && cd ..
```

Expected: build succeeds.

- [ ] **Step 5: Terraform validate**

```bash
cd infra && terraform validate && cd ..
```

Expected: `Success!` (no infra changes in this plan, but verify).

- [ ] **Step 6: OpenAPI consistency check**

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
git diff --exit-code docs/api/openapi.yaml
```

Expected: no diff (already regenerated in Task 1.8).

- [ ] **Step 7: Commit any auto-formatted output if generated**

If the openapi script auto-reflowed or any prettier diff appeared:

```bash
git add -A
git commit -m "chore: post-build artifact sync"
```

Otherwise skip.

---

## Done

All three surfaces ship plus 7 backend prereqs. Open PR via `caveman:caveman-commit` to generate title + body, then `gh pr create` against `main`.

**Out of scope (already documented in spec, not in this plan):**
- Artist enrichment data + UI
- Mobile triage tile
- Markdown rendering of `summary`
- Bookmarks / favorites
- Run cancellation UI
- Stuck-run reconciler UI

