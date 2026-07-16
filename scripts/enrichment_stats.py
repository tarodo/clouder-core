#!/usr/bin/env python3
"""Operator report: enrichment cell cost/usage stats + Instagram fill-rate.

Reads directly from Aurora via the RDS Data API (boto3 rds-data) — this is
an operator script run from a laptop, not Lambda code, so it talks to
`clouder_label_enrichment_cells` / `clouder_artist_enrichment_cells` /
`clouder_label_info` / `clouder_artist_info` directly rather than going
through the app's `DataAPIClient`.

Companion to `scripts/openai_usage_report.py` (OpenAI org billing side) and
the design in `docs/superpowers/specs/2026-07-15-enrichment-cost-instagram-design.md`
§6 / `docs/superpowers/plans/2026-07-16-enrichment-prod-v2.md` Task 7.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/enrichment_stats.py --months 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from typing import Any

_DEFAULT_CLUSTER_ARN = (
    "arn:aws:rds:us-east-1:223458487728:cluster:clouder-prod-aurora"
)
_DEFAULT_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:223458487728:"
    "secret:rds!cluster-1ebed129-3946-4c55-a18e-72b53364e0e6-pCk4dS"
)

_CELLS_SQL = """
SELECT 'label' AS kind,
       to_char(created_at, 'YYYY-MM') AS month,
       coalesce((usage->>'input_tokens')::numeric, 0) AS input_tokens,
       coalesce((usage->>'output_tokens')::numeric, 0) AS output_tokens,
       coalesce((usage->>'web_search_calls')::numeric, 0) AS web_search_calls,
       coalesce((usage->>'tavily_credits')::numeric, 0) AS tavily_credits,
       coalesce((usage->>'cost_usd')::numeric, 0) AS cost_usd,
       latency_ms,
       (error IS NOT NULL) AS has_error
FROM clouder_label_enrichment_cells
WHERE created_at >= DATE '{cutoff}'
UNION ALL
SELECT 'artist' AS kind,
       to_char(created_at, 'YYYY-MM') AS month,
       coalesce((usage->>'input_tokens')::numeric, 0) AS input_tokens,
       coalesce((usage->>'output_tokens')::numeric, 0) AS output_tokens,
       coalesce((usage->>'web_search_calls')::numeric, 0) AS web_search_calls,
       coalesce((usage->>'tavily_credits')::numeric, 0) AS tavily_credits,
       coalesce((usage->>'cost_usd')::numeric, 0) AS cost_usd,
       latency_ms,
       (error IS NOT NULL) AS has_error
FROM clouder_artist_enrichment_cells
WHERE created_at >= DATE '{cutoff}'
"""

_INSTAGRAM_FILL_SQL = """
SELECT 'label' AS kind,
       COUNT(*) AS total,
       COUNT(*) FILTER (
           WHERE merged->>'instagram_url' IS NOT NULL AND merged->>'instagram_url' != ''
       ) AS filled
FROM clouder_label_info
UNION ALL
SELECT 'artist' AS kind,
       COUNT(*) AS total,
       COUNT(*) FILTER (
           WHERE merged->>'instagram_url' IS NOT NULL AND merged->>'instagram_url' != ''
       ) AS filled
FROM clouder_artist_info
"""


def cutoff_date(months: int, today: date | None = None) -> date:
    """First day of the month `months - 1` months before `today`'s month.

    months=3 with today in July returns May 1 — i.e. the window covers the
    current month plus the two preceding ones (3 months total).
    """
    today = today or date.today()
    total = today.year * 12 + (today.month - 1) - (months - 1)
    year, month0 = divmod(total, 12)
    return date(year, month0 + 1, 1)


def resolve_arn(cli_value: str | None, env_var: str, default: str) -> str:
    if cli_value:
        return cli_value
    return os.environ.get(env_var) or default


def fetch(
    client: Any,
    sql: str,
    *,
    cluster_arn: str,
    secret_arn: str,
    database: str,
    retries: int = 3,
    wait_s: float = 15.0,
) -> list[dict]:
    """Thin execute_statement wrapper: JSON-formatted rows, resume-retry.

    Aurora Serverless v2 at min_acu=0 needs to resume from a cold pause on
    the first call after idling; the Data API raises DatabaseResumingException
    while it does. This is an operator tool run interactively, so retrying
    in-process (rather than making the caller re-run the script) is the
    right call.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.execute_statement(
                resourceArn=cluster_arn,
                secretArn=secret_arn,
                database=database,
                sql=sql,
                formatRecordsAs="JSON",
            )
            return json.loads(resp.get("formattedRecords") or "[]")
        except client.exceptions.DatabaseResumingException as exc:
            last_exc = exc
            if attempt < retries - 1:
                print(
                    f"Aurora is resuming (attempt {attempt + 1}/{retries}); "
                    f"retrying in {wait_s:.0f}s...",
                    file=sys.stderr,
                )
                time.sleep(wait_s)
                continue
    assert last_exc is not None
    raise last_exc


