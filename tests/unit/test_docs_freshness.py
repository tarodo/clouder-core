"""Live docs describe the system that is deployed, not the one that was removed."""

from __future__ import annotations

import re

from test_docs_links import ROOT, live_docs

REMOVED = re.compile(
    r"search_handler|ai_search_results|ai[-_]search[-_]worker|AI_SEARCH_QUEUE_URL|perplexity",
    re.IGNORECASE,
)


def deployed_handlers() -> set[str]:
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").glob("*.tf"))
    return set(re.findall(r'handler\s*=\s*"(collector\.[a-z_]+)\.lambda_handler"', tf))


def test_every_deployed_lambda_is_in_the_architecture_doc() -> None:
    doc = (ROOT / "docs" / "architecture.md").read_text()
    missing = sorted(h for h in deployed_handlers() if f"`{h}`" not in doc)
    assert len(deployed_handlers()) >= 18 and missing == []


def test_live_docs_do_not_describe_removed_components() -> None:
    hits = []
    for doc in live_docs():
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if REMOVED.search(line):
                hits.append(f"{doc.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert hits == []
