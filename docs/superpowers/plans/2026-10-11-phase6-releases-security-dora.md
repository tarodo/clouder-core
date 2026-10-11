# Phase 6 — Releases, CHANGELOG, SECURITY.md, DORA metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The repo shows it ships: five retro release tags with GitHub Releases, a `CHANGELOG.md` with one line per merged PR, a `SECURITY.md` with a private reporting channel, and DORA delivery metrics computed from its own history in the README.

**Architecture:** Tags sit on the main-branch merge commits that closed each milestone. git-cliff (pinned, run through `uvx`, no new lock entry) builds the changelog from PR merge commits only — the 2 200 branch commits stay in `git log`. `scripts/dora.py` (stdlib) reads deploy runs with one `gh run list` call and PR merges plus first commits from the local first-parent history, and applies the DORA 2023 definitions. Tag pushes trigger no workflow (`deploy.yml` and `dbt-docs.yml` run on `push: branches: [main]` only, `pr.yml` on `pull_request`).

**Tech Stack:** git-cliff 2.14.2, GitHub CLI, Python 3.12 stdlib, pytest.

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-08.ru.md` §0 phase 6; §8 rows "Версионирование", "Changelog"; §9 (EU: `SECURITY.md`; US: DORA, `scripts/dora.py` → "By the numbers"); §11 P1 "Releases", P2 "DORA-метрики", P2 "`SECURITY.md`". Measured 2026-10-11: no tags or releases; 320 first-parent PR merges; Deploy runs on main: 331 success, 31 failure, 1 cancelled; private vulnerability reporting disabled.

## Global Constraints

- Worktree `<repo>` (`clouder-core-p1`), branch `docs/releases-security-dora` from `origin/main` (`8c425edd`).
- Tags (annotated, tagger date = the milestone's merge date) — exactly:

| Tag | Commit (PR) | Title |
|---|---|---|
| `v0.1.0` | `fcd804c1` (#21, 2026-03-14) | Ingest and canonical catalog |
| `v1.0.0` | `cdc50b8b` (#174, 2026-05-31) | Curation app |
| `v1.1.0` | `100b3964` (#216, 2026-07-02) | Analytics lake |
| `v2.0.0` | `165abc83` (#281, 2026-10-08) | Data platform |
| `v2.1.0` | `8c425edd` (#300, 2026-10-11) | Delivery hardening |

- Tags are pushed and Releases created only after the PR merges (Task 4); nothing is pushed to `main` directly.
- No money figures, no personal e-mail in any file (repo is public).
- Commits and PR text via `caveman:caveman-commit`; no attribution lines.

## Review Focus

1. **A PR merged into main but never deployed by a successful run** (deploy failed, next one succeeded) counts its lead time to the first later successful deploy — `test_lead_time_waits_for_the_next_successful_deploy`.
2. **A streak of failed deploys is one failure to recover from**, measured from the first failure — `test_recovery_counts_a_failure_streak_once`.
3. **Cancelled runs and runs outside the window do not count** — `test_window_and_cancelled_runs_are_excluded`.
4. **The changelog cannot silently fall back to every branch commit** (a config regression would add ~1 900 lines) — `test_every_changelog_entry_is_a_pull_request`.
5. **The reporting channel in `SECURITY.md` works** — private vulnerability reporting is enabled on the repo (checked with `gh api`), and the doc links resolve (`test_docs_links`).

---

### Task 1: Tags (local), `cliff.toml`, `CHANGELOG.md`

**Files:** Create `cliff.toml`, `CHANGELOG.md`, `tests/unit/test_changelog.py`; modify `Makefile` (`changelog` target).

- [ ] **Step 1: Failing test** `tests/unit/test_changelog.py`:

```python
"""CHANGELOG.md has one line per merged pull request, newest release first."""

from __future__ import annotations

import re
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"


def _versions() -> list[tuple[int, ...]]:
    return [tuple(map(int, v.split("."))) for v in re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(), re.M)]


def test_releases_are_newest_first() -> None:
    versions = _versions()
    assert versions and versions == sorted(versions, reverse=True)


def test_every_changelog_entry_is_a_pull_request() -> None:
    entries = [line for line in CHANGELOG.read_text().splitlines() if line.startswith("- ")]
    assert entries
    pr_link = re.compile(r"\(\[#\d+\]\(https://github\.com/tarodo/clouder-core/pull/\d+\)\)$")
    assert [e for e in entries if not pr_link.search(e)] == []
