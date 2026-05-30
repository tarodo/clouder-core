"""Unit tests for curation_handler helpers (enqueue wiring etc.)."""
from __future__ import annotations


def test_add_playlist_tracks_enqueues_ytmusic(monkeypatch):
    from collector import curation_handler as ch
    from collector.curation.playlists_repository import AppendTracksResult

    captured = {}

    def fake_enqueue(repo, added_track_ids, correlation_id):
        captured["ids"] = list(added_track_ids)

    monkeypatch.setattr(ch, "_enqueue_ytmusic", fake_enqueue)

    class Repo:
        def validate_tracks_in_scope(self, *, user_id, track_ids):
            return set(track_ids)

        def append_tracks(self, *, user_id, playlist_id, track_ids, now):
            return AppendTracksResult(
                added_track_ids=["t1"], skipped_duplicates=["t2"], position_after=1,
            )

    event = {
        "pathParameters": {"id": "pl1"},
        "body": '{"track_ids": ["t1", "t2"]}',
    }
    ch._handle_add_playlist_tracks(event, Repo(), "user1", "corr1")
    assert captured["ids"] == ["t1"]  # only newly added, not skipped duplicates
