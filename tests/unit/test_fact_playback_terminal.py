import pytest

from playback_terminal_mirror import resolve_plays


def ev(name, ts, **kw):
    return {"event_name": name, "ts_server": ts, **kw}


def test_remote_resume_no_replay_resolves_to_end():
    # play, pause, (remote resume = NO playback_play), end -> ONE play, terminal=end
    events = [
        ev("playback_play", 1, duration_ms=200000, source="triage_player"),
        ev("playback_pause", 2, position_ms=50000),
        ev("playback_ended", 3, duration_ms=200000, listen_through_ratio=0.98),
    ]
    plays = resolve_plays(events)
    assert len(plays) == 1
    assert plays[0]["terminal"] == "playback_ended"
    assert plays[0]["skipped"] is False
    assert plays[0]["listen_through_ratio"] == pytest.approx(0.98)


def test_local_resume_emits_new_play_two_rows():
    # play, pause, play (local resume re-emit), end -> TWO plays; 2nd resolves to end
    events = [
        ev("playback_play", 1, duration_ms=200000, source="triage_player"),
        ev("playback_pause", 2, position_ms=50000),
        ev("playback_play", 3, duration_ms=200000, source="triage_player"),
        ev("playback_ended", 4, duration_ms=200000, listen_through_ratio=1.0),
    ]
    plays = resolve_plays(events)
    assert len(plays) == 2
    assert plays[0]["terminal"] == "playback_pause"
    assert plays[0]["played_ms"] == 50000
    assert plays[1]["terminal"] == "playback_ended"


def test_skip_marks_skipped():
    events = [
        ev("playback_play", 1, duration_ms=200000, source="playlist_player"),
        ev("playback_skip", 2, position_ms=12000, duration_ms=200000),
    ]
    plays = resolve_plays(events)
    assert plays[0]["skipped"] is True
    assert plays[0]["played_ms"] == 12000


def test_pause_only_terminal_is_pause():
    events = [
        ev("playback_play", 1, duration_ms=200000, source="category_player"),
        ev("playback_pause", 2, position_ms=30000),
    ]
    plays = resolve_plays(events)
    assert len(plays) == 1
    assert plays[0]["terminal"] == "playback_pause"
    assert plays[0]["skipped"] is False


def test_ended_played_ms_from_ratio_when_no_position():
    # playback_ended carries no position_ms (only listen_through_ratio + duration)
    events = [
        ev("playback_play", 1, duration_ms=100000, source="triage_player"),
        ev("playback_ended", 2, duration_ms=100000, listen_through_ratio=0.5),
    ]
    plays = resolve_plays(events)
    assert plays[0]["played_ms"] == 50000
