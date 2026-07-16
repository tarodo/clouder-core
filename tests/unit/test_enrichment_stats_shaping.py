"""Pure shaping helpers for scripts/enrichment_stats.py and
scripts/openai_usage_report.py. No boto3/urllib calls, no network — the
scripts import boto3 lazily inside main() precisely so importing them here
doesn't require live AWS/OpenAI credentials.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import enrichment_stats  # noqa: E402
import openai_usage_report  # noqa: E402


# ── enrichment_stats.cutoff_date ───────────────────────────────────────────


def test_cutoff_date_default_three_months_spans_current_plus_two():
    assert enrichment_stats.cutoff_date(3, today=date(2026, 7, 16)) == date(2026, 5, 1)


def test_cutoff_date_one_month_is_current_month_start():
    assert enrichment_stats.cutoff_date(1, today=date(2026, 7, 16)) == date(2026, 7, 1)


def test_cutoff_date_crosses_year_boundary():
    assert enrichment_stats.cutoff_date(3, today=date(2026, 1, 16)) == date(2025, 11, 1)


# ── enrichment_stats.shape_cells_stats ─────────────────────────────────────


def test_shape_cells_stats_groups_by_month_and_kind_with_averages():
    rows = [
        {
            "month": "2026-06",
            "kind": "label",
            "input_tokens": 20000,
            "output_tokens": 1000,
            "web_search_calls": 3,
            "tavily_credits": 0,
            "cost_usd": 0.03,
            "latency_ms": 4000,
            "has_error": False,
        },
        {
            "month": "2026-06",
            "kind": "label",
            "input_tokens": 22000,
            "output_tokens": 1200,
            "web_search_calls": 5,
            "tavily_credits": 1,
            "cost_usd": 0.05,
            "latency_ms": 6000,
            "has_error": True,
        },
        {
            "month": "2026-06",
            "kind": "artist",
            "input_tokens": 10000,
            "output_tokens": 500,
            "web_search_calls": 2,
            "tavily_credits": 0,
            "cost_usd": 0.02,
            "latency_ms": None,
            "has_error": False,
        },
    ]

    stats = enrichment_stats.shape_cells_stats(rows)

    by_key = {(s["month"], s["kind"]): s for s in stats}
    label = by_key[("2026-06", "label")]
    assert label["cells"] == 2
    assert label["avg_input_tokens"] == 21000.0
    assert label["avg_output_tokens"] == 1100.0
    assert label["avg_web_search_calls"] == 4.0
    assert label["avg_tavily_credits"] == 0.5
    assert abs(label["avg_cost_usd"] - 0.04) < 1e-9
    assert label["avg_latency_ms"] == 5000.0
    assert label["error_count"] == 1

    artist = by_key[("2026-06", "artist")]
    assert artist["cells"] == 1
    # latency_ms=None must not corrupt the average (divide-by-zero guard).
    assert artist["avg_latency_ms"] == 0.0


def test_shape_cells_stats_coalesces_missing_jsonb_keys_on_old_rows():
    """Old cells predate web_search_calls/tavily_credits; SQL coalesces them
    to 0 but the shaping function must also tolerate the keys being absent
    entirely from the row dict (defensive, matches `.get(..., 0)` usage)."""
    rows = [{"month": "2026-05", "kind": "label", "cost_usd": 0.01, "has_error": False}]

    stats = enrichment_stats.shape_cells_stats(rows)

    assert stats == [
        {
            "month": "2026-05",
            "kind": "label",
            "cells": 1,
            "avg_input_tokens": 0.0,
            "avg_output_tokens": 0.0,
            "avg_web_search_calls": 0.0,
            "avg_tavily_credits": 0.0,
            "avg_cost_usd": 0.01,
            "avg_latency_ms": 0.0,
            "error_count": 0,
        }
    ]


def test_shape_cells_stats_empty_input():
    assert enrichment_stats.shape_cells_stats([]) == []


# ── enrichment_stats.shape_instagram_fill ──────────────────────────────────


def test_shape_instagram_fill_computes_rate_per_kind():
    rows = [
        {"kind": "label", "total": 500, "filled": 220},
        {"kind": "artist", "total": 300, "filled": 90},
    ]

    fill = enrichment_stats.shape_instagram_fill(rows)

    assert fill == [
        {"kind": "label", "total": 500, "filled": 220, "fill_rate": 220 / 500},
        {"kind": "artist", "total": 300, "filled": 90, "fill_rate": 90 / 300},
    ]


def test_shape_instagram_fill_guards_zero_total():
    rows = [{"kind": "label", "total": 0, "filled": 0}]

    fill = enrichment_stats.shape_instagram_fill(rows)

    assert fill == [{"kind": "label", "total": 0, "filled": 0, "fill_rate": 0.0}]


# ── openai_usage_report.to_float ───────────────────────────────────────────


def test_to_float_parses_decimal_string_zero_scientific_notation():
    # Real API response: comped gpt-5.4-mini tokens bill as this exact
    # Decimal-string shape. Must not raise, must equal 0.0.
    assert openai_usage_report.to_float("0E-6176") == 0.0


def test_to_float_parses_plain_decimal_string():
    assert openai_usage_report.to_float("1.6500000000000000000000000000000000") == 1.65


def test_to_float_handles_numeric_and_none():
    assert openai_usage_report.to_float(0.04) == 0.04
    assert openai_usage_report.to_float(None) == 0.0


# ── openai_usage_report.aggregate_costs ────────────────────────────────────


def _cost_result(line_item: str, value: str, quantity: float) -> dict:
    return {
        "object": "organization.costs.result",
        "amount": {"value": value, "currency": "usd"},
        "quantity": quantity,
        "line_item": line_item,
        "project_id": "proj_default",
    }


def test_aggregate_costs_sums_usd_and_quantity_by_month_and_line_item():
    buckets = [
        {
            "object": "bucket",
            "start_time": 1780531200,  # 2026-06-04T00:00:00Z
            "results": [
                _cost_result("gpt-5.4-mini-2026-03-17, input", "0E-6176", 22091.0),
                _cost_result("web search tool calls", "0.0400000000000000000000", 4.0),
            ],
        },
        {
            "object": "bucket",
            "start_time": 1780617600,  # 2026-06-05T00:00:00Z
            "results": [
                _cost_result("web search tool calls", "0.0200000000000000000000", 2.0),
            ],
        },
    ]

    costs = openai_usage_report.aggregate_costs(buckets)

    by_key = {(r["month"], r["line_item"]): r for r in costs}
    assert by_key[("2026-06", "gpt-5.4-mini-2026-03-17, input")]["usd"] == 0.0
    assert by_key[("2026-06", "gpt-5.4-mini-2026-03-17, input")]["quantity"] == 22091.0
    web_search = by_key[("2026-06", "web search tool calls")]
    assert abs(web_search["usd"] - 0.06) < 1e-9
    assert web_search["quantity"] == 6.0
    assert costs == sorted(costs, key=lambda r: (r["month"], r["line_item"]))


def test_aggregate_costs_empty_results_bucket_contributes_nothing():
    buckets = [{"object": "bucket", "start_time": 1780272000, "results": []}]
    assert openai_usage_report.aggregate_costs(buckets) == []


# ── openai_usage_report.aggregate_usage ────────────────────────────────────


def _usage_result(model: str, requests: int, inp: int, cached: int, out: int) -> dict:
    return {
        "object": "organization.usage.completions.result",
        "model": model,
        "project_id": "proj_default",
        "num_model_requests": requests,
        "input_tokens": inp,
        "input_cached_tokens": cached,
        "output_tokens": out,
    }


def test_aggregate_usage_sums_tokens_and_requests_by_month_and_model():
    buckets = [
        {
            "object": "bucket",
            "start_time": 1780531200,  # 2026-06-04
            "results": [_usage_result("gpt-5.4-mini-2026-03-17", 1, 22091, 0, 1045)],
        },
        {
            "object": "bucket",
            "start_time": 1780617600,  # 2026-06-05
            "results": [_usage_result("gpt-5.4-mini-2026-03-17", 1, 23527, 5000, 1144)],
        },
    ]

    usage = openai_usage_report.aggregate_usage(buckets)

    assert usage == [
        {
            "month": "2026-06",
            "model": "gpt-5.4-mini-2026-03-17",
            "requests": 2,
            "input_tokens": 45618,
            "cached_tokens": 5000,
            "output_tokens": 2189,
        }
    ]


def test_aggregate_usage_empty_results_bucket_contributes_nothing():
    buckets = [{"object": "bucket", "start_time": 1780272000, "results": []}]
    assert openai_usage_report.aggregate_usage(buckets) == []
