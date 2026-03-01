from datetime import datetime, timezone

from collector.data_api import _to_field


def test_datetime_is_serialized_for_rds_data_api_timestamp() -> None:
    value = datetime(2026, 3, 1, 16, 31, 43, 123456, tzinfo=timezone.utc)

    field = _to_field(value)

    assert field == {"stringValue": "2026-03-01 16:31:43.123456"}
