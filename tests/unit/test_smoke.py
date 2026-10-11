"""The post-deploy smoke test is harmless and reports every failure (phase 3, ADR-0029)."""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke.py"
HANDLERS = {
    "collector-api": "collector.handler",
    "curation": "collector.curation_handler",
    "auth-handler": "collector.auth_handler",
    "auth-authorizer": "collector.auth_authorizer",
    "analytics-api": "collector.analytics_handler",
    "telemetry": "collector.telemetry_handler",
}


def _smoke():
    spec = importlib.util.spec_from_file_location("smoke", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("suffix", sorted(HANDLERS))
def test_each_smoke_event_is_answered_before_any_io(suffix: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import boto3

    def no_aws(*_a: Any, **_k: Any) -> Any:
        raise AssertionError(f"smoke event for {suffix} reached AWS")

    monkeypatch.setattr(boto3, "client", no_aws)
    monkeypatch.setattr(boto3, "resource", no_aws)
    smoke = _smoke()
    event, expected = smoke.LAMBDA_CHECKS[suffix]
    payload = importlib.import_module(HANDLERS[suffix]).lambda_handler(json.loads(json.dumps(event)), None)
    assert smoke.check_lambda(payload, expected) is None


def test_every_api_function_has_a_smoke_check() -> None:
    assert set(_smoke().LAMBDA_CHECKS) == set(HANDLERS)


def test_check_lambda_flags_wrong_status_and_function_errors() -> None:
    smoke = _smoke()
    assert smoke.check_lambda({"statusCode": 500}, 404)
    assert smoke.check_lambda({"errorMessage": "boom", "errorType": "ImportError"}, 404)
    assert smoke.check_lambda({"isAuthorized": True}, {"isAuthorized": False})
    assert smoke.check_lambda({"statusCode": 404}, 404) is None


def test_check_http_flags_status_redirect_and_body() -> None:
    smoke = _smoke()
    assert smoke.check_http(302, {"Location": "https://accounts.spotify.com/authorize?x"}, "",
                            {"status": 302, "location_host": "accounts.spotify.com"}) is None
    assert smoke.check_http(302, {"Location": "https://evil.example/"}, "",
                            {"status": 302, "location_host": "accounts.spotify.com"})
    assert smoke.check_http(200, {}, "<html></html>", {"status": 200, "contains": '<div id="root">'})
    assert smoke.check_http(503, {}, "", {"status": 401})


def test_main_returns_one_and_names_each_failure(capsys: pytest.CaptureFixture[str]) -> None:
    smoke = _smoke()

    def invoke(function: str, _event: dict) -> dict:
        suffix = function.removeprefix("clouder-prod-")
        if suffix == "curation":
            return {"statusCode": 500}
        expected = smoke.LAMBDA_CHECKS[suffix][1]
        return expected if isinstance(expected, dict) else {"statusCode": expected}

    def fetch(url: str) -> tuple[int, dict, str]:
        if url.endswith("/auth/login"):
            return 302, {"Location": "https://accounts.spotify.com/authorize"}, ""
        if url.endswith("/styles"):
            return 401, {}, ""
        return 200, {}, '<div id="root"></div>'

    code = smoke.main("https://api.example", "https://site.example", "clouder-prod", invoke, fetch)
    out = capsys.readouterr().out
    assert code == 1
    assert [line for line in out.splitlines() if line.startswith("FAIL")] == [
        line for line in out.splitlines() if "clouder-prod-curation" in line and line.startswith("FAIL")
    ]


def test_main_returns_zero_when_everything_answers() -> None:
    smoke = _smoke()

    def invoke(function: str, _event: dict) -> dict:
        expected = smoke.LAMBDA_CHECKS[function.removeprefix("clouder-prod-")][1]
        return expected if isinstance(expected, dict) else {"statusCode": expected}

    def fetch(url: str) -> tuple[int, dict, str]:
        if url.endswith("/auth/login"):
            return 302, {"Location": "https://accounts.spotify.com/authorize"}, ""
        return (401, {}, "") if url.endswith("/styles") else (200, {}, '<div id="root"></div>')

    assert smoke.main("https://api.example", "https://site.example", "clouder-prod", invoke, fetch) == 0


def test_fetch_retries_a_network_error_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error
    import urllib.request

    smoke = _smoke()
    calls = {"n": 0}

    class Resp:
        status = 200
        headers: ClassVar[dict[str, str]] = {}

        def read(self) -> bytes:
            return b"ok"

        def __enter__(self) -> Resp:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    class Opener:
        def open(self, url: str, timeout: int) -> Resp:
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.URLError("connection reset")
            return Resp()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_a: Opener())
    monkeypatch.setattr(smoke.time, "sleep", lambda _s: None)
    assert smoke._fetch("https://site.example/") == (200, {}, "ok")
    assert calls["n"] == 2
