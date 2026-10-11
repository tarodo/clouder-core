"""collector-api: the router serves exactly the gateway routes; routes live in collector/api."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _gateway_routes() -> set[str]:
    keys = set()
    route = re.compile(r'resource "aws_apigatewayv2_route" "[^"]+" \{(.*?)\n\}', re.S)
    for tf in (ROOT / "infra").glob("*.tf"):
        for body in route.findall(tf.read_text()):
            if "collector_lambda" in body:
                keys.add(re.search(r'route_key\s*=\s*"([^"]+)"', body).group(1))
    return keys


def test_route_table_serves_exactly_the_gateway_routes() -> None:
    from collector.handler import _ROUTE_TABLE

    assert set(_ROUTE_TABLE) - {""} == _gateway_routes()


def test_handler_module_is_a_thin_router() -> None:
    assert len((ROOT / "src/collector/handler.py").read_text().splitlines()) <= 250


def test_routes_call_collaborators_through_deps() -> None:
    # A route that imports a collaborator by name ignores a patch on `deps`.
    from collector.api import deps

    routes = list((ROOT / "src/collector/api").glob("routes_*.py"))
    assert routes, "collector/api/routes_*.py missing"
    for module in routes:
        tree = ast.parse(module.read_text())
        bound = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert not bound & set(deps.__all__), (
            f"{module.name} binds {sorted(bound & set(deps.__all__))}"
        )


def test_enrichment_loads_on_first_use() -> None:
    code = (
        "import json, sys, collector.handler; "
        "print(json.dumps(sorted(m for m in sys.modules "
        "if m.startswith(('collector.label_enrichment', 'collector.artist_enrichment')))))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(ROOT / "src")},
        check=True,
    ).stdout
    assert json.loads(out) == []


def test_legacy_direct_invoke_still_collects() -> None:
    # No routeKey = direct Lambda invoke of the collect endpoint: the body is validated, not 404'd.
    from collector.handler import lambda_handler

    resp = lambda_handler({"body": "{}"}, None)
    assert resp["statusCode"] == 400


def test_unknown_route_is_404() -> None:
    from collector.handler import lambda_handler

    resp = lambda_handler({"requestContext": {"routeKey": "GET /nope"}}, None)
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error_code"] == "not_found"
