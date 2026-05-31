# YouTube Music Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user publish a playlist to their own YouTube Music account from the playlist page, with the same experience as the existing Spotify publish (first publish, republish-with-overwrite, skipped-tracks modal).

**Architecture:** Mirror the Spotify publish path one-to-one with separate YouTube Music classes (do not refactor the working Spotify path). YouTube Music is a secondary linked account connected via Google's device-flow OAuth; tokens reuse the existing `user_vendor_tokens` table (vendor=`ytmusic`) and KMS envelope encryption. The publish itself uses the authenticated `ytmusicapi` client. Matched `video_id`s already exist in `vendor_track_map` and are surfaced by `playlists_repository.fetch_ytmusic_status`.

**Tech Stack:** Python 3.12 Lambdas (Data API, not psycopg), `ytmusicapi>=1.7` (already in `requirements-lambda.txt`), Terraform (API Gateway HTTP v2), Alembic, React 19 + Mantine 9 + TanStack Query + Vitest.

**Spec:** `docs/superpowers/specs/2026-05-31-youtube-music-publish-design.md`

---

## Conventions for every task

- **Python tests run from the worktree, but `.venv` lives at the MAIN repo root.**
  Define once and reuse:
  ```bash
  VENV=/Users/roman/Projects/clouder-projects/clouder-core/.venv
  WT=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/youtube_publish
  ```
  Run pytest as: `cd "$WT" && "$VENV/bin/pytest" <path> -q` (pytest.ini sets `PYTHONPATH=src`).
- **Scripts importing project deps** use `"$VENV/bin/python"` with `PYTHONPATH=src`.
- **Commits** go through the `caveman:caveman-commit` skill, then `git commit -m "..."`. No AI-attribution trailer. Branch is already `feat/youtube-music-publish`.
- **Frontend** runs from `frontend/`: `pnpm test <file>` (jsdom), `pnpm test:browser <file>` (Playwright), `pnpm typecheck`, `pnpm lint`.

---

## File map

**Create (backend):**
- `src/collector/auth/ytmusic_oauth.py` — Google device-flow OAuth client.
- `src/collector/curation/ytmusic_token_resolver.py` — read + decrypt + refresh ytmusic token → ytmusicapi token dict.
- `src/collector/curation/ytmusic_user_client.py` — authenticated `ytmusicapi` wrapper + `build_authenticated_ytmusic`.
- `src/collector/curation/ytmusic_publish_service.py` — publish orchestration.
- `alembic/versions/20260531_29_playlists_ytmusic_publish.py` — schema columns.

**Modify (backend):**
- `src/collector/curation/__init__.py` — new error classes.
- `src/collector/curation/playlists_repository.py` — `PlaylistRow`, `_PLAYLIST_SELECT`, `_row`, `set_ytmusic_publish_state`.
- `src/collector/auth/auth_settings.py` — `resolve_ytmusic_oauth_credentials`.
- `src/collector/auth_handler.py` — device-code / poll / disconnect handlers, `_route`, `/me` extension.
- `src/collector/curation_handler.py` — `_handle_publish_ytmusic`, `_build_ytmusic_user_client`, route table.
- `scripts/generate_openapi.py` — `ROUTES` entries.
- `infra/auth.tf` — connect routes + env vars.
- `infra/curation.tf` — env vars (ytmusic SSM params).
- `infra/curation_routes_playlists.tf` — publish-ytmusic route.
- `infra/variables.tf` — ytmusic SSM param variables.

**Create (frontend):**
- `frontend/src/features/playlists/hooks/usePublishYtmusic.ts`
- `frontend/src/features/playlists/hooks/useYtmusicConnect.ts`
- `frontend/src/features/playlists/hooks/useMe.ts`
- `frontend/src/features/playlists/components/PublishYtMusicButton.tsx`
- `frontend/src/features/playlists/components/YtMusicConnectModal.tsx`

**Modify (frontend):**
- `frontend/src/features/playlists/lib/playlistTypes.ts` — `Playlist` fields, `YtmusicPublishResult`, `MeResponse`.
- `frontend/src/features/playlists/components/PublishResultModal.tsx` — generalize for vendor.
- `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx` — render the new button.
- `frontend/src/i18n/en.json` — new strings.
- `frontend/src/api/schema.d.ts` — regenerated from OpenAPI (CI gate).

---

# Phase 1 — Backend errors + schema

## Task 1: YouTube Music error classes

**Files:**
- Modify: `src/collector/curation/__init__.py` (append after `NothingToPublishError`, ~line 243)
- Test: `tests/unit/test_curation_errors_ytmusic.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_curation_errors_ytmusic.py`:

```python
from collector.curation import (
    CurationError,
    YtmusicApiError,
    YtmusicNotAuthorizedError,
    YtmusicNotFoundError,
)


def test_not_authorized_is_412():
    exc = YtmusicNotAuthorizedError("no token")
    assert exc.http_status == 412
    assert exc.error_code == "ytmusic_not_authorized"
    assert isinstance(exc, CurationError)


def test_api_error_is_502():
    exc = YtmusicApiError("boom")
    assert exc.http_status == 502
    assert exc.error_code == "ytmusic_api_error"


def test_not_found_subclasses_api_error():
    exc = YtmusicNotFoundError("gone")
    assert isinstance(exc, YtmusicApiError)
    assert exc.http_status == 502
    assert exc.error_code == "ytmusic_not_found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_curation_errors_ytmusic.py -q`
Expected: FAIL with `ImportError: cannot import name 'YtmusicNotAuthorizedError'`.

- [ ] **Step 3: Add the error classes**

Append to `src/collector/curation/__init__.py`:

```python


class YtmusicNotAuthorizedError(CurationError):
    error_code = "ytmusic_not_authorized"
    http_status = 412


class YtmusicApiError(CurationError):
    error_code = "ytmusic_api_error"
    http_status = 502


class YtmusicNotFoundError(YtmusicApiError):
    """ytmusicapi reported the playlist does not exist (orphan recreate path)."""

    error_code = "ytmusic_not_found"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_curation_errors_ytmusic.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add src/collector/curation/__init__.py tests/unit/test_curation_errors_ytmusic.py
git commit -m "feat(curation): add YouTube Music publish error types"
```

---

## Task 2: Alembic migration — ytmusic publish columns

**Files:**
- Create: `alembic/versions/20260531_29_playlists_ytmusic_publish.py`

- [ ] **Step 1: Write the migration**

Create `alembic/versions/20260531_29_playlists_ytmusic_publish.py`:

```python
"""playlists: per-user YouTube Music publish state

Revision ID: 20260531_29
Revises: 20260530_28
Create Date: 2026-05-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260531_29"
down_revision = "20260530_28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "playlists",
        sa.Column("ytmusic_playlist_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "playlists",
        sa.Column(
            "ytmusic_last_published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "playlists",
        sa.Column(
            "ytmusic_needs_republish",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "idx_playlists_ytmusic_playlist_id",
        "playlists",
        ["ytmusic_playlist_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_playlists_ytmusic_playlist_id", table_name="playlists"
    )
    op.drop_column("playlists", "ytmusic_needs_republish")
    op.drop_column("playlists", "ytmusic_last_published_at")
    op.drop_column("playlists", "ytmusic_playlist_id")
```

- [ ] **Step 2: Apply against a local Postgres and verify reversibility**

Run (requires a local Postgres as in CLAUDE.md):
```bash
cd "$WT"
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
"$VENV/bin/alembic" upgrade head
"$VENV/bin/alembic" downgrade -1
"$VENV/bin/alembic" upgrade head
```
Expected: each command exits 0; `upgrade head` lands on `20260531_29`.

- [ ] **Step 3: Verify columns exist**

Run:
```bash
cd "$WT" && export PYTHONPATH=src
"$VENV/bin/python" - <<'PY'
import sqlalchemy as sa, os
e = sa.create_engine(os.environ["ALEMBIC_DATABASE_URL"])
with e.connect() as c:
    cols = {r[0] for r in c.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='playlists'"
    ))}
assert {"ytmusic_playlist_id","ytmusic_last_published_at","ytmusic_needs_republish"} <= cols, cols
print("OK", sorted(c for c in cols if c.startswith("ytmusic")))
PY
```
Expected: `OK ['ytmusic_last_published_at', 'ytmusic_needs_republish', 'ytmusic_playlist_id']`.

- [ ] **Step 4: Commit**

```bash
cd "$WT" && git add alembic/versions/20260531_29_playlists_ytmusic_publish.py
git commit -m "feat(db): add ytmusic publish columns to playlists"
```

---

## Task 3: Repository — PlaylistRow fields + set_ytmusic_publish_state

**Files:**
- Modify: `src/collector/curation/playlists_repository.py` (`PlaylistRow` ~37-53, `_PLAYLIST_SELECT` ~56-69, `_row` ~102-125, add method after `set_publish_state` ~764)
- Test: `tests/unit/test_playlists_repository_ytmusic_publish.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_playlists_repository_ytmusic_publish.py`:

```python
from datetime import datetime, timezone

from collector.curation.playlists_repository import PlaylistsRepository, _row


class FakeDataApi:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self._rows


def test_row_maps_ytmusic_columns():
    raw = {
        "id": "p1", "user_id": "u1", "name": "n", "normalized_name": "n",
        "description": None, "is_public": True, "cover_s3_key": None,
        "cover_uploaded_at": None, "spotify_playlist_id": None,
        "last_published_at": None, "needs_republish": False,
        "status": "active", "created_at": "t", "updated_at": "t",
        "track_count": 0,
        "ytmusic_playlist_id": "PLabc",
        "ytmusic_last_published_at": "2026-05-31T00:00:00+00:00",
        "ytmusic_needs_republish": True,
    }
    row = _row(raw)
    assert row.ytmusic_playlist_id == "PLabc"
    assert row.ytmusic_last_published_at == "2026-05-31T00:00:00+00:00"
    assert row.ytmusic_needs_republish is True


def test_set_ytmusic_publish_state_writes_columns():
    fake = FakeDataApi(rows=[{"id": "p1"}])
    repo = PlaylistsRepository(data_api=fake)
    now = datetime(2026, 5, 31, tzinfo=timezone.utc)
    ok = repo.set_ytmusic_publish_state(
        user_id="u1", playlist_id="p1",
        ytmusic_playlist_id="PLabc", now=now,
    )
    assert ok is True
    sql, params = fake.calls[-1]
    assert "ytmusic_playlist_id = :ytmusic_playlist_id" in sql
    assert "ytmusic_needs_republish = FALSE" in sql
    assert params["ytmusic_playlist_id"] == "PLabc"
    assert params["id"] == "p1"
```

> Note: `PlaylistsRepository.__init__` takes `data_api=`. Confirm the exact keyword by reading the class constructor at the top of `playlists_repository.py` before running; adjust the fake wiring if it differs.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_playlists_repository_ytmusic_publish.py -q`
Expected: FAIL — `_row` raises `KeyError`/`TypeError` (no ytmusic fields) and `set_ytmusic_publish_state` does not exist.

- [ ] **Step 3a: Extend `PlaylistRow`**

In `src/collector/curation/playlists_repository.py`, add three fields at the END of the `PlaylistRow` dataclass (after `status: str`), with defaults so existing direct constructions keep working:

```python
    status: str  # 'active' | 'completed'
    ytmusic_playlist_id: str | None = None
    ytmusic_last_published_at: str | None = None
    ytmusic_needs_republish: bool = False
```

- [ ] **Step 3b: Extend `_PLAYLIST_SELECT`**

Add the three columns to the `SELECT` list (after `p.spotify_playlist_id, p.last_published_at, p.needs_republish,`):

```python
        p.spotify_playlist_id, p.last_published_at, p.needs_republish,
        p.ytmusic_playlist_id, p.ytmusic_last_published_at,
        p.ytmusic_needs_republish,
```

- [ ] **Step 3c: Extend `_row`**

In `_row(...)`, before `status=...`, add:

```python
        ytmusic_playlist_id=raw.get("ytmusic_playlist_id"),
        ytmusic_last_published_at=(
            str(raw["ytmusic_last_published_at"])
            if raw.get("ytmusic_last_published_at") else None
        ),
        ytmusic_needs_republish=bool(raw.get("ytmusic_needs_republish")),
