"""Server-side validation for the telemetry envelope (spec §3.1/§3.2).

Schema-on-read: props are key-allowlisted per event_name, not deeply typed —
new props ship without a migration. The envelope is strict (extra forbidden),
so any secret-shaped or unexpected top-level key is rejected outright.
`context.user_id` is never trusted: it is dropped on parse and re-stamped by
the handler from the authorizer. props is returned as a dict; the handler
serializes it to a JSON string to match the bronze Glue column type.
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

# Mirrors the Glue partition-projection enum in infra/telemetry.tf.
# ponytail: adding an event = one line here + one line in that enum. ~13 names.
EVENT_NAMES: frozenset[str] = frozenset(
    {
        "triage_session_start",
        "triage_session_end",
        "track_view",
        "track_categorized",
        "playback_play",
        "playback_pause",
        "playback_seek",
        "playback_ended",
        "playback_skip",
        "hotkey_used",
        "playlist_add",
        "playlist_reorder",
        "playlist_publish",
    }
)

# Per-event allowed prop keys (spec §3.2). Unknown keys are dropped (forward-
# compat), secret-shaped keys are stripped everywhere via _SECRET_KEYS.
PROP_ALLOWLIST: dict[str, frozenset[str]] = {
    "triage_session_start": frozenset({"block_id", "bucket_id"}),
    "triage_session_end": frozenset(
        {"session_ms", "tracks_seen", "tracks_categorized", "undo_rate"}
    ),
    "track_view": frozenset({"track_id", "dwell_ms"}),
    "track_categorized": frozenset(
        {"track_id", "decision_ms", "category_key", "action", "surface"}
    ),
    "playback_play": frozenset({"track_id", "position_ms", "duration_ms", "source"}),
    "playback_pause": frozenset(
        {"track_id", "position_ms", "duration_ms", "seek_count"}
    ),
    "playback_seek": frozenset({"track_id", "from_position_ms", "to_position_ms"}),
    "playback_ended": frozenset({"track_id", "duration_ms", "listen_through_ratio"}),
    "playback_skip": frozenset({"track_id", "position_ms", "duration_ms"}),
    "hotkey_used": frozenset({"hotkey_code", "action", "source"}),
    "playlist_add": frozenset(
        {"track_ids", "playlist_id", "track_count", "source_category_id"}
    ),
    "playlist_reorder": frozenset({"playlist_id", "track_count", "reorder_count"}),
    "playlist_publish": frozenset(
        {
            "track_ids",
            "playlist_id",
            "track_count",
            "confirm_overwrite",
            "skipped_count",
            "target",
        }
    ),
}

_SECRET_KEYS = {"bp_token", "authorization", "token", "access_token", "secret"}


class EnvelopeContext(BaseModel):
    # extra="ignore": a client-sent context.user_id is silently dropped; the
    # server re-stamps it. Only coarse, non-PII context fields are kept.
    model_config = ConfigDict(extra="ignore")
    device: str | None = None
    route: str | None = None
    app_version: str | None = None


class TelemetryEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_name: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    ts_client: str = Field(min_length=1)
    context: EnvelopeContext = Field(default_factory=EnvelopeContext)
    props: dict[str, Any] = Field(default_factory=dict)


def _strip_secrets(d: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k.lower() not in _SECRET_KEYS}


def validate_event(
    raw: Any, *, user_id: str | None, ts_server: str
) -> dict[str, Any]:
    """Validate one raw event; return the cleaned, server-stamped envelope.

    ``props`` is returned as a dict — the handler serializes it to a JSON
    string before emitting (it lands on a ``string``-typed Glue column).
    Raises pydantic.ValidationError / ValueError on a bad event so the handler
    can drop it individually and increment ``rejected``.
    """
    env = TelemetryEnvelope.model_validate(raw)
    if env.event_name not in EVENT_NAMES:
        raise ValueError(f"unknown event_name: {env.event_name}")
    allowed = PROP_ALLOWLIST[env.event_name]
    clean_props = {
        k: v for k, v in _strip_secrets(env.props).items() if k in allowed
    }
    return {
        "event_name": env.event_name,
        "event_id": env.event_id,
        "session_id": env.session_id,
        "ts_client": env.ts_client,
        "ts_server": ts_server,
        "context": {
            "user_id": user_id,  # SERVER-STAMPED; client value ignored
            "device": env.context.device,
            "route": env.context.route,
            "app_version": env.context.app_version,
        },
        "props": clean_props,
    }
