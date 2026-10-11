#!/usr/bin/env python3
"""DORA delivery metrics from this repository's own history (DORA 2023 definitions).

- Deployment frequency: successful `Deploy` runs on main, per week.
- Lead time for changes: a pull request's first commit -> the end of the first successful
  deploy that started after its merge.
- Change failure rate: failed deploy runs / finished deploy runs (cancelled runs excluded).
- Failed deployment recovery time: the end of the first failed deploy of a streak -> the end
  of the next successful deploy.

Deploy runs come from `gh run list`; merges and first commits from the local first-parent
history of main ("Merge pull request #N"), so run it in a full clone with `gh` logged in.

Usage: scripts/dora.py [--days 90] [--ref origin/main]
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class Deploy:
    started: datetime
    finished: datetime
    ok: bool


@dataclass(frozen=True)
class Change:
    first_commit: datetime
    merged: datetime


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def parse_deploys(raw: list[dict[str, Any]], since: datetime) -> list[Deploy]:
    runs = [
        Deploy(
            started=_ts(r["createdAt"]),
            finished=_ts(r["updatedAt"]),
            ok=r["conclusion"] == "success",
        )
        for r in raw
        if r["conclusion"] in ("success", "failure")
    ]
    return sorted((d for d in runs if d.started >= since), key=lambda d: d.started)


def deploys_per_week(deploys: list[Deploy], days: int) -> float:
    return sum(d.ok for d in deploys) / (days / 7)


def lead_times(changes: list[Change], deploys: list[Deploy]) -> list[timedelta]:
    shipped = sorted((d for d in deploys if d.ok), key=lambda d: d.started)
    out = []
    for change in changes:
        deploy = next((d for d in shipped if d.started >= change.merged), None)
        if deploy is not None:
            out.append(deploy.finished - change.first_commit)
    return out


def change_failure_rate(deploys: list[Deploy]) -> float:
    return sum(not d.ok for d in deploys) / len(deploys) if deploys else 0.0


def recovery_times(deploys: list[Deploy]) -> list[timedelta]:
    ordered = sorted(deploys, key=lambda d: d.started)
    out = []
    for i, deploy in enumerate(ordered):
        if deploy.ok or (i and not ordered[i - 1].ok):
            continue  # only the first failure of a streak starts a recovery
        fixed = next((d for d in ordered[i + 1 :] if d.ok), None)
        if fixed is not None:
            out.append(fixed.finished - deploy.finished)
    return out


def _fmt(td: timedelta) -> str:
    hours = td.total_seconds() / 3600
    if hours < 1:
        return f"{round(td.total_seconds() / 60)} min"
    return f"{hours:.1f} h" if hours < 48 else f"{hours / 24:.1f} days"


def summary(
    per_week: float, lead: list[timedelta], cfr: float, recovery: list[timedelta], days: int
) -> str:
    parts = [f"last {days} days: {per_week:.1f} deploys a week"]
    if lead:
        parts.append(f"median lead time {_fmt(statistics.median(lead))}")
    parts.append(f"change failure rate {round(cfr * 100)} %")
    if recovery:
        parts.append(f"median recovery from a failed deploy {_fmt(statistics.median(recovery))}")
    return ", ".join(parts)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def fetch_changes(ref: str, since: datetime) -> list[Change]:
    changes = []
    for line in _git("log", ref, "--first-parent", "--merges", "--format=%H %cI %s").splitlines():
        sha, merged, subject = line.split(" ", 2)
        if not subject.startswith("Merge pull request #") or _ts(merged) < since:
            continue
        firsts = _git("log", "--format=%aI", f"{sha}^1..{sha}^2").split()
        if firsts:
            changes.append(Change(first_commit=min(map(_ts, firsts)), merged=_ts(merged)))
    return changes


def fetch_deploys(since: datetime) -> list[Deploy]:
    raw = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            "deploy.yml",
            "--branch",
            "main",
            "--limit",
            "1000",
            "--json",
            "conclusion,createdAt,updatedAt",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return parse_deploys(json.loads(raw), since)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--ref", default="origin/main")
    ns = parser.parse_args()
    since = datetime.now(UTC) - timedelta(days=ns.days)
    deploys = fetch_deploys(since)
    changes = fetch_changes(ns.ref, since)
    lead = lead_times(changes, deploys)
    print(
        summary(
            deploys_per_week(deploys, ns.days),
            lead,
            change_failure_rate(deploys),
            recovery_times(deploys),
            ns.days,
        )
    )
    print(
        f"({len(deploys)} deploys, {len(changes)} merged pull requests, {len(lead)} of them deployed)"
    )
