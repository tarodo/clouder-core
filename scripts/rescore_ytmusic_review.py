"""Close open YT Music reviews the version rule accepts, from stored candidates.

No YouTube request is made. The dry run (default) reads production through the
agent's read-only role, so it cannot change anything:

    PYTHONPATH=src .venv/bin/python scripts/rescore_ytmusic_review.py --csv /tmp/rescore.csv

`--apply` connects as the master user and, per review, links the first stored
candidate the rule accepts (best first) as `fuzzy_version` and resolves the
review; a review no candidate of which names our artist is closed as not on
YouTube, unless it waits for its second chance (docs/data/entity-resolution.md).
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

from collector.vendor_match.rescore import (  # noqa: E402
    accept,
    artist_absent,
    close_absent,
    decide,
    open_reviews,
)

PAGE = 50  # full candidate payloads: about 10 KB a review, under the 1 MB cap
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
        writer.writerow(["action", "track_id", "score", "ours", "candidate", "url"])
    after, scanned, accepted, closed = "", 0, 0, 0
    try:
        while rows := open_reviews(client, after=after, limit=PAGE):
            after = rows[-1]["review_id"]
            scanned += len(rows)
            ok, absent = [], []
            for r in rows:
                if (chosen := decide(r)) is not None:
                    r["candidate"] = chosen
                    ok.append(r)
                elif artist_absent(r):
                    absent.append(r)
            accepted += len(ok)
            closed += len(absent)
            if writer:
                for action, group in (("accept", ok), ("not_on_youtube", absent)):
                    for r in group:
                        r.setdefault("candidate", r["candidates"][0])
                        ours, theirs = _line(r)
                        url = (
                            f"https://music.youtube.com/watch?v={r['candidate']['ref']['videoId']}"
                        )
                        writer.writerow(
                            [action, r["track_id"], r["candidate"]["score"], ours, theirs, url]
                        )
            if args.apply:
                accept(client, ok, now)
                close_absent(client, absent, now)
    finally:
        if out:
            out.close()
    summary = {
        "open_reviews": scanned,
        "accepted": accepted,
        "closed": closed,
        "applied": int(args.apply),
    }
    print(summary)
    return summary


if __name__ == "__main__":
    main()
