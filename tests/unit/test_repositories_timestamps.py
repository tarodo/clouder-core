from datetime import datetime, timezone

import pytest

from collector.repositories import as_utc_datetime

UTC = timezone.utc


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-10-07 11:08:49.563", datetime(2026, 10, 7, 11, 8, 49, 563000, tzinfo=UTC)),
        ("2026-10-07T11:08:49+00:00", datetime(2026, 10, 7, 11, 8, 49, tzinfo=UTC)),
        ("2026-10-07T11:08:49Z", datetime(2026, 10, 7, 11, 8, 49, tzinfo=UTC)),
        (datetime(2026, 10, 7, 11, 8), datetime(2026, 10, 7, 11, 8, tzinfo=UTC)),
        (datetime(2026, 10, 7, 11, 8, tzinfo=UTC), datetime(2026, 10, 7, 11, 8, tzinfo=UTC)),
        (None, None),
    ],
)
def test_as_utc_datetime(value, expected) -> None:
    assert as_utc_datetime(value) == expected
