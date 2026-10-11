#!/usr/bin/env python3
"""Delete one CLOUDER user from every store (docs/privacy.md).

Aurora rows in one transaction (tables found from the catalog), every version
of the user's playlist covers in the raw bucket, a tombstone in the lake, and
the user's rows in the Iceberg silver/gold tables. Always prints the dry run
first and asks for the user id again before deleting. Every step is
idempotent: after a partial failure, run it again.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/delete_user.py --user-id <uuid> --dry-run
    PYTHONPATH=src .venv/bin/python scripts/delete_user.py --user-id <uuid>

Needs AURORA_CLUSTER_ARN, AURORA_SECRET_ARN and RAW_BUCKET_NAME (or the flags).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from collector.user_deletion import delete_covers, delete_user, purge_lake

REGION = "us-east-1"


def require(cli_value: str | None, env: str, flag: str) -> str:
    value = (cli_value or os.environ.get(env) or "").strip()
    if not value:
        print(f"{env} is not set (or pass {flag}); refusing to guess", file=sys.stderr)
        raise SystemExit(2)
    return value


def _data_api(cluster_arn: str, secret_arn: str, database: str) -> Any:
    from collector.data_api import create_default_data_api_client
    from collector.data_api_retry import wake_database

    client = create_default_data_api_client(
        resource_arn=cluster_arn, secret_arn=secret_arn, database=database
    )
    wake_database(client)
    return client


def _clients() -> tuple[Any, Any]:
    import boto3

    return boto3.client("s3", region_name=REGION), boto3.client("athena", region_name=REGION)


def _print_counts(title: str, counts: dict[str, int]) -> None:
    print(title)
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")
    if not counts:
        print("  nothing (no such user in Aurora)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete one user from every store")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--dry-run", action="store_true", help="report what would go, change nothing")
    parser.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    parser.add_argument("--cluster-arn")
    parser.add_argument("--secret-arn")
    parser.add_argument("--database", default="clouder")
    parser.add_argument("--raw-bucket")
    parser.add_argument("--lake-bucket",
                        default=os.environ.get("ANALYTICS_LAKE_BUCKET", "clouder-prod-analytics-lake"))
    parser.add_argument("--workgroup", default=os.environ.get("ATHENA_WORKGROUP", "beatport-prod-analytics"))
    args = parser.parse_args(argv)

    try:
        user_id = str(uuid.UUID(args.user_id))
    except ValueError:
        print(f"--user-id must be a UUID, got {args.user_id!r}", file=sys.stderr)
        return 2
    cluster_arn = require(args.cluster_arn, "AURORA_CLUSTER_ARN", "--cluster-arn")
    secret_arn = require(args.secret_arn, "AURORA_SECRET_ARN", "--secret-arn")
    raw_bucket = require(args.raw_bucket, "RAW_BUCKET_NAME", "--raw-bucket")

    db = _data_api(cluster_arn, secret_arn, args.database)
    _print_counts("Aurora (dry run, rolled back):", delete_user(db, user_id, dry_run=True))
    print(f"Then: every version under s3://{raw_bucket}/covers/{user_id}/, a tombstone in "
          f"s3://{args.lake_bucket}/governance/deleted_users/, and Athena DELETE from "
          "clouder_silver.events and clouder_gold.fct_play.")
    if args.dry_run:
        return 0
    if not args.yes and input("Type the user id to delete it everywhere: ").strip() != user_id:
        print("aborted, nothing deleted", file=sys.stderr)
        return 1

    _print_counts("Aurora (committed):", delete_user(db, user_id))
    s3, athena = _clients()
    print(f"Cover object versions deleted: {delete_covers(s3, raw_bucket, user_id)}")
    purge_lake(s3, athena, user_id=user_id, lake_bucket=args.lake_bucket,
               workgroup=args.workgroup, now=datetime.now(UTC))
    print("Lake: tombstone written, silver/gold rows deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