```

- [ ] **Step 2 (RED):** run → FAIL (`CHANGELOG.md` missing).
- [ ] **Step 3:** local annotated tags, dated at their merge commits:

```bash
tag() { GIT_COMMITTER_DATE="$(git log -1 --format=%cI "$2")" git tag -a "$1" "$2" -m "$1 — $3"; }
tag v0.1.0 fcd804c1 "Ingest and canonical catalog"
tag v1.0.0 cdc50b8b "Curation app"
tag v1.1.0 100b3964 "Analytics lake"
tag v2.0.0 165abc83 "Data platform"
tag v2.1.0 8c425edd "Delivery hardening"
```

`cliff.toml`:

```toml
# CHANGELOG.md: one line per merged pull request (`make changelog`).
[changelog]
header = """
# Changelog

One line per merged pull request, grouped by release and kind. Generated by
[git-cliff](https://git-cliff.org) from the PR merge commits (`make changelog`);
the commits inside each pull request are in `git log`.\n
"""
body = """
{% if version %}\
## [{{ version | trim_start_matches(pat="v") }}] — {{ timestamp | date(format="%Y-%m-%d") }}
{% else %}\
## Unreleased
{% endif %}\
{% for group, commits in commits | group_by(attribute="group") %}
### {{ group | striptags | trim }}
{% for commit in commits %}
- {% if commit.scope %}**{{ commit.scope }}:** {% endif %}{{ commit.message | upper_first }}\
{% endfor %}
{% endfor %}\n
"""
trim = true

