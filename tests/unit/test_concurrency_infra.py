"""Background workers cannot take the API's Lambda capacity (postmortem 2026-10-11)."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))


def _block(kind: str, name: str) -> str:
    m = re.search(rf'{kind} "{name}" \{{(.*?)\n\}}', TF, re.S)
    assert m, f"{kind} {name}"
    return m.group(1)


def _caps() -> dict[str, str]:
    """Event source mapping name → the variable that holds its maximum_concurrency."""
    caps = {}
    for name, body in re.findall(
        r'resource "aws_lambda_event_source_mapping" "([a-z_]+)" \{(.*?)\n\}', TF, re.S
    ):
        m = re.search(r"maximum_concurrency\s*=\s*var\.([a-z_]+)", body)
        caps[name] = m.group(1) if m else ""
    return caps


def test_every_sqs_worker_has_a_concurrency_cap() -> None:
    caps = _caps()
    assert len(caps) >= 7
    for esm, var in caps.items():
        assert var, f"{esm}: scaling_config.maximum_concurrency is missing"
        assert re.search(rf"var\.{var} >= 2 && var\.{var} <= 1000", _block("variable", var)), var
