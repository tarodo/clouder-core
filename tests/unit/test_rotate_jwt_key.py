"""scripts/rotate_jwt_key.py writes a fresh key to SSM and never prints it."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rotate_jwt_key.py"


def _load():
    spec = importlib.util.spec_from_file_location("rotate_jwt_key", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeSSM:
    def __init__(self) -> None:
        self.puts: list[dict] = []

    def put_parameter(self, **kw):
        self.puts.append(kw)
        return {"Version": 7}


def test_writes_a_new_secure_key_and_prints_only_the_version(capsys) -> None:
    ssm = FakeSSM()

    _load().main(["--name", "/clouder/auth/jwt_signing_key"], ssm=ssm)

    (put,) = ssm.puts
    assert put["Name"] == "/clouder/auth/jwt_signing_key"
    assert put["Type"] == "SecureString" and put["Overwrite"] is True
    assert len(put["Value"]) >= 64
    out = capsys.readouterr().out
    assert put["Value"] not in out and "7" in out


def test_two_rotations_never_repeat_a_key() -> None:
    ssm = FakeSSM()
    mod = _load()
    mod.main([], ssm=ssm)
    mod.main([], ssm=ssm)
    assert ssm.puts[0]["Value"] != ssm.puts[1]["Value"]
    assert ssm.puts[0]["Name"] == "/clouder/auth/jwt_signing_key"  # the default


def test_writes_in_the_production_region_whatever_the_default(monkeypatch, capsys) -> None:
    # A wrong default region would create a new parameter there and report success.
    import sys
    import types

    regions = []
    fake_boto3 = types.SimpleNamespace(
        client=lambda service, region_name=None: regions.append(region_name) or FakeSSM()
    )
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    _load().main([])

    assert regions == ["us-east-1"]
    assert "us-east-1" in capsys.readouterr().out
