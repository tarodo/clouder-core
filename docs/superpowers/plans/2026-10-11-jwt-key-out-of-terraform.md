# JWT Signing Key out of Terraform — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The read-only pull-request role can no longer read the JWT signing key — neither through the Terraform state nor through SSM — and the key can be rotated without a deploy.

**Architecture:** Terraform stops managing the key (`removed` blocks with `destroy = false`, so the SSM parameter stays), the plan role's inline Deny covers `/clouder/auth/*`, and a script writes a fresh key straight into SSM. The auth Lambdas re-read the key every 5 minutes instead of caching it for the container's life, so a rotation reaches warm containers without a deploy. Old state versions in the versioned state bucket still hold the old key, so the owner rotates it once after the merge.

**Tech Stack:** Python 3.12, boto3, Terraform ≥ 1.7 (`removed` blocks), pytest.

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-11.ru.md` §1.4 п. 4 and §0.3 phase 3. Evidence: `infra/auth.tf` creates the key with `random_password` (in state); the plan role's `NoVendorSecrets` Deny lists vendor paths only, so `ssm:GetParameter` on `/clouder/auth/jwt_signing_key` is allowed by `ReadOnlyAccess`; `value_wo` would not help because the provider's Read decrypts the parameter. Refresh tokens are JWTs signed with the same key (`src/collector/auth/jwt_utils.py:issue_refresh_token`), so a rotation signs every user out.

## Global Constraints

- Worktree `../clouder-core-loop`, branch `fix/jwt-key-out-of-terraform` from `origin/main`. Tools from the main checkout's `.venv/bin/`.
- The key value never appears in a terminal, a log, a file or the shell history.
- Commit messages from `caveman:caveman-commit`; Conventional Commits; no AI attribution. English in the repo; no money figures.
- `README.md` counts are guarded: Terraform resource definitions drop by 2.

## Review Focus

1. **Terraform must not delete the live parameter** when the resources leave the config → `removed { lifecycle { destroy = false } }` for both; the PR plan must show "will no longer be managed", 0 to destroy. Pinned in Task 2 (test) and Task 4 (plan read).
2. **A rotated key reaches every warm container** within the TTL; a rotation mid-request does not crash. Pinned in Task 1.
3. **The TTL cache must not leak between tests or hide `JWT_SIGNING_KEY`** (the env override wins). Pinned in Task 1.
4. **The rotation script never prints the key** and writes `SecureString` with `Overwrite`. Pinned in Task 3.
5. **The plan role reads nothing under `/clouder/auth/`** → Deny + IAM policy simulator in production. Pinned in Task 2 (test) and Task 4 (simulator).

---

### Task 1: Re-read the key every 5 minutes

**Files:**
- Modify: `src/collector/secrets.py` (public uncached `fetch_ssm_parameter`)
- Modify: `src/collector/auth/auth_settings.py` (`resolve_jwt_signing_key` with a TTL)
- Modify: `tests/unit/test_auth_settings.py`

**Interfaces:**
- Produces: `collector.secrets.fetch_ssm_parameter(name: str) -> str` (no cache); `collector.auth.auth_settings.JWT_KEY_TTL_SECONDS = 300.0`; `reset_auth_settings_cache()` also forgets the key.

- [ ] **Step 1: Failing tests** — in `tests/unit/test_auth_settings.py`, replace `test_resolve_jwt_signing_key_via_ssm` and add two tests:

```python
def test_resolve_jwt_signing_key_via_ssm(monkeypatch) -> None:
    monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
    monkeypatch.setenv("JWT_SIGNING_KEY_SSM_PARAMETER", "/clouder/auth/jwt_signing_key")
    fetched = []
    monkeypatch.setattr(
        "collector.secrets.fetch_ssm_parameter", lambda name: fetched.append(name) or "from-ssm"
    )

    assert mod.resolve_jwt_signing_key() == "from-ssm"
    assert mod.resolve_jwt_signing_key() == "from-ssm"
    assert fetched == ["/clouder/auth/jwt_signing_key"]  # cached within the TTL


