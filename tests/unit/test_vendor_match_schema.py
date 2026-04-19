"""VendorMatchMessage schema tests (Plan 4 Task 6)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from collector.schemas import VendorMatchMessage


def test_minimal_valid_payload() -> None:
    msg = VendorMatchMessage.model_validate(
        {
            "clouder_track_id": "t-1",
            "vendor": "spotify",
            "artist": "Foo",
            "title": "Bar",
        }
    )
    assert msg.clouder_track_id == "t-1"
    assert msg.vendor == "spotify"
    assert msg.artist == "Foo"
    assert msg.title == "Bar"
    assert msg.isrc is None
    assert msg.duration_ms is None
    assert msg.album is None
    assert msg.attempt == 1


def test_full_payload() -> None:
    msg = VendorMatchMessage.model_validate(
        {
            "clouder_track_id": "t-1",
            "vendor": "ytmusic",
            "isrc": "US1234567890",
            "artist": "Foo",
            "title": "Bar",
            "duration_ms": 200_000,
            "album": "Baz",
            "attempt": 2,
        }
    )
    assert msg.isrc == "US1234567890"
    assert msg.duration_ms == 200_000
    assert msg.album == "Baz"
    assert msg.attempt == 2


def test_empty_required_field_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        VendorMatchMessage.model_validate(
            {
                "clouder_track_id": "  ",
                "vendor": "spotify",
                "artist": "Foo",
                "title": "Bar",
            }
        )


def test_attempt_below_one_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        VendorMatchMessage.model_validate(
            {
                "clouder_track_id": "t-1",
                "vendor": "spotify",
                "artist": "Foo",
                "title": "Bar",
                "attempt": 0,
            }
        )


def test_extra_fields_ignored() -> None:
    msg = VendorMatchMessage.model_validate(
        {
            "clouder_track_id": "t-1",
            "vendor": "spotify",
            "artist": "Foo",
            "title": "Bar",
            "extra_field": "ignored",
        }
    )
    assert not hasattr(msg, "extra_field")