[git]
conventional_commits = true
filter_unconventional = true
commit_preprocessors = [
  # "Merge pull request #N from owner/branch\n\n<PR title>" -> "<PR title> ([#N](…/pull/N))"
  { pattern = '^Merge pull request #([0-9]+) from \S+\s+([^\n]+)[\s\S]*$', replace = "${2} ([#${1}](https://github.com/tarodo/clouder-core/pull/${1}))" },
]
commit_parsers = [
  { field = "merge_commit", pattern = "false", skip = true },  # branch commits stay in git log
  { message = "^feat", group = "<!-- 0 -->Features" },
  { message = "^fix", group = "<!-- 1 -->Fixes" },
  { message = "^perf", group = "<!-- 2 -->Performance" },
  { message = "^refactor", group = "<!-- 3 -->Refactoring" },
  { message = "^test", group = "<!-- 4 -->Tests" },
  { message = "^(ci|build)", group = "<!-- 5 -->Build and CI" },
  { message = "^chore\\(graphify\\)", skip = true },
  { message = "^chore", group = "<!-- 6 -->Maintenance" },
  { message = "^docs", group = "<!-- 7 -->Documentation" },
  { message = ".*", skip = true },
]
tag_pattern = "v[0-9]+\\.[0-9]+\\.[0-9]+"
sort_commits = "oldest"
```

(Local `Merge branch '…'` merges with a conventional subject such as `feat(curation): merge spec-D triage layer` have no PR link; if `test_every_changelog_entry_is_a_pull_request` flags them, skip messages without `([#` in the last parser before the groups — ledger the count.)

`Makefile`:

```make
changelog:       ## CHANGELOG.md from PR merge commits (git-cliff via uvx)
	uvx git-cliff@2.14.2 -o CHANGELOG.md
```

Run `make changelog` (or the `uvx` line) on a branch whose `HEAD` contains `8c425edd`.
- [ ] **Step 4 (GREEN):** test passes; `uvx git-cliff@2.14.2 -o /tmp/x.md && diff -q /tmp/x.md CHANGELOG.md` (deterministic); five release sections, ~270 entries.
- [ ] **Step 5: Commit** (`docs: CHANGELOG from merged pull requests`).

---

### Task 2: `SECURITY.md`

**Files:** Create `SECURITY.md`; modify `README.md` (link it next to the other project docs). Repo setting: private vulnerability reporting.

- [ ] **Step 1 (RED):** `gh api repos/tarodo/clouder-core/private-vulnerability-reporting` → `{"enabled":false}`.
- [ ] **Step 2:** `gh api -X PUT repos/tarodo/clouder-core/private-vulnerability-reporting` → re-read → `{"enabled":true}`.
- [ ] **Step 3:** `SECURITY.md`:

```markdown
# Security policy

## Reporting a vulnerability

Report it privately through GitHub: **Security → Report a vulnerability** on this
repository (private vulnerability reporting). Please do not open a public issue or pull
request for a security problem.

Include what is affected (URL, API route, file), how to reproduce it, and the impact you
expect. A proof of concept against your own account is welcome; do not access other
users' data.

## What to expect

CLOUDER is maintained by one person, so response is best effort:

- acknowledgement within 5 days;
- an assessment, and a fix plan for confirmed issues, within 14 days;
- a fix for a critical issue (auth bypass, data of another user, leaked credentials)
  deployed as soon as it is ready — every merge to `main` deploys to production.

You will be credited in the release notes unless you prefer otherwise.

## Scope

In scope: the code in this repository and the production deployment it describes —
the HTTP API, the web app and the AWS configuration in `infra/`.

Out of scope:

- third-party services CLOUDER calls (Beatport, Spotify, YouTube, AWS) — report to them;
- denial-of-service and load testing, spam, social engineering;
- reports from automated scanners without a demonstrated impact;
- missing hardening that is already listed as a known gap in
  [`docs/security.md`](docs/security.md).

## Supported versions

Only the current `main` branch, which is what runs in production. Releases are milestones
of that branch, not separately maintained versions.

## How CLOUDER is secured

The threat model, IAM boundaries, secret handling and known gaps are in
[`docs/security.md`](docs/security.md).
```

- [ ] **Step 4 (GREEN):** `test_docs_links`, `test_docs_freshness`, `test_repo_hygiene`, `test_readme` green (if `test_docs_links` does not cover root-level files, check the two links by hand).
- [ ] **Step 5: Commit** (`docs: security policy with private reporting`).

---

### Task 3: `scripts/dora.py` + README line

**Files:** Create `scripts/dora.py`, `tests/unit/test_dora.py`; modify `README.md` ("By the numbers"), `docs/ops/deploy.md` (short "Delivery metrics" section), `Makefile` (`dora` target).

**Interfaces:**
- Produces: `Deploy(started: datetime, finished: datetime, ok: bool)`, `Change(first_commit: datetime, merged: datetime)`; `deploys_per_week(deploys, days) -> float`, `lead_times(changes, deploys) -> list[timedelta]`, `change_failure_rate(deploys) -> float`, `recovery_times(deploys) -> list[timedelta]`, `in_window(items, since, attr) -> list`.

- [ ] **Step 1: Failing tests** `tests/unit/test_dora.py` (load the script with `importlib.util.spec_from_file_location`, as `tests/unit/test_dashboard_snapshots.py` does):

```python
"""scripts/dora.py: DORA delivery metrics from deploy runs and PR merges."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dora.py"
spec = importlib.util.spec_from_file_location("dora", SCRIPT)
dora = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dora)

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def deploy(start: float, ok: bool, minutes: float = 5) -> object:
    return dora.Deploy(started=at(start), finished=at(start) + timedelta(minutes=minutes), ok=ok)


def test_deploys_per_week_counts_successes() -> None:
    runs = [deploy(1, True), deploy(2, False), deploy(3, True)]
    assert dora.deploys_per_week(runs, days=14) == 1.0


def test_lead_time_runs_from_first_commit_to_the_deploy_that_ships_it() -> None:
    change = dora.Change(first_commit=at(0), merged=at(10))
    assert dora.lead_times([change], [deploy(10, True)]) == [timedelta(hours=10, minutes=5)]


def test_lead_time_waits_for_the_next_successful_deploy() -> None:
    change = dora.Change(first_commit=at(0), merged=at(10))
    runs = [deploy(10, False), deploy(12, True)]
    assert dora.lead_times([change], runs) == [timedelta(hours=12, minutes=5)]


def test_a_change_not_yet_deployed_has_no_lead_time() -> None:
    assert dora.lead_times([dora.Change(first_commit=at(0), merged=at(10))], [deploy(5, True)]) == []


def test_change_failure_rate() -> None:
    assert dora.change_failure_rate([deploy(1, True), deploy(2, False), deploy(3, True), deploy(4, True)]) == 0.25
    assert dora.change_failure_rate([]) == 0.0


def test_recovery_counts_a_failure_streak_once() -> None:
    runs = [deploy(1, False), deploy(2, False), deploy(3, True)]
    # From the end of the first failure (1h05) to the end of the next success (3h05).
    assert dora.recovery_times(runs) == [timedelta(hours=2)]


def test_a_failure_not_yet_recovered_has_no_recovery_time() -> None:
    assert dora.recovery_times([deploy(1, True), deploy(2, False)]) == []


def test_window_and_cancelled_runs_are_excluded() -> None:
    raw = [
        {"conclusion": "success", "createdAt": "2026-09-01T00:00:00Z", "updatedAt": "2026-09-01T00:05:00Z"},
        {"conclusion": "cancelled", "createdAt": "2026-10-02T00:00:00Z", "updatedAt": "2026-10-02T00:01:00Z"},
        {"conclusion": "failure", "createdAt": "2026-10-03T00:00:00Z", "updatedAt": "2026-10-03T00:04:00Z"},
    ]
    runs = dora.parse_deploys(raw, since=T0)
    assert runs == [dora.Deploy(started=datetime(2026, 10, 3, tzinfo=UTC),
                                finished=datetime(2026, 10, 3, 0, 4, tzinfo=UTC), ok=False)]


def test_summary_line() -> None:
    line = dora.summary(per_week=4.25, lead=[timedelta(hours=2)], cfr=0.081, recovery=[timedelta(minutes=25)], days=90)
    assert line == ("last 90 days: 4.2 deploys a week, median lead time 2.0 h, "
                    "change failure rate 8 %, median recovery from a failed deploy 25 min")
```

- [ ] **Step 2 (RED):** → FAIL (script missing).
- [ ] **Step 3:** `scripts/dora.py`:

```python
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
        Deploy(started=_ts(r["createdAt"]), finished=_ts(r["updatedAt"]), ok=r["conclusion"] == "success")
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


def summary(per_week: float, lead: list[timedelta], cfr: float, recovery: list[timedelta], days: int) -> str:
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
        ["gh", "run", "list", "--workflow", "deploy.yml", "--branch", "main", "--limit", "1000",
         "--json", "conclusion,createdAt,updatedAt"],
        capture_output=True, text=True, check=True,
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
    print(summary(deploys_per_week(deploys, ns.days), lead, change_failure_rate(deploys),
                  recovery_times(deploys), ns.days))
    print(f"({len(deploys)} deploys, {len(changes)} merged pull requests, {len(lead)} of them deployed)")
```

- [ ] **Step 4 (GREEN):** tests pass; run `python3 scripts/dora.py` in `<repo>` → read the numbers. README "By the numbers": one line, `- Delivery (DORA, [scripts/dora.py](scripts/dora.py), <date>): <summary line>.`; `docs/ops/deploy.md` gets `## Delivery metrics` with the four definitions in one paragraph and the command; `Makefile` `dora:` → `python3 scripts/dora.py`.
- [ ] **Step 5:** full suite green; commit (`feat(scripts): DORA metrics from deploy history`).

---

### Task 4: PR, review, merge, tags, Releases, verify

- [ ] Plan commit, graphify, push, PR; fresh review; one fix pass.
- [ ] Checks green → merge (merge commit) → Deploy green (smoke 9/9).
- [ ] `git push origin v0.1.0 v1.0.0 v1.1.0 v2.0.0 v2.1.0` (tag pushes start no workflow — confirm with `gh run list --limit 3`).
- [ ] For each tag: notes = one summary sentence + `uvx git-cliff@2.14.2 <prev>..<tag> --strip all` (first tag: `$(git rev-list --max-parents=0 HEAD)..v0.1.0`); `gh release create <tag> --title "<tag> — <title>" --notes-file <file> --latest=false`, and `--latest` for `v2.1.0`. Summaries:
  - v0.1.0: Beatport weekly ingest into an S3 raw zone, canonicalization into Aurora through the RDS Data API, ISRC search on Spotify.
  - v1.0.0: The curation app — triage, categories, tags, in-page players, playlists published to Spotify and YouTube Music, label and artist enrichment.
  - v1.1.0: YouTube comments per track; telemetry through Firehose into an S3 lake, with Athena-backed listening and funnel cards.
  - v2.0.0: Nightly data-quality SLOs, a raw data contract with quarantine, replayable backfills, an Iceberg silver/gold lakehouse built by dbt, scheduled auto-ingest, CI gates and least-privilege IAM.
  - v2.1.0: A read-only role for PR plans, versioned API Lambdas with smoke-gated rollback, a freshness gate on the nightly build, the API handler and repository split, stricter typing and lint.
- [ ] Verify: `gh release list` shows 5 with `v2.1.0` Latest; the repo page shows the Releases block; `gh api …/private-vulnerability-reporting` → enabled.
- [ ] §0 board: phase 6 done.
