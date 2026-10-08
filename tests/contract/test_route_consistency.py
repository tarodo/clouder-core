"""A route exists in all three places or in none: Terraform, OpenAPI, handler code.

A route missing from API Gateway answers {"message":"Not Found"} in prod while every
unit test passes — this pins the three lists together.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY = re.compile(r'"((?:GET|POST|PUT|PATCH|DELETE) /[^"]*)"')


def terraform_routes() -> set[str]:
    return {k for p in (ROOT / "infra").glob("*.tf") for k in KEY.findall(p.read_text())}


def openapi_routes() -> set[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_openapi

    return {f"{r['method'].upper()} {r['path']}" for r in generate_openapi.ROUTES}


def test_route_keys_agree() -> None:
    tf, spec = terraform_routes(), openapi_routes()
    assert len(tf) >= 100
    assert sorted(tf - spec) == [] and sorted(spec - tf) == []


# Single-purpose Lambdas that dispatch on the path, not on the full route key:
# route → (handler module, literal the module must contain).
PATH_DISPATCHED = {
    "GET /v1/analytics/listening": ("analytics_handler.py", '"listening"'),
    "GET /v1/analytics/time-per-track": ("analytics_handler.py", '"time-per-track"'),
    "POST /v1/telemetry": ("telemetry_handler.py", '"telemetry"'),
}


def test_every_route_is_handled_in_code() -> None:
    src = ROOT / "src" / "collector"
    code = "\n".join(p.read_text() for p in src.rglob("*.py"))
    unhandled = []
    for key in sorted(terraform_routes()):
        if key in PATH_DISPATCHED:
            module, literal = PATH_DISPATCHED[key]
            if literal not in (src / module).read_text():
                unhandled.append(key)
        elif f'"{key}"' not in code:
            unhandled.append(key)
    assert unhandled == []