```

- [ ] **Step 3d: Add `set_ytmusic_publish_state`**

Immediately after `set_publish_state` (after its `return bool(rows)`), add:

```python
    def set_ytmusic_publish_state(
        self,
        *,
        user_id: str,
        playlist_id: str,
        ytmusic_playlist_id: str,
        now: datetime,
    ) -> bool:
        """Record the YouTube Music playlist id + publish timestamp and clear
        the ytmusic drift flag. Mirror of ``set_publish_state`` for the
        ytmusic target."""
        rows = self._data_api.execute(
            """
            UPDATE playlists SET
                ytmusic_playlist_id = :ytmusic_playlist_id,
                ytmusic_last_published_at = :now,
                ytmusic_needs_republish = FALSE,
                updated_at = :now
            WHERE id = :id AND user_id = :user_id AND deleted_at IS NULL
            RETURNING id
            """,
            {
                "id": playlist_id,
                "user_id": user_id,
                "ytmusic_playlist_id": ytmusic_playlist_id,
                "now": now,
            },
        )
        return bool(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_playlists_repository_ytmusic_publish.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the existing repository tests to confirm no regressions**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit -k playlists_repository -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd "$WT" && git add src/collector/curation/playlists_repository.py tests/unit/test_playlists_repository_ytmusic_publish.py
git commit -m "feat(curation): read+write ytmusic publish state in playlists repo"
```

---

# Phase 2 — YouTube Music OAuth (device flow)

## Task 4: `YtmusicOAuthClient` + settings resolver

Google device-flow against `https://oauth2.googleapis.com/device/code` and `.../token`. Modeled on `spotify_oauth.py` (urllib + injectable `urlopen`).

**Files:**
- Create: `src/collector/auth/ytmusic_oauth.py`
- Modify: `src/collector/auth/auth_settings.py` (append `resolve_ytmusic_oauth_credentials`)
- Test: `tests/unit/test_ytmusic_oauth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ytmusic_oauth.py`:

```python
import json
import io

import pytest

from collector.auth.ytmusic_oauth import (
    YtmusicAuthError,
    YtmusicAuthExpired,
    YtmusicAuthPending,
    YtmusicOAuthClient,
)


class FakeResp:
    def __init__(self, status, body):
        self.status = status
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_client(responses):
    """responses: list of (status, body) returned in order."""
    seq = list(responses)

    def fake_urlopen(req, timeout):
        status, body = seq.pop(0)
        return FakeResp(status, body)

    return YtmusicOAuthClient(
        client_id="cid", client_secret="csec", urlopen=fake_urlopen
    )


def test_request_device_code():
    client = make_client([
        (200, {
            "device_code": "dc", "user_code": "ABCD-EFGH",
            "verification_url": "https://www.google.com/device",
            "expires_in": 1800, "interval": 5,
        }),
    ])
    code = client.request_device_code()
    assert code.device_code == "dc"
    assert code.user_code == "ABCD-EFGH"
    assert code.verification_url == "https://www.google.com/device"
    assert code.interval == 5
    assert code.expires_in == 1800


def test_exchange_pending_raises_pending():
    client = make_client([(428, {"error": "authorization_pending"})])
    with pytest.raises(YtmusicAuthPending):
        client.exchange_device_code(device_code="dc")


def test_exchange_expired_raises_expired():
    client = make_client([(400, {"error": "expired_token"})])
    with pytest.raises(YtmusicAuthExpired):
        client.exchange_device_code(device_code="dc")


def test_exchange_success_returns_tokens():
    client = make_client([
        (200, {
            "access_token": "at", "refresh_token": "rt",
            "expires_in": 3599, "scope": "https://www.googleapis.com/auth/youtube",
            "token_type": "Bearer",
        }),
    ])
    tokens = client.exchange_device_code(device_code="dc")
    assert tokens.access_token == "at"
    assert tokens.refresh_token == "rt"
    assert tokens.expires_in == 3599


def test_refresh_keeps_old_refresh_token_when_absent():
    client = make_client([
        (200, {"access_token": "at2", "expires_in": 3599,
                "scope": "s", "token_type": "Bearer"}),
    ])
    tokens = client.refresh(refresh_token="rt-old")
    assert tokens.access_token == "at2"
    assert tokens.refresh_token == "rt-old"


def test_unknown_error_raises_autherror():
    client = make_client([(403, {"error": "access_denied"})])
    with pytest.raises(YtmusicAuthError):
        client.exchange_device_code(device_code="dc")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_ytmusic_oauth.py -q`
Expected: FAIL — module `collector.auth.ytmusic_oauth` does not exist.

- [ ] **Step 3: Implement `ytmusic_oauth.py`**

Create `src/collector/auth/ytmusic_oauth.py`:

```python
"""Google device-flow OAuth client for YouTube Music (ytmusicapi auth).

Uses the OAuth 2.0 flow for "TVs and Limited Input devices" — the same flow
ytmusicapi expects. We drive Google's endpoints directly (urllib) so the poll
endpoint can return a clean 202 on authorization_pending instead of blocking.
Modeled on collector.auth.spotify_oauth.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
YTMUSIC_SCOPE = "https://www.googleapis.com/auth/youtube"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class YtmusicAuthError(Exception):
    """Generic / unrecoverable device-flow error."""


class YtmusicAuthPending(YtmusicAuthError):
    """User has not yet approved — caller should keep polling."""


class YtmusicAuthSlowDown(YtmusicAuthError):
    """Google asked us to poll less frequently."""


class YtmusicAuthDenied(YtmusicAuthError):
    """User denied the consent screen."""


class YtmusicAuthExpired(YtmusicAuthError):
    """device_code expired — restart the flow."""


@dataclass(frozen=True)
class YtmusicDeviceCode:
    device_code: str
    user_code: str
    verification_url: str
    interval: int
    expires_in: int


@dataclass(frozen=True)
class YtmusicTokenSet:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str | None


class YtmusicOAuthClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        timeout_seconds: float = 15.0,
        urlopen: Callable[[urllib.request.Request, float], Any] | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout_seconds
        self._urlopen = urlopen or (
            lambda req, timeout: urllib.request.urlopen(req, timeout=timeout)
        )

    def request_device_code(self) -> YtmusicDeviceCode:
        body = urllib.parse.urlencode(
            {"client_id": self._client_id, "scope": YTMUSIC_SCOPE}
        )
        payload = self._post(DEVICE_CODE_URL, body)
        return YtmusicDeviceCode(
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_url=str(
                payload.get("verification_url")
                or payload.get("verification_uri")
            ),
            interval=int(payload.get("interval", 5)),
            expires_in=int(payload.get("expires_in", 1800)),
        )

    def exchange_device_code(self, *, device_code: str) -> YtmusicTokenSet:
        body = urllib.parse.urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "device_code": device_code,
                "grant_type": DEVICE_GRANT,
            }
        )
        payload = self._post(TOKEN_URL, body, allow_error=True)
        self._raise_for_flow_error(payload)
        return self._token_set(payload, fallback_refresh=None)

    def refresh(self, *, refresh_token: str) -> YtmusicTokenSet:
        body = urllib.parse.urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        )
        payload = self._post(TOKEN_URL, body, allow_error=True)
        self._raise_for_flow_error(payload)
        return self._token_set(payload, fallback_refresh=refresh_token)

    # ---- internals -----------------------------------------------------

    def _raise_for_flow_error(self, payload: dict) -> None:
        err = payload.get("error")
        if not err:
            return
        if err == "authorization_pending":
            raise YtmusicAuthPending(err)
        if err == "slow_down":
            raise YtmusicAuthSlowDown(err)
        if err == "access_denied":
            raise YtmusicAuthDenied(err)
        if err in ("expired_token", "token_expired"):
            raise YtmusicAuthExpired(err)
        raise YtmusicAuthError(f"google oauth error: {payload}")

    def _token_set(
        self, payload: dict, *, fallback_refresh: str | None
    ) -> YtmusicTokenSet:
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise YtmusicAuthError("token response missing access_token")
        refresh = payload.get("refresh_token") or fallback_refresh
        if not isinstance(refresh, str) or not refresh:
            raise YtmusicAuthError("token response missing refresh_token")
        return YtmusicTokenSet(
            access_token=access,
            refresh_token=refresh,
            expires_in=int(payload.get("expires_in", 3599)),
            scope=payload.get("scope"),
        )

    def _post(self, url: str, body: str, *, allow_error: bool = False) -> dict:
        request = urllib.request.Request(
            url=url,
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with self._urlopen(request, self._timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            # Google returns 4xx with a JSON {"error": ...} body for flow
            # states (authorization_pending/slow_down/...). Parse it.
            raw = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
            if not allow_error:
                raise YtmusicAuthError(
                    f"google oauth HTTP {exc.code}: {raw[:200]}"
                ) from exc
        except (URLError, TimeoutError) as exc:
            raise YtmusicAuthError(f"google oauth request failed: {exc}") from exc
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise YtmusicAuthError("google oauth response was not JSON") from exc
```

> **Note on the test's `FakeResp`:** the fake `urlopen` returns a 2xx-style object for every case, so the `HTTPError` branch is exercised only in production. The flow-error tests above pass the error body as a normal 2xx-shaped `FakeResp` with `allow_error=True` reading `{"error": ...}` — which is fine because `_raise_for_flow_error` keys off the `error` field, not the HTTP status. This keeps the unit test independent of urllib's `HTTPError` plumbing. **Manual-verification (Task 15)** exercises the real `HTTPError` path.

- [ ] **Step 4: Add `resolve_ytmusic_oauth_credentials` to settings**

Append to `src/collector/auth/auth_settings.py`:

```python


def resolve_ytmusic_oauth_credentials() -> tuple[str, str]:
    from collector import secrets

    cid = os.environ.get("YTMUSIC_OAUTH_CLIENT_ID", "").strip()
    csec = os.environ.get("YTMUSIC_OAUTH_CLIENT_SECRET", "").strip()
    if cid and csec:
        return cid, csec

    ssm_id = os.environ.get("YTMUSIC_OAUTH_CLIENT_ID_SSM_PARAMETER", "").strip()
    ssm_sec = os.environ.get(
        "YTMUSIC_OAUTH_CLIENT_SECRET_SSM_PARAMETER", ""
    ).strip()
    if ssm_id and ssm_sec:
        return (
            cid or secrets._fetch_ssm_parameter(ssm_id),
            csec or secrets._fetch_ssm_parameter(ssm_sec),
        )

    raise RuntimeError(
        "YouTube Music OAuth credentials not configured: set "
        "YTMUSIC_OAUTH_CLIENT_ID/SECRET or *_SSM_PARAMETER pair"
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_ytmusic_oauth.py -q`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
cd "$WT" && git add src/collector/auth/ytmusic_oauth.py src/collector/auth/auth_settings.py tests/unit/test_ytmusic_oauth.py
git commit -m "feat(auth): add YouTube Music device-flow OAuth client"
```

---

## Task 5: Auth handler — connect / poll / disconnect + /me extension

**Files:**
- Modify: `src/collector/auth_handler.py` (imports ~12-48, `_route` ~125-146, new handlers, `_handle_me` ~548)
- Test: `tests/unit/test_auth_handler_ytmusic.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_handler_ytmusic.py`:

```python
import json
from unittest.mock import patch

from collector import auth_handler
from collector.auth.ytmusic_oauth import (
    YtmusicAuthPending,
    YtmusicDeviceCode,
    YtmusicTokenSet,
)


def _event(route, body=None, user_id="u1"):
    return {
        "requestContext": {
            "routeKey": route,
            "authorizer": {"lambda": {"user_id": user_id, "session_id": "s1"}},
        },
        "body": json.dumps(body) if body is not None else None,
    }


class FakeOAuth:
    def __init__(self, *, code=None, exchange=None, raises=None):
        self._code = code
        self._exchange = exchange
        self._raises = raises

    def request_device_code(self):
        return self._code

    def exchange_device_code(self, *, device_code):
        if self._raises:
            raise self._raises
        return self._exchange


class FakeRepo:
    def __init__(self):
        self.upserts = []
        self.deleted = []

    def upsert_vendor_token(self, cmd):
        self.upserts.append(cmd)

    def delete_vendor_token(self, *, user_id, vendor):
        self.deleted.append((user_id, vendor))


def test_device_code_returns_user_code():
    code = YtmusicDeviceCode(
        device_code="dc", user_code="ABCD-EFGH",
        verification_url="https://www.google.com/device",
        interval=5, expires_in=1800,
    )
    with patch.object(auth_handler, "resolve_ytmusic_oauth_credentials",
                      return_value=("cid", "csec")), \
         patch.object(auth_handler, "YtmusicOAuthClient",
                      return_value=FakeOAuth(code=code)):
        resp = auth_handler._handle_ytmusic_device_code(
            _event("POST /auth/ytmusic/device-code"), "corr"
        )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["user_code"] == "ABCD-EFGH"
    assert body["device_code"] == "dc"
    assert body["interval"] == 5


def test_poll_pending_returns_202():
    with patch.object(auth_handler, "resolve_ytmusic_oauth_credentials",
                      return_value=("cid", "csec")), \
         patch.object(auth_handler, "YtmusicOAuthClient",
                      return_value=FakeOAuth(raises=YtmusicAuthPending("pending"))):
        resp = auth_handler._handle_ytmusic_poll(
            _event("POST /auth/ytmusic/poll", {"device_code": "dc"}), "corr"
        )
    assert resp["statusCode"] == 202
    assert json.loads(resp["body"])["status"] == "authorization_pending"


def test_poll_success_stores_token_and_returns_200():
    tokens = YtmusicTokenSet(
        access_token="at", refresh_token="rt", expires_in=3599, scope="s"
    )
    repo = FakeRepo()
    with patch.object(auth_handler, "resolve_ytmusic_oauth_credentials",
                      return_value=("cid", "csec")), \
         patch.object(auth_handler, "YtmusicOAuthClient",
                      return_value=FakeOAuth(exchange=tokens)), \
         patch.object(auth_handler, "_build_auth_repository", return_value=repo), \
         patch.object(auth_handler, "_build_kms_envelope",
                      return_value=_FakeEnvelope()):
        resp = auth_handler._handle_ytmusic_poll(
            _event("POST /auth/ytmusic/poll", {"device_code": "dc"}), "corr"
        )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["connected"] is True
    assert len(repo.upserts) == 1
    assert repo.upserts[0].vendor == "ytmusic"


class _FakeEnvelope:
    def encrypt(self, b):
        from collector.auth.kms_envelope import EnvelopePayload
        return EnvelopePayload(data_key_enc=b"k", nonce=b"0" * 12, ciphertext=b)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_auth_handler_ytmusic.py -q`
Expected: FAIL — handlers and imported names don't exist on `auth_handler`.

- [ ] **Step 3a: Add imports**

In `src/collector/auth_handler.py`, extend the `auth_settings` import (lines 17-21) to add `resolve_ytmusic_oauth_credentials`, and add an import for the OAuth client + flow errors near the other `auth.*` imports:

```python
from .auth.auth_settings import (
    get_auth_settings,
    resolve_jwt_signing_key,
    resolve_oauth_client_credentials,
    resolve_ytmusic_oauth_credentials,
)
from .auth.ytmusic_oauth import (
    YtmusicAuthError,
    YtmusicAuthExpired,
    YtmusicAuthPending,
    YtmusicAuthSlowDown,
    YtmusicOAuthClient,
)
```

- [ ] **Step 3b: Wire `_route`**

In `_route` (after the `DELETE /me/sessions/{session_id}` branch, before the 404 return), add:

```python
    if route == "POST /auth/ytmusic/device-code":
        return _handle_ytmusic_device_code(event, correlation_id)
    if route == "POST /auth/ytmusic/poll":
        return _handle_ytmusic_poll(event, correlation_id)
    if route == "DELETE /auth/ytmusic":
        return _handle_ytmusic_disconnect(event, correlation_id)
```

- [ ] **Step 3c: Add the three handlers**

Add (e.g. after `_handle_revoke_session`):

```python
def _handle_ytmusic_device_code(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    ctx = _authorizer_context(event)
    user_id = ctx.get("user_id")
    if not user_id:
        raise RefreshInvalidError("authorizer context missing user_id")

    cid, csec = resolve_ytmusic_oauth_credentials()
    oauth = YtmusicOAuthClient(client_id=cid, client_secret=csec)
    code = oauth.request_device_code()
    return _json_response(
        200,
        {
            "device_code": code.device_code,
            "user_code": code.user_code,
            "verification_url": code.verification_url,
            "interval": code.interval,
            "expires_in": code.expires_in,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_ytmusic_poll(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    ctx = _authorizer_context(event)
    user_id = ctx.get("user_id")
    if not user_id:
        raise RefreshInvalidError("authorizer context missing user_id")

    body = json.loads(event.get("body") or "{}")
    device_code = body.get("device_code")
    if not device_code:
        raise ValidationError("device_code is required")

    cid, csec = resolve_ytmusic_oauth_credentials()
    oauth = YtmusicOAuthClient(client_id=cid, client_secret=csec)
    try:
        tokens = oauth.exchange_device_code(device_code=device_code)
    except (YtmusicAuthPending, YtmusicAuthSlowDown) as exc:
        return _json_response(
            202,
            {
                "status": "authorization_pending"
                if isinstance(exc, YtmusicAuthPending) else "slow_down",
                "correlation_id": correlation_id,
            },
            correlation_id,
        )
    except YtmusicAuthExpired as exc:
        raise ValidationError("device code expired, restart connect") from exc
    except YtmusicAuthError as exc:
        raise OAuthExchangeFailedError(str(exc)) from exc

    repo = _build_auth_repository()
    envelope = _build_kms_envelope()
    now = _now()
    access_payload = envelope.encrypt(tokens.access_token.encode("utf-8"))
    refresh_payload = envelope.encrypt(tokens.refresh_token.encode("utf-8"))
    repo.upsert_vendor_token(
        UpsertVendorTokenCmd(
            user_id=str(user_id),
            vendor="ytmusic",
            access_token_enc=access_payload.serialize(),
            refresh_token_enc=refresh_payload.serialize(),
            data_key_enc=access_payload.data_key_enc,
            scope=tokens.scope,
            expires_at=now + timedelta(seconds=tokens.expires_in),
            updated_at=now,
        )
    )
    log_event(
        "INFO", "ytmusic_connect_success",
        correlation_id=correlation_id, user_id=str(user_id),
    )
    return _json_response(
        200, {"connected": True, "correlation_id": correlation_id}, correlation_id
    )


def _handle_ytmusic_disconnect(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    ctx = _authorizer_context(event)
    user_id = ctx.get("user_id")
    if not user_id:
        raise RefreshInvalidError("authorizer context missing user_id")
    repo = _build_auth_repository()
    repo.delete_vendor_token(user_id=str(user_id), vendor="ytmusic")
    return _json_response(
        200, {"connected": False, "correlation_id": correlation_id}, correlation_id
    )
```

- [ ] **Step 3d: Extend `/me` with `ytmusic_connected`**

In `_handle_me`, after `user = repo.get_user_by_id(...)` and before building the response, add:

```python
    ytmusic_connected = (
        repo.get_vendor_token(user_id=str(user_id), vendor="ytmusic") is not None
    )
```

Then add `"ytmusic_connected": ytmusic_connected,` to the response body dict (next to `"is_admin": user.is_admin,`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_auth_handler_ytmusic.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the existing auth + me tests for regressions**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_auth_handler_me.py tests/unit/test_auth_handler_callback.py -q`
Expected: PASS. (If `test_auth_handler_me` asserts the exact `/me` body keys, add `ytmusic_connected` to that assertion.)

- [ ] **Step 6: Commit**

```bash
cd "$WT" && git add src/collector/auth_handler.py tests/unit/test_auth_handler_ytmusic.py
git commit -m "feat(auth): add YouTube Music connect/poll/disconnect endpoints"
```

---

# Phase 3 — Token resolver, user client, publish service

## Task 6: `YtmusicTokenResolver`

Read + decrypt + refresh the ytmusic token, return a ytmusicapi-compatible token dict (fresh access token, `expires_at` epoch). Mirror of `SpotifyTokenResolver`.

**Files:**
- Create: `src/collector/curation/ytmusic_token_resolver.py`
- Test: `tests/unit/test_ytmusic_token_resolver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ytmusic_token_resolver.py`:

```python
import base64
from datetime import datetime, timedelta, timezone

from collector.auth.kms_envelope import EnvelopePayload
from collector.curation import YtmusicNotAuthorizedError
from collector.curation.ytmusic_token_resolver import YtmusicTokenResolver


class FakeEnvelope:
    def encrypt(self, b):
        return EnvelopePayload(data_key_enc=b"k", nonce=b"0" * 12, ciphertext=b)

    def decrypt(self, payload):
        return payload.ciphertext


def _enc(value: str) -> str:
    payload = EnvelopePayload(
        data_key_enc=b"k", nonce=b"0" * 12, ciphertext=value.encode("utf-8")
    )
    return base64.b64encode(payload.serialize()).decode("ascii")


class FakeDataApi:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def execute(self, sql, params=None):
        if sql.strip().upper().startswith("UPDATE"):
            self.updates.append(params)
            return []
        return self.rows


class FakeOAuth:
    def __init__(self, new_access="fresh"):
        self.new_access = new_access
        self.refreshed = False

    def refresh(self, *, refresh_token):
        from collector.auth.ytmusic_oauth import YtmusicTokenSet
        self.refreshed = True
        return YtmusicTokenSet(
            access_token=self.new_access, refresh_token=refresh_token,
            expires_in=3599, scope="s",
        )


def test_no_token_raises():
    resolver = YtmusicTokenResolver(
        data_api=FakeDataApi(rows=[]), envelope=FakeEnvelope(), oauth_client=FakeOAuth()
    )
    try:
        resolver.resolve(user_id="u1")
        assert False
    except YtmusicNotAuthorizedError:
        pass


def test_valid_token_no_refresh():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    rows = [{
        "access_token_enc": _enc("AT"),
        "refresh_token_enc": _enc("RT"),
        "data_key_enc": "", "expires_at": future,
    }]
    oauth = FakeOAuth()
    resolver = YtmusicTokenResolver(
        data_api=FakeDataApi(rows), envelope=FakeEnvelope(), oauth_client=oauth
    )
    token = resolver.resolve(user_id="u1")
    assert token.token_dict["access_token"] == "AT"
    assert oauth.refreshed is False


def test_expired_token_refreshes_and_persists():
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    rows = [{
        "access_token_enc": _enc("OLD"),
        "refresh_token_enc": _enc("RT"),
        "data_key_enc": "", "expires_at": past,
    }]
    api = FakeDataApi(rows)
    oauth = FakeOAuth(new_access="NEW")
    resolver = YtmusicTokenResolver(
        data_api=api, envelope=FakeEnvelope(), oauth_client=oauth
    )
    token = resolver.resolve(user_id="u1")
    assert token.token_dict["access_token"] == "NEW"
    assert oauth.refreshed is True
    assert len(api.updates) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_ytmusic_token_resolver.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `ytmusic_token_resolver.py`**

Create `src/collector/curation/ytmusic_token_resolver.py` (mirror of `spotify_token_resolver.py`, but builds a ytmusicapi token dict and refreshes via Google):

```python
"""Read + KMS-decrypt + refresh the user's YouTube Music OAuth token.

Storage shape comes from user_vendor_tokens (vendor='ytmusic'). Returns a
ytmusicapi-compatible token dict (with a fresh access token + epoch
expires_at) used to build an authenticated YTMusic client.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from collector.auth.kms_envelope import EnvelopePayload, KmsEnvelope
from collector.data_api import DataAPIClient
from collector.logging_utils import log_event

from . import YtmusicNotAuthorizedError

_REFRESH_LEEWAY_SECONDS = 60
_SCOPE = "https://www.googleapis.com/auth/youtube"


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64d(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if value is None:
        return b""
    return base64.b64decode(value)


def _parse_expires_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).replace(" ", "T")
    if "+" not in s and "Z" not in s:
        s = s + "+00:00"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass(frozen=True)
class ResolvedYtmusicToken:
    user_id: str
    token_dict: dict
    refreshed: bool


class _OAuthClientLike(Protocol):
    def refresh(self, *, refresh_token: str) -> Any: ...


class YtmusicTokenResolver:
    def __init__(
        self,
        *,
        data_api: DataAPIClient,
        envelope: KmsEnvelope,
        oauth_client: _OAuthClientLike,
    ) -> None:
        self._data_api = data_api
        self._envelope = envelope
        self._oauth = oauth_client

    def resolve(self, *, user_id: str) -> ResolvedYtmusicToken:
        rows = self._data_api.execute(
            """
            SELECT
                encode(access_token_enc, 'base64')  AS access_token_enc,
                encode(refresh_token_enc, 'base64') AS refresh_token_enc,
                encode(data_key_enc, 'base64')      AS data_key_enc,
                expires_at
            FROM user_vendor_tokens
            WHERE user_id = :user_id AND vendor = 'ytmusic'
            """,
            {"user_id": user_id},
        )
        if not rows:
            raise YtmusicNotAuthorizedError(
                f"No YouTube Music token on file for user {user_id}"
            )
        row = rows[0]
        expires_at = _parse_expires_at(row["expires_at"])
        now = datetime.now(timezone.utc)

        refresh_plain = self._envelope.decrypt(
            EnvelopePayload.deserialize(_b64d(row["refresh_token_enc"]))
        ).decode("utf-8")

        if (expires_at - now).total_seconds() > _REFRESH_LEEWAY_SECONDS:
            access_plain = self._envelope.decrypt(
                EnvelopePayload.deserialize(_b64d(row["access_token_enc"]))
            ).decode("utf-8")
            return ResolvedYtmusicToken(
                user_id=user_id,
                token_dict=self._token_dict(access_plain, refresh_plain, expires_at),
                refreshed=False,
            )

        # Refresh via Google.
        try:
            new_tokens = self._oauth.refresh(refresh_token=refresh_plain)
        except Exception as exc:
            raise YtmusicNotAuthorizedError("YouTube Music refresh failed") from exc

        new_expires = now + timedelta(seconds=int(round(new_tokens.expires_in)))
        access_payload_new = self._envelope.encrypt(
            new_tokens.access_token.encode("utf-8")
        )
        refresh_payload_new = self._envelope.encrypt(
            new_tokens.refresh_token.encode("utf-8")
        )
        self._data_api.execute(
            """
            UPDATE user_vendor_tokens SET
                access_token_enc = decode(:access_enc, 'base64'),
                refresh_token_enc = decode(:refresh_enc, 'base64'),
                expires_at = :expires_at,
                updated_at = :updated_at
            WHERE user_id = :user_id AND vendor = 'ytmusic'
            """,
            {
                "user_id": user_id,
                "access_enc": _b64e(access_payload_new.serialize()),
                "refresh_enc": _b64e(refresh_payload_new.serialize()),
                "expires_at": new_expires,
                "updated_at": now,
            },
        )
        log_event("INFO", "ytmusic_publish_token_refreshed", user_id=user_id)
        return ResolvedYtmusicToken(
            user_id=user_id,
            token_dict=self._token_dict(
                new_tokens.access_token, new_tokens.refresh_token, new_expires
            ),
            refreshed=True,
        )

    @staticmethod
    def _token_dict(
        access_token: str, refresh_token: str, expires_at: datetime
    ) -> dict:
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "scope": _SCOPE,
            "token_type": "Bearer",
            "expires_at": int(expires_at.timestamp()),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_ytmusic_token_resolver.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add src/collector/curation/ytmusic_token_resolver.py tests/unit/test_ytmusic_token_resolver.py
git commit -m "feat(curation): add YouTube Music token resolver"
```

---

## Task 7: `YtmusicUserClient`

Authenticated `ytmusicapi` wrapper. Methods chunk at 100, map failures to the curation error types.

**Files:**
- Create: `src/collector/curation/ytmusic_user_client.py`
- Test: `tests/unit/test_ytmusic_user_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ytmusic_user_client.py`:

```python
import pytest

from collector.curation import YtmusicApiError
from collector.curation.ytmusic_user_client import YtmusicUserClient


class FakeYt:
    def __init__(self, *, create_ret="PLnew", playlist=None):
        self.create_ret = create_ret
        self.playlist = playlist or {"tracks": []}
        self.added = []
        self.removed = []
        self.edited = []

    def create_playlist(self, title, description, privacy_status=None, video_ids=None):
        return self.create_ret

    def get_playlist(self, playlist_id, limit=None):
        return self.playlist

    def add_playlist_items(self, playlist_id, videoIds, duplicates=False):
        self.added.append(list(videoIds))
        return {"status": "STATUS_SUCCEEDED"}

    def remove_playlist_items(self, playlist_id, videos):
        self.removed.append(videos)
        return {"status": "STATUS_SUCCEEDED"}

    def edit_playlist(self, playlist_id, title=None, description=None, privacyStatus=None):
        self.edited.append((title, description, privacyStatus))
        return {"status": "STATUS_SUCCEEDED"}


def test_create_playlist_returns_id():
    client = YtmusicUserClient(yt=FakeYt(create_ret="PLabc"))
    assert client.create_playlist(name="n", description="d", privacy="PUBLIC") == "PLabc"


def test_create_playlist_non_str_raises():
    client = YtmusicUserClient(yt=FakeYt(create_ret={"error": "nope"}))
    with pytest.raises(YtmusicApiError):
        client.create_playlist(name="n", description="d", privacy="PUBLIC")


def test_add_items_chunks_by_100():
    yt = FakeYt()
    client = YtmusicUserClient(yt=yt)
    client.add_items("PL", [f"v{i}" for i in range(250)])
    assert [len(c) for c in yt.added] == [100, 100, 50]


def test_get_existing_items_returns_video_setvideo_pairs():
    yt = FakeYt(playlist={"tracks": [
        {"videoId": "v1", "setVideoId": "s1"},
        {"videoId": "v2", "setVideoId": "s2"},
        {"videoId": "v3"},  # no setVideoId -> skipped
    ]})
    client = YtmusicUserClient(yt=yt)
    items = client.get_existing_items("PL")
    assert items == [
        {"videoId": "v1", "setVideoId": "s1"},
        {"videoId": "v2", "setVideoId": "s2"},
    ]


def test_remove_items_noop_when_empty():
    yt = FakeYt()
    client = YtmusicUserClient(yt=yt)
    client.remove_items("PL", [])
    assert yt.removed == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_ytmusic_user_client.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `ytmusic_user_client.py`**

Create `src/collector/curation/ytmusic_user_client.py`:

```python
"""Authenticated ytmusicapi wrapper for playlist publish.

Single point of impact if Google changes the YouTube Music internal API.
Construct via build_authenticated_ytmusic(); inject a fake `yt` in tests.
"""

from __future__ import annotations

from typing import Any

from . import YtmusicApiError, YtmusicNotFoundError

_CHUNK = 100


def build_authenticated_ytmusic(token_dict: dict, client_id: str, client_secret: str):
    """Build an authenticated ytmusicapi.YTMusic from a token dict."""
    from ytmusicapi import YTMusic

    try:
        from ytmusicapi import OAuthCredentials
    except ImportError:  # pragma: no cover - layout fallback
        from ytmusicapi.auth.oauth import OAuthCredentials

    return YTMusic(
        auth=token_dict,
        oauth_credentials=OAuthCredentials(
            client_id=client_id, client_secret=client_secret
        ),
    )


class YtmusicUserClient:
    def __init__(self, *, yt: Any) -> None:
        self._yt = yt

    def create_playlist(self, *, name: str, description: str | None, privacy: str) -> str:
        result = self._yt.create_playlist(
            name, description or "", privacy_status=privacy
        )
        if not isinstance(result, str):
            raise YtmusicApiError(f"create_playlist failed: {result!r}")
        return result

    def edit_meta(self, *, playlist_id: str, name: str, description: str | None, privacy: str) -> None:
        try:
            self._yt.edit_playlist(
                playlist_id, title=name, description=description or "",
                privacyStatus=privacy,
            )
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from exc

    def get_existing_items(self, playlist_id: str) -> list[dict]:
        try:
            playlist = self._yt.get_playlist(playlist_id, limit=None)
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from exc
        items: list[dict] = []
        for track in (playlist or {}).get("tracks", []) or []:
            vid = track.get("videoId")
            set_vid = track.get("setVideoId")
            if vid and set_vid:
                items.append({"videoId": vid, "setVideoId": set_vid})
        return items

    def add_items(self, playlist_id: str, video_ids: list[str]) -> None:
        for i in range(0, len(video_ids), _CHUNK):
            chunk = video_ids[i : i + _CHUNK]
            if not chunk:
                continue
            try:
                self._yt.add_playlist_items(playlist_id, chunk, duplicates=True)
            except Exception as exc:  # noqa: BLE001
                raise self._classify(exc) from exc

    def remove_items(self, playlist_id: str, items: list[dict]) -> None:
        if not items:
            return
        try:
            self._yt.remove_playlist_items(playlist_id, items)
        except Exception as exc:  # noqa: BLE001
            raise self._classify(exc) from exc

    @staticmethod
    def _classify(exc: Exception) -> YtmusicApiError:
        msg = str(exc).lower()
        if "not found" in msg or "404" in msg or "does not exist" in msg:
            return YtmusicNotFoundError(str(exc))
        return YtmusicApiError(str(exc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_ytmusic_user_client.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add src/collector/curation/ytmusic_user_client.py tests/unit/test_ytmusic_user_client.py
git commit -m "feat(curation): add authenticated ytmusicapi user client"
```

---

## Task 8: `YtmusicPublishService`

**Files:**
- Create: `src/collector/curation/ytmusic_publish_service.py`
- Test: `tests/unit/test_ytmusic_publish_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ytmusic_publish_service.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from collector.curation import (
    ConfirmOverwriteRequiredError,
    NothingToPublishError,
    PlaylistNotFoundError,
    YtmusicNotFoundError,
)
from collector.curation.playlists_repository import YtmusicStatus
from collector.curation.ytmusic_publish_service import YtmusicPublishService


@dataclass
class FakePlaylist:
    id: str
    name: str
    description: str | None
    is_public: bool
    ytmusic_playlist_id: str | None = None


@dataclass
class FakeTrackRow:
    track_id: str
    title: str


class FakeRepo:
    def __init__(self, playlist, rows, statuses):
        self._playlist = playlist
        self._rows = rows
        self._statuses = statuses
        self.published_state = None

    def get(self, *, user_id, playlist_id):
        return self._playlist

    def list_tracks(self, *, user_id, playlist_id, limit, offset):
        return self._rows, len(self._rows)

    def fetch_ytmusic_status(self, track_ids):
        return self._statuses

    def set_ytmusic_publish_state(self, *, user_id, playlist_id, ytmusic_playlist_id, now):
        self.published_state = (ytmusic_playlist_id, now)
        return True


class FakeClient:
    def __init__(self, *, create_ret="PLnew", edit_raises=None):
        self.create_ret = create_ret
        self.edit_raises = edit_raises
        self.created = None
        self.edited = None
        self.added = []
        self.removed = []

    def create_playlist(self, *, name, description, privacy):
        self.created = (name, description, privacy)
        return self.create_ret

    def edit_meta(self, *, playlist_id, name, description, privacy):
        if self.edit_raises:
            raise self.edit_raises
        self.edited = (playlist_id, name, description, privacy)

    def get_existing_items(self, playlist_id):
        return [{"videoId": "old", "setVideoId": "s"}]

    def add_items(self, playlist_id, video_ids):
        self.added.append((playlist_id, list(video_ids)))

    def remove_items(self, playlist_id, items):
        self.removed.append((playlist_id, items))


def _now():
    return datetime(2026, 5, 31, tzinfo=timezone.utc)


def _matched(vid):
    return YtmusicStatus(status="matched", video_id=vid, url=f"u/{vid}", confidence=0.9)


def test_playlist_not_found():
    repo = FakeRepo(None, [], {})
    svc = YtmusicPublishService(repo=repo, ytmusic_client=FakeClient(), now=_now)
    with pytest.raises(PlaylistNotFoundError):
        svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)


def test_first_publish_creates_and_adds():
    pl = FakePlaylist(id="p", name="N", description="D", is_public=True)
    rows = [FakeTrackRow("t1", "T1"), FakeTrackRow("t2", "T2")]
    statuses = {"t1": _matched("v1"), "t2": _matched("v2")}
    client = FakeClient(create_ret="PLnew")
    repo = FakeRepo(pl, rows, statuses)
    svc = YtmusicPublishService(repo=repo, ytmusic_client=client, now=_now)
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)
    assert result.ytmusic_playlist_id == "PLnew"
    assert client.created == ("N", "D", "PUBLIC")
    assert client.added == [("PLnew", ["v1", "v2"])]
    assert result.skipped == []
    assert repo.published_state[0] == "PLnew"


def test_skips_unmatched_tracks():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=False)
    rows = [FakeTrackRow("t1", "T1"), FakeTrackRow("t2", "T2")]
    statuses = {"t1": _matched("v1"), "t2": YtmusicStatus(status="not_found")}
    client = FakeClient()
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=client, now=_now)
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)
    assert client.created[2] == "PRIVATE"
    assert result.skipped == [{"track_id": "t2", "title": "T2", "reason": "no_ytmusic_match"}]
    assert client.added == [("PLnew", ["v1"])]


def test_nothing_to_publish():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True)
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": YtmusicStatus(status="pending")}
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=FakeClient(), now=_now)
    with pytest.raises(NothingToPublishError):
        svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)


def test_republish_requires_confirm():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLold")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    svc = YtmusicPublishService(repo=FakeRepo(pl, rows, statuses), ytmusic_client=FakeClient(), now=_now)
    with pytest.raises(ConfirmOverwriteRequiredError):
        svc.publish(user_id="u", playlist_id="p", confirm_overwrite=False)


def test_republish_edits_in_place():
    pl = FakePlaylist(id="p", name="N2", description="D2", is_public=True, ytmusic_playlist_id="PLold")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    client = FakeClient()
    repo = FakeRepo(pl, rows, statuses)
    svc = YtmusicPublishService(repo=repo, ytmusic_client=client, now=_now)
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True)
    assert result.ytmusic_playlist_id == "PLold"
    assert client.edited == ("PLold", "N2", "D2", "PUBLIC")
    assert client.removed == [("PLold", [{"videoId": "old", "setVideoId": "s"}])]
    assert client.added == [("PLold", ["v1"])]


def test_orphan_recreates_when_edit_404s():
    pl = FakePlaylist(id="p", name="N", description=None, is_public=True, ytmusic_playlist_id="PLgone")
    rows = [FakeTrackRow("t1", "T1")]
    statuses = {"t1": _matched("v1")}
    client = FakeClient(create_ret="PLnew", edit_raises=YtmusicNotFoundError("gone"))
    repo = FakeRepo(pl, rows, statuses)
    svc = YtmusicPublishService(repo=repo, ytmusic_client=client, now=_now)
    result = svc.publish(user_id="u", playlist_id="p", confirm_overwrite=True)
    assert result.ytmusic_playlist_id == "PLnew"
    assert client.created is not None
    assert repo.published_state[0] == "PLnew"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_ytmusic_publish_service.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `ytmusic_publish_service.py`**

Create `src/collector/curation/ytmusic_publish_service.py`:

```python
"""Publish orchestration for the YouTube Music target.

Mirror of PlaylistsPublishService. Matched video_ids come from
fetch_ytmusic_status; unmatched tracks are skipped with reason
'no_ytmusic_match'. No cover (YouTube Music has no custom-cover API).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from collector.logging_utils import log_event

from . import (
    ConfirmOverwriteRequiredError,
    NothingToPublishError,
    PlaylistNotFoundError,
    YtmusicNotFoundError,
)

_YTMUSIC_PLAYLIST_URL = "https://music.youtube.com/playlist?list={}"


@dataclass(frozen=True)
class YtmusicPublishResult:
    ytmusic_playlist_id: str
    ytmusic_url: str | None
    skipped: list[dict]
    published_at: str


class YtmusicPublishService:
    def __init__(
        self,
        *,
        repo,
        ytmusic_client,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._repo = repo
        self._yt = ytmusic_client
        self._now = now

    def publish(
        self,
        *,
        user_id: str,
        playlist_id: str,
        confirm_overwrite: bool,
        treat_404_as_orphan: bool = True,
    ) -> YtmusicPublishResult:
        playlist = self._repo.get(user_id=user_id, playlist_id=playlist_id)
        if playlist is None:
            raise PlaylistNotFoundError()

        if playlist.ytmusic_playlist_id and not confirm_overwrite:
            raise ConfirmOverwriteRequiredError(
                "Playlist already published to YouTube Music — pass "
                "confirm_overwrite=true to replace"
            )

        rows, _total = self._repo.list_tracks(
            user_id=user_id, playlist_id=playlist_id, limit=10_000, offset=0
        )
        statuses = self._repo.fetch_ytmusic_status([r.track_id for r in rows])

        video_ids: list[str] = []
        skipped: list[dict] = []
        for r in rows:
            st = statuses.get(r.track_id)
            if st is not None and st.status == "matched" and st.video_id:
                video_ids.append(st.video_id)
            else:
                skipped.append(
                    {"track_id": r.track_id, "title": r.title, "reason": "no_ytmusic_match"}
                )
        if not video_ids:
            raise NothingToPublishError("Playlist has no matched YouTube Music tracks")

        privacy = "PUBLIC" if playlist.is_public else "PRIVATE"

        log_event(
            "INFO", "ytmusic_publish_started",
            user_id=user_id, playlist_id=playlist_id,
            first_time=not bool(playlist.ytmusic_playlist_id),
            track_count=len(video_ids),
        )

        target_id = playlist.ytmusic_playlist_id
        if target_id:
            try:
                self._yt.edit_meta(
                    playlist_id=target_id, name=playlist.name,
                    description=playlist.description, privacy=privacy,
                )
                existing = self._yt.get_existing_items(target_id)
                self._yt.remove_items(target_id, existing)
            except YtmusicNotFoundError:
                if not treat_404_as_orphan:
                    raise
                log_event(
                    "WARNING", "ytmusic_publish_orphan_recreated",
                    user_id=user_id, playlist_id=playlist_id,
                    old_ytmusic_playlist_id=target_id,
                )
                target_id = None

        if not target_id:
            target_id = self._yt.create_playlist(
                name=playlist.name, description=playlist.description, privacy=privacy
            )

        self._yt.add_items(target_id, video_ids)

        now = self._now()
        self._repo.set_ytmusic_publish_state(
            user_id=user_id, playlist_id=playlist_id,
            ytmusic_playlist_id=target_id, now=now,
        )
        log_event(
            "INFO", "ytmusic_publish_succeeded",
            user_id=user_id, playlist_id=playlist_id,
            ytmusic_playlist_id=target_id, skipped=len(skipped),
        )
        return YtmusicPublishResult(
            ytmusic_playlist_id=target_id,
            ytmusic_url=_YTMUSIC_PLAYLIST_URL.format(target_id),
            skipped=skipped,
            published_at=now.isoformat(),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_ytmusic_publish_service.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add src/collector/curation/ytmusic_publish_service.py tests/unit/test_ytmusic_publish_service.py
git commit -m "feat(curation): add YouTube Music publish service"
```

---

## Task 9: Curation handler — publish-ytmusic route

**Files:**
- Modify: `src/collector/curation_handler.py` (add handler near `_handle_publish` ~1172, builder near `_build_spotify_user_client` ~1805, route table ~1861)
- Test: `tests/unit/test_handle_publish_ytmusic.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_handle_publish_ytmusic.py`:

```python
import json
from unittest.mock import patch

from collector import curation_handler
from collector.curation.ytmusic_publish_service import YtmusicPublishResult


def _event(pid="p1", body=None):
    return {
        "pathParameters": {"id": pid},
        "body": json.dumps(body) if body is not None else None,
    }


def test_handle_publish_ytmusic_returns_payload():
    result = YtmusicPublishResult(
        ytmusic_playlist_id="PLabc",
        ytmusic_url="https://music.youtube.com/playlist?list=PLabc",
        skipped=[{"track_id": "t2", "title": "T2", "reason": "no_ytmusic_match"}],
        published_at="2026-05-31T00:00:00+00:00",
    )

    class FakeSvc:
        def publish(self, **kwargs):
            assert kwargs["confirm_overwrite"] is True
            return result

    with patch.object(curation_handler, "_build_ytmusic_user_client", return_value=object()), \
         patch("collector.curation.ytmusic_publish_service.YtmusicPublishService",
               return_value=FakeSvc()):
        resp = curation_handler._handle_publish_ytmusic(
            _event(body={"confirm_overwrite": True}), repo=object(),
            user_id="u1", correlation_id="corr",
        )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["ytmusic_playlist_id"] == "PLabc"
    assert body["ytmusic_url"].endswith("PLabc")
    assert body["skipped_tracks"][0]["reason"] == "no_ytmusic_match"
    assert "publish-ytmusic" not in body  # sanity


def test_route_table_has_publish_ytmusic():
    assert "POST /playlists/{id}/publish-ytmusic" in curation_handler._ROUTE_TABLE
    handler, _factory = curation_handler._ROUTE_TABLE["POST /playlists/{id}/publish-ytmusic"]
    assert handler is curation_handler._handle_publish_ytmusic
```

> Confirm the existing body-model name (`PublishPlaylistIn`) and `_parse_body` are reused; the handler below mirrors `_handle_publish`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_handle_publish_ytmusic.py -q`
Expected: FAIL — `_handle_publish_ytmusic` / route entry missing.

- [ ] **Step 3a: Add the builder**

In `src/collector/curation_handler.py`, after `_build_spotify_user_client` (~line 1805), add:

```python
def _build_ytmusic_user_client(user_id: str, correlation_id: str):
    """Build an authenticated YouTube Music client for the user.

    Token refresh + KMS decrypt go through YtmusicTokenResolver. Raises
    YtmusicNotAuthorizedError (→ 412) if the user has not connected YT Music.
    """
    import boto3
    from collector.auth.auth_settings import (
        get_auth_settings,
        resolve_ytmusic_oauth_credentials,
    )
    from collector.auth.kms_envelope import KmsEnvelope
    from collector.auth.ytmusic_oauth import YtmusicOAuthClient
    from collector.curation.ytmusic_token_resolver import YtmusicTokenResolver
    from collector.curation.ytmusic_user_client import (
        YtmusicUserClient,
        build_authenticated_ytmusic,
    )
    from collector.data_api import create_default_data_api_client
    from collector.settings import get_data_api_settings

    db = get_data_api_settings()
    auth = get_auth_settings()
    cid, csec = resolve_ytmusic_oauth_credentials()
    data_api = create_default_data_api_client(
        resource_arn=str(db.aurora_cluster_arn),
        secret_arn=str(db.aurora_secret_arn),
        database=db.aurora_database,
    )
    envelope = KmsEnvelope(
        kms_client=boto3.client("kms"),
        key_arn=auth.kms_user_tokens_key_arn,
    )
    oauth = YtmusicOAuthClient(client_id=cid, client_secret=csec)
    resolver = YtmusicTokenResolver(
        data_api=data_api, envelope=envelope, oauth_client=oauth,
    )
    token = resolver.resolve(user_id=user_id)
    yt = build_authenticated_ytmusic(token.token_dict, cid, csec)
    return YtmusicUserClient(yt=yt)
```

- [ ] **Step 3b: Add the handler**

After `_handle_publish` (~line 1172), add:

```python
def _handle_publish_ytmusic(event, repo, user_id, correlation_id):
    pid = (event.get("pathParameters") or {}).get("id")
    if not pid:
        raise ValidationError("id is required in path")
    body = PublishPlaylistIn.model_validate(_parse_body(event))

    yt_client = _build_ytmusic_user_client(user_id, correlation_id)

    from .curation.ytmusic_publish_service import YtmusicPublishService

    svc = YtmusicPublishService(repo=repo, ytmusic_client=yt_client)
    result = svc.publish(
        user_id=user_id, playlist_id=pid,
        confirm_overwrite=body.confirm_overwrite,
    )
    return _json_response(
        200,
        {
            "ytmusic_playlist_id": result.ytmusic_playlist_id,
            "ytmusic_url": result.ytmusic_url,
            "skipped_tracks": result.skipped,
            "published_at": result.published_at,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )
```

- [ ] **Step 3c: Register the route**

In `_ROUTE_TABLE`, after the `POST /playlists/{id}/publish` entry, add:

```python
    "POST /playlists/{id}/publish-ytmusic": (
        _handle_publish_ytmusic, _playlists_factory,
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit/test_handle_publish_ytmusic.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full backend unit suite for regressions**

Run: `cd "$WT" && "$VENV/bin/pytest" tests/unit -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
cd "$WT" && git add src/collector/curation_handler.py tests/unit/test_handle_publish_ytmusic.py
git commit -m "feat(curation): add POST /playlists/{id}/publish-ytmusic route"
```

---

# Phase 4 — API surface (OpenAPI + infra)

## Task 10: OpenAPI routes + regenerate spec & schema

**Files:**
- Modify: `scripts/generate_openapi.py` (`ROUTES` — auth section ~1329, playlists publish section ~2908)
- Regenerated: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`

- [ ] **Step 1: Add the publish-ytmusic route entry**

In `scripts/generate_openapi.py`, immediately after the `/playlists/{id}/publish` route dict (ends ~line 2908), add:

```python
    {
        "method": "post",
        "path": "/playlists/{id}/publish-ytmusic",
        "auth": AUTH,
        "summary": "Publish the playlist to the user's YouTube Music account.",
        "description": (
            "Creates or overwrites the linked YouTube Music playlist with the "
            "current matched tracks (video ids from vendor_track_map) and "
            "metadata (name, description, privacy). Unmatched tracks are "
            "skipped. On overwrite the client must pass `confirm_overwrite=true`."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": False,
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {
                    "confirm_overwrite": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"confirm_overwrite": True},
        "responses": {
            "200": _make_response(200, "Playlist published; returns YouTube Music playlist id.", {"type": "object"}),
            "400": _error(400, "nothing_to_publish (no matched YouTube Music tracks)."),
            "404": _error(404, "playlist_not_found."),
            "409": _error(409, "confirm_overwrite_required."),
            "412": _error(412, "ytmusic_not_authorized (YouTube Music not connected)."),
            "502": _error(502, "ytmusic_api_error."),
            **COMMON_AUTH_ERRORS,
        },
    },
```

- [ ] **Step 2: Add the three connect route entries**

After the `/me/sessions/{session_id}` route dict (~line 1346), add:

```python
    {
        "method": "post",
        "path": "/auth/ytmusic/device-code",
        "auth": AUTH,
        "summary": "Start YouTube Music device-flow OAuth.",
        "description": "Returns a user_code + verification_url; client shows it and polls /auth/ytmusic/poll.",
        "responses": {
            "200": _make_response(200, "Device code issued.", {"type": "object"}),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/auth/ytmusic/poll",
        "auth": AUTH,
        "summary": "Poll for YouTube Music device-flow completion.",
        "description": "Exchanges the device_code. 202 while pending; 200 once the account is linked.",
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {"device_code": {"type": "string"}},
                "required": ["device_code"],
                "additionalProperties": False,
            }}},
        },
        "responses": {
            "200": _make_response(200, "Account linked.", {"type": "object"}),
            "202": {"description": "authorization_pending or slow_down — keep polling."},
            "422": _error(422, "device code expired — restart."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/auth/ytmusic",
        "auth": AUTH,
        "summary": "Disconnect the user's YouTube Music account.",
        "responses": {
            "200": _make_response(200, "Disconnected.", {"type": "object"}),
            **COMMON_AUTH_ERRORS,
        },
    },
```

- [ ] **Step 3: Regenerate the OpenAPI spec**

Run: `cd "$WT" && PYTHONPATH=src "$VENV/bin/python" scripts/generate_openapi.py`
Expected: writes `docs/api/openapi.yaml`; exit 0. Verify the new paths appear:
```bash
cd "$WT" && grep -n "publish-ytmusic\|auth/ytmusic" docs/api/openapi.yaml
```
Expected: 4 path entries shown.

- [ ] **Step 4: Regenerate the frontend schema types**

Run: `cd "$WT/frontend" && pnpm run gen:api` (or the script the repo uses to produce `src/api/schema.d.ts` from `docs/api/openapi.yaml`; check `frontend/package.json` "scripts" for the exact name — likely `gen:api` or `openapi-typescript`).
Expected: `src/api/schema.d.ts` updated; `git diff --stat` shows it changed.

- [ ] **Step 5: Commit**

```bash
cd "$WT" && git add scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts
git commit -m "feat(api): document ytmusic publish + connect routes in OpenAPI"
```

---

## Task 11: Infra — routes, env vars, variables

**Files:**
- Modify: `infra/curation_routes_playlists.tf` (route list)
- Modify: `infra/auth.tf` (connect routes + auth_handler env)
- Modify: `infra/curation.tf` (curation env)
- Modify: `infra/variables.tf` (ytmusic SSM param variables)

- [ ] **Step 1: Add the publish-ytmusic route**

In `infra/curation_routes_playlists.tf`, add to the `curation_playlist_routes` list (after `"POST /playlists/{id}/publish",`):

```hcl
    "POST /playlists/{id}/publish-ytmusic",
```

- [ ] **Step 2: Add the connect routes (auth Lambda, JWT-gated)**

In `infra/auth.tf`, after the `me_session_revoke` route resource, add:

```hcl
resource "aws_apigatewayv2_route" "ytmusic_device_code" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /auth/ytmusic/device-code"
  target             = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "ytmusic_poll" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /auth/ytmusic/poll"
  target             = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "ytmusic_disconnect" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "DELETE /auth/ytmusic"
  target             = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 3: Add ytmusic SSM variables**

In `infra/variables.tf`, add (near the `spotify_client_*_ssm_parameter` variables — search for `spotify_client_id_ssm_parameter` to find them):

```hcl
variable "ytmusic_client_id_ssm_parameter" {
  type        = string
  description = "SSM parameter name holding the YouTube Music (Google TV-device) OAuth client_id."
  default     = "/beatport-prod/ytmusic/oauth_client_id"
}

variable "ytmusic_client_secret_ssm_parameter" {
  type        = string
  description = "SSM parameter name holding the YouTube Music OAuth client_secret."
  default     = "/beatport-prod/ytmusic/oauth_client_secret"
}
```

> The actual values are pushed into these SSM SecureString params out-of-band (same pattern as Spotify — see the comment in `auth.tf`). Confirm the collector_lambda IAM role already grants `ssm:GetParameter` on the project SSM prefix; if it is scoped to specific Spotify param ARNs, extend it to include these two names.

- [ ] **Step 4: Wire env vars on the auth_handler Lambda**

In `infra/auth.tf`, inside `aws_lambda_function.auth_handler` → `environment.variables`, add:

```hcl
      YTMUSIC_OAUTH_CLIENT_ID_SSM_PARAMETER     = var.ytmusic_client_id_ssm_parameter
      YTMUSIC_OAUTH_CLIENT_SECRET_SSM_PARAMETER = var.ytmusic_client_secret_ssm_parameter
```

- [ ] **Step 5: Wire env vars on the curation Lambda**

In `infra/curation.tf`, inside the curation Lambda `environment.variables`, add the same two lines:

```hcl
      YTMUSIC_OAUTH_CLIENT_ID_SSM_PARAMETER     = var.ytmusic_client_id_ssm_parameter
      YTMUSIC_OAUTH_CLIENT_SECRET_SSM_PARAMETER = var.ytmusic_client_secret_ssm_parameter
```

- [ ] **Step 6: Validate**

Run:
```bash
cd "$WT/infra" && terraform fmt && terraform validate
```
Expected: `Success! The configuration is valid.` (Requires `terraform init` already run in this infra dir. Do not `terraform apply` as part of this task.)

- [ ] **Step 7: Commit**

```bash
cd "$WT" && git add infra/
git commit -m "feat(infra): add ytmusic connect routes, publish route, oauth env"
```

---

# Phase 5 — Frontend

## Task 12: Types + `useMe` + `usePublishYtmusic`

**Files:**
- Modify: `frontend/src/features/playlists/lib/playlistTypes.ts`
- Create: `frontend/src/features/playlists/hooks/useMe.ts`
- Create: `frontend/src/features/playlists/hooks/usePublishYtmusic.ts`
- Test: `frontend/src/features/playlists/hooks/usePublishYtmusic.test.tsx`

- [ ] **Step 1: Extend types**

In `frontend/src/features/playlists/lib/playlistTypes.ts`:

Add to the `Playlist` interface (after `needs_republish`):
```typescript
  ytmusic_playlist_id: string | null;
  ytmusic_last_published_at: string | null;
  ytmusic_needs_republish: boolean;
```

Add new interfaces (after `PublishResult`):
```typescript
export interface YtmusicPublishResult {
  ytmusic_playlist_id: string;
  ytmusic_url: string;
  skipped_tracks: { track_id: string; title: string; reason: string }[];
  published_at: string;
  correlation_id?: string;
}

export interface MeResponse {
  id: string;
  spotify_id: string;
  display_name: string | null;
  email: string | null;
  is_admin: boolean;
  ytmusic_connected: boolean;
}
```

- [ ] **Step 2: Write the failing hook test**

Create `frontend/src/features/playlists/hooks/usePublishYtmusic.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { usePublishYtmusic } from './usePublishYtmusic';
import * as client from '../../../api/client';

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('usePublishYtmusic', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('POSTs to publish-ytmusic with confirm_overwrite', async () => {
    const spy = vi.spyOn(client, 'api').mockResolvedValue({
      ytmusic_playlist_id: 'PLabc',
      ytmusic_url: 'https://music.youtube.com/playlist?list=PLabc',
      skipped_tracks: [],
      published_at: '2026-05-31T00:00:00Z',
    });
    const { result } = renderHook(() => usePublishYtmusic(), { wrapper });
    await result.current.mutateAsync({ playlistId: 'p1', confirmOverwrite: true });
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith('/playlists/p1/publish-ytmusic', {
      method: 'POST',
      body: JSON.stringify({ confirm_overwrite: true }),
    });
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd "$WT/frontend" && pnpm test usePublishYtmusic -- --run`
Expected: FAIL — hook module does not exist.

- [ ] **Step 4: Implement the hooks**

Create `frontend/src/features/playlists/hooks/usePublishYtmusic.ts`:

```typescript
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { YtmusicPublishResult } from '../lib/playlistTypes';
import { playlistDetailKey } from '../lib/queryKeys';

export interface PublishYtmusicInput {
  playlistId: string;
  confirmOverwrite: boolean;
}

export function usePublishYtmusic(): UseMutationResult<YtmusicPublishResult, Error, PublishYtmusicInput> {
  const qc = useQueryClient();
  return useMutation<YtmusicPublishResult, Error, PublishYtmusicInput>({
    mutationFn: ({ playlistId, confirmOverwrite }) =>
      api<YtmusicPublishResult>(`/playlists/${playlistId}/publish-ytmusic`, {
        method: 'POST',
        body: JSON.stringify({ confirm_overwrite: confirmOverwrite }),
      }),
    onSuccess: (_data, { playlistId }) => {
      qc.invalidateQueries({ queryKey: playlistDetailKey(playlistId) });
      qc.invalidateQueries({ queryKey: ['playlists', 'list'] });
    },
  });
}
```

Create `frontend/src/features/playlists/hooks/useMe.ts`:

```typescript
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { MeResponse } from '../lib/playlistTypes';

export function useMe(): UseQueryResult<MeResponse, Error> {
  return useQuery<MeResponse, Error>({
    queryKey: ['me'],
    queryFn: () => api<MeResponse>('/me'),
    staleTime: 60_000,
  });
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "$WT/frontend" && pnpm test usePublishYtmusic -- --run`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd "$WT" && git add frontend/src/features/playlists/lib/playlistTypes.ts frontend/src/features/playlists/hooks/useMe.ts frontend/src/features/playlists/hooks/usePublishYtmusic.ts frontend/src/features/playlists/hooks/usePublishYtmusic.test.tsx
git commit -m "feat(frontend): add ytmusic publish + me hooks and types"
```

---

## Task 13: `YtMusicConnectModal` + connect hooks

**Files:**
- Create: `frontend/src/features/playlists/hooks/useYtmusicConnect.ts`
- Create: `frontend/src/features/playlists/components/YtMusicConnectModal.tsx`
- Modify: `frontend/src/i18n/en.json`
- Test: `frontend/src/features/playlists/components/YtMusicConnectModal.test.tsx`

- [ ] **Step 1: Add i18n strings**

In `frontend/src/i18n/en.json`, under `playlists.publish` add:
```json
      "ytmusic": "Publish to YT Music",
      "ytmusic_again": "Re-publish to YT Music",
      "open_in_ytmusic": "Open in YouTube Music"
```
Under `playlists.toast` add:
```json
      "ytmusic_published_first": "Playlist published to YouTube Music",
      "ytmusic_published_again": "Playlist re-published to YouTube Music"
```
Under `playlists.errors` add:
```json
      "ytmusic_not_authorized": "YouTube Music isn't connected.",
      "ytmusic_api_error": "YouTube Music is unreachable, retry in a moment."
```
Add a new `playlists.ytmusic_connect` object:
```json
    "ytmusic_connect": {
      "title": "Connect YouTube Music",
      "body": "Open the link, sign in with the YouTube Music account you want to publish to, and enter this code:",
      "open_link": "Open google.com/device",
      "waiting": "Waiting for you to approve…",
      "expired": "The code expired. Close and try again.",
      "error": "Could not connect. Close and try again."
    }
```

- [ ] **Step 2: Write the failing component test**

Create `frontend/src/features/playlists/components/YtMusicConnectModal.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '../../../test/renderApp';
import { YtMusicConnectModal } from './YtMusicConnectModal';
import * as client from '../../../api/client';

describe('YtMusicConnectModal', () => {
  it('shows the user code and verification link', async () => {
    vi.spyOn(client, 'api').mockResolvedValue({
      device_code: 'dc', user_code: 'ABCD-EFGH',
      verification_url: 'https://www.google.com/device',
      interval: 1, expires_in: 1800,
    });
    render(
      <YtMusicConnectModal opened onClose={() => {}} onConnected={() => {}} />,
    );
    expect(await screen.findByText('ABCD-EFGH')).toBeInTheDocument();
  });
});
```

> Adjust the `render`/`renderApp` import to match the repo's test harness signature (see `src/test/renderApp.tsx`). It already seeds an auth token.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd "$WT/frontend" && pnpm test YtMusicConnectModal -- --run`
Expected: FAIL — component module does not exist.

- [ ] **Step 4: Implement the connect hooks**

Create `frontend/src/features/playlists/hooks/useYtmusicConnect.ts`:

```typescript
import { useMutation } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface DeviceCodeResponse {
  device_code: string;
  user_code: string;
  verification_url: string;
  interval: number;
  expires_in: number;
}

export interface PollResponse {
  status?: 'authorization_pending' | 'slow_down';
  connected?: boolean;
}

export function useRequestDeviceCode() {
  return useMutation<DeviceCodeResponse, Error, void>({
    mutationFn: () => api<DeviceCodeResponse>('/auth/ytmusic/device-code', { method: 'POST' }),
  });
}

export function usePollYtmusic() {
  return useMutation<PollResponse, Error, { deviceCode: string }>({
    mutationFn: ({ deviceCode }) =>
      api<PollResponse>('/auth/ytmusic/poll', {
        method: 'POST',
        body: JSON.stringify({ device_code: deviceCode }),
      }),
  });
}
```

- [ ] **Step 5: Implement `YtMusicConnectModal`**

Create `frontend/src/features/playlists/components/YtMusicConnectModal.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react';
import { Anchor, Button, Code, Group, Loader, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { useRequestDeviceCode, usePollYtmusic } from '../hooks/useYtmusicConnect';

export interface YtMusicConnectModalProps {
  opened: boolean;
  onClose: () => void;
  onConnected: () => void;
}

export function YtMusicConnectModal({ opened, onClose, onConnected }: YtMusicConnectModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const requestCode = useRequestDeviceCode();
  const poll = usePollYtmusic();
  const [code, setCode] = useState<{ userCode: string; url: string; deviceCode: string; interval: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Request a device code when the modal opens.
  useEffect(() => {
    if (!opened) return;
    setError(null);
    setCode(null);
    requestCode
      .mutateAsync()
      .then((r) =>
        setCode({ userCode: r.user_code, url: r.verification_url, deviceCode: r.device_code, interval: r.interval }),
      )
      .catch(() => setError(t('playlists.ytmusic_connect.error')));
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  // Poll until connected.
  useEffect(() => {
    if (!opened || !code) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await poll.mutateAsync({ deviceCode: code.deviceCode });
        if (cancelled) return;
        if (r.connected) {
          qc.invalidateQueries({ queryKey: ['me'] });
          onConnected();
          return;
        }
        timer.current = setTimeout(tick, Math.max(code.interval, 1) * 1000);
      } catch {
        if (!cancelled) setError(t('playlists.ytmusic_connect.expired'));
      }
    };
    timer.current = setTimeout(tick, Math.max(code.interval, 1) * 1000);
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, code]);

  return (
    <Modal opened={opened} onClose={onClose} title={t('playlists.ytmusic_connect.title')} centered>
      <Stack gap="md">
        {error ? (
          <Text c="red">{error}</Text>
        ) : code ? (
          <>
            <Text>{t('playlists.ytmusic_connect.body')}</Text>
            <Code fz="xl" ta="center">{code.userCode}</Code>
            <Anchor href={code.url} target="_blank" rel="noopener noreferrer">
              {t('playlists.ytmusic_connect.open_link')}
            </Anchor>
            <Group gap="xs">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">{t('playlists.ytmusic_connect.waiting')}</Text>
            </Group>
          </>
        ) : (
          <Group justify="center"><Loader /></Group>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>{t('playlists.form.cancel')}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd "$WT/frontend" && pnpm test YtMusicConnectModal -- --run`
Expected: PASS.

- [ ] **Step 7: Browser test for layout**

Create `frontend/src/features/playlists/components/YtMusicConnectModal.browser.test.tsx` mirroring an existing `*.browser.test.tsx` (render the modal opened with a mocked `api`, assert the code element is visible and centered). Run:
`cd "$WT/frontend" && pnpm test:browser YtMusicConnectModal`
Expected: PASS. (Per CLAUDE.md gotcha #11, this validates real layout; jsdom does not.)

- [ ] **Step 8: Commit**

```bash
cd "$WT" && git add frontend/src/features/playlists/hooks/useYtmusicConnect.ts frontend/src/features/playlists/components/YtMusicConnectModal.tsx frontend/src/features/playlists/components/YtMusicConnectModal.test.tsx frontend/src/features/playlists/components/YtMusicConnectModal.browser.test.tsx frontend/src/i18n/en.json
git commit -m "feat(frontend): add YouTube Music connect modal + device-flow hooks"
```

---

## Task 14: `PublishYtMusicButton` + generalize result modal + page wiring

**Files:**
- Modify: `frontend/src/features/playlists/components/PublishResultModal.tsx`
- Create: `frontend/src/features/playlists/components/PublishYtMusicButton.tsx`
- Modify: `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx` (~line 260)
- Test: `frontend/src/features/playlists/components/PublishYtMusicButton.test.tsx`

- [ ] **Step 1: Generalize `PublishResultModal`**

Change `PublishResultModalProps` and the body to accept a vendor URL + label so both Spotify and YT Music can reuse it. Replace the file body with:

```tsx
import { Anchor, Button, Group, List, Modal, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export interface PublishResultModalProps {
  opened: boolean;
  onClose: () => void;
  skippedTracks: { track_id: string; title: string; reason: string }[] | null;
  openUrl: string;
  openLabelKey: string; // i18n key, e.g. 'playlists.publish.open_in_spotify'
}

export function PublishResultModal({
  opened, onClose, skippedTracks, openUrl, openLabelKey,
}: PublishResultModalProps) {
  const { t } = useTranslation();
  if (!skippedTracks) return null;
  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t('playlists.publish.result_skipped_title', { count: skippedTracks.length })}
      centered
      transitionProps={{ duration: 0 }}
    >
      <Stack gap="md">
        <Text>{t('playlists.publish.result_skipped_body')}</Text>
        <List size="sm">
          {skippedTracks.map((s) => (
            <List.Item key={s.track_id}>
              {s.title} — {s.reason}
            </List.Item>
          ))}
        </List>
        <Group justify="space-between">
          <Anchor href={openUrl} target="_blank" rel="noopener noreferrer">
            {t(openLabelKey)}
          </Anchor>
          <Button onClick={onClose}>{t('playlists.form.cancel')}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
```

- [ ] **Step 2: Update the existing Spotify `PublishButton` to the new props**

In `frontend/src/features/playlists/components/PublishButton.tsx`, the `<PublishResultModal>` usage changes. Replace the `resultModal` state type and the modal render:

```tsx
  const [resultModal, setResultModal] = useState<PublishResult | null>(null);
  // ... in doPublish success branch keep: setResultModal(r);
  // Replace the JSX:
      <PublishResultModal
        opened={resultModal !== null}
        onClose={() => setResultModal(null)}
        skippedTracks={resultModal?.skipped_tracks ?? null}
        openUrl={resultModal?.spotify_url ?? ''}
        openLabelKey="playlists.publish.open_in_spotify"
      />
```

- [ ] **Step 3: Write the failing button test**

Create `frontend/src/features/playlists/components/PublishYtMusicButton.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '../../../test/renderApp';
import userEvent from '@testing-library/user-event';
import { PublishYtMusicButton } from './PublishYtMusicButton';
import * as client from '../../../api/client';
import type { Playlist } from '../lib/playlistTypes';

const playlist: Playlist = {
  id: 'p1', user_id: 'u1', name: 'N', description: null, is_public: true,
  cover_s3_key: null, cover_url: null, cover_uploaded_at: null,
  spotify_playlist_id: null, last_published_at: null, needs_republish: false,
  ytmusic_playlist_id: null, ytmusic_last_published_at: null, ytmusic_needs_republish: false,
  track_count: 2, status: 'active', created_at: 't', updated_at: 't',
};

describe('PublishYtMusicButton', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('publishes when already connected', async () => {
    vi.spyOn(client, 'api').mockImplementation(async (path: string) => {
      if (path === '/me') return { ytmusic_connected: true } as never;
      if (path.endsWith('/publish-ytmusic'))
        return {
          ytmusic_playlist_id: 'PLabc',
          ytmusic_url: 'https://music.youtube.com/playlist?list=PLabc',
          skipped_tracks: [], published_at: 't',
        } as never;
      return {} as never;
    });
    render(<PublishYtMusicButton playlist={playlist} />);
    await userEvent.click(await screen.findByRole('button', { name: /YT Music/i }));
    await waitFor(() =>
      expect(client.api).toHaveBeenCalledWith('/playlists/p1/publish-ytmusic', expect.any(Object)),
    );
  });

  it('opens connect modal on 412', async () => {
    const { ApiError } = await import('../../../api/error');
    vi.spyOn(client, 'api').mockImplementation(async (path: string) => {
      if (path === '/me') return { ytmusic_connected: false } as never;
      if (path.endsWith('/publish-ytmusic'))
        throw new ApiError('ytmusic_not_authorized', 412, 'no token');
      if (path.endsWith('/device-code'))
        return { device_code: 'dc', user_code: 'ABCD-EFGH', verification_url: 'u', interval: 1, expires_in: 60 } as never;
      return {} as never;
    });
    render(<PublishYtMusicButton playlist={playlist} />);
    await userEvent.click(await screen.findByRole('button', { name: /YT Music/i }));
    expect(await screen.findByText('ABCD-EFGH')).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd "$WT/frontend" && pnpm test PublishYtMusicButton -- --run`
Expected: FAIL — component does not exist.

- [ ] **Step 5: Implement `PublishYtMusicButton`**

Create `frontend/src/features/playlists/components/PublishYtMusicButton.tsx`:

```tsx
import { useState } from 'react';
import { Anchor, Button, Group } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconBrandYoutube } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import type { Playlist, YtmusicPublishResult } from '../lib/playlistTypes';
import { usePublishYtmusic } from '../hooks/usePublishYtmusic';
import { useMe } from '../hooks/useMe';
import { PublishConfirmModal } from './PublishConfirmModal';
import { PublishResultModal } from './PublishResultModal';
import { YtMusicConnectModal } from './YtMusicConnectModal';

export interface PublishYtMusicButtonProps {
  playlist: Playlist;
}

export function PublishYtMusicButton({ playlist }: PublishYtMusicButtonProps) {
  const { t } = useTranslation();
  const me = useMe();
  const publishMut = usePublishYtmusic();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [resultModal, setResultModal] = useState<YtmusicPublishResult | null>(null);

  const alreadyPublished = !!playlist.ytmusic_playlist_id;

  function handleClick() {
    if (me.data && !me.data.ytmusic_connected) {
      setConnectOpen(true);
      return;
    }
    if (alreadyPublished) {
      setConfirmOpen(true);
    } else {
      void doPublish(false);
    }
  }

  async function doPublish(confirmOverwrite: boolean) {
    try {
      const r = await publishMut.mutateAsync({ playlistId: playlist.id, confirmOverwrite });
      setConfirmOpen(false);
      notifications.show({
        color: 'green',
        message: (
          <Group gap="sm">
            <span>
              {alreadyPublished
                ? t('playlists.toast.ytmusic_published_again')
                : t('playlists.toast.ytmusic_published_first')}
            </span>
            <Anchor href={r.ytmusic_url} target="_blank" rel="noopener noreferrer">
              {t('playlists.publish.open_in_ytmusic')}
            </Anchor>
          </Group>
        ),
      });
      if (r.skipped_tracks.length > 0) setResultModal(r);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === 'confirm_overwrite_required') {
        setConfirmOpen(true);
      } else if (err instanceof ApiError && err.status === 412) {
        setConnectOpen(true);
      } else if (err instanceof ApiError && err.status === 502) {
        notifications.show({ message: t('playlists.errors.ytmusic_api_error'), color: 'red' });
      } else if (err instanceof ApiError && err.status === 400) {
        notifications.show({ message: err.message, color: 'yellow' });
      } else {
        notifications.show({ message: t('playlists.toast.generic_error'), color: 'red' });
      }
    }
  }

  return (
    <>
      <Button
        leftSection={<IconBrandYoutube size={16} />}
        color="red"
        variant="outline"
        loading={publishMut.isPending}
        onClick={handleClick}
      >
        {alreadyPublished ? t('playlists.publish.ytmusic_again') : t('playlists.publish.ytmusic')}
      </Button>
      <PublishConfirmModal
        opened={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => void doPublish(true)}
        playlistName={playlist.name}
        trackCount={playlist.track_count}
        loading={publishMut.isPending}
      />
      <YtMusicConnectModal
        opened={connectOpen}
        onClose={() => setConnectOpen(false)}
        onConnected={() => {
          setConnectOpen(false);
          void me.refetch();
          if (alreadyPublished) setConfirmOpen(true);
          else void doPublish(false);
        }}
      />
      <PublishResultModal
        opened={resultModal !== null}
        onClose={() => setResultModal(null)}
        skippedTracks={resultModal?.skipped_tracks ?? null}
        openUrl={resultModal?.ytmusic_url ?? ''}
        openLabelKey="playlists.publish.open_in_ytmusic"
      />
    </>
  );
}
```

> `PublishConfirmModal` copy is Spotify-worded ("Re-publish to Spotify?"). For v1 it is acceptable to reuse it; if the wording must be vendor-neutral, pass a title/body prop — out of scope here, note it but do not block.

- [ ] **Step 6: Render the button on the detail page**

In `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx`, next to `<PublishButton playlist={playlist} />` (line ~260), add:

```tsx
            <PublishYtMusicButton playlist={playlist} />
```
and add the import at the top:
```tsx
import { PublishYtMusicButton } from '../components/PublishYtMusicButton';
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd "$WT/frontend" && pnpm test PublishYtMusicButton PublishResultModal PublishButton -- --run`
Expected: PASS (the existing `PublishButton`/`PublishResultModal` tests must still pass after the prop change — update their assertions if they referenced the old `result` prop).

- [ ] **Step 8: Browser test**

Add `PublishYtMusicButton.browser.test.tsx` (mirror an existing button browser test) asserting the button renders with the YouTube icon and the connect modal opens. Run:
`cd "$WT/frontend" && pnpm test:browser PublishYtMusicButton`
Expected: PASS.

- [ ] **Step 9: Frontend CI gates (per memory `feedback_verify_frontend_ci_gates`)**

Run:
```bash
cd "$WT/frontend" && pnpm typecheck && pnpm lint && pnpm test -- --run
```
Expected: all green. Fix any type/lint errors before committing.

- [ ] **Step 10: Commit**

```bash
cd "$WT" && git add frontend/src/features/playlists/components/PublishYtMusicButton.tsx frontend/src/features/playlists/components/PublishYtMusicButton.test.tsx frontend/src/features/playlists/components/PublishYtMusicButton.browser.test.tsx frontend/src/features/playlists/components/PublishResultModal.tsx frontend/src/features/playlists/components/PublishButton.tsx frontend/src/features/playlists/routes/PlaylistDetailPage.tsx
git commit -m "feat(frontend): add Publish to YT Music button on playlist page"
```

---

# Phase 6 — Manual verification (unofficial-API risk)

## Task 15: End-to-end smoke against a real Google test account

This is the one part unit tests cannot cover: the unofficial ytmusicapi behavior + the real Google device flow. Do this with a throwaway/test Google account added as a test user on the OAuth consent screen.

- [ ] **Step 1: Create the Google OAuth client**

In Google Cloud Console: create a project, enable "YouTube Data API v3" (the scope gate), configure the OAuth consent screen in **Testing** mode, add your test Google account as a test user, then create an OAuth client of type **"TVs and Limited Input devices"**. Note `client_id` + `client_secret`.

- [ ] **Step 2: Verify the device flow + token dict end-to-end locally**

Run (replace creds):
```bash
cd "$WT" && export PYTHONPATH=src
YTMUSIC_OAUTH_CLIENT_ID=... YTMUSIC_OAUTH_CLIENT_SECRET=... "$VENV/bin/python" - <<'PY'
import os, time
from collector.auth.ytmusic_oauth import YtmusicOAuthClient, YtmusicAuthPending
c = YtmusicOAuthClient(
    client_id=os.environ["YTMUSIC_OAUTH_CLIENT_ID"],
    client_secret=os.environ["YTMUSIC_OAUTH_CLIENT_SECRET"],
)
code = c.request_device_code()
print("Go to", code.verification_url, "and enter:", code.user_code)
while True:
    try:
        tokens = c.exchange_device_code(device_code=code.device_code)
        break
    except YtmusicAuthPending:
        time.sleep(code.interval)
print("access_token len:", len(tokens.access_token), "refresh present:", bool(tokens.refresh_token))
PY
```
Expected: after approving in the browser, prints token lengths. Confirms `request_device_code` + `exchange_device_code` + the real `HTTPError` pending path.

- [ ] **Step 3: Verify `YtmusicUserClient` create + add + edit + remove**

Build an authenticated client from those tokens and exercise the real ytmusicapi surface:
```bash
cd "$WT" && export PYTHONPATH=src
YTMUSIC_OAUTH_CLIENT_ID=... YTMUSIC_OAUTH_CLIENT_SECRET=... "$VENV/bin/python" - <<'PY'
import os, time
from datetime import datetime, timezone, timedelta
from collector.curation.ytmusic_user_client import YtmusicUserClient, build_authenticated_ytmusic
# Paste tokens from Step 2 (or re-run the flow inline):
token_dict = {
    "access_token": "PASTE", "refresh_token": "PASTE",
    "scope": "https://www.googleapis.com/auth/youtube", "token_type": "Bearer",
    "expires_at": int((datetime.now(timezone.utc)+timedelta(hours=1)).timestamp()),
}
yt = build_authenticated_ytmusic(token_dict, os.environ["YTMUSIC_OAUTH_CLIENT_ID"], os.environ["YTMUSIC_OAUTH_CLIENT_SECRET"])
c = YtmusicUserClient(yt=yt)
pid = c.create_playlist(name="CLOUDER smoke", description="delete me", privacy="PRIVATE")
print("created", pid)
# Use a couple of known-good YT Music song videoIds from vendor_track_map:
c.add_items(pid, ["dQw4w9WgXcQ"])
print("existing", c.get_existing_items(pid))
c.edit_meta(playlist_id=pid, name="CLOUDER smoke 2", description="edited", privacy="PRIVATE")
print("OK — now delete it manually in YT Music")
PY
```
Expected: a playlist appears in the test account's YouTube Music library with the track. **Crucially, confirm that videoIds taken from `vendor_track_map` (ytmusicapi "songs" search results) are accepted by `add_playlist_items`.** If some video_ids are rejected, capture the error shape and refine `YtmusicUserClient._classify` / the skip logic before shipping.

- [ ] **Step 4: Note findings**

Record in the PR description: which ytmusicapi exception types `get_playlist`/`edit_playlist` raise for a deleted playlist (to confirm the `_classify` not-found heuristic in Task 7), and whether `add_playlist_items` accepted all matched video_ids. Adjust `_classify` if the real exception messages differ from the heuristic.

---

# Phase 7 — Integration & PR

## Task 16: Full suite + OpenAPI sync check + PR

- [ ] **Step 1: Backend suite**

Run: `cd "$WT" && "$VENV/bin/pytest" -q`
Expected: PASS.

- [ ] **Step 2: OpenAPI is in sync (CI diff-gate)**

Run:
```bash
cd "$WT" && PYTHONPATH=src "$VENV/bin/python" scripts/generate_openapi.py
git diff --exit-code docs/api/openapi.yaml frontend/src/api/schema.d.ts
```
Expected: no diff (already regenerated in Task 10). If there is a diff, commit it.

- [ ] **Step 3: Frontend gates**

Run: `cd "$WT/frontend" && pnpm typecheck && pnpm lint && pnpm test -- --run`
Expected: PASS.

- [ ] **Step 4: Generate PR title + body via caveman-commit, open PR**

Use the `caveman:caveman-commit` skill to produce the PR title + body, then:
```bash
cd "$WT" && gh pr create --base main --head feat/youtube-music-publish --title "<generated>" --body "<generated>"
```
PR body must call out: (a) the manual-verification findings from Task 15, (b) the Google OAuth client + SSM params that must exist before deploy, (c) that YouTube Music has no custom-cover API (parity gap), (d) the unofficial-API risk isolated in `YtmusicUserClient`.

---

## Self-review notes (author)

- **Spec coverage:** OAuth connect (Tasks 4–5, 11), token resolver (6), user client (7), publish service (8), handler/route (9), OpenAPI (10), DB (2–3), errors (1), frontend button/connect/result (12–14), `/me` extension (5), manual verification of the unofficial path (15). All spec sections map to a task.
- **Error codes** corrected to the real values: `confirm_overwrite_required`=409, `nothing_to_publish`=400, `ytmusic_not_authorized`=412, `ytmusic_api_error`=502.
- **Type consistency:** `YtmusicPublishResult` fields (`ytmusic_playlist_id`, `ytmusic_url`, `skipped`/`skipped_tracks`, `published_at`) are consistent across service (Python `skipped`) → handler payload (`skipped_tracks`) → frontend (`skipped_tracks`). `set_ytmusic_publish_state`, `build_authenticated_ytmusic`, `get_existing_items`, `remove_items`, `add_items`, `edit_meta`, `create_playlist` names are used identically in the client (Task 7) and service (Task 8).
- **Known risk flagged, not hidden:** the ytmusicapi not-found heuristic (`_classify`) and the videoId-acceptance assumption are explicitly verified in Task 15 and may need a follow-up tweak.
