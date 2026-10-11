"""Snapshot and restore the `live` alias of the API Lambdas (ADR-0029).

The deploy snapshots the alias versions before `terraform apply`; if the smoke test
fails, `restore` points every alias back to its snapshot version. A function without
the alias (the first deploy that creates it) is not in the snapshot and is left alone.

Usage:
  api_aliases.py snapshot --prefix clouder-prod > aliases.json
  api_aliases.py restore aliases.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Same set as scripts/smoke.py LAMBDA_CHECKS and infra/lambda_aliases.tf.
API_FUNCTIONS = ("collector-api", "curation", "auth-handler", "auth-authorizer", "analytics-api", "telemetry")
ALIAS = "live"


def snapshot(client: Any, functions: list[str]) -> dict[str, str]:
    versions = {}
    for function in functions:
        try:
            versions[function] = client.get_alias(FunctionName=function, Name=ALIAS)["FunctionVersion"]
        except client.exceptions.ResourceNotFoundException:
            continue
    return versions


def restore(client: Any, versions: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """Point each alias back; one failing function never stops the others."""
    changed, errors = [], {}
    for function, version in versions.items():
        try:
            if client.get_alias(FunctionName=function, Name=ALIAS)["FunctionVersion"] != version:
                client.update_alias(FunctionName=function, Name=ALIAS, FunctionVersion=version)
                changed.append(function)
        except Exception as exc:  # throttling, transient API errors: report, keep going
            errors[function] = repr(exc)
    return changed, errors


if __name__ == "__main__":
    import boto3

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--prefix", required=True)
    rest = sub.add_parser("restore")
    rest.add_argument("file")
    ns = parser.parse_args()
    client = boto3.client("lambda")
    if ns.cmd == "snapshot":
        json.dump(snapshot(client, [f"{ns.prefix}-{s}" for s in API_FUNCTIONS]), sys.stdout)
    else:
        changed, errors = restore(client, json.loads(Path(ns.file).read_text()))
        for function in changed:
            print(f"rolled back {function}")
        for function, error in errors.items():
            print(f"FAILED {function}: {error}")
        sys.exit(1 if errors else 0)
