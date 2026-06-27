"""Python transcription of fact_playback.sql per-play grouping + terminal selection.

CONTRACT-PINNING MIRROR (offline) of the SQL. ASSUMPTION (recon, PlaybackProvider.tsx):
playback_play is emitted at track start AND when queue transitions from idle/ended
(togglePlayPause -> play()), but NOT on normal local pause->resume (playerRef.togglePlay)
and NOT on REMOTE-device resume (spotifyApi.resume()). Grouping by a running
playback_play count therefore makes an idle/ended->play a new play row, while both
local pause-resume and remote pause-resume stay in the same group whose terminal still
resolves to the later end/skip.
ponytail: if remote resume ever starts emitting playback_play, the running-count grouping
still holds (it just splits into a new group).
"""
from __future__ import annotations

_TERMINAL_PRIORITY = {"playback_ended": 0, "playback_skip": 0, "playback_pause": 1}


def resolve_plays(events: list[dict]) -> list[dict]:
    ordered = sorted(events, key=lambda e: e["ts_server"])
    groups: list[dict] = []
    current: dict | None = None
    for e in ordered:
        if e["event_name"] == "playback_play":
            current = {"play": e, "events": []}
            groups.append(current)
        elif current is not None:
            current["events"].append(e)

    plays: list[dict] = []
    for g in groups:
        non_play = g["events"]
        if not non_play:
            continue  # play with no terminal yet (open) -> not a completed play row
        terminal = sorted(
            non_play,
            key=lambda e: (_TERMINAL_PRIORITY.get(e["event_name"], 2), -e["ts_server"]),
        )[0]
        duration_ms = g["play"].get("duration_ms")
        ratio = terminal.get("listen_through_ratio")
        position = terminal.get("position_ms")
        if position is None and ratio is not None and duration_ms is not None:
            position = int(ratio * duration_ms)
        played_ms = position
        if ratio is None and played_ms is not None and duration_ms:
            ratio = played_ms / duration_ms
        plays.append({
            "terminal": terminal["event_name"],
            "skipped": terminal["event_name"] == "playback_skip",
            "played_ms": played_ms,
            "duration_ms": duration_ms,
            "listen_through_ratio": ratio,
            "source": g["play"].get("source"),
        })
    return plays