def test_rotated_key_is_picked_up_after_the_ttl(monkeypatch) -> None:
    monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
    monkeypatch.setenv("JWT_SIGNING_KEY_SSM_PARAMETER", "/clouder/auth/jwt_signing_key")
    values = iter(["old-key", "new-key"])
    monkeypatch.setattr("collector.secrets.fetch_ssm_parameter", lambda name: next(values))
    clock = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    assert mod.resolve_jwt_signing_key() == "old-key"
    clock[0] += mod.JWT_KEY_TTL_SECONDS - 1
    assert mod.resolve_jwt_signing_key() == "old-key"
    clock[0] += 2
    assert mod.resolve_jwt_signing_key() == "new-key"


def test_env_key_wins_over_a_cached_ssm_key(monkeypatch) -> None:
    monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
    monkeypatch.setenv("JWT_SIGNING_KEY_SSM_PARAMETER", "/clouder/auth/jwt_signing_key")
    monkeypatch.setattr("collector.secrets.fetch_ssm_parameter", lambda name: "from-ssm")
    assert mod.resolve_jwt_signing_key() == "from-ssm"

    monkeypatch.setenv("JWT_SIGNING_KEY", "from-env")
    assert mod.resolve_jwt_signing_key() == "from-env"
```

- [ ] **Step 2: Run** — `PYTHONPATH=src .venv/bin/pytest tests/unit/test_auth_settings.py -q` → Expected: 3 failed (`fetch_ssm_parameter` / `JWT_KEY_TTL_SECONDS` / `mod.time` missing).

- [ ] **Step 3: Implement**

`src/collector/secrets.py` — replace the module docstring's last sentence and split the fetch:

```python
"""AWS SSM Parameter Store fetch helpers.

Service-level API keys and OAuth client creds live as SSM SecureString
parameters. The Standard tier is free (up to 10 000 parameters, 4 KB each,
KMS-encrypted via the AWS-managed key). `_fetch_ssm_parameter` caches for the
container's life; the JWT signing key uses `fetch_ssm_parameter` with its own
short TTL so a rotation needs no deploy (collector.auth.auth_settings).
"""
```

```python
def fetch_ssm_parameter(name: str) -> str:
    response = _ssm_client().get_parameter(Name=name, WithDecryption=True)
    parameter = response.get("Parameter")
    if not isinstance(parameter, dict):
        raise RuntimeError(f"ssm response malformed, missing Parameter field (name={name})")
    value = parameter.get("Value")
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"ssm parameter is empty or not a string (name={name})")
    return value


@functools.lru_cache(maxsize=64)
def _fetch_ssm_parameter(name: str) -> str:
    return fetch_ssm_parameter(name)
```

`src/collector/auth/auth_settings.py` — add `import time`; module-level state after the imports:

```python
# The key is re-read this often, so a rotation (scripts/rotate_jwt_key.py) reaches warm
# containers without a deploy.
JWT_KEY_TTL_SECONDS = 300.0
_jwt_key: tuple[str, float] | None = None  # (value, fetched at, time.monotonic)
```

`reset_auth_settings_cache`:

```python
def reset_auth_settings_cache() -> None:
    global _jwt_key
    get_auth_settings.cache_clear()
    _jwt_key = None
```

`resolve_jwt_signing_key`:

```python
def resolve_jwt_signing_key() -> str:
    global _jwt_key
    from collector import secrets

    direct = os.environ.get("JWT_SIGNING_KEY", "").strip()
    if direct:
        return direct
    ssm_name = os.environ.get("JWT_SIGNING_KEY_SSM_PARAMETER", "").strip()
    if ssm_name:
        now = time.monotonic()
        if _jwt_key is None or now - _jwt_key[1] >= JWT_KEY_TTL_SECONDS:
            _jwt_key = (secrets.fetch_ssm_parameter(ssm_name), now)
        return _jwt_key[0]
    raise RuntimeError(
        "JWT signing key not configured: set JWT_SIGNING_KEY or JWT_SIGNING_KEY_SSM_PARAMETER"
    )
