#!/usr/bin/env python3
"""Precision per Spotify match tier and a recall estimate from a labelled gold set.

  PYTHONPATH=src .venv/bin/python scripts/eval_spotify_match.py spotify_gold_<ts>.jsonl \
      --labels spotify_gold_<ts>_labels.csv [--out report.md]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from collector.spotify_gold import evaluate, render_report
from collector.vendor_match.evaluate import read_labels


def main(argv: list[str] | None = None) -> str:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("gold", type=Path)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    records = [json.loads(line) for line in args.gold.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = render_report(evaluate(records, read_labels(args.labels.read_text(encoding="utf-8").splitlines())))
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    print(report, end="")
    return report


if __name__ == "__main__":
    main()
