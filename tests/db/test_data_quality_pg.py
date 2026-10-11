"""Each data-quality check's SQL against a real Postgres."""

from __future__ import annotations

from datetime import date

from collector.data_quality import CHECKS, check_by_name, run_checks

TODAY = date(2026, 10, 7)  # Wednesday; latest due Saturday-week ends Fri 2026-10-02


def _value(pg, name: str):
    (result,) = run_checks(pg, TODAY, checks=[check_by_name(name)])
    return result


def _run(
    pg,
    run_id,
    style_id,
    status="COMPLETED",
    items=100,
    period_end="2026-10-02",
    started="now()",
    custom=False,
):
    pg.execute(
        "INSERT INTO ingest_runs (run_id, source, style_id, raw_s3_key, status, item_count, "
        f"started_at, period_end, is_custom_range) VALUES (:id, 'beatport', :style, 'k', :status, "
        f":items, {started}, CAST(:end AS date), :custom)",
        {
            "id": run_id,
            "style": style_id,
            "status": status,
            "items": items,
            "end": period_end,
            "custom": custom,
        },
    )


def _style(pg, bp_id, *, hidden=False):
    pg.execute(
        "INSERT INTO clouder_styles (id, name, normalized_name, is_hidden, created_at, updated_at) "
        "VALUES (:id, 'S', 's', :hidden, now(), now())",
        {"id": f"cs{bp_id}", "hidden": hidden},
    )
    pg.execute(
        "INSERT INTO identity_map (source, entity_type, external_id, clouder_entity_type, clouder_id, "
        "match_type, confidence, first_seen_at, last_seen_at) VALUES ('beatport', 'style', :ext, "
        "'style', :cid, 'auto_create', 0.6, now(), now())",
        {"ext": str(bp_id), "cid": f"cs{bp_id}"},
    )


def _track(
    pg,
    tid,
    *,
    created="now()",
    isrc="ISRC",
    searched="now()",
    spotify_id=None,
    bpm=None,
    length_ms=None,
    origin="beatport",
):
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, isrc, bpm, length_ms, "
        f"spotify_id, spotify_searched_at, created_at, updated_at, origin) VALUES (:id, 'T', 't', "
        f":isrc, :bpm, :len, :sp, {searched}, {created}, now(), :origin)",
        {"id": tid, "isrc": isrc, "bpm": bpm, "len": length_ms, "sp": spotify_id, "origin": origin},
    )


def test_stuck_ingest_runs(pg) -> None:
    _run(pg, "stuck", 1, status="RAW_SAVED", started="now() - INTERVAL '3 hours'")
    _run(pg, "fresh", 1, status="RAW_SAVED")
    _run(pg, "done", 1, started="now() - INTERVAL '3 hours'")

    result = _value(pg, "stuck_ingest_runs")

    assert result.value == 1.0 and not result.passed


def test_styles_behind(pg) -> None:
    _run(pg, "s1", 1, period_end="2026-10-02")  # up to date
    _run(pg, "s2", 2, period_end="2026-09-25")  # one week behind
    _run(pg, "s3", 3, period_end="2026-06-05")  # inactive: older than 8 weeks

    assert _value(pg, "styles_behind").value == 1.0


def test_weekly_volume_anomalies_compares_latest_week_with_median(pg) -> None:
    weeks = ["2026-08-28", "2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25"]
    for i, end in enumerate(weeks):
        _run(pg, f"a{i}", 7, items=100, period_end=end)
        _run(pg, f"b{i}", 8, items=100, period_end=end)
    _run(pg, "a-retry", 7, items=90, period_end="2026-09-25")  # same week twice: counted once
    _run(pg, "a-latest", 7, items=30, period_end="2026-10-02")  # collapse: anomaly
    _run(pg, "b-latest", 8, items=110, period_end="2026-10-02")  # normal
    _run(pg, "c0", 9, items=100, period_end="2026-09-25")
    _run(pg, "c-latest", 9, items=5, period_end="2026-10-02")  # < 4 weeks of history: skipped

    assert _value(pg, "weekly_volume_anomalies").value == 1.0


def test_isrc_coverage_pct(pg) -> None:
    for i in range(3):
        _track(pg, f"ok{i}")
    _track(pg, "no-isrc", isrc=None)
    _track(pg, "old", isrc=None, created="now() - INTERVAL '60 days'")

    result = _value(pg, "isrc_coverage_pct")

    assert result.value == 75.0 and not result.passed


def test_spotify_match_pct(pg) -> None:
    _track(pg, "f1", spotify_id="sp1")
    _track(pg, "f2", spotify_id="sp2")
    _track(pg, "n1")
    _track(pg, "n2")

    assert _value(pg, "spotify_match_pct").value == 50.0


def test_spotify_unsearched_stale(pg) -> None:
    _track(pg, "stale", searched="NULL", created="now() - INTERVAL '2 days'")
    _track(pg, "new", searched="NULL")
    _track(pg, "imported", searched="NULL", spotify_id="sp", created="now() - INTERVAL '2 days'")

    assert _value(pg, "spotify_unsearched_stale").value == 1.0


