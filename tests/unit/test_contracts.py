from __future__ import annotations

from collector import contracts
from collector.contracts import screen


def _record(**overrides):
    base = {key: None for key in contracts.FIELDS}
    base.update(
        id=1, name="Track", mix_name="Original Mix", isrc="QZ1", bpm=128, length_ms=300000,
        publish_date="2026-09-26", new_release_date="2026-09-26", key={"name": "A Minor"},
        artists=[{"id": 2, "name": "A"}], release={"id": 3, "name": "R"}, genre={"id": 1, "name": "G"},
        remixers=[], bsrc_remixer=[], free_downloads=[], available_worldwide=True, exclusive=False,
        is_available_for_streaming=True, is_dj_edit=False, is_dj_version=False, is_explicit=False,
        is_hype=False, is_ugc_remix=False, pre_order=False, catalog_number="C1", current_status={},
        encoded_date="2026-09-01T00:00:00", image={}, length="5:00", price={}, publish_status="published",
        sale_type={}, sample_end_ms=1, sample_start_ms=0, sample_url="u", slug="track", url="u",
    )
    base.update(overrides)
    return base


def test_a_conforming_run_is_clean() -> None:
    report = screen([_record(id=1), _record(id=2)])
    assert [r["id"] for r in report.valid] == [1, 2]
    assert report.quarantined == [] and report.drift_fields == ()


def test_records_normalize_would_skip_are_quarantined_with_reasons() -> None:
    report = screen([_record(id=1), _record(id=0), _record(id=2, name="  "), "not a dict"])
    assert [r["id"] for r in report.valid] == [1]
    assert [q["reasons"] for q in report.quarantined] == [
        ["id: not a positive integer"], ["name: empty"], ["record: not an object"],
    ]


def test_type_drift_is_reported_not_quarantined() -> None:
    report = screen([_record(id=1, bpm="128"), _record(id=2)])
    assert [r["id"] for r in report.valid] == [1, 2]
    assert report.type_drift == {"bpm": 1}
    assert report.drift_fields == ("bpm",)


def test_unknown_fields_are_reported_sorted() -> None:
    report = screen([_record(id=1, is_new=True, **{"a b": 1})])
    assert report.unknown_fields == ("a b", "is_new")


def test_a_field_missing_from_every_record_is_reported() -> None:
    rows = [_record(id=i) for i in (1, 2)]
    for row in rows:
        del row["isrc"]
    assert screen(rows).missing_fields == ("isrc",)


def test_null_share_over_the_limit_is_reported() -> None:
    rows = [_record(id=i) for i in range(1, 101)]
    rows[0]["bpm"] = rows[1]["bpm"] = None
    assert screen(rows).null_share_over == {"bpm": 0.02}
    rows[0]["bpm"] = 128  # one NULL in 100 = exactly the limit, not over it
    assert screen(rows).null_share_over == {}


def test_empty_run_reports_nothing() -> None:
    report = screen([])
    assert report.drift_fields == () and report.quarantined == []


def test_the_september_drift_would_have_been_caught(monkeypatch) -> None:
    # The contract as of July did not know is_dj_version.
    fields = dict(contracts.FIELDS)
    del fields["is_dj_version"]
    monkeypatch.setattr(contracts, "FIELDS", fields)
    assert screen([_record(id=1)]).unknown_fields == ("is_dj_version",)