def shape_cells_stats(rows: list[dict]) -> list[dict]:
    """Group raw per-cell rows into per (month, kind) averages.

    `rows` come straight off `_CELLS_SQL` (one row per cell). Pure —
    no I/O, safe to unit test with fixture dicts.
    """
    groups: dict[tuple[str, str], dict[str, float]] = {}
    for row in rows:
        key = (row["month"], row["kind"])
        g = groups.setdefault(
            key,
            {
                "cells": 0,
                "input_tokens_sum": 0.0,
                "output_tokens_sum": 0.0,
                "web_search_calls_sum": 0.0,
                "tavily_credits_sum": 0.0,
                "cost_usd_sum": 0.0,
                "latency_ms_sum": 0.0,
                "latency_ms_count": 0,
                "error_count": 0,
            },
        )
        g["cells"] += 1
        g["input_tokens_sum"] += float(row.get("input_tokens") or 0)
        g["output_tokens_sum"] += float(row.get("output_tokens") or 0)
        g["web_search_calls_sum"] += float(row.get("web_search_calls") or 0)
        g["tavily_credits_sum"] += float(row.get("tavily_credits") or 0)
        g["cost_usd_sum"] += float(row.get("cost_usd") or 0)
        latency = row.get("latency_ms")
        if latency is not None:
            g["latency_ms_sum"] += float(latency)
            g["latency_ms_count"] += 1
        if row.get("has_error"):
            g["error_count"] += 1

    out = []
    for (month, kind), g in sorted(groups.items()):
        cells = g["cells"]
        out.append(
            {
                "month": month,
                "kind": kind,
                "cells": cells,
                "avg_input_tokens": g["input_tokens_sum"] / cells,
                "avg_output_tokens": g["output_tokens_sum"] / cells,
                "avg_web_search_calls": g["web_search_calls_sum"] / cells,
                "avg_tavily_credits": g["tavily_credits_sum"] / cells,
                "avg_cost_usd": g["cost_usd_sum"] / cells,
                "avg_latency_ms": (
                    g["latency_ms_sum"] / g["latency_ms_count"]
                    if g["latency_ms_count"]
                    else 0.0
                ),
                "error_count": g["error_count"],
            }
        )
    return out


def shape_instagram_fill(rows: list[dict]) -> list[dict]:
    """Per-kind instagram_url fill-rate from `_INSTAGRAM_FILL_SQL` rows."""
    out = []
    for row in rows:
        total = int(row.get("total") or 0)
        filled = int(row.get("filled") or 0)
        fill_rate = (filled / total) if total else 0.0
        out.append(
            {"kind": row["kind"], "total": total, "filled": filled, "fill_rate": fill_rate}
        )
    return out


def _print_cells_table(stats: list[dict]) -> None:
    print(
        f"{'month':<8} {'kind':<7} {'cells':>6} {'avg_in_tok':>11} "
        f"{'avg_out_tok':>12} {'avg_search':>10} {'avg_credit':>10} "
        f"{'avg_cost':>10} {'avg_lat_ms':>10} {'errors':>7}"
    )
    for s in stats:
        print(
            f"{s['month']:<8} {s['kind']:<7} {s['cells']:>6} "
            f"{s['avg_input_tokens']:>11.1f} {s['avg_output_tokens']:>12.1f} "
            f"{s['avg_web_search_calls']:>10.2f} {s['avg_tavily_credits']:>10.2f} "
            f"{s['avg_cost_usd']:>10.4f} {s['avg_latency_ms']:>10.0f} {s['error_count']:>7}"
        )


def _print_instagram_table(fill: list[dict]) -> None:
    print(f"{'kind':<7} {'total':>7} {'filled':>7} {'fill_rate':>10}")
    for f in fill:
        print(f"{f['kind']:<7} {f['total']:>7} {f['filled']:>7} {f['fill_rate']:>9.1%}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enrichment cost/usage/fill-rate report")
    parser.add_argument("--cluster-arn", default=None)
    parser.add_argument("--secret-arn", default=None)
    parser.add_argument("--database", default="clouder")
    parser.add_argument("--months", type=int, default=3)
    args = parser.parse_args(argv)

    cluster_arn = resolve_arn(args.cluster_arn, "CLOUDER_CLUSTER_ARN", _DEFAULT_CLUSTER_ARN)
    secret_arn = resolve_arn(args.secret_arn, "CLOUDER_SECRET_ARN", _DEFAULT_SECRET_ARN)
    cutoff = cutoff_date(args.months)

    import boto3

    client = boto3.client("rds-data", region_name="us-east-1")

    cell_rows = fetch(
        client,
        _CELLS_SQL.format(cutoff=cutoff.isoformat()),
        cluster_arn=cluster_arn,
        secret_arn=secret_arn,
        database=args.database,
    )
    fill_rows = fetch(
        client,
        _INSTAGRAM_FILL_SQL,
        cluster_arn=cluster_arn,
        secret_arn=secret_arn,
        database=args.database,
    )

    print(f"=== Enrichment cell stats (since {cutoff.isoformat()}, {args.months} months) ===")
    _print_cells_table(shape_cells_stats(cell_rows))

    print("\n=== Instagram fill-rate (clouder_label_info / clouder_artist_info) ===")
    _print_instagram_table(shape_instagram_fill(fill_rows))

    return 0


if __name__ == "__main__":
    sys.exit(main())
