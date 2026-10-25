"""scripts/delete_user.py: dry run first, typed confirmation, then every store."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "delete_user.py"
UID = "3f2b8c1e-0000-4000-8000-000000000001"
HEX = "3f2b8c1e000040008000000000000001"  # users.id: auth mints uuid4().hex
ARGS = ["--user-id", UID, "--cluster-arn", "c", "--secret-arn", "s", "--raw-bucket", "raw"]


@pytest.fixture
def script(monkeypatch):
    spec = importlib.util.spec_from_file_location("delete_user_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls: list[tuple] = []
    monkeypatch.setattr(mod, "_data_api", lambda *a: "db")
    monkeypatch.setattr(mod, "_clients", lambda: ("s3", "athena"))
    monkeypatch.setattr(
        mod,
        "delete_user",
        lambda db, uid, dry_run=False: calls.append(("aurora", dry_run, uid)) or {"users": 1},
    )
    monkeypatch.setattr(
        mod, "delete_covers", lambda s3, bucket, uid: calls.append(("covers", bucket)) or 2
    )
    monkeypatch.setattr(
        mod, "delete_models", lambda s3, bucket, uid: calls.append(("models", bucket)) or 3
    )
    monkeypatch.setattr(
        mod, "purge_lake", lambda s3, athena, **kw: calls.append(("lake", kw["lake_bucket"]))
    )
    mod.calls = calls
    return mod


def test_dry_run_changes_nothing(script) -> None:
    assert script.main([*ARGS, "--dry-run"]) == 0
    assert script.calls == [("aurora", True, HEX)]  # the stored spelling, whichever was typed


def test_wrong_confirmation_aborts_before_any_delete(script, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "someone-else")
    assert script.main(ARGS) == 1
    assert script.calls == [("aurora", True, HEX)]


def test_confirmed_run_deletes_aurora_covers_models_then_lake(script, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: HEX)
    assert script.main([*ARGS, "--lake-bucket", "lake", "--features-bucket", "features"]) == 0
    assert script.calls == [
        ("aurora", True, HEX),
        ("aurora", False, HEX),
        ("covers", "raw"),
        ("models", "features"),
        ("lake", "lake"),
    ]


def test_rejects_a_user_id_that_is_not_a_uuid(script) -> None:
    assert (
        script.main(
            [
                "--user-id",
                "../etc",
                "--cluster-arn",
                "c",
                "--secret-arn",
                "s",
                "--raw-bucket",
                "raw",
                "--dry-run",
            ]
        )
        == 2
    )
    assert script.calls == []
