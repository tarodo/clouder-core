"""End-to-end Playlists flow with in-memory repository.

Mirrors the pattern from test_curation_handler.py — FakeRepo +
monkey-patched factory + lambda_handler invocations. Spotify HTTP
client and S3 storage are also stubbed via monkeypatch on the
handler's _build_spotify_user_client / _build_s3_storage helpers."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import MagicMock

import pytest

from collector.curation import (
    OrderMismatchError,
    PlaylistLimitReachedError,
    PlaylistNameConflictError,
    PlaylistNotFoundError,
    PlaylistTrackLimitError,
    SpotifyNotFoundError,
)
from collector.curation.playlists_repository import (
    AppendTracksResult,
    PlaylistRow,
    PlaylistTrackRow,
)
from collector.curation_handler import lambda_handler


# ---------- Fake repository ------------------------------------------------


class FakePlaylistsRepo:
    """In-memory PlaylistsRepository for integration tests.

    Implements the subset of methods exercised by the playlists handler.
    """

    def __init__(self) -> None:
        self.playlists: dict[str, dict] = {}
        # (playlist_id, track_id) -> {position, added_at}
        self.tracks: dict[tuple[str, str], dict] = {}
        # canonical clouder_tracks rows by id (and by spotify_id)
        self.canonical_tracks: dict[str, dict] = {}
        # user_imported_tracks markers: set of (user_id, track_id)
        self.imports: set[tuple[str, str]] = set()
        # user_id -> set of track_ids visible through categories
        self.category_tracks: dict[str, set[str]] = {}
        # merged enrichment blobs, keyed by artist/label id (export reads these)
        self.artist_info: dict[str, dict] = {}
        self.label_info: dict[str, dict] = {}
        # Mock data_api used by UserSpotifyIdReader and the export enrichment read.
        self.data_api = MagicMock()
        self.data_api.execute.side_effect = self._fake_execute

    def _fake_execute(self, sql: str, params=None, transaction_id=None):
        # Used by UserSpotifyIdReader.get_spotify_id and the export enrichment read.
        if "SELECT spotify_id FROM users" in sql:
            return [{"spotify_id": "user-sp-1"}]
        if "clouder_artist_info" in sql:
            return [
                {"artist_id": aid, "merged": self.artist_info[aid]}
                for aid in (params or {}).values()
                if aid in self.artist_info
            ]
        if "clouder_label_info" in sql:
            return [
                {"label_id": lid, "merged": self.label_info[lid]}
                for lid in (params or {}).values()
                if lid in self.label_info
            ]
        return []

    # ---------- helpers ----------------------------------------------------

    def _row(self, p: dict) -> PlaylistRow:
        return PlaylistRow(
            id=p["id"], user_id=p["user_id"],
            name=p["name"], normalized_name=p["normalized_name"],
            description=p.get("description"),
            is_public=bool(p["is_public"]),
            cover_s3_key=p.get("cover_s3_key"),
            cover_uploaded_at=p.get("cover_uploaded_at"),
            spotify_playlist_id=p.get("spotify_playlist_id"),
            last_published_at=p.get("last_published_at"),
            needs_republish=bool(p["needs_republish"]),
            track_count=sum(1 for (pid, _) in self.tracks if pid == p["id"]),
            created_at=p["created_at"], updated_at=p["updated_at"],
            status=p.get("status", "active"),
        )

    def _alive_playlists_for(self, user_id: str) -> list[dict]:
        return [
            p for p in self.playlists.values()
            if p["user_id"] == user_id and p.get("deleted_at") is None
        ]

    # ---------- CRUD -------------------------------------------------------

    def create(self, *, user_id, playlist_id, name, normalized_name,
               description, is_public, now) -> PlaylistRow:
        if len(self._alive_playlists_for(user_id)) >= 200:
            raise PlaylistLimitReachedError("limit")
        for p in self._alive_playlists_for(user_id):
            if p["normalized_name"] == normalized_name:
                raise PlaylistNameConflictError("dup name")
        p = {
            "id": playlist_id, "user_id": user_id,
            "name": name, "normalized_name": normalized_name,
            "description": description, "is_public": is_public,
            "cover_s3_key": None, "cover_uploaded_at": None,
            "spotify_playlist_id": None, "last_published_at": None,
            "needs_republish": False,
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
            "deleted_at": None,
        }
        self.playlists[playlist_id] = p
        return self._row(p)

    def get(self, *, user_id, playlist_id) -> PlaylistRow | None:
        p = self.playlists.get(playlist_id)
        if p is None or p["user_id"] != user_id or p.get("deleted_at"):
            return None
        return self._row(p)

    def list_all(self, *, user_id, limit, offset, status=None):
        items = self._alive_playlists_for(user_id)
        if status is not None:
            items = [p for p in items if p.get("status", "active") == status]
        items.sort(key=lambda p: p["created_at"], reverse=True)
        return [self._row(p) for p in items[offset:offset+limit]], len(items)

    def patch(self, *, user_id, playlist_id, name, normalized_name,
              description, is_public, status, now) -> PlaylistRow:
        p = self.playlists.get(playlist_id)
        if p is None or p["user_id"] != user_id or p.get("deleted_at"):
            raise PlaylistNotFoundError()
        if name is not None:
            for other in self._alive_playlists_for(user_id):
                if other["id"] != playlist_id and other["normalized_name"] == normalized_name:
                    raise PlaylistNameConflictError("dup name")
            p["name"] = name
            p["normalized_name"] = normalized_name
        if description is not None:
            p["description"] = description
        if is_public is not None:
            p["is_public"] = is_public
        if status is not None:
            p["status"] = status
        if p["spotify_playlist_id"] and (
            name is not None or description is not None or is_public is not None
        ):
            p["needs_republish"] = True
        p["updated_at"] = now.isoformat()
        return self._row(p)

    def soft_delete(self, *, user_id, playlist_id, now) -> bool:
        p = self.playlists.get(playlist_id)
        if p is None or p["user_id"] != user_id or p.get("deleted_at"):
            return False
        p["deleted_at"] = now.isoformat()
        return True

    # ---------- Tracks -----------------------------------------------------

    def append_tracks(self, *, user_id, playlist_id, track_ids, now) -> AppendTracksResult:
        p = self.playlists.get(playlist_id)
        if p is None or p["user_id"] != user_id or p.get("deleted_at"):
            raise PlaylistNotFoundError()
        existing_in_p = {tid for (pid, tid) in self.tracks if pid == playlist_id}
        positions = sorted(
            v["position"] for (pid, _), v in self.tracks.items() if pid == playlist_id
        )
        max_pos = positions[-1] if positions else -1
        if not track_ids:
            return AppendTracksResult([], [], max_pos + 1)
        to_add = [t for t in track_ids if t not in existing_in_p]
        skipped = [t for t in track_ids if t in existing_in_p]
        if len(existing_in_p) + len(to_add) > 1000:
            raise PlaylistTrackLimitError("over 1000")
        start = max_pos + 1
        for i, t in enumerate(to_add):
            self.tracks[(playlist_id, t)] = {
                "position": start + i, "added_at": now.isoformat(),
            }
        if p["spotify_playlist_id"] and to_add:
            p["needs_republish"] = True
        return AppendTracksResult(
            added_track_ids=to_add,
            skipped_duplicates=skipped,
            position_after=start + len(to_add),
        )

    def remove_track(self, *, user_id, playlist_id, track_id, now) -> bool:
        p = self.playlists.get(playlist_id)
        if p is None or p["user_id"] != user_id or p.get("deleted_at"):
            raise PlaylistNotFoundError()
        if (playlist_id, track_id) not in self.tracks:
            return False
        removed_pos = self.tracks[(playlist_id, track_id)]["position"]
        del self.tracks[(playlist_id, track_id)]
        for (pid, t), v in self.tracks.items():
            if pid == playlist_id and v["position"] > removed_pos:
                v["position"] -= 1
        if p["spotify_playlist_id"]:
            p["needs_republish"] = True
        return True

    def reorder_tracks(self, *, user_id, playlist_id, ordered_track_ids, now) -> None:
        p = self.playlists.get(playlist_id)
        if p is None or p["user_id"] != user_id or p.get("deleted_at"):
            raise PlaylistNotFoundError()
        current = {tid for (pid, tid) in self.tracks if pid == playlist_id}
        requested = set(ordered_track_ids)
        if len(ordered_track_ids) != len(requested):
            raise OrderMismatchError("duplicates")
        if current != requested:
            raise OrderMismatchError("set mismatch")
        for i, t in enumerate(ordered_track_ids):
            self.tracks[(playlist_id, t)]["position"] = i
        if p["spotify_playlist_id"]:
            p["needs_republish"] = True

    def list_tracks(self, *, user_id, playlist_id, limit, offset):
        p = self.playlists.get(playlist_id)
        if p is None or p["user_id"] != user_id or p.get("deleted_at"):
            raise PlaylistNotFoundError()
        rows = []
        for (pid, tid), v in self.tracks.items():
            if pid != playlist_id:
                continue
            meta = self.canonical_tracks.get(tid, {})
            rows.append(PlaylistTrackRow(
                track_id=tid, position=v["position"],
                added_at=v["added_at"],
                title=meta.get("title", tid),
                spotify_id=meta.get("spotify_id"),
                isrc=meta.get("isrc"),
                length_ms=meta.get("length_ms"),
                origin=meta.get("origin", "beatport"),
                # Mirrors the real repo, which projects artists/label onto the row.
                artists=tuple(meta.get("artist_refs", ())),
                label=meta.get("label"),
            ))
        rows.sort(key=lambda r: r.position)
        total = len(rows)
        return rows[offset:offset+limit], total

    # ---------- Cover + publish-state -------------------------------------

    def set_cover(self, *, user_id, playlist_id, s3_key, now) -> bool:
        p = self.playlists.get(playlist_id)
        if p is None or p["user_id"] != user_id or p.get("deleted_at"):
            return False
        p["cover_s3_key"] = s3_key
        p["cover_uploaded_at"] = now.isoformat()
        if p["spotify_playlist_id"]:
            p["needs_republish"] = True
        p["updated_at"] = now.isoformat()
        return True

    def clear_cover(self, *, user_id, playlist_id, now) -> bool:
        p = self.playlists.get(playlist_id)
        if p is None or p["user_id"] != user_id or p.get("deleted_at"):
            return False
        p["cover_s3_key"] = None
        p["cover_uploaded_at"] = None
        if p["spotify_playlist_id"]:
            p["needs_republish"] = True
        p["updated_at"] = now.isoformat()
        return True

    def set_publish_state(self, *, user_id, playlist_id,
                          spotify_playlist_id, now,
                          mark_dirty: bool = False) -> bool:
        p = self.playlists.get(playlist_id)
        if p is None or p["user_id"] != user_id or p.get("deleted_at"):
            return False
        p["spotify_playlist_id"] = spotify_playlist_id
        p["last_published_at"] = now.isoformat()
        p["needs_republish"] = bool(mark_dirty)
        p["updated_at"] = now.isoformat()
        return True

    # ---------- Scope + import --------------------------------------------

    def validate_tracks_in_scope(self, *, user_id, track_ids) -> set[str]:
        visible = self.category_tracks.get(user_id, set()).copy()
        # Tracks already in user's own playlists are also in scope.
        for (pid, tid) in self.tracks:
            owner = self.playlists.get(pid)
            if owner and owner["user_id"] == user_id and not owner.get("deleted_at"):
                visible.add(tid)
        # User-imported tracks.
        for (u, t) in self.imports:
            if u == user_id:
                visible.add(t)
        return {t for t in track_ids if t in visible}

    def import_tracks_batch(self, *, user_id, tracks, now) -> list[str]:
        ids: list[str] = []
        for t in tracks:
            existing = next(
                (tid for tid, meta in self.canonical_tracks.items()
                 if meta.get("spotify_id") == t.spotify_id),
                None,
            )
            if existing is not None:
                tid = existing
            else:
                tid = f"t-{len(self.canonical_tracks) + 1}"
                self.canonical_tracks[tid] = {
                    "spotify_id": t.spotify_id, "title": t.title,
                    "artists": list(t.artists),
                }
            self.imports.add((user_id, tid))
            ids.append(tid)
        return ids


# ---------- Helpers -----------------------------------------------------------


@pytest.fixture
def fake_repo(monkeypatch) -> FakePlaylistsRepo:
    repo = FakePlaylistsRepo()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_playlists_repository",
        lambda: repo,
    )
    return repo


@pytest.fixture
def fake_s3(monkeypatch):
    s3 = MagicMock()
    s3.cover_key.side_effect = (
        lambda *, user_id, playlist_id, epoch_ms:
        f"covers/{user_id}/{playlist_id}/{epoch_ms}.jpg"
    )
    s3.presigned_cover_put_url.return_value = "https://signed-put"
    s3.presigned_cover_get_url.return_value = "https://signed-get"
    s3.head_cover.return_value = {"size": 1024, "content_type": "image/jpeg"}
    s3.read_cover_bytes.return_value = b"\xff\xd8jpegbytes"
    monkeypatch.setattr(
        "collector.curation_handler._build_s3_storage",
        lambda: s3,
    )
    return s3


@pytest.fixture
def fake_spotify_client(monkeypatch):
    client = MagicMock()
    # Default: import returns a fresh track
    client.get_track.side_effect = (
        lambda spotify_id: SimpleNamespace(
            id=spotify_id,
            name=f"Imported {spotify_id}",
            duration_ms=200_000,
            isrc=None,
            artists=(),
        )
    )
    # Default: create returns spt-new
    client.create_playlist.return_value = SimpleNamespace(
        id="spt-new",
        url="https://open.spotify.com/playlist/spt-new",
    )
    # Default: whole-playlist import reads a name and two tracks
    client.get_playlist_name.return_value = "Spotify Mix"
    client.get_playlist_tracks.return_value = [
        SimpleNamespace(id="spt-1", name="One", duration_ms=100, isrc=None,
                        artists=(SimpleNamespace(name="Guri"),)),
        SimpleNamespace(id="spt-2", name="Two", duration_ms=200, isrc=None,
                        artists=(SimpleNamespace(name="Nu Zau"),)),
    ]
    monkeypatch.setattr(
        "collector.curation_handler._build_spotify_user_client",
        lambda user_id, correlation_id: client,
    )
    return client


def _event(*, method: str, route: str, user_id: str = "u1",
           path_params: Mapping[str, str] | None = None,
           body: Any | None = None,
           correlation_id: str = "cid-int") -> dict:
    return {
        "requestContext": {
            "routeKey": f"{method} {route}",
            "authorizer": {"lambda": {"user_id": user_id}},
        },
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body is not None else "",
        "headers": {"x-correlation-id": correlation_id},
    }


# ---------- Tests ------------------------------------------------------------


def test_full_lifecycle(fake_repo):
    # 1. Create
    resp = lambda_handler(
        _event(method="POST", route="/playlists", body={"name": "My Set"}),
        None,
    )
    assert resp["statusCode"] == 201
    created = json.loads(resp["body"])
    pid = created["id"]
    # Newly-created playlist has no cover → cover_url is null.
    assert created["cover_url"] is None

    # 2. List
    resp = lambda_handler(
        _event(method="GET", route="/playlists"), None,
    )
    assert resp["statusCode"] == 200
    listed = json.loads(resp["body"])
    assert listed["total"] == 1
    assert listed["items"][0]["cover_url"] is None

    # 3. Seed a canonical track in user's category scope
    fake_repo.canonical_tracks["t-1"] = {
        "title": "Track A", "spotify_id": "spt-a", "isrc": "ISRC1",
        "length_ms": 200000, "origin": "beatport",
    }
    fake_repo.category_tracks["u1"] = {"t-1"}

    # 4. Add a track from user's category
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/{id}/tracks",
            body={"track_ids": ["t-1"]},
            path_params={"id": pid},
        ),
        None,
    )
    assert resp["statusCode"] == 201

    # 5. Try to add a foreign track → 404
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/{id}/tracks",
            body={"track_ids": ["t-foreign"]},
            path_params={"id": pid},
        ),
        None,
    )
    assert resp["statusCode"] == 404
    assert "t-foreign" in json.loads(resp["body"])["missing_track_ids"]

    # 6. Soft-delete
    resp = lambda_handler(
        _event(method="DELETE", route="/playlists/{id}",
               path_params={"id": pid}),
        None,
    )
    assert resp["statusCode"] == 204

    # 7. List is empty
    resp = lambda_handler(
        _event(method="GET", route="/playlists"), None,
    )
    assert json.loads(resp["body"])["total"] == 0


def test_publish_first_time_full_flow(fake_repo, fake_s3, fake_spotify_client):
    # Set up: create playlist + add canonical track with spotify_id
    resp = lambda_handler(
        _event(method="POST", route="/playlists", body={"name": "Set"}),
        None,
    )
    pid = json.loads(resp["body"])["id"]
    fake_repo.canonical_tracks["t-1"] = {
        "title": "Track A", "spotify_id": "spt-a", "isrc": None,
        "length_ms": 200000, "origin": "beatport",
    }
    fake_repo.category_tracks["u1"] = {"t-1"}
    lambda_handler(
        _event(method="POST", route="/playlists/{id}/tracks",
               body={"track_ids": ["t-1"]}, path_params={"id": pid}),
        None,
    )

    resp = lambda_handler(
        _event(method="POST", route="/playlists/{id}/publish",
               body={"confirm_overwrite": False},
               path_params={"id": pid}),
        None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["spotify_playlist_id"] == "spt-new"
    fake_spotify_client.create_playlist.assert_called_once()
    fake_spotify_client.replace_tracks.assert_called_once_with(
        "spt-new", ["spotify:track:spt-a"],
    )

    # State persisted in repo
    saved = fake_repo.playlists[pid]
    assert saved["spotify_playlist_id"] == "spt-new"
    assert saved["needs_republish"] is False


def test_repub_without_confirm_returns_409(fake_repo, fake_s3, fake_spotify_client):
    # Seed playlist with spotify_playlist_id set
    pid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    fake_repo.playlists[pid] = {
        "id": pid, "user_id": "u1",
        "name": "n", "normalized_name": "n",
        "description": None, "is_public": False,
        "cover_s3_key": None, "cover_uploaded_at": None,
        "spotify_playlist_id": "spt-existing",
        "last_published_at": now, "needs_republish": True,
        "created_at": now, "updated_at": now, "deleted_at": None,
    }
    fake_repo.canonical_tracks["t-1"] = {
        "title": "T", "spotify_id": "spt-a", "isrc": None,
        "length_ms": 200000, "origin": "beatport",
    }
    fake_repo.tracks[(pid, "t-1")] = {"position": 0, "added_at": now}

    resp = lambda_handler(
        _event(method="POST", route="/playlists/{id}/publish",
               body={"confirm_overwrite": False},
               path_params={"id": pid}),
        None,
    )
    assert resp["statusCode"] == 409
    assert json.loads(resp["body"])["error_code"] == "confirm_overwrite_required"


def test_import_spotify_then_publish(fake_repo, fake_s3, fake_spotify_client):
    resp = lambda_handler(
        _event(method="POST", route="/playlists", body={"name": "Import Set"}),
        None,
    )
    pid = json.loads(resp["body"])["id"]

    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/{id}/tracks/import-spotify",
            body={"spotify_refs": ["spotify:track:5xkAVrKKnHeBHb1Mqt6wEt"]},
            path_params={"id": pid},
        ),
        None,
    )
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert len(body["added"]) == 1
    new_track_id = body["added"][0]["track_id"]
    assert body["added"][0]["spotify_id"] == "5xkAVrKKnHeBHb1Mqt6wEt"

    # Track is now in canonical_tracks AND user_imported_tracks.
    assert any(
        meta.get("spotify_id") == "5xkAVrKKnHeBHb1Mqt6wEt"
        for meta in fake_repo.canonical_tracks.values()
    )
    assert ("u1", new_track_id) in fake_repo.imports

    # Publish now succeeds and includes the imported track URI.
    resp = lambda_handler(
        _event(method="POST", route="/playlists/{id}/publish",
               body={"confirm_overwrite": False},
               path_params={"id": pid}),
        None,
    )
    assert resp["statusCode"] == 200
    fake_spotify_client.replace_tracks.assert_called_with(
        "spt-new", ["spotify:track:5xkAVrKKnHeBHb1Mqt6wEt"],
    )


def test_import_spotify_persists_artists(fake_repo, fake_s3, fake_spotify_client):
    fake_spotify_client.get_track.side_effect = lambda spotify_id: SimpleNamespace(
        id=spotify_id, name=f"Imported {spotify_id}", duration_ms=200_000,
        isrc=None, artists=(SimpleNamespace(name="Guri"),),
    )
    resp = lambda_handler(
        _event(method="POST", route="/playlists", body={"name": "Set"}),
        None,
    )
    pid = json.loads(resp["body"])["id"]
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/{id}/tracks/import-spotify",
            body={"spotify_refs": ["spotify:track:5xkAVrKKnHeBHb1Mqt6wEt"]},
            path_params={"id": pid},
        ),
        None,
    )
    assert resp["statusCode"] == 201
    tid = json.loads(resp["body"])["added"][0]["track_id"]
    assert fake_repo.canonical_tracks[tid]["artists"] == ["Guri"]


def test_import_spotify_playlist_creates_mirror(fake_repo, fake_s3, fake_spotify_client):
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/import-spotify-playlist",
            body={"spotify_ref": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"},
        ),
        None,
    )
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["name"] == "Spotify Mix"
    assert body["imported"] == 2
    assert body["truncated"] is False
    assert body["total"] == 2
    # A new clouder playlist was created and both tracks appended.
    pid = body["playlist_id"]
    assert fake_repo.get(user_id="u1", playlist_id=pid) is not None
    assert sum(1 for (p, _t) in fake_repo.tracks if p == pid) == 2
    # Artists were persisted through the batch importer.
    assert any(m.get("artists") == ["Guri"] for m in fake_repo.canonical_tracks.values())


def test_import_spotify_playlist_name_override(fake_repo, fake_s3, fake_spotify_client):
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/import-spotify-playlist",
            body={"spotify_ref": "37i9dQZF1DXcBWIGoYBM5M", "name": "My Name"},
        ),
        None,
    )
    assert json.loads(resp["body"])["name"] == "My Name"


def test_import_spotify_playlist_rejects_bad_ref(fake_repo, fake_s3, fake_spotify_client):
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/import-spotify-playlist",
            body={"spotify_ref": "not-a-playlist"},
        ),
        None,
    )
    assert resp["statusCode"] == 400


def test_import_spotify_playlist_missing_returns_404(fake_repo, fake_s3, fake_spotify_client):
    """Regression for I1: a bad/inaccessible Spotify playlist must surface
    the route's documented 404 (playlist_not_found), not SpotifyNotFoundError's
    inherited 502 upstream-error status."""
    fake_spotify_client.get_playlist_name.side_effect = SpotifyNotFoundError(
        "no such playlist"
    )
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/import-spotify-playlist",
            body={"spotify_ref": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"},
        ),
        None,
    )
    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert body["error_code"] == "playlist_not_found"
    # Nothing was created before the Spotify read failed.
    assert fake_repo.playlists == {}


def test_import_spotify_playlist_soft_deletes_orphan_on_post_create_failure(
    fake_repo, fake_s3, fake_spotify_client, monkeypatch,
):
    """Regression for I2: if anything after repo.create() fails, the
    just-created playlist must be soft-deleted rather than left as an
    empty orphan that would block retry with a 409 name conflict."""
    original_soft_delete = fake_repo.soft_delete
    soft_delete_spy = MagicMock(side_effect=original_soft_delete)
    monkeypatch.setattr(fake_repo, "soft_delete", soft_delete_spy)

    def _raising_import_tracks_batch(*, user_id, tracks, now):
        raise RuntimeError("boom during import")

    monkeypatch.setattr(
        fake_repo, "import_tracks_batch", _raising_import_tracks_batch,
    )

    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/import-spotify-playlist",
            body={"spotify_ref": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"},
        ),
        None,
    )
    assert resp["statusCode"] == 500
    soft_delete_spy.assert_called_once()
    # The playlist created before the failure must not survive as alive —
    # soft_delete flipped it, so a fresh `get()` finds nothing for the user.
    assert len(fake_repo.playlists) == 1
    orphan_id = next(iter(fake_repo.playlists))
    assert fake_repo.get(user_id="u1", playlist_id=orphan_id) is None


def test_cover_upload_lifecycle(fake_repo, fake_s3):
    resp = lambda_handler(
        _event(method="POST", route="/playlists", body={"name": "Cover Set"}),
        None,
    )
    pid = json.loads(resp["body"])["id"]

    # Request upload URL
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/{id}/cover/upload-url",
            body={"content_type": "image/jpeg"},
            path_params={"id": pid},
        ),
        None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    s3_key = body["s3_key"]
    assert s3_key.startswith(f"covers/u1/{pid}/")

    # Confirm upload
    resp = lambda_handler(
        _event(
            method="POST", route="/playlists/{id}/cover/confirm",
            body={"s3_key": s3_key},
            path_params={"id": pid},
        ),
        None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["cover_s3_key"] == s3_key
    # Cover URL is a presigned GET on the cover key.
    assert body["cover_url"] == "https://signed-get"

    # GET /playlists/{id} also surfaces cover_url.
    resp = lambda_handler(
        _event(method="GET", route="/playlists/{id}",
               path_params={"id": pid}),
        None,
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["cover_url"] == "https://signed-get"

    # Delete cover
    resp = lambda_handler(
        _event(method="DELETE", route="/playlists/{id}/cover",
               path_params={"id": pid}),
        None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["cover_s3_key"] is None
    assert body["cover_url"] is None


def test_publish_cover_failure_keeps_dirty(
    fake_repo, fake_s3, fake_spotify_client,
):
    """When cover upload fails during publish, the playlist stays
    needs_republish=True and the response carries cover_failed=True."""
    from collector.curation import SpotifyApiError

    # Set up: create playlist, set a cover, add a track with spotify_id.
    resp = lambda_handler(
        _event(method="POST", route="/playlists", body={"name": "Set"}),
        None,
    )
    pid = json.loads(resp["body"])["id"]
    fake_repo.playlists[pid]["cover_s3_key"] = f"covers/u1/{pid}/1.jpg"
    fake_repo.canonical_tracks["t-1"] = {
        "title": "T", "spotify_id": "spt-a", "isrc": None,
        "length_ms": 200000, "origin": "beatport",
    }
    fake_repo.category_tracks["u1"] = {"t-1"}
    lambda_handler(
        _event(method="POST", route="/playlists/{id}/tracks",
               body={"track_ids": ["t-1"]}, path_params={"id": pid}),
        None,
    )

    # Force the cover upload to fail.
    fake_spotify_client.set_cover.side_effect = SpotifyApiError("503")

    resp = lambda_handler(
        _event(method="POST", route="/playlists/{id}/publish",
               body={"confirm_overwrite": False},
               path_params={"id": pid}),
        None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["cover_failed"] is True
    assert body["spotify_playlist_id"] == "spt-new"

    # Repo state: spotify_playlist_id persisted, needs_republish kept TRUE
    # so the next publish retries the cover.
    saved = fake_repo.playlists[pid]
    assert saved["spotify_playlist_id"] == "spt-new"
    assert saved["needs_republish"] is True


def test_export_playlist_includes_tracks_comments_and_enrichment(
    fake_repo, fake_s3, monkeypatch,
):
    """GET /playlists/{id}/export returns the full copy payload in one call."""
    resp = lambda_handler(
        _event(method="POST", route="/playlists", body={"name": "Export Set"}), None,
    )
    pid = json.loads(resp["body"])["id"]

    # A track carrying artists + label, so the export has entities to enrich.
    fake_repo.canonical_tracks["t-1"] = {
        "title": "One",
        "spotify_id": "spt1",
        "artist_refs": [{"id": "a1", "name": "Guri"}, {"id": "a2", "name": "Nu Zau"}],
        "label": {"id": "l1", "name": "Label X"},
    }
    fake_repo.category_tracks["u1"] = {"t-1"}
    fake_repo.artist_info["a1"] = {"country": "RO", "cost_usd": 0.5}
    fake_repo.label_info["l1"] = {"country": "DE"}
    lambda_handler(
        _event(method="POST", route="/playlists/{id}/tracks",
               body={"track_ids": ["t-1"]}, path_params={"id": pid}),
        None,
    )

    comments_repo = MagicMock()
    comments_repo.list_comments_for_tracks.return_value = {
        "t-1": (
            SimpleNamespace(status="ok", comment_count=1, external_video_id="v1"),
            [SimpleNamespace(author_name="bob", author_avatar_url="http://a",
                             text="fire", like_count=3, published_at="2026-01-01")],
        )
    }
    monkeypatch.setattr(
        "collector.curation_handler._comments_factory", lambda: comments_repo,
    )

    resp = lambda_handler(
        _event(method="GET", route="/playlists/{id}/export", path_params={"id": pid}),
        None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    assert body["playlist"] == "Export Set"
    assert body["track_count"] == 1
    track = body["tracks"][0]
    assert track["artists"] == ["Guri", "Nu Zau"]
    assert track["label"] == "Label X"
    assert track["spotify_url"] == "https://open.spotify.com/track/spt1"
    assert track["comments"] == [
        {"author": "bob", "text": "fire", "like_count": 3, "published_at": "2026-01-01"}
    ]

    # Enrichment is attached once per entity, with admin-only fields stripped.
    assert body["artists"] == [
        {"id": "a1", "name": "Guri", "info": {"country": "RO"}},
        {"id": "a2", "name": "Nu Zau", "info": None},
    ]
    assert body["labels"] == [{"id": "l1", "name": "Label X", "info": {"country": "DE"}}]


def test_export_playlist_404_for_other_users_playlist(fake_repo, fake_s3):
    resp = lambda_handler(
        _event(method="POST", route="/playlists", body={"name": "Mine"}), None,
    )
    pid = json.loads(resp["body"])["id"]
    resp = lambda_handler(
        _event(method="GET", route="/playlists/{id}/export",
               path_params={"id": pid}, user_id="someone-else"),
        None,
    )
    assert resp["statusCode"] == 404