def test_orphan_identities_and_artists_without_identity(pg) -> None:
    _track(pg, "t1")
    for aid in ("a1", "a2", "a3"):
        pg.execute(
            "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at) "
            "VALUES (:id, 'A', 'a', now(), now())",
            {"id": aid},
        )
    for ext, kind, cid in (("1", "track", "t1"), ("2", "track", "missing"), ("3", "artist", "a1")):
        pg.execute(
            "INSERT INTO identity_map (source, entity_type, external_id, clouder_entity_type, "
            "clouder_id, match_type, confidence, first_seen_at, last_seen_at) VALUES "
            "('beatport', :kind, :ext, :kind, :cid, 'auto_create', 0.6, now(), now())",
            {"kind": kind, "ext": ext, "cid": cid},
        )

    assert _value(pg, "orphan_identities").value == 1.0
    info = _value(pg, "artists_without_identity")
    assert info.value == 2.0 and info.passed  # recorded only


def test_bpm_and_length_out_of_range(pg) -> None:
    _track(pg, "fast", bpm=300)
    _track(pg, "normal", bpm=128, length_ms=300000)
    _track(pg, "empty", length_ms=0)
    _track(pg, "dj-mix", length_ms=2 * 3600 * 1000)  # continuous mixes run for hours

    assert _value(pg, "bpm_out_of_range").value == 1.0
    assert _value(pg, "length_out_of_range").value == 1.0


def test_review_backlog_days(pg) -> None:
    _track(pg, "t1")
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at) "
        "VALUES ('q1', 't1', 'ytmusic', '[]'::jsonb, 'pending', now() - INTERVAL '20 days')"
    )

    result = _value(pg, "review_backlog_days")

    assert result.value == 20.0 and result.passed  # recorded only: user workflow state


def test_empty_database_passes_with_nothing_to_measure(pg) -> None:
    results = run_checks(pg, TODAY)

    assert all(r.passed for r in results)
    assert {r.name for r in results if r.value is None} >= {
        "isrc_coverage_pct",
        "spotify_match_pct",
        "review_backlog_days",
    }
    assert len(results) == len(CHECKS)


# ── final-review fixes: no false alarms on a healthy catalog ──────────


def test_stuck_ingest_runs_ignores_runs_older_than_two_weeks(pg) -> None:
    _run(pg, "ancient", 1, status="RAW_SAVED", started="now() - INTERVAL '30 days'")

    assert _value(pg, "stuck_ingest_runs").value == 0.0


def test_styles_behind_ignores_hidden_styles(pg) -> None:
    _style(pg, 4, hidden=True)
    _run(pg, "h1", 4, period_end="2026-09-25")

    assert _value(pg, "styles_behind").value == 0.0


def test_weekly_volume_ignores_custom_ranges_open_weeks_and_inactive_styles(pg) -> None:
    for i, end in enumerate(["2026-08-28", "2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25"]):
        _run(pg, f"a{i}", 7, items=100, period_end=end)
        _run(pg, f"h{i}", 11, items=100, period_end=end)
    _run(pg, "a-closed", 7, items=100, period_end="2026-10-02")
    _run(pg, "a-custom", 7, items=2400, period_end="2026-10-02", custom=True)  # 4-week override
    _run(pg, "a-open", 7, items=30, period_end="2026-10-09")  # week still open
    _style(pg, 11, hidden=True)
    _run(pg, "h-latest", 11, items=5, period_end="2026-10-02")  # hidden style collapse
    for i, end in enumerate(["2026-05-29", "2026-06-05", "2026-06-12", "2026-06-19"]):
        _run(pg, f"x{i}", 10, items=100, period_end=end)
    _run(pg, "x-last", 10, items=5, period_end="2026-06-26")  # abandoned in June

    assert _value(pg, "weekly_volume_anomalies").value == 0.0


def test_spotify_match_pct_ignores_retries_of_old_tracks_and_user_imports(pg) -> None:
    _track(pg, "found", spotify_id="sp1")
    _track(pg, "missed")
    _track(pg, "retried-old", created="now() - INTERVAL '60 days'")  # searched again today
    _track(pg, "imported", spotify_id="sp2", origin="spotify_user_import")

    assert _value(pg, "spotify_match_pct").value == 50.0


def test_isrc_coverage_ignores_user_imports(pg) -> None:
    _track(pg, "bp")
    _track(pg, "imported", isrc=None, origin="spotify_user_import")

    assert _value(pg, "isrc_coverage_pct").value == 100.0


def test_spotify_unsearched_stale_ignores_tracks_without_isrc(pg) -> None:
    _track(pg, "no-isrc", isrc=None, searched="NULL", created="now() - INTERVAL '2 days'")

    assert _value(pg, "spotify_unsearched_stale").value == 0.0
