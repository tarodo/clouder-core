"""Test the album.release_date precision parser used by spotify_handler."""

from __future__ import annotations

from datetime import date

from collector.spotify_handler import _extract_release_date


def test_day_precision() -> None:
    payload = {
        "album": {
            "release_date": "2024-03-15",
            "release_date_precision": "day",
        }
    }
    assert _extract_release_date(payload) == date(2024, 3, 15)


def test_month_precision_pads_to_first_of_month() -> None:
    payload = {
        "album": {
            "release_date": "2024-03",
            "release_date_precision": "month",
        }
    }
    assert _extract_release_date(payload) == date(2024, 3, 1)


def test_year_precision_pads_to_jan_first() -> None:
    payload = {
        "album": {
            "release_date": "2024",
            "release_date_precision": "year",
        }
    }
    assert _extract_release_date(payload) == date(2024, 1, 1)


def test_missing_album_returns_none() -> None:
    assert _extract_release_date({}) is None
    assert _extract_release_date(None) is None


def test_missing_precision_returns_none() -> None:
    payload = {"album": {"release_date": "2024-03-15"}}
    assert _extract_release_date(payload) is None


def test_unknown_precision_returns_none() -> None:
    payload = {
        "album": {
            "release_date": "2024-03-15",
            "release_date_precision": "decade",
        }
    }
    assert _extract_release_date(payload) is None


def test_malformed_date_returns_none() -> None:
    payload = {
        "album": {
            "release_date": "not-a-date",
            "release_date_precision": "day",
        }
    }
    assert _extract_release_date(payload) is None


def test_non_string_release_date_returns_none() -> None:
    payload = {
        "album": {"release_date": 2024, "release_date_precision": "year"}
    }
    assert _extract_release_date(payload) is None


def test_non_mapping_album_returns_none() -> None:
    payload = {"album": "wrong-shape"}
    assert _extract_release_date(payload) is None
