#!/usr/bin/env python3
"""Operator report: OpenAI org billing (Costs API) + model usage (Usage API).

Stdlib urllib only — no `openai` SDK dependency needed for two read-only
GETs. Companion to `scripts/enrichment_stats.py` (Aurora-side cost/usage)
and the design in
`docs/superpowers/specs/2026-07-15-enrichment-cost-instagram-design.md` §6 /
`docs/superpowers/plans/2026-07-16-enrichment-prod-v2.md` Task 7. Query
shape and pagination verified live against
`docs/superpowers/specs/2026-07-15-enrichment-openai-usage-analysis.md`'s
phase-0 pull.

Requires `OPENAI_ADMIN_KEY` — an *admin* API key (Organization > API keys >
Admin keys) with the `api.usage.read` scope. A regular project key is
rejected by both endpoints.

Usage:
    OPENAI_ADMIN_KEY=sk-... python3 scripts/openai_usage_report.py
    OPENAI_ADMIN_KEY=sk-... python3 scripts/openai_usage_report.py --since 2026-05-01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

API_BASE = "https://api.openai.com/v1"
_REQUIRED_SCOPE = "api.usage.read"


def to_float(value: Any) -> float:
    """Parse a cost `amount.value`, which the API sends as a Decimal string.

    Real responses include zero-cost line items as scientific-notation
    strings like "0E-6176" (gpt-5.4-mini tokens are comped) — `float()`
    handles that directly, but route through Decimal first so any other
    exotic decimal-string shape parses the same way instead of raising.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return 0.0


def _bucket_month(bucket: dict) -> str:
    ts = bucket.get("start_time")
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m")


def aggregate_costs(buckets: list[dict]) -> list[dict]:
    """Sum `/organization/costs` bucket results into month x line_item rows.

    Pure — no I/O. `buckets` is the list of top-level bucket dicts (each
    with `start_time` + `results`), i.e. the concatenation of `data` across
    every page.
    """
    totals: dict[tuple[str, str], dict[str, float]] = {}
    for bucket in buckets:
        month = _bucket_month(bucket)
        for result in bucket.get("results") or []:
            line_item = result.get("line_item") or "(unknown)"
            key = (month, line_item)
            entry = totals.setdefault(key, {"usd": 0.0, "quantity": 0.0})
            amount = result.get("amount") or {}
            entry["usd"] += to_float(amount.get("value"))
            entry["quantity"] += to_float(result.get("quantity"))
    return [
        {"month": month, "line_item": line_item, "usd": v["usd"], "quantity": v["quantity"]}
        for (month, line_item), v in sorted(totals.items())
    ]


def aggregate_usage(buckets: list[dict]) -> list[dict]:
    """Sum `/organization/usage/completions` bucket results into month x model rows."""
    totals: dict[tuple[str, str], dict[str, int]] = {}
    for bucket in buckets:
        month = _bucket_month(bucket)
        for result in bucket.get("results") or []:
            model = result.get("model") or "(unknown)"
            key = (month, model)
            entry = totals.setdefault(
                key, {"requests": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0}
            )
            entry["requests"] += int(result.get("num_model_requests") or 0)
            entry["input_tokens"] += int(result.get("input_tokens") or 0)
            entry["cached_tokens"] += int(result.get("input_cached_tokens") or 0)
            entry["output_tokens"] += int(result.get("output_tokens") or 0)
    return [
        {"month": month, "model": model, **v} for (month, model), v in sorted(totals.items())
    ]


def _require_api_key() -> str:
    key = os.environ.get("OPENAI_ADMIN_KEY")
    if not key:
        print(
            "OPENAI_ADMIN_KEY is not set. Create an admin API key with the "
            f"'{_REQUIRED_SCOPE}' scope (platform.openai.com > Organization > "
            "API keys > Admin keys) and export it as OPENAI_ADMIN_KEY.",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


def _get(url: str, api_key: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in (401, 403):
            print(
                f"OpenAI API rejected the request ({exc.code}): the key needs the "
                f"'{_REQUIRED_SCOPE}' scope. Response: {body}",
                file=sys.stderr,
            )
            sys.exit(1)
        raise RuntimeError(f"OpenAI API error {exc.code}: {body}") from exc


def _paginate(path: str, api_key: str, params: dict[str, Any]) -> list[dict]:
    buckets: list[dict] = []
    page_token: str | None = None
    while True:
        query = list(params.items())
        if page_token:
            query.append(("page", page_token))
        url = f"{API_BASE}{path}?{urllib.parse.urlencode(query, doseq=True)}"
        data = _get(url, api_key)
        buckets.extend(data.get("data") or [])
        if data.get("has_more") and data.get("next_page"):
            page_token = data["next_page"]
        else:
            break
    return buckets


def fetch_costs(api_key: str, since_ts: int, limit: int = 180) -> list[dict]:
    return _paginate(
        "/organization/costs",
        api_key,
        {"start_time": since_ts, "limit": limit, "group_by": ["line_item", "project_id"]},
    )


def fetch_usage(api_key: str, since_ts: int, limit: int = 31) -> list[dict]:
    return _paginate(
        "/organization/usage/completions",
        api_key,
        {
            "start_time": since_ts,
            "bucket_width": "1d",
            "limit": limit,
            "group_by": ["model", "project_id"],
        },
    )


def default_since() -> str:
    """First day of last month, as YYYY-MM-DD."""
    today = date.today()
    first_of_this_month = today.replace(day=1)
    last_month_end = first_of_this_month - timedelta(days=1)
    return last_month_end.replace(day=1).isoformat()


def parse_since(value: str) -> int:
    dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _print_costs_table(costs: list[dict]) -> None:
    print(f"{'month':<8} {'line_item':<38} {'usd':>10} {'quantity':>14}")
    for row in costs:
        print(
            f"{row['month']:<8} {row['line_item']:<38} {row['usd']:>10.4f} "
            f"{row['quantity']:>14.1f}"
        )


def _print_usage_table(usage: list[dict]) -> None:
    print(f"{'month':<8} {'model':<26} {'requests':>9} {'input':>10} {'cached':>10} {'output':>10}")
    for row in usage:
        print(
            f"{row['month']:<8} {row['model']:<26} {row['requests']:>9} "
            f"{row['input_tokens']:>10} {row['cached_tokens']:>10} {row['output_tokens']:>10}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenAI org costs + usage report")
    parser.add_argument("--since", default=None, help="YYYY-MM-DD (default: first of last month)")
    args = parser.parse_args(argv)

    api_key = _require_api_key()
    since_str = args.since or default_since()
    since_ts = parse_since(since_str)

    print(f"Since: {since_str}")

    costs = aggregate_costs(fetch_costs(api_key, since_ts))
    usage = aggregate_usage(fetch_usage(api_key, since_ts))

    print("\n=== USD by month x line item ===")
    _print_costs_table(costs)

    print("\n=== Tokens/requests by month x model ===")
    _print_usage_table(usage)

    total_usd = sum(row["usd"] for row in costs)
    print(f"\nTotal USD since {since_str}: {total_usd:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
