"""Cost and safety guardrails a reviewer would otherwise check by eye."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))


def _block(kind: str, name: str) -> str:
    match = re.search(rf'resource "{kind}" "{name}" \{{(.*?)\n\}}', TF, re.S)
    assert match, f"{kind}.{name} is missing"
    return match.group(1)


def test_athena_workgroup_enforces_its_settings_and_caps_each_query() -> None:
    wg = _block("aws_athena_workgroup", "analytics")
    assert re.search(r"enforce_workgroup_configuration\s*=\s*true", wg)
    assert re.search(r"bytes_scanned_cutoff_per_query\s*=\s*10737418240", wg)  # 10 GiB


def test_budget_exists_only_when_the_limit_is_configured() -> None:
    budget = _block("aws_budgets_budget", "monthly")
    assert re.search(r'count\s*=\s*var\.budget_monthly_limit != ""', budget)
    assert re.search(r"limit_amount\s*=\s*var\.budget_monthly_limit", budget)
    assert re.search(
        r'threshold\s*=\s*80\s+threshold_type\s*=\s*"PERCENTAGE"\s+notification_type\s*=\s*"ACTUAL"',
        budget,
    )
    assert re.search(
        r'threshold\s*=\s*100\s+threshold_type\s*=\s*"PERCENTAGE"\s+notification_type\s*=\s*"FORECASTED"',
        budget,
    )
    assert "var.alarm_email" in budget
    variable = re.search(r'variable "budget_monthly_limit" \{(.*?)\n\}', TF, re.S)
    assert variable and re.search(r'default\s*=\s*""', variable.group(1))  # no amount in the repo
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "TF_VAR_budget_monthly_limit: ${{ secrets.BUDGET_MONTHLY_LIMIT }}" in deploy
    # No amount anywhere in the public repo, not even as an example.
    docs_row = next(
        line
        for line in (ROOT / "docs" / "ops" / "deploy.md").read_text().splitlines()
        if "BUDGET_MONTHLY_LIMIT" in line
    )
    for text in (variable.group(1), docs_row):
        assert not re.search(r"e\.g\.[^|]*\d", text), text


def test_raw_bucket_moves_old_versions_to_glacier_ir_and_never_expires_them() -> None:
    rules = _block("aws_s3_bucket_lifecycle_configuration", "raw")
    assert re.search(r"noncurrent_days\s*=\s*30\s+storage_class\s*=\s*\"GLACIER_IR\"", rules)
    assert re.search(r"days_after_initiation\s*=\s*7", rules)
    assert "expiration" not in rules  # versions are the backup: nothing is deleted


def test_every_cloudfront_behaviour_sends_the_security_headers() -> None:
    policy = _block("aws_cloudfront_response_headers_policy", "security")
    assert re.search(r"access_control_max_age_sec\s*=\s*31536000", policy)
    assert re.search(r"include_subdomains\s*=\s*true", policy)
    assert "content_type_options" in policy
    assert re.search(r'frame_option\s*=\s*"DENY"', policy)
    assert re.search(r'referrer_policy\s*=\s*"strict-origin-when-cross-origin"', policy)
    assert re.search(r'header\s*=\s*"Content-Security-Policy-Report-Only"', policy)
    assert "content_security_policy" not in policy  # report-only until the SDK's needs are known
    for host in (
        "'self'",
        "https://sdk.scdn.co",
        "https://api.spotify.com",
        "https://fonts.googleapis.com",
        "https://fonts.gstatic.com",
        "https://i.scdn.co",
    ):
        assert host in policy, host
    dist = _block("aws_cloudfront_distribution", "frontend")
    behaviours = dist.count("target_origin_id")
    attached = dist.count(
        "response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id"
    )
    assert behaviours == attached == 3  # default + the two API behaviour groups


CYRILLIC = re.compile(r"[Ѐ-ӿ]")
MONEY = re.compile(r"[$€£]\s?\d|\d\s?(USD|EUR)\b|/mo(nth)?\b|/мес", re.IGNORECASE)


def test_infra_text_is_english_and_moneyless() -> None:
    files = [*sorted(INFRA.glob("*.tf")), INFRA / "terraform.tfvars.example"]
    hits = [
        f"{p.name}:{n}"
        for p in files
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if CYRILLIC.search(line) or MONEY.search(line)
    ]
    assert hits == []


def test_default_cloudfront_certificate_keeps_tlsv1() -> None:
    # With cloudfront_default_certificate CloudFront forces TLSv1; any other value is a
    # perpetual plan diff and a security claim that is not true (docs/security.md).
    cert = re.search(
        r"viewer_certificate \{(.*?)\}", (INFRA / "frontend.tf").read_text(), re.S
    ).group(1)
    assert re.search(r"cloudfront_default_certificate\s*=\s*true", cert)
    assert re.search(r'minimum_protocol_version\s*=\s*"TLSv1"', cert)
