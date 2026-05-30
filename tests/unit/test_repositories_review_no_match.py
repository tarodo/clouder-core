from datetime import datetime, timezone

from collector.repositories import ClouderRepository


class FakeDataAPI:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params))
        return []


def test_mark_no_match_inserts_no_match_row():
    api = FakeDataAPI()
    repo = ClouderRepository(api)
    repo.mark_no_match(
        clouder_track_id="t1",
        vendor="ytmusic",
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )
    sql, params = api.calls[-1]
    assert "INSERT INTO match_review_queue" in sql
    assert "'no_match'" in sql
    assert "ON CONFLICT" in sql and "status = 'no_match'" in sql
    assert params["clouder_track_id"] == "t1"
    assert params["vendor"] == "ytmusic"
    assert params["candidates"] == []
