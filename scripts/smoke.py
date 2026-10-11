"""Post-deploy smoke test (ADR-0029): no writes, no Aurora.

Each API Lambda is invoked through its `live` alias with a request it answers before any
I/O (an unknown route, an empty telemetry body, a missing token), and three public URLs
are fetched. Prints one line per check; exits 1 if any failed.

Usage: smoke.py --api URL --site URL --prefix clouder-prod
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

Invoke = Callable[[str, dict], dict]
Fetch = Callable[[str], tuple[int, dict, str]]


def _api_event(route_key: str, body: str = "") -> dict:
    method, path = route_key.split(" ", 1)
    return {
        "version": "2.0",
        "routeKey": route_key,
        "rawPath": path,
        "headers": {},
        "requestContext": {"http": {"method": method, "path": path}, "requestId": "smoke"},
        "body": body,
        "isBase64Encoded": False,
    }


# function suffix -> (event, expected statusCode, or the exact authorizer answer)
LAMBDA_CHECKS: dict[str, tuple[dict, Any]] = {
    "collector-api": (_api_event("GET /__smoke"), 404),
    "curation": (_api_event("GET /__smoke"), 401),  # no authorizer user: rejected before routing
    "auth-handler": (_api_event("GET /__smoke"), 404),
    "analytics-api": (_api_event("GET /v1/analytics/__smoke"), 404),
    "telemetry": (_api_event("POST /v1/telemetry"), 400),
    "auth-authorizer": ({"type": "REQUEST", "headers": {}, "routeArn": "smoke"}, {"isAuthorized": False}),
}

HTTP_CHECKS: list[tuple[str, str, dict]] = [
    ("api", "/auth/login", {"status": 302, "location_host": "accounts.spotify.com"}),
    ("api", "/styles", {"status": 401}),
    ("site", "/", {"status": 200, "contains": '<div id="root">'}),
]


def check_lambda(payload: dict, expected: Any) -> str | None:
    if "errorMessage" in payload:
        return f"function error {payload.get('errorType')}: {payload['errorMessage']}"
    if isinstance(expected, dict):
        return None if payload == expected else f"expected {expected}, got {payload}"
    status = payload.get("statusCode")
    return None if status == expected else f"expected status {expected}, got {status}"


def check_http(status: int, headers: dict, body: str, expect: dict) -> str | None:
    if status != expect["status"]:
        return f"expected HTTP {expect['status']}, got {status}"
    if "location_host" in expect:
        host = urlparse({k.lower(): v for k, v in headers.items()}.get("location", "")).hostname
        if host != expect["location_host"]:
            return f"expected a redirect to {expect['location_host']}, got {host}"
    if "contains" in expect and expect["contains"] not in body:
        return f"body lacks {expect['contains']!r}"
    return None


def main(api_url: str, site_url: str, prefix: str, invoke: Invoke, fetch: Fetch) -> int:
    failures = 0
    for suffix, (event, expected) in LAMBDA_CHECKS.items():
        function = f"{prefix}-{suffix}"
        problem = check_lambda(invoke(function, event), expected)
        failures += problem is not None
        print(f"{'FAIL' if problem else 'ok  '} lambda {function}" + (f": {problem}" if problem else ""))
    bases = {"api": api_url.rstrip("/"), "site": site_url.rstrip("/")}
    for base, path, expect in HTTP_CHECKS:
        url = bases[base] + path
        problem = check_http(*fetch(url), expect)
        failures += problem is not None
        print(f"{'FAIL' if problem else 'ok  '} GET {url}" + (f": {problem}" if problem else ""))
    return 1 if failures else 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _fetch(url: str) -> tuple[int, dict, str]:
    opener = urllib.request.build_opener(_NoRedirect)
    for attempt in range(2):  # one retry: CloudFront or API Gateway may blip right after a deploy
        try:
            with opener.open(url, timeout=20) as resp:
                return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            if err.code >= 500 and attempt == 0:
                continue
            return err.code, dict(err.headers), err.read().decode("utf-8", "replace")
    raise AssertionError("unreachable")


def _invoke(client: Any) -> Invoke:
    def invoke(function: str, event: dict) -> dict:
        resp = client.invoke(FunctionName=function, Qualifier="live", Payload=json.dumps(event).encode())
        payload = json.loads(resp["Payload"].read() or b"{}")
        if resp.get("FunctionError") and "errorMessage" not in payload:
            payload = {"errorMessage": str(payload), "errorType": resp["FunctionError"]}
        return payload

    return invoke


if __name__ == "__main__":
    import boto3

    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--api", required=True)
    args.add_argument("--site", required=True)
    args.add_argument("--prefix", required=True)
    ns = args.parse_args()
    sys.exit(main(ns.api, ns.site, ns.prefix, _invoke(boto3.client("lambda")), _fetch))
