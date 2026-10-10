"""Python deps are declared in .in files and locked in the .txt files CI and packaging install."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def declared(path: Path) -> set[str]:
    names = set()
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.add(NAME.match(line).group(1).lower().replace("_", "-"))
    return names


def pinned(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;]+)", line)
        if m:
            pins[m.group(1).lower().replace("_", "-")] = m.group(2)
    return pins


def test_every_declared_dependency_is_pinned() -> None:
    for name in ("requirements-lambda", "requirements-dev"):
        missing = declared(ROOT / f"{name}.in") - set(pinned(ROOT / f"{name}.txt"))
        assert missing == set(), (name, missing)
    assert "-r requirements-lambda.in" in (ROOT / "requirements-dev.in").read_text()
    assert not (ROOT / "src" / "collector" / "requirements.txt").exists()


def test_dependabot_watches_every_ecosystem() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    seen = {(u["package-ecosystem"], u["directory"]) for u in config["updates"]}
    assert seen >= {("pip", "/"), ("npm", "/frontend"), ("github-actions", "/"), ("terraform", "/infra")}


def test_ci_checks_locks_and_audits() -> None:
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "pr.yml").read_text())["jobs"]
    run = "\n".join(s.get("run", "") for s in jobs["deps"]["steps"])
    assert "uv pip compile" in run and "git diff --exit-code" in run
    assert "pip-audit" in run and "pnpm audit --prod --audit-level high" in run


def test_shared_pins_are_equal() -> None:
    # Dependabot may bump one lock and not the other; CI must test what ships.
    lam, dev = pinned(ROOT / "requirements-lambda.txt"), pinned(ROOT / "requirements-dev.txt")
    assert {n: (v, dev[n]) for n, v in lam.items() if n in dev and dev[n] != v} == {}
    assert set(lam) <= set(dev)


def test_ci_uses_a_pinned_uv_and_fails_on_test_failures() -> None:
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "pr.yml").read_text())["jobs"]
    setup = next(s for s in jobs["deps"]["steps"] if "setup-uv" in s.get("uses", ""))
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(setup["with"]["version"]))
    # `pytest … | tee` returns tee's status unless pipefail is on.
    run = next(s["run"] for s in jobs["tests"]["steps"] if "pytest" in s.get("run", ""))
    assert run.lstrip().startswith("set -o pipefail")


def test_pip_version_updates_go_through_uv_not_dependabot() -> None:
    # Dependabot's compiled lock differs from `uv pip compile --universal`, so its pip
    # PRs always fail the lock-drift check; security updates still open.
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    pip_root = next(u for u in config["updates"] if (u["package-ecosystem"], u["directory"]) == ("pip", "/"))
    assert pip_root["open-pull-requests-limit"] == 0
    assert "upgrade:" in (ROOT / "Makefile").read_text()
