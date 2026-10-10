"""The Spotify ban marker on real Postgres: read back, and never shortened."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from collector.repositories import ClouderRepository


def test_a_ban_is_stored_and_a_shorter_one_does_not_cut_it(pg) -> None:
    repo = ClouderRepository(pg)
    now = datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc)
    try:
        assert repo.get_vendor_blocked_until("spotify") is None

        repo.set_vendor_blocked_until("spotify", now + timedelta(hours=5), now)
        assert repo.get_vendor_blocked_until("spotify") == now + timedelta(hours=5)

        repo.set_vendor_blocked_until("spotify", now + timedelta(minutes=10), now)
        assert repo.get_vendor_blocked_until("spotify") == now + timedelta(hours=5)

        repo.set_vendor_blocked_until("spotify", now + timedelta(hours=6), now)
        assert repo.get_vendor_blocked_until("spotify") == now + timedelta(hours=6)
    finally:
        pg.execute("DELETE FROM vendor_rate_limits WHERE vendor = 'spotify'")