```

Grep for other patchers of `_fetch_ssm_parameter` that target the JWT key (`grep -rn "_fetch_ssm_parameter" tests src`) and point JWT-key ones at `fetch_ssm_parameter`.

- [ ] **Step 4: Run** — `PYTHONPATH=src .venv/bin/pytest tests/unit/test_auth_settings.py tests/unit/test_secrets.py tests/unit -q -k "auth or secrets or jwt" && .venv/bin/mypy` → all pass.

- [ ] **Step 5: Commit** (e.g. `feat(auth): re-read the JWT key every 5 minutes`)

---

### Task 2: Terraform lets go of the key; the plan role cannot read it

**Files:**
- Modify: `infra/auth.tf`, `infra/providers.tf` (`required_version = ">= 1.7.0"`), `infra/ci_roles.tf`
- Modify: `tests/unit/test_ci_roles_infra.py`
- Create: `tests/unit/test_jwt_key_infra.py`
- Modify: `README.md` (resource count)

- [ ] **Step 1: Failing tests**

`tests/unit/test_ci_roles_infra.py`: in `test_plan_role_cannot_read_secrets_or_data` replace the line `assert "/clouder/auth/" not in tf  # Terraform manages the JWT key and must read it` with:

```python
    # The JWT signing key is not Terraform's (infra/auth.tf): nothing in a plan reads it.
    assert '/clouder/auth/*"' in tf
```

`tests/unit/test_jwt_key_infra.py`:

```python
"""Terraform neither creates nor reads the JWT signing key (security.md, ADR-0028)."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))


def test_no_terraform_resource_holds_the_key() -> None:
    assert 'resource "random_password"' not in TF
    assert 'resource "aws_ssm_parameter" "jwt_signing_key"' not in TF


def test_the_live_parameter_is_released_not_destroyed() -> None:
    for address in ("aws_ssm_parameter.jwt_signing_key", "random_password.jwt_signing_key"):
        block = re.search(rf"removed \{{\s*from\s*=\s*{re.escape(address)}(.*?)\n\}}", TF, re.S)
        assert block, address
        assert re.search(r"destroy\s*=\s*false", block.group(1)), address
    assert re.search(r'required_version\s*=\s*">= 1\.7', TF)  # removed blocks need 1.7
```

- [ ] **Step 2: Run** — `PYTHONPATH=src .venv/bin/pytest tests/unit/test_ci_roles_infra.py tests/unit/test_jwt_key_infra.py -q` → Expected: 3 failed.

- [ ] **Step 3: Implement**

`infra/auth.tf` — replace the `random_password` and `aws_ssm_parameter` resources with:

```hcl
# The JWT signing key is not Terraform's: a resource here put it in the state, which the
# read-only pull-request role can read (ADR-0028). scripts/rotate_jwt_key.py writes it
# straight to SSM; the auth Lambdas read it by name (var.jwt_signing_key_ssm_parameter).
removed {
  from = aws_ssm_parameter.jwt_signing_key
  lifecycle {
    destroy = false
  }
}

removed {
  from = random_password.jwt_signing_key
  lifecycle {
    destroy = false
  }
}
```

`infra/providers.tf`: `required_version = ">= 1.6.0"` → `required_version = ">= 1.7.0"`.

`infra/ci_roles.tf`, statement `NoVendorSecrets`: rename `sid` to `NoSecrets` and add `"${local.ssm_parameter_arn}/clouder/auth/*",` as the last resource. If a test pins the sid name, update it.

README: `grep -c '^resource "' infra/*.tf | awk -F: '{s+=$2} END {print s}'` and replace both `243 Terraform resource definitions` with the result (expected 241).

