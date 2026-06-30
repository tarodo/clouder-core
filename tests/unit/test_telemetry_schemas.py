# tests/unit/test_telemetry_schemas.py
import json

import pytest
from pydantic import ValidationError

from collector.telemetry_schemas import (
    EVENT_NAMES,
    HOT_PROPS,
    PROP_ALLOWLIST,
    validate_event,
)

TS_SERVER = "2026-06-27T10:00:00.000000+00:00"

def _envelope(event_name="track_view", props=None, context=None):
    return {
        "event_name": event_name,
        "event_id": "01J0ULID",
        "session_id": "sess-1",
        "ts_client": "2026-06-27T10:00:00.123Z",
        "context": context if context is not None else {"device": "desktop", "route": "/curate/:id"},
        "props": props if props is not None else {"track_id": "t1", "dwell_ms": 1200},
    }

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

def test_unknown_event_name_raises():
    with pytest.raises(ValueError):
        validate_event(_envelope(event_name="not_a_real_event"), user_id="u-1", ts_server=TS_SERVER)

def test_client_user_id_in_context_is_ignored_and_server_stamps():
    ev = _envelope(context={"user_id": "EVIL", "device": "mobile"})
    out = validate_event(ev, user_id="u-real", ts_server=TS_SERVER)
    assert out["user_id"] == "u-real"
    assert "EVIL" not in json.dumps(out)

def test_secret_and_unknown_props_dropped():
    ev = _envelope(props={"track_id": "t1", "dwell_ms": 5, "access_token": "x", "junk": 1})
    out = validate_event(ev, user_id="u-1", ts_server=TS_SERVER)
    assert out["track_id"] == "t1"
    assert out["dwell_ms"] == 5
    assert "access_token" not in json.dumps(out)
    assert "junk" not in out

def test_extra_top_level_key_rejected():
    ev = _envelope()
    ev["bp_token"] = "secret"
    with pytest.raises(ValidationError):
        validate_event(ev, user_id="u-1", ts_server=TS_SERVER)

def test_missing_event_id_rejected():
    ev = _envelope()
    del ev["event_id"]
    with pytest.raises(ValidationError):
        validate_event(ev, user_id="u-1", ts_server=TS_SERVER)

_VALID_PROPS = {
    "triage_session_start": {"block_id": "b", "bucket_id": "k"},
    "triage_session_end": {"session_ms": 1, "tracks_seen": 2, "tracks_categorized": 1, "undo_rate": 0.0},
    "track_view": {"track_id": "t", "dwell_ms": 1},
    "track_categorized": {"track_id": "t", "decision_ms": 1, "category_key": "NEW", "action": "moved_to_bucket", "surface": "triage"},
    "playback_play": {"track_id": "t", "position_ms": 0, "duration_ms": 200, "source": "triage_player"},
    "playback_pause": {"track_id": "t", "position_ms": 5, "duration_ms": 200, "seek_count": 0},
    "playback_seek": {"track_id": "t", "from_position_ms": 1, "to_position_ms": 9},
    "playback_ended": {"track_id": "t", "duration_ms": 200, "listen_through_ratio": 1.0},
    "playback_skip": {"track_id": "t", "position_ms": 9, "duration_ms": 200},
    "hotkey_used": {"hotkey_code": "Space", "action": "toggle_play", "source": "playback"},
    "playlist_add": {"track_ids": ["a", "b"], "playlist_id": "p", "track_count": 2, "source_category_id": None},
    "playlist_reorder": {"playlist_id": "p", "track_count": 3, "reorder_count": 1},
    "playlist_publish": {"track_ids": ["a"], "playlist_id": "p", "track_count": 1, "confirm_overwrite": False, "skipped_count": 0, "target": "spotify"},
}

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
