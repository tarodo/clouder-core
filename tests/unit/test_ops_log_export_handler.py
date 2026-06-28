import json

import collector.ops_log_export_handler as ole
from collector.ops_log_export_handler import _day_window, _ops_records, export_ops_logs


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kw):
        self.objects[kw["Key"]] = kw["Body"]
        return {}


class FakeLogs:
    def __init__(self, by_group, paginate=False) -> None:
        self.by_group = by_group
        self.paginate = paginate
        self.calls: list[dict] = []

    def filter_log_events(self, **kw):
        self.calls.append(kw)
        msgs = self.by_group.get(kw["logGroupName"], [])
        if self.paginate and "nextToken" not in kw:
            half = len(msgs) // 2
            return {"events": [{"message": m} for m in msgs[:half]], "nextToken": "more"}
        if self.paginate:
            half = len(msgs) // 2
            return {"events": [{"message": m} for m in msgs[half:]]}
        return {"events": [{"message": m} for m in msgs]}


def _line(message, **fields):
    # REAL structlog JSON shape: event name under 'message' (EventRenamer),
    # top-level timestamp/level, allowlisted metric fields alongside.
    return json.dumps({"timestamp": "2026-06-27T10:00:00Z", "level": "INFO",
                       "message": message, **fields})


def test_day_window_epoch_ms() -> None:
    assert _day_window("2026-06-27") == (1782518400000, 1782604800000)


def test_reads_event_name_from_message_not_event() -> None:
    real = _line("label_enrichment_completed", duration_ms=1234, labels_total=3)
    synthetic = json.dumps({"timestamp": "t", "level": "INFO",
                            "event": "label_enrichment_completed", "duration_ms": 9})

    records = _ops_records([real, synthetic])

    assert len(records) == 1  # synthetic {"event":...} has no 'message' -> dropped
    assert records[0]["message"] == "label_enrichment_completed"
    assert records[0]["duration_ms"] == 1234
    assert "labels_total" not in records[0]  # not in _OPS_FIELDS -> projected out


def test_drops_non_ops_event_and_non_json() -> None:
    assert "collection_completed" not in ole._OPS_EVENTS  # negative-event contract
    keep = _line("auto_enrich_dispatched", source_hint="triage", claimed=4)
    non_ops = _line("collection_completed", item_count=7)
    junk = "START RequestId: abc Version: $LATEST"

    records = _ops_records([keep, non_ops, junk])

    assert [r["message"] for r in records] == ["auto_enrich_dispatched"]
    assert records[0]["source_hint"] == "triage"


def test_export_writes_per_group_ndjson_with_window() -> None:
    grp = "/aws/lambda/beatport-prod-label-enricher-worker"
    logs = FakeLogs({
        grp: [
            _line("label_enrichment_completed", duration_ms=10),
            _line("label_enrichment_worker_invoked", sqs_record_count=2),
        ],
        "/aws/lambda/beatport-prod-collector-api": [],
    })
    s3 = FakeS3()

    counts = export_ops_logs(
        logs, s3, "lake",
        [grp, "/aws/lambda/beatport-prod-collector-api"],
        "2026-06-27", 1782518400000, 1782604800000,
    )

    assert counts[grp] == 2
    assert counts["/aws/lambda/beatport-prod-collector-api"] == 0
    assert logs.calls[0]["startTime"] == 1782518400000
    assert logs.calls[0]["endTime"] == 1782604800000
    assert "bronze/ops/dt=2026-06-27/beatport-prod-label-enricher-worker.json" in s3.objects
    assert "bronze/ops/dt=2026-06-27/beatport-prod-collector-api.json" not in s3.objects  # empty -> no object


def test_paginates_with_next_token() -> None:
    grp = "/aws/lambda/beatport-prod-auto-enrich-dispatch-worker"
    logs = FakeLogs({grp: [
        _line("auto_enrich_dispatched", claimed=1),
        _line("auto_enrich_dispatched", claimed=2),
        _line("auto_enrich_dispatched", claimed=3),
        _line("auto_enrich_dispatched", claimed=4),
    ]}, paginate=True)
    s3 = FakeS3()

    counts = export_ops_logs(logs, s3, "lake", [grp],
                             "2026-06-27", 1782518400000, 1782604800000)

    assert counts[grp] == 4
    assert len(logs.calls) == 2
    assert logs.calls[1]["nextToken"] == "more"