- [ ] **Step 4: Run** — `PYTHONPATH=src .venv/bin/pytest tests/unit/test_ci_roles_infra.py tests/unit/test_jwt_key_infra.py tests/unit/test_readme.py -q && (cd infra && terraform fmt -check && terraform init -backend=false -input=false >/dev/null && terraform validate)` → pass; valid.

- [ ] **Step 5: Commit** (e.g. `fix(infra): take the JWT key out of Terraform`)

---

### Task 3: A rotation script and the documents

**Files:**
- Create: `scripts/rotate_jwt_key.py`, `tests/unit/test_rotate_jwt_key.py`
- Modify: `docs/ops/runbook.md` (new section before `## Running a one-off script against prod`), `docs/security.md` (GitHub ↔ AWS row and Known gaps), `docs/adr/0028-ci-roles.md` (Consequences), `docs/ops/deploy.md` (rebuild note, if it has a bootstrap/first-deploy section; else the runbook covers it)

- [ ] **Step 1: Failing test** — `tests/unit/test_rotate_jwt_key.py`:

```python
"""scripts/rotate_jwt_key.py writes a fresh key to SSM and never prints it."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rotate_jwt_key.py"


def _load():
    spec = importlib.util.spec_from_file_location("rotate_jwt_key", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeSSM:
    def __init__(self) -> None:
        self.puts: list[dict] = []

    def put_parameter(self, **kw):
        self.puts.append(kw)
        return {"Version": 7}


def test_writes_a_new_secure_key_and_prints_only_the_version(capsys) -> None:
    ssm = FakeSSM()

    _load().main(["--name", "/clouder/auth/jwt_signing_key"], ssm=ssm)

    (put,) = ssm.puts
    assert put["Name"] == "/clouder/auth/jwt_signing_key"
    assert put["Type"] == "SecureString" and put["Overwrite"] is True
    assert len(put["Value"]) >= 64
    out = capsys.readouterr().out
    assert put["Value"] not in out and "7" in out


def test_two_rotations_never_repeat_a_key() -> None:
    ssm = FakeSSM()
    mod = _load()
    mod.main([], ssm=ssm)
    mod.main([], ssm=ssm)
    assert ssm.puts[0]["Value"] != ssm.puts[1]["Value"]
    assert ssm.puts[0]["Name"] == "/clouder/auth/jwt_signing_key"  # the default
```

- [ ] **Step 2: Run** — `PYTHONPATH=src .venv/bin/pytest tests/unit/test_rotate_jwt_key.py -q` → Expected: errors, the script does not exist.

- [ ] **Step 3: Script** — `scripts/rotate_jwt_key.py`:

```python
"""Write a fresh JWT signing key to SSM (creates the parameter on a new account).

Signs every user out: access and refresh tokens are JWTs signed with this key. The value
goes straight from the CSPRNG to SSM and is never printed; the auth Lambdas pick it up
within 5 minutes (collector.auth.auth_settings.JWT_KEY_TTL_SECONDS).

    python scripts/rotate_jwt_key.py [--name /clouder/auth/jwt_signing_key]
"""

from __future__ import annotations

import argparse
import secrets
from typing import Any

DEFAULT_NAME = "/clouder/auth/jwt_signing_key"


def main(argv: list[str] | None = None, ssm: Any = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default=DEFAULT_NAME)
    args = parser.parse_args(argv)
    if ssm is None:
        import boto3

        ssm = boto3.client("ssm")
    response = ssm.put_parameter(
        Name=args.name,
        Value=secrets.token_urlsafe(48),  # 64 characters, as the Terraform-made key had
        Type="SecureString",
        Overwrite=True,
        Description="HS256 secret used by auth_handler and auth_authorizer",
    )
    print(f"{args.name}: version {response['Version']}; sessions end within 5 minutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run** — the test file → 2 passed; `.venv/bin/ruff check scripts tests && .venv/bin/ruff format --check scripts tests`.

- [ ] **Step 5: Documents**

Runbook — new section before `## Running a one-off script against prod`:

