#!/usr/bin/env python3
"""Score the YT Music fuzzy matcher against a gold set from scripts/export_match_gold.py.

  PYTHONPATH=src .venv/bin/python scripts/eval_vendor_match.py match_gold_<ts>.jsonl \
      [--labels match_gold_<ts>_labels.csv] [--fp-cost 10] [--review-cost 1] [--out report.md]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from collector.settings import get_vendor_match_settings
from collector.vendor_match.evaluate import load_gold, read_labels, render_report, sweep


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("gold", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--fp-cost", type=float, default=10.0, help="cost of one wrong auto-match")
    parser.add_argument("--review-cost", type=float, default=1.0, help="cost of one manual review")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    records = [json.loads(line) for line in args.gold.read_text(encoding="utf-8").splitlines() if line.strip()]
    labels = read_labels(args.labels.read_text(encoding="utf-8").splitlines()) if args.labels else {}
    items = load_gold(records, labels)
    results = sweep(items, fp_cost=args.fp_cost, review_cost=args.review_cost)
    duplicates = next((r for r in records if r.get("kind") == "duplicate_artists"), None)
    report = render_report(
        items, results,
        current=get_vendor_match_settings().fuzzy_match_threshold,
        fp_cost=args.fp_cost, review_cost=args.review_cost, duplicates=duplicates,
    )
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    print(report, end="")
    return report


if __name__ == "__main__":
    main()
