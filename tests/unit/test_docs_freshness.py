"""Live docs describe the system that is deployed, not the one that was removed."""

from __future__ import annotations

import re

from test_docs_links import ROOT, live_docs

REMOVED = re.compile(
    r"\bsearch_handler\b|ai_search_results|ai[-_]search[-_]worker|AI_SEARCH_QUEUE_URL|perplexity"
    r"|propagate_ai_flag",
    re.IGNORECASE,
)
MONEY = re.compile(r"[$€£]\s?\d|\d\s?(USD|EUR)\b|per month|/month", re.IGNORECASE)


def deployed_handlers() -> set[str]:
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").glob("*.tf"))
    return set(re.findall(r'handler\s*=\s*"(collector\.[a-z_]+)\.lambda_handler"', tf))


def test_every_deployed_lambda_is_in_the_architecture_doc() -> None:
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").glob("*.tf"))
    # Every Lambda resource contributes a handler the regex can read — none slips past.
    assert len(deployed_handlers()) == len(re.findall(r'^resource "aws_lambda_function"', tf, re.M))
    doc = (ROOT / "docs" / "architecture.md").read_text()
    documented = set(re.findall(r"`(collector\.[a-z_]+)`", doc))
    assert documented == deployed_handlers()  # nothing missing, nothing stale


def test_live_docs_do_not_describe_removed_components() -> None:
    hits = []
    for doc in live_docs():
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if REMOVED.search(line):
                hits.append(f"{doc.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert hits == []


def test_docs_have_no_money_figures() -> None:
    extra = [
        *sorted((ROOT / "docs" / "adr").glob("*.md")),
        ROOT / "frontend" / "README.md",
        ROOT / "dbt" / "README.md",
    ]
    hits = []
    for doc in [*live_docs(), *(p for p in extra if p.exists())]:
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if MONEY.search(line):
                hits.append(f"{doc.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert hits == []


def test_diagrams_show_the_api_and_ingest_writes_to_aurora() -> None:
    readme = (ROOT / "README.md").read_text()
    arch = (ROOT / "docs" / "architecture.md").read_text()
    assert re.search(r"^\s*API & AI --> DB\b", readme, re.M)
    for edge in (
        r"CAPI & AI --> DB",
        r"CAPI & BF -->\|SQS\| SPW",
        r"CUR -->\|SQS\| VMW & DSP & CMT",
    ):
        assert re.search(edge, arch), edge


def test_architecture_table_puts_the_funnel_on_the_collector() -> None:
    rows = {
        r.split("|")[1].strip(): r
        for r in (ROOT / "docs" / "architecture.md").read_text().splitlines()
        if r.startswith("| `")
    }
    assert "funnel" not in rows["`analytics-api`"] and "funnel" in rows["`collector-api`"]


def test_env_vars_do_not_claim_registry_publishing() -> None:
    row = next(
        r
        for r in (ROOT / "docs" / "ops" / "env-vars.md").read_text().splitlines()
        if r.startswith("| `ytmusic`")
    )
    assert "playlist publish" not in row  # the registry exporter is a stub


def _lambda_suffixes() -> set[str]:
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").glob("*.tf"))
    # Names are set as `function_name = "${local.name_prefix}-x"` or through a `*lambda_name` local.
    return set(
        re.findall(
            r'(?:function_name|lambda_name)\s*=\s*"\$\{local\.name_prefix\}-([a-z0-9-]+)"', tf
        )
    )


def test_docs_call_lambdas_by_their_current_names() -> None:
    # The functions were renamed beatport-prod-* -> clouder-prod-*; buckets and the Athena
    # workgroup kept the old prefix on purpose (CLAUDE.md gotcha 4), so only function names count.
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").glob("*.tf"))
    suffixes = _lambda_suffixes()
    assert len(suffixes) == len(re.findall(r'^resource "aws_lambda_function"', tf, re.M))
    stale = re.compile(
        r"beatport-prod-(" + "|".join(sorted(suffixes, key=len, reverse=True)) + r")\b"
    )
    docs = [
        *live_docs(),
        *sorted((ROOT / "docs" / "adr").glob("*.md")),
        ROOT / "frontend" / "README.md",
    ]
    hits = [
        f"{d.relative_to(ROOT)}:{n}"
        for d in docs
        for n, line in enumerate(d.read_text(encoding="utf-8").splitlines(), 1)
        if stale.search(line)
    ]
    assert hits == []


def test_auto_ingest_doc_reports_production() -> None:
    doc = (ROOT / "docs" / "data" / "auto-ingest.md").read_text()
    status = next(line for line in doc.splitlines() if line.startswith("Status:"))
    assert "disabled" not in status
    after = doc.split("## After", 1)[1].split("\n## ", 1)[0]
    assert "Pending" not in after and re.search(r"\d", after)


def test_long_lambda_invokes_in_docs_wait_for_the_result() -> None:
    # The CLI reads for 60 s, then retries a synchronous invoke: a minutes-long export
    # would run two or three times at once.
    for doc in live_docs():
        for line in doc.read_text().splitlines():
            if "aws lambda invoke" in line and "catalog-export" in line:
                assert "--cli-read-timeout 0" in line, f"{doc}: {line.strip()}"
