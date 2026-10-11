# Auto-ingest Phase A (credentials, Beatport login, spike) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that CLOUDER can obtain a Beatport token from AWS with the owner's credentials — no browser, no token stored — before building the scheduler and planner.

**Architecture:** `collector.beatport_auth.fetch_access_token` runs Beatport API v4's login → authorize → token flow with `urllib`; a new `clouder-prod-auto-ingest` Lambda (`collector.auto_ingest_handler`) exposes an `auth_check` action that reads the credentials from SSM and reports only success or the failing step and HTTP status. The deploy workflow copies the GitHub secrets to SSM.

**Tech Stack:** Python 3.12 stdlib (`urllib`, `http.cookiejar`), AWS Lambda, SSM Parameter Store (SecureString), Terraform, GitHub Actions, pytest.

**Spec:** `docs/superpowers/specs/2026-10-07-auto-ingest-design.md` (sections 1 and 6 — rollout A).

## Global Constraints

- The token and the password never appear in a log, an exception message, a return value or storage.
- Stdlib only for the login (no `requests` in the Lambda bundle).
- The deploy must not fail while the GitHub secrets are unset.
- The new role reads exactly the two SSM parameters; no other grants beyond its own logs.
- Branch `feat/auto-ingest`, worktree `../clouder-core-autoingest`; `$VENV=<repo>/.venv/bin`; commits via caveman-commit rules; `terraform fmt -check`.

## Review Focus

1. A login, authorize or token step fails → `BeatportAuthError` names the step and status; no body, password or token in `str(error)`. Test: `test_each_failing_step_is_named_without_secrets`.
2. Authorize answers 200 instead of a redirect (session not established) → error at `authorize`. Test: `test_authorize_without_redirect_fails`.
3. Credentials missing in SSM → `auth_check` returns `{"ok": false, "step": "credentials"}` instead of crashing. Test: `test_auth_check_reports_missing_credentials`.
4. The deploy runs before the owner adds the secrets → the SSM step skips. Test: `test_deploy_skips_beatport_sync_without_secrets`.

---

### Task 1: `beatport_auth.fetch_access_token`

**Files:** Create `src/collector/beatport_auth.py`, `tests/unit/test_beatport_auth.py`.

**Interfaces — Produces:** `fetch_access_token(username: str, password: str, *, client_id: str | None = None, opener: Any = None, timeout: float = 20.0) -> str`; `BeatportAuthError(step: str, status: int | str)` with attributes `step`, `status`; constants `API`, `DEFAULT_CLIENT_ID`, `REDIRECT_URI`.

- [ ] Step 1 — failing tests with a fake opener (`open(request, timeout)` returns objects with `.status`, `.headers`, `.read()`, or raises `urllib.error.HTTPError`):
  - `test_three_step_flow_returns_the_access_token`: login 200 → authorize 302 `Location: …/post-message/?code=abc` → token 200 `{"access_token": "T", …}` returns `"T"`; asserts the login body is JSON with username/password, the authorize query has `response_type=code`, `client_id`, `redirect_uri`, the token form has `grant_type=authorization_code`, `code=abc`.
  - `test_each_failing_step_is_named_without_secrets` (parametrized login 401 / token 400): `BeatportAuthError.step` is the step, `.status` the code, and neither the password nor `"T"` occurs in `str(error)`.
  - `test_authorize_without_redirect_fails`: authorize returns 200 → `step == "authorize"`.
  - `test_network_error_is_reported_as_network`: `URLError` → `status == "network"`.
  Run: `$VENV/pytest tests/unit/test_beatport_auth.py -q` → `ModuleNotFoundError`.
- [ ] Step 2 — implement (a redirect handler that returns `None` so the 302 surfaces as `HTTPError`; `HTTPCookieProcessor` keeps the session; `raise … from None` so `HTTPError` bodies are not chained). Run → pass.
- [ ] Step 3 — commit `feat(auth): Beatport token via API v4 login flow`.

### Task 2: `auto_ingest_handler` (`auth_check`), Lambda, role, deploy step

**Files:** Create `src/collector/auto_ingest_handler.py`, `tests/unit/test_auto_ingest_handler.py`, `infra/auto_ingest.tf`, `tests/unit/test_auto_ingest_infra.py`; Modify `.github/workflows/deploy.yml`, `src/collector/logging_utils.py` (`ok`, `step`, `action` if absent).

**Interfaces — Consumes:** Task 1. **Produces:** `lambda_handler(event, context)`; event `{"action": "auth_check"}` → `{"ok": true}` | `{"ok": false, "step": str, "status": int | str | None}`; env `BEATPORT_USERNAME_SSM_PARAMETER`, `BEATPORT_PASSWORD_SSM_PARAMETER`.

- [ ] Step 1 — failing tests:
  - handler: `test_auth_check_ok` (monkeypatch `_read_credentials` and `fetch_access_token`) → `{"ok": True}` and the token is not in the result or in captured log events; `test_auth_check_reports_failed_step` → `{"ok": False, "step": "token", "status": 400}`; `test_auth_check_reports_missing_credentials` (`_fetch_ssm_parameter` raises) → `{"ok": False, "step": "credentials", "status": None}`; `test_unknown_action_raises`.
  - infra: `infra/auto_ingest.tf` has a Lambda with handler `collector.auto_ingest_handler.lambda_handler`, `reserved_concurrent_executions = 1`; its policy grants `ssm:GetParameter` only on the two `/clouder/beatport/*` parameters and `kms:Decrypt` on `alias/aws/ssm`.
  - workflow: `test_deploy_skips_beatport_sync_without_secrets` — `deploy.yml` has a step that reads `secrets.BEATPORT_USERNAME`/`BEATPORT_PASSWORD` through `env:`, exits 0 when either is empty, and puts `/clouder/beatport/username` and `/clouder/beatport/password` as `SecureString`.
  Run → failures.
- [ ] Step 2 — implement handler, Terraform (log group, role, policy, Lambda: timeout 900, memory 512, env with the SSM names, `reserved_concurrent_executions = 1`), deploy step (after the existing "Sync GitHub secrets to SSM Parameter Store"). `terraform fmt`. Run tests + full suite → pass.
- [ ] Step 3 — commit `feat(auto-ingest): login check Lambda and credentials sync`.

## After merge (gate)

1. Deploy; the owner's secrets must exist (`aws ssm get-parameter --name /clouder/beatport/username --query Parameter.Name` — name only).
2. `aws lambda invoke --function-name clouder-prod-auto-ingest --cli-binary-format raw-in-base64-out --payload '{"action":"auth_check"}' out.json && cat out.json` → `{"ok": true}` continues to Phase B; anything else stops and goes to the owner with the step and status.
