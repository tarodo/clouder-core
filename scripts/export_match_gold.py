#!/usr/bin/env python3
"""Export the YT Music matching gold set (read-only) for scripts/eval_vendor_match.py.

  PYTHONPATH=src .venv/bin/python scripts/export_match_gold.py                 # prod, RDS Data API
  PYTHONPATH=src .venv/bin/python scripts/export_match_gold.py --database-url postgresql://...

Writes match_gold_<ts>.jsonl (review-queue accepts, a sample of auto-accepted fuzzy
matches, a duplicate-artist summary) and match_gold_<ts>_labels.csv — fill its `label`
column with y/n to measure precision above the current threshold. Both files hold
catalog rows and are git-ignored.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from collector.vendor_match.gold import (  # noqa: E402
    auto_population,
    auto_sample,
    duplicate_artists,
    review_accepts,
)


def _client(database_url: str | None) -> Any:
    if database_url:
        sys.path.insert(0, str(ROOT / "tests" / "db"))
        from pg_data_api import PgDataAPIClient

        return PgDataAPIClient(database_url)
    import boto3

    from collector.data_api import create_default_data_api_client

    cluster = boto3.client("rds").describe_db_clusters(
        DBClusterIdentifier=os.environ.get("CLUSTER", "clouder-prod-aurora")
    )["DBClusters"][0]
    return create_default_data_api_client(
        resource_arn=cluster["DBClusterArn"],
        secret_arn=cluster["MasterUserSecret"]["SecretArn"],
        database=cluster["DatabaseName"],
    )


def main(argv: list[str] | None = None) -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", help="any Postgres instead of production")
    parser.add_argument("--sample", type=int, default=100, help="auto-accepted matches to sample")
    parser.add_argument("--out-dir", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    client = _client(args.database_url)
    reviews = review_accepts(client)
    sample = auto_sample(client, args.sample)
    population = auto_population(client)
    duplicates = duplicate_artists(client)

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M")
    gold = args.out_dir / f"match_gold_{stamp}.jsonl"
    with gold.open("w", encoding="utf-8") as f:
        for record in [*reviews, *sample, population, duplicates]:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    labels = args.out_dir / f"match_gold_{stamp}_labels.csv"
    with labels.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["track_id", "query", "candidate", "url", "label"])
        for record in sample:
            cand = record["candidate"]
            names = ", ".join(
                a.get("name", "") for a in cand.get("artists") or [] if isinstance(a, dict)
            )
            writer.writerow([
                record["track_id"],
                f"{record['artist']} — {record['title']}",
                f"{names} — {cand.get('title', '')}",
                f"https://music.youtube.com/watch?v={cand.get('videoId', '')}",
                "",
            ])

    print(
        f"{len(reviews)} review accepts, {len(sample)} auto-accepted matches -> {gold}\n"
        f"Optional: label the sample (y/n) in {labels}, then run\n"
        f"  PYTHONPATH=src .venv/bin/python scripts/eval_vendor_match.py {gold} --labels {labels}"
    )
    return gold, labels


if __name__ == "__main__":
    main()
