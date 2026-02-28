import pytest

from collector.errors import ValidationError
from collector.models import compute_iso_week_date_range, validate_collect_request


def test_compute_iso_week_range_returns_date_only_strings() -> None:
    start, end = compute_iso_week_date_range(2026, 9)
    assert start == "2026-02-23"
    assert end == "2026-03-01"


def test_compute_iso_week_range_handles_year_boundary() -> None:
    start, end = compute_iso_week_date_range(2020, 53)
    assert start == "2020-12-28"
    assert end == "2021-01-03"


def test_validate_collect_request_rejects_invalid_week_combo() -> None:
    with pytest.raises(ValidationError):
        validate_collect_request(
            {
                "bp_token": "x",
                "style_id": 1,
                "iso_year": 2021,
                "iso_week": 53,
            }
        )


def test_validate_collect_request_rejects_non_integer_style_id() -> None:
    with pytest.raises(ValidationError):
        validate_collect_request(
            {
                "bp_token": "x",
                "style_id": "1",
                "iso_year": 2026,
                "iso_week": 9,
            }
        )
