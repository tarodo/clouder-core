"""Snapshot and restore of the API functions' live alias (phase 3, ADR-0029)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _NotFound(Exception):
    pass


class FakeLambda:
    class exceptions:  # noqa: N801 - mirrors boto3's client.exceptions
        ResourceNotFoundException = _NotFound

    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = dict(aliases)
        self.updates: list[tuple[str, str]] = []

    def get_alias(self, FunctionName: str, Name: str) -> dict:  # noqa: N803 - boto3 casing
        assert Name == "live"
        if FunctionName not in self.aliases:
            raise _NotFound(FunctionName)
        return {"FunctionVersion": self.aliases[FunctionName]}

    def update_alias(self, FunctionName: str, Name: str, FunctionVersion: str) -> dict:  # noqa: N803
        self.aliases[FunctionName] = FunctionVersion
        self.updates.append((FunctionName, FunctionVersion))
        return {}


def test_snapshot_skips_functions_without_the_alias() -> None:
    aa = _load("api_aliases")
    client = FakeLambda({"p-collector-api": "7", "p-curation": "3"})
    assert aa.snapshot(client, ["p-collector-api", "p-curation", "p-telemetry"]) == {"p-collector-api": "7", "p-curation": "3"}


def test_restore_moves_only_aliases_that_changed() -> None:
    aa = _load("api_aliases")
    client = FakeLambda({"p-collector-api": "8", "p-curation": "3"})
    assert aa.restore(client, {"p-collector-api": "7", "p-curation": "3"}) == (["p-collector-api"], {})
    assert client.updates == [("p-collector-api", "7")]


def test_restoring_an_empty_snapshot_does_nothing() -> None:
    aa = _load("api_aliases")
    client = FakeLambda({"p-collector-api": "8"})
    assert aa.restore(client, {}) == ([], {}) and client.updates == []


def test_alias_functions_match_the_smoke_checks_and_terraform() -> None:
    aa, smoke = _load("api_aliases"), _load("smoke")
    assert set(aa.API_FUNCTIONS) == set(smoke.LAMBDA_CHECKS)
    tf = (ROOT / "infra" / "lambda_aliases.tf").read_text()
    assert tf.count("= aws_lambda_function.") == len(aa.API_FUNCTIONS)


def test_restore_keeps_going_after_one_function_fails() -> None:
    # A throttle on one alias must not leave the others on the bad version.
    aa = _load("api_aliases")
    client = FakeLambda({"p-collector-api": "8", "p-curation": "4"})
    real_update = client.update_alias

    def flaky(FunctionName: str, Name: str, FunctionVersion: str) -> dict:  # noqa: N803
        if FunctionName == "p-collector-api":
            raise RuntimeError("TooManyRequestsException")
        return real_update(FunctionName=FunctionName, Name=Name, FunctionVersion=FunctionVersion)

    client.update_alias = flaky
    changed, errors = aa.restore(client, {"p-collector-api": "7", "p-curation": "3"})
    assert changed == ["p-curation"] and list(errors) == ["p-collector-api"]
