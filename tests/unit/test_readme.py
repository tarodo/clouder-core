"""README: no money, no retired claims, the sections a reviewer looks for."""

from __future__ import annotations

import re
from pathlib import Path

README = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")


def test_readme_has_no_money_or_retired_claims() -> None:
    assert not re.search(r"[$€£]\s?\d|\d\s?(USD|EUR)\b|per month|/month", README)
    for retired in ("AI-assisted screening", "internal use only", "Weekly automated ingest"):
        assert retired not in README


def test_readme_has_the_reviewer_sections() -> None:
    for heading in ("## Architecture", "## Measured results", "## What this project demonstrates",
                    "## AWS services", "## Data pipeline", "## Screenshots", "## Running it locally",
                    "## Known limitations", "## How this was built", "## License"):
        assert heading in README, heading
    assert "```mermaid" in README and "docs/assets/" in README


ROOT = Path(__file__).resolve().parents[2]


def test_local_run_migrates_before_the_db_tests() -> None:
    # tests/db needs the schema; each `cd` runs in a subshell so the block works top to bottom.
    assert README.index("alembic upgrade head") < README.index("pytest tests/db")
    assert "(cd frontend" in README and "(cd dbt" in README


def test_readme_counts_match_the_sources() -> None:
    import yaml

    spec = yaml.safe_load((ROOT / "docs" / "api" / "openapi.yaml").read_text())
    ops = sum(1 for path in spec["paths"].values() for m in path if m in {"get", "put", "post", "patch", "delete"})
    assert set(re.findall(r"(\d+) (?:API )?operations", README)) == {str(ops)}
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").glob("*.tf"))
    lambdas = len(re.findall(r'^resource "aws_lambda_function"', tf, re.M))
    assert set(re.findall(r"(\d+) (?:AWS )?Lambda functions", README)) == {str(lambdas)}


def test_readme_lists_every_route_without_the_authorizer() -> None:
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").glob("*.tf"))
    open_routes = []
    for block in re.findall(r'resource "aws_apigatewayv2_route" "[^"]+" \{(.*?)\n\}', tf, re.S):
        key = re.search(r'route_key\s*=\s*"([A-Z]+ (/[^"]+))"', block)
        if key and 'authorization_type = "CUSTOM"' not in re.sub(r"\s+", " ", block):
            open_routes.append(key.group(2))
    assert len(open_routes) >= 4
    for path in open_routes:
        assert f"`{path}`" in README, path


def test_license_allows_evaluation() -> None:
    license_text = (ROOT / "LICENSE").read_text()
    assert "clone" in license_text and "run" in license_text and "evaluat" in license_text