```markdown
## Rotate the JWT signing key

**When:** the key may have leaked; anyone gained read access to the Terraform state or to `/clouder/auth/*`; or on a new account (it creates the parameter).

**Effect:** every user is signed out — access and refresh tokens are both JWTs signed with this key. Warm Lambdas pick the new key up within 5 minutes; until then a token signed by one container can be rejected by another, so rotate when nobody is curating.

```bash
python scripts/rotate_jwt_key.py   # prints the new SSM version, never the key
```

Terraform does not manage this parameter (ADR-0028): a deploy never changes it, and `terraform plan` never reads it.
```

`docs/security.md`:
- GitHub ↔ AWS row: replace `it cannot change AWS resources or read vendor secrets, but it reads the Terraform state, whose JWT signing key makes it roughly application-admin;` with `it cannot change AWS resources or read any application secret — vendor credentials and the JWT signing key live only in SSM, outside the Terraform state, under an explicit Deny;`.
- Known gaps: delete the bullet `**The JWT signing key is in the Terraform state.** …`. In the bullet `**HS256 with one shared key.** … Rotating it signs every user out.` append ` Rotation: \`scripts/rotate_jwt_key.py\` (runbook).`

`docs/adr/0028-ci-roles.md` — in Consequences, replace the bullet that starts `- A pull request can read the account's configuration and the Terraform state but change no` (through `generating it outside Terraform).`) with:

```markdown
- A pull request can read the account's configuration and the Terraform state but change no
  AWS resource and read no application secret. The JWT signing key used to sit in the state
  (`random_password`), which made plan access roughly application-admin; on 2026-10-11 it
  left Terraform (`removed` blocks, the SSM parameter kept), `/clouder/auth/*` joined the
  Deny and the key was rotated, since old state versions still hold the old value. A
  write-only attribute would not have been enough: the provider's read of the parameter
  decrypts it, so the role would still have needed to read it.
```

Read each file before editing; keep surrounding wording.

- [ ] **Step 6: Guards and commit** — `PYTHONPATH=src .venv/bin/pytest -q` all pass; commit (e.g. `feat(auth): rotate the JWT key without Terraform`).

---

### Task 4: Ship and verify

- [ ] **Step 1: PR** (title/body from `caveman:caveman-commit`); wait for checks; read the plan: expected `aws_ssm_parameter.jwt_signing_key` and `random_password.jwt_signing_key` "will no longer be managed by Terraform", `aws_iam_role_policy.gha_plan_no_data` updated, Lambda code updated, **0 to destroy**. Anything destroyed → stop.
- [ ] **Step 2: Merge, deploy** — green, smoke 9/9. `aws ssm get-parameter --name /clouder/auth/jwt_signing_key --query 'Parameter.[Version,Type]'` still exists (do not decrypt).
- [ ] **Step 3: Simulate the plan role** —

```bash
ROLE=$(aws iam get-role --role-name clouder-prod-gha-plan --query Role.Arn --output text)
ACCT=$(aws sts get-caller-identity --query Account --output text)
aws iam simulate-principal-policy --policy-source-arn "$ROLE" --action-names ssm:GetParameter \
  --resource-arns "arn:aws:ssm:us-east-1:$ACCT:parameter/clouder/auth/jwt_signing_key" \
  --query 'EvaluationResults[0].EvalDecision'
```

Expected: `explicitDeny`.

- [ ] **Step 4: Owner — rotate** — stop and ask the owner to run `python scripts/rotate_jwt_key.py` at a quiet moment (it signs everyone out, including the DJ group; writing a secret is the owner's step). After it: the owner logs in again; `clouder-prod-auth-*` errors stay at 0 for 10 minutes.
- [ ] **Step 5: Board** — phase 3 → `done` with plan, PR, simulator result and the rotation version.
