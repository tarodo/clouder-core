#!/usr/bin/env python3
"""Render widgets of the live overview dashboard to PNG for the README.

Reads the dashboard Terraform deployed (infra/dashboard.tf), so the images and
the dashboard never disagree. Operational metrics only: no user data.

Usage:
    .venv/bin/python scripts/dashboard_snapshots.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_WIDGETS = ["Lambda errors", "API latency p95 (ms)", "Aurora capacity (ACU)", "Data quality: completeness (%)"]
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "assets"


def snapshot(cloudwatch: Any, dashboard: str, titles: list[str], out_dir: Path) -> list[Path]:
    body = json.loads(cloudwatch.get_dashboard(DashboardName=dashboard)["DashboardBody"])
    by_title = {w["properties"]["title"]: w["properties"] for w in body["widgets"]}
    written = []
    for title in titles:
        widget = {**by_title[title], "start": "-P7D", "width": 800, "height": 300}
        png = cloudwatch.get_metric_widget_image(MetricWidget=json.dumps(widget), OutputFormat="png")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower().split("(")[0]).strip("-")
        path = out_dir / f"dashboard-{slug}.png"
        path.write_bytes(png["MetricWidgetImage"])
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dashboard", default="clouder-prod-overview")
    parser.add_argument("--widget", action="append", help="widget title (repeatable)")
    args = parser.parse_args(argv)

    import boto3

    cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
    for path in snapshot(cloudwatch, args.dashboard, args.widget or DEFAULT_WIDGETS, OUT_DIR):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
