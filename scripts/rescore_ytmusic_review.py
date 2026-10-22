"""Close open YT Music reviews the version rule accepts, from stored candidates.

No YouTube request is made. The dry run (default) reads production through the
agent's read-only role, so it cannot change anything:

    PYTHONPATH=src .venv/bin/python scripts/rescore_ytmusic_review.py --csv /tmp/rescore.csv

`--apply` connects as the master user and, per accepted review, links the track
as `fuzzy_version` and resolves the review (docs/data/entity-resolution.md).
The CSV lists the accepted reviews for a look before applying; it holds catalog
rows, so keep it out of the repository.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from collector.vendor_match.rescore import accept, decide, open_reviews  # noqa: E402

PAGE = 200
AGENT_SECRET = "clouder/agent/aurora-readonly"


def _client(database_url: str | None, *, apply: bool) -> Any:
    if database_url:
        sys.path.insert(0, str(ROOT / "tests" / "db"))
        from pg_data_api import PgDataAPIClient

        return PgDataAPIClient(database_url)
    import boto3

    from collector.data_api import create_default_data_api_client

    cluster = boto3.client("rds").describe_db_clusters(
        DBClusterIdentifier=os.environ.get("CLUSTER", "clouder-prod-aurora")
    )["DBClusters"][0]
    secret = (
        cluster["MasterUserSecret"]["SecretArn"]
        if apply
        else boto3.client("secretsmanager").describe_secret(SecretId=AGENT_SECRET)["ARN"]
    )
    return create_default_data_api_client(
        resource_arn=cluster["DBClusterArn"], secret_arn=secret, database=cluster["DatabaseName"]
    )


def _mmss(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = round(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _line(row: dict[str, Any]) -> tuple[str, str]:
    ref = row["candidate"]["ref"]
    mix = f" ({row['mix_name']})" if row.get("mix_name") else ""
    length = row["length_ms"] / 1000 if row.get("length_ms") else None
    ours = f"{row.get('artists') or ''} — {row['title']}{mix} · {_mmss(length)}"
    theirs_artists = ", ".join(a.get("name", "") for a in ref.get("artists") or [])
    theirs = f"{theirs_artists} — {ref.get('title', '')} · {_mmss(ref.get('duration_seconds'))}"
    return ours, theirs


def main(argv: list[str] | None = None) -> dict[str, int]:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", help="any Postgres instead of production")
    parser.add_argument("--apply", action="store_true", help="write; default is a dry run")
    parser.add_argument("--csv", type=Path, help="list the accepted reviews here")
    args = parser.parse_args(argv)

    client = _client(args.database_url, apply=args.apply)
    now = datetime.now(UTC)
    out = args.csv.open("w", newline="", encoding="utf-8") if args.csv else None
    writer = csv.writer(out) if out else None
    if writer:
        writer.writerow(["track_id", "score", "ours", "candidate", "url"])
    after, scanned, accepted = "", 0, 0
    try:
        while rows := open_reviews(client, after=after, limit=PAGE):
            after = rows[-1]["review_id"]
            scanned += len(rows)
            ok = [r for r in rows if decide(r)]
            accepted += len(ok)
            if writer:
                for r in ok:
                    ours, theirs = _line(r)
                    url = f"https://music.youtube.com/watch?v={r['candidate']['ref']['videoId']}"
                    writer.writerow([r["track_id"], r["candidate"]["score"], ours, theirs, url])
            if args.apply:
                accept(client, ok, now)
    finally:
        if out:
            out.close()
    summary = {"open_reviews": scanned, "accepted": accepted, "applied": int(args.apply)}
    print(summary)
    return summary


if __name__ == "__main__":
    main()
