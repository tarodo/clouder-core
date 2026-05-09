from datetime import date

import pytest
from pydantic import ValidationError

from collector.schemas import AdminIngestRequestIn


def _base_payload() -> dict:
    return {
        "style_id": 1,
        "week_year": 2026,
        "week_number": 5,
        "bp_token": "abc",
    }


def test_minimal_payload_is_valid():
    req = AdminIngestRequestIn.model_validate(_base_payload())
    assert req.style_id == 1
    assert req.week_year == 2026
    assert req.week_number == 5
    assert req.period_start is None
    assert req.period_end is None


def test_both_period_fields_present_is_valid():
    payload = _base_payload() | {
        "period_start": "2026-01-31",
        "period_end": "2026-02-06",
    }
    req = AdminIngestRequestIn.model_validate(payload)
    assert req.period_start == date(2026, 1, 31)
    assert req.period_end == date(2026, 2, 6)


def test_only_period_start_is_rejected():
    payload = _base_payload() | {"period_start": "2026-01-31"}
    with pytest.raises(ValidationError) as exc:
        AdminIngestRequestIn.model_validate(payload)
    assert "period" in str(exc.value)


def test_only_period_end_is_rejected():
    payload = _base_payload() | {"period_end": "2026-02-06"}
    with pytest.raises(ValidationError) as exc:
        AdminIngestRequestIn.model_validate(payload)
    assert "period" in str(exc.value)


def test_period_end_before_start_is_rejected():
    payload = _base_payload() | {
        "period_start": "2026-02-06",
        "period_end": "2026-01-31",
    }
    with pytest.raises(ValidationError):
        AdminIngestRequestIn.model_validate(payload)


def test_blank_bp_token_is_rejected():
    payload = _base_payload() | {"bp_token": "   "}
    with pytest.raises(ValidationError):
        AdminIngestRequestIn.model_validate(payload)


def test_week_number_zero_is_rejected():
    payload = _base_payload() | {"week_number": 0}
    with pytest.raises(ValidationError):
        AdminIngestRequestIn.model_validate(payload)


def test_week_number_too_large_for_year_is_rejected():
    # 2026 has 52 weeks.
    payload = _base_payload() | {"week_number": 53}
    with pytest.raises(ValidationError):
        AdminIngestRequestIn.model_validate(payload)


def test_extra_fields_forbidden():
    payload = _base_payload() | {"unknown": "x"}
    with pytest.raises(ValidationError):
        AdminIngestRequestIn.model_validate(payload)


def test_week_53_valid_for_53_week_year():
    # 2028 has 53 Saturday-anchored weeks.
    req = AdminIngestRequestIn.model_validate(
        _base_payload() | {"week_year": 2028, "week_number": 53}
    )
    assert req.week_number == 53
