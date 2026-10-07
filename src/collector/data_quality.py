"""Nightly data-quality checks (docs/data/data-quality.md).

Each check is one read-only SQL statement returning a single `value`, compared
with a threshold: `max` passes when value <= threshold, `min` when value >=
threshold, `None` threshold is recorded only. A `None` value means there was
nothing to measure and passes. A check whose SQL fails is recorded as failed so
a broken check cannot hide behind a green run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Sequence

from .logging_utils import log_event

NAMESPACE = "CLOUDER/DataQuality"
FRESHNESS_GRACE_DAYS = 4  # a week closes Friday; it is due by the end of Monday (UTC)
STUCK_RUN_WINDOW_DAYS = 14
ACTIVE_STYLE_WINDOW_DAYS = 56  # 8 Saturday-weeks
_FRIDAY = 4


@dataclass(frozen=True)
class Check:
    name: str
    description: str
    sql: str
    comparison: str  # "max" | "min"
    threshold: float | None
    params: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckResult:
    name: str
    value: float | None
    threshold: float | None
    comparison: str
    passed: bool


CHECKS: tuple[Check, ...] = (
    Check(
        "stuck_ingest_runs",
        "Recent ingest runs without a final status two hours after they started.",
        """
        SELECT count(*) AS value
        FROM ingest_runs
        WHERE status NOT IN ('COMPLETED', 'FAILED')
          AND started_at < now() - INTERVAL '2 hours'
          AND started_at > now() - INTERVAL '14 days'
        """,
        "max", 0,
    ),
    Check(
        "styles_behind",
        "Active, visible styles whose latest completed week ends before the week that is due.",
        """
        WITH active AS (
            SELECT ir.style_id, max(ir.period_end) AS last_end
            FROM ingest_runs ir
            LEFT JOIN identity_map im
              ON im.source = 'beatport'
             AND im.entity_type = 'style'
             AND im.clouder_entity_type = 'style'
             AND im.external_id = CAST(ir.style_id AS text)
            LEFT JOIN clouder_styles cs ON cs.id = im.clouder_id
            WHERE ir.status = 'COMPLETED'
              AND ir.period_end IS NOT NULL
              AND NOT COALESCE(cs.is_hidden, false)
            GROUP BY ir.style_id
            HAVING max(ir.period_end) >= :since
        )
        SELECT count(*) AS value FROM active WHERE last_end < :expected_end
        """,
        "max", 0, ("since", "expected_end"),
    ),
    Check(
        "weekly_volume_anomalies",
        "Styles whose latest week has under half or over twice their 8-week median volume.",
        """
        WITH weekly AS (
            SELECT ir.style_id, ir.period_end, max(ir.item_count) AS items
            FROM ingest_runs ir
            LEFT JOIN identity_map im
              ON im.source = 'beatport'
             AND im.entity_type = 'style'
             AND im.clouder_entity_type = 'style'
             AND im.external_id = CAST(ir.style_id AS text)
            LEFT JOIN clouder_styles cs ON cs.id = im.clouder_id
            WHERE ir.status = 'COMPLETED'
              AND ir.period_end IS NOT NULL
              AND ir.period_end <= :expected_end
              AND NOT ir.is_custom_range
              AND NOT COALESCE(cs.is_hidden, false)
            GROUP BY ir.style_id, ir.period_end
        ),
        ranked AS (
            SELECT style_id, period_end, items,
                   row_number() OVER (PARTITION BY style_id ORDER BY period_end DESC) AS rn
            FROM weekly
        ),
        baseline AS (
            SELECT style_id,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY items) AS median_items,
                   count(*) AS weeks
            FROM ranked
            WHERE rn BETWEEN 2 AND 9
            GROUP BY style_id
        )
        SELECT count(*) AS value
        FROM ranked l
        JOIN baseline b ON b.style_id = l.style_id
        WHERE l.rn = 1
          AND l.period_end >= :since
          AND b.weeks >= 4
          AND (l.items < 0.5 * b.median_items OR l.items > 2 * b.median_items)
        """,
        "max", 0, ("since", "expected_end"),
    ),
    Check(
        "isrc_coverage_pct",
        "Share of Beatport tracks created in the last 30 days that carry an ISRC.",
        """
        SELECT round(100.0 * count(*) FILTER (WHERE isrc IS NOT NULL) / nullif(count(*), 0), 2) AS value
        FROM clouder_tracks
        WHERE origin = 'beatport'
          AND created_at >= now() - INTERVAL '30 days'
        """,
        "min", 99,
    ),
    Check(
        "spotify_match_pct",
        "Share of Beatport tracks created in the last 30 days and already searched that were found.",
        """
        SELECT round(100.0 * count(*) FILTER (WHERE spotify_id IS NOT NULL) / nullif(count(*), 0), 2) AS value
        FROM clouder_tracks
        WHERE origin = 'beatport'
          AND created_at >= now() - INTERVAL '30 days'
          AND spotify_searched_at IS NOT NULL
        """,
        "min", 95,
    ),
    Check(
        "spotify_unsearched_stale",
        "Tracks with an ISRC, older than a day, never searched on Spotify.",
        """
        SELECT count(*) AS value
        FROM clouder_tracks
        WHERE spotify_searched_at IS NULL
          AND spotify_id IS NULL
          AND isrc IS NOT NULL
          AND created_at < now() - INTERVAL '1 day'
        """,
        "max", 0,
    ),
    Check(
        "orphan_identities",
        "identity_map rows whose canonical row does not exist.",
        """
        SELECT count(*) AS value
        FROM identity_map im
        WHERE NOT EXISTS (
            SELECT 1 FROM clouder_tracks t WHERE im.clouder_entity_type = 'track' AND t.id = im.clouder_id
            UNION ALL
            SELECT 1 FROM clouder_artists a WHERE im.clouder_entity_type = 'artist' AND a.id = im.clouder_id
            UNION ALL
            SELECT 1 FROM clouder_albums al WHERE im.clouder_entity_type = 'album' AND al.id = im.clouder_id
            UNION ALL
            SELECT 1 FROM clouder_labels l WHERE im.clouder_entity_type = 'label' AND l.id = im.clouder_id
            UNION ALL
            SELECT 1 FROM clouder_styles s WHERE im.clouder_entity_type = 'style' AND s.id = im.clouder_id
        )
        """,
        "max", 0,
    ),
    Check(
        "artists_without_identity",
        "Canonical artists no source maps to — duplicate suspects (recorded only).",
        """
        SELECT count(*) AS value
        FROM clouder_artists a
        WHERE NOT EXISTS (
            SELECT 1 FROM identity_map im
            WHERE im.clouder_entity_type = 'artist' AND im.clouder_id = a.id
        )
        """,
        "max", None,
    ),
    Check(
        "bpm_out_of_range",
        "Tracks with a BPM outside 40-250.",
        """
        SELECT count(*) AS value
        FROM clouder_tracks
        WHERE bpm IS NOT NULL AND (bpm < 40 OR bpm > 250)
        """,
        "max", 0,
    ),
    Check(
        "length_out_of_range",
        "Tracks with a length of zero or over three hours (continuous DJ mixes run for hours).",
        """
        SELECT count(*) AS value
        FROM clouder_tracks
        WHERE length_ms IS NOT NULL AND (length_ms <= 0 OR length_ms > 10800000)
        """,
        "max", 0,
    ),
    Check(
        "review_backlog_days",
        "Age in days of the oldest pending match review (recorded only: user workflow state).",
        """
        SELECT round(CAST(EXTRACT(EPOCH FROM now() - min(created_at)) / 86400.0 AS numeric), 1) AS value
        FROM match_review_queue
        WHERE status = 'pending'
        """,
        "max", None,
    ),
)


def check_by_name(name: str) -> Check:
    return next(c for c in CHECKS if c.name == name)


def expected_week_end(today: date, grace_days: int = FRESHNESS_GRACE_DAYS) -> date:
    """End (Friday) of the latest Saturday-week that should already be ingested."""
    d = today - timedelta(days=grace_days)
    return d - timedelta(days=(d.weekday() - _FRIDAY) % 7)


def _passes(check: Check, value: float | None) -> bool:
    if value is None or check.threshold is None:
        return True
    return value <= check.threshold if check.comparison == "max" else value >= check.threshold


def run_checks(
    client: Any, today: date, checks: Sequence[Check] = CHECKS
) -> list[CheckResult]:
    expected_end = expected_week_end(today)
    context = {
        "expected_end": expected_end,
        "since": expected_end - timedelta(days=ACTIVE_STYLE_WINDOW_DAYS),
    }
    results: list[CheckResult] = []
    for check in checks:
        params = {name: context[name] for name in check.params} or None
        try:
            rows = client.execute(check.sql, params)
        except Exception as exc:  # a broken check must surface as a failure
            log_event(
                "ERROR", "dq_check_failed_to_run",
                check=check.name, error_type=exc.__class__.__name__,
                error_message=str(exc)[:500],
            )
            results.append(CheckResult(check.name, None, check.threshold, check.comparison, False))
            continue
        raw = rows[0].get("value") if rows else None
        value = float(raw) if raw is not None else None
        results.append(
            CheckResult(check.name, value, check.threshold, check.comparison, _passes(check, value))
        )
    return results
