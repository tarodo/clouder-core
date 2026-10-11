#!/usr/bin/env python3
"""Export the Spotify matching gold set (read-only) for scripts/eval_spotify_match.py.

  PYTHONPATH=src .venv/bin/python scripts/export_spotify_gold.py                 # prod, RDS Data API
  PYTHONPATH=src .venv/bin/python scripts/export_spotify_gold.py --database-url postgresql://...

Writes spotify_gold_<ts>.jsonl (a sample per match tier, searched-but-not-found
tracks, the population of each) and spotify_gold_<ts>_labels.csv. Fill its `label`
column: for a match, y = the right recording; for a miss, y = really not on
Spotify (open the search link). Both files hold catalog rows and are git-ignored.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector.spotify_gold import export_gold
from export_match_gold import _client  # same prod / local client


def main(argv: list[str] | None = None) -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", help="any Postgres instead of production")
    parser.add_argument(
        "--per-tier", type=int, default=50, help="tracks to sample per tier and of the misses"
    )
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    records = export_gold(_client(args.database_url), args.per_tier)

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    gold = args.out_dir / f"spotify_gold_{stamp}.jsonl"
    gold.write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in records),
        encoding="utf-8",
    )
    labels = args.out_dir / f"spotify_gold_{stamp}_labels.csv"
    with labels.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["track_id", "kind", "tier", "query", "candidate", "url", "label"])
        for r in records:
            if r["kind"] == "match":
                writer.writerow(
                    [
                        r["track_id"],
                        "match",
                        r["tier"],
                        f"{r['artist']} — {r['title']}",
                        f"{r['spotify_artists']} — {r['spotify_title']}",
                        r["spotify_url"],
                        "",
                    ]
                )
            elif r["kind"] == "not_found":
                writer.writerow(
                    [
                        r["track_id"],
                        "not_found",
                        "",
                        f"{r['artist']} — {r['title']}",
                        "",
                        r["search_url"],
                        "",
                    ]
                )

    print(
        f"{len(records) - 1} tracks -> {gold}\nLabel {labels} (y/n), then run\n"
        f"  PYTHONPATH=src .venv/bin/python scripts/eval_spotify_match.py {gold} --labels {labels}"
    )
    return gold, labels


if __name__ == "__main__":
    main()
