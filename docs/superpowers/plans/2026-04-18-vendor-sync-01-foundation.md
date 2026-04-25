# Vendor-Sync Plan 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the codebase and infrastructure for the vendor-sync work: make the search worker entity-generic, migrate service secrets to SSM Parameter Store, and switch the migration Lambda to Aurora IAM auth so the Secrets Manager VPC endpoint can be removed.

**Architecture:** No new runtime features. We refactor three boundaries: (1) the AI search worker's input message moves from a label-specific pydantic model to a generic `EntitySearchMessage` with a translator for backward-compat; (2) `settings.py` gains an SSM Parameter Store code path alongside the existing Secrets Manager fallback; (3) the migration Lambda grows a second auth mode using IAM-issued RDS tokens against a dedicated DB user `clouder_migrator`.

**Tech Stack:** Python 3.12, pydantic v2, boto3 (`ssm`, `rds`), SQLAlchemy 2, Alembic, Terraform (AWS provider), pytest with `monkeypatch`.

**Spec:** [docs/superpowers/specs/2026-04-18-vendor-sync-readiness-design.md](../specs/2026-04-18-vendor-sync-readiness-design.md), sections §6.4, §8.1, §8.2.

---

## File Structure

Files this plan creates:

- `src/collector/secrets.py` — SSM Parameter Store fetch helper with `lru_cache`.
- `tests/unit/test_secrets.py` — unit tests for SSM fetcher.
- `alembic/versions/20260419_07_bootstrap_iam_auth.py` — DB migration that creates the `clouder_migrator` role and grants `rds_iam`.
- `tests/unit/test_entity_search_message.py` — tests for the new pydantic schema and the back-compat translator.

Files this plan modifies:

- `src/collector/schemas.py` — add `EntitySearchMessage`; keep `LabelSearchMessage` as a back-compat alias.
- `src/collector/search_handler.py` — accept both message shapes; dispatch inline on `entity_type`.
- `src/collector/settings.py` — add `_fetch_ssm_parameter`; new `*_SSM_PARAMETER` env aliases; precedence env > SSM > Secrets Manager.
- `src/collector/migration_handler.py` — add IAM auth branch gated by `AURORA_AUTH_MODE`.
- `infra/iam.tf` — add `ssm:GetParameter` permissions on new SSM resources; add `rds-db:connect` permission on the migration Lambda role.
- `infra/lambda.tf` — switch Perplexity / Spotify Lambdas to consume SSM param names; add `AURORA_AUTH_MODE` env on migration Lambda.
- `infra/variables.tf` — add `perplexity_api_key_ssm_parameter`, `spotify_credentials_ssm_parameter_prefix`, `migration_db_user` variables.
- `infra/terraform.tfvars.example` — example values.
- `tests/unit/test_search_handler.py` — extend existing tests, keep back-compat coverage.
- `tests/unit/test_settings.py` — extend for SSM code paths.

Files this plan does NOT touch:

- `db_models.py` — no SQLAlchemy model changes in this plan.
- Any other `clouder_*` tables — column additions belong to Plan 2.

---

## Task 1: Add `EntitySearchMessage` schema

**Files:**

- Modify: `src/collector/schemas.py:85-100`
- Test: `tests/unit/test_entity_search_message.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_entity_search_message.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from collector.schemas import EntitySearchMessage


def test_entity_search_message_accepts_full_payload() -> None:
    msg = EntitySearchMessage.model_validate(
        {
            "entity_type": "label",
            "entity_id": "label-123",
            "prompt_slug": "label_info",
            "prompt_version": "v1",
            "context": {"label_name": "Test", "styles": "Techno"},
        }
    )

    assert msg.entity_type == "label"
    assert msg.entity_id == "label-123"
    assert msg.prompt_slug == "label_info"
    assert msg.prompt_version == "v1"
    assert msg.context == {"label_name": "Test", "styles": "Techno"}


def test_entity_search_message_requires_entity_type() -> None:
    with pytest.raises(ValidationError):
        EntitySearchMessage.model_validate(
            {
                "entity_id": "x",
                "prompt_slug": "label_info",
                "prompt_version": "v1",
                "context": {},
            }
        )


def test_entity_search_message_trims_whitespace() -> None:
    msg = EntitySearchMessage.model_validate(
        {
            "entity_type": " label ",
            "entity_id": " x ",
            "prompt_slug": " p ",
            "prompt_version": " v1 ",
            "context": {},
        }
    )
    assert msg.entity_type == "label"
    assert msg.entity_id == "x"
    assert msg.prompt_slug == "p"
    assert msg.prompt_version == "v1"


def test_entity_search_message_defaults_empty_context() -> None:
    msg = EntitySearchMessage.model_validate(
        {
            "entity_type": "label",
            "entity_id": "x",
            "prompt_slug": "p",
            "prompt_version": "v1",
        }
    )
    assert msg.context == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_entity_search_message.py -q
```

Expected: all 4 tests FAIL with `ImportError: cannot import name 'EntitySearchMessage'`.

- [ ] **Step 3: Implement the schema**

Append to `src/collector/schemas.py` after the existing `LabelSearchMessage`:

```python
class EntitySearchMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity_type: str
    entity_id: str
    prompt_slug: str
    prompt_version: str
    context: dict[str, object] = Field(default_factory=dict)

    @field_validator("entity_type", "entity_id", "prompt_slug", "prompt_version")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must be a non-empty string")
        return normalized
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_entity_search_message.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

Use the `caveman:caveman-commit` skill to generate the commit message, then:

```bash
git add src/collector/schemas.py tests/unit/test_entity_search_message.py
git commit -m "<caveman-commit output>"
```

---

## Task 2: Back-compat translator `coerce_search_message`

**Files:**

- Modify: `src/collector/schemas.py` (add helper at bottom)
- Test: `tests/unit/test_entity_search_message.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_entity_search_message.py`:

```python
def test_coerce_label_search_message_payload() -> None:
    from collector.schemas import coerce_search_message

    coerced = coerce_search_message(
        {
            "label_id": "label-123",
            "label_name": "Test",
            "styles": "Techno",
            "prompt_slug": "label_info",
            "prompt_version": "v1",
        }
    )

    assert coerced.entity_type == "label"
    assert coerced.entity_id == "label-123"
    assert coerced.prompt_slug == "label_info"
    assert coerced.prompt_version == "v1"
    assert coerced.context == {"label_name": "Test", "styles": "Techno"}


def test_coerce_passes_through_entity_search_message() -> None:
    from collector.schemas import coerce_search_message

    payload = {
        "entity_type": "label",
        "entity_id": "x",
        "prompt_slug": "label_info",
        "prompt_version": "v1",
        "context": {"label_name": "Test", "styles": "Techno"},
    }
    coerced = coerce_search_message(payload)

    assert coerced.entity_type == "label"
    assert coerced.context == {"label_name": "Test", "styles": "Techno"}


def test_coerce_raises_on_unknown_shape() -> None:
    import pytest as _pytest
    from pydantic import ValidationError

    from collector.schemas import coerce_search_message

    with _pytest.raises(ValidationError):
        coerce_search_message({"unknown": "payload"})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_entity_search_message.py -q
```

Expected: 3 new tests FAIL with `ImportError: cannot import name 'coerce_search_message'`.

- [ ] **Step 3: Implement the translator**

Append to `src/collector/schemas.py`:

```python
def coerce_search_message(payload: dict[str, object]) -> EntitySearchMessage:
    """Accept both EntitySearchMessage and LabelSearchMessage shapes.

    LabelSearchMessage is the legacy on-wire shape for in-flight SQS messages.
    It translates into EntitySearchMessage with entity_type='label' and
    context={label_name, styles}.
    """
    if "entity_type" in payload:
        return EntitySearchMessage.model_validate(payload)

    legacy = LabelSearchMessage.model_validate(payload)
    return EntitySearchMessage(
        entity_type="label",
        entity_id=legacy.label_id,
        prompt_slug=legacy.prompt_slug,
        prompt_version=legacy.prompt_version,
        context={"label_name": legacy.label_name, "styles": legacy.styles},
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/test_entity_search_message.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/schemas.py tests/unit/test_entity_search_message.py
git commit -m "<caveman-commit output>"
```

---

## Task 3: Rewire `search_handler.lambda_handler` to dispatch on `entity_type`

**Files:**

- Modify: `src/collector/search_handler.py:1-137`
- Test: `tests/unit/test_search_handler.py` (add tests, keep existing)

- [ ] **Step 1: Write the failing tests (back-compat + new shape)**

Append to `tests/unit/test_search_handler.py`:

```python
def test_happy_path_accepts_entity_search_message(monkeypatch) -> None:
    repo = _setup_search_worker(monkeypatch)

    event = _sqs_event(
        {
            "entity_type": "label",
            "entity_id": "label-456",
            "prompt_slug": "label_info",
            "prompt_version": "v1",
            "context": {"label_name": "Entity Label", "styles": "House"},
        }
    )
    response = lambda_handler(event, context=None)

    assert response == {"processed": 1}
    assert len(repo.saved_results) == 1
    saved = repo.saved_results[0]
    assert saved["entity_type"] == "label"
    assert saved["entity_id"] == "label-456"
    assert saved["result"]["label_name"] == "Test Label"
    reset_settings_cache()


def test_unknown_entity_type_is_skipped(monkeypatch) -> None:
    repo = _setup_search_worker(monkeypatch)

    event = _sqs_event(
        {
            "entity_type": "artist",
            "entity_id": "artist-1",
            "prompt_slug": "artist_info",
            "prompt_version": "v1",
            "context": {},
        }
    )
    response = lambda_handler(event, context=None)

    assert response == {"processed": 0}
    assert repo.saved_results == []
    reset_settings_cache()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_search_handler.py -q
```

Expected: 2 new tests FAIL (existing tests still pass).

- [ ] **Step 3: Rewire the handler**

Replace the body of `src/collector/search_handler.py` with:

```python
"""SQS worker that performs AI-powered entity research via Perplexity."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from .logging_utils import log_event
from .repositories import create_clouder_repository_from_env, utc_now
from .schemas import (
    EntitySearchMessage,
    coerce_search_message,
    validation_error_message,
)
from .search.perplexity_client import search_label
from .search.prompts import get_prompt
from .settings import get_search_worker_settings


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records")
    if not isinstance(records, list):
        return {"processed": 0}

    log_event(
        "INFO",
        "search_worker_invoked",
        sqs_record_count=len(records),
    )

    settings = get_search_worker_settings()
    repository = create_clouder_repository_from_env()
    if repository is None:
        raise RuntimeError(
            "AURORA Data API configuration is required for search worker"
        )

    processed = 0
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue

        try:
            payload = json.loads(body)
            message = coerce_search_message(payload)
        except (ValueError, PydanticValidationError) as exc:
            log_event(
                "ERROR",
                "search_message_invalid",
                sqs_record_index=index,
                error_code="validation_error",
                error_message=(
                    validation_error_message(exc)
                    if isinstance(exc, PydanticValidationError)
                    else str(exc)[:500]
                ),
            )
            continue

        correlation_id = (
            _extract_message_attribute(record, "correlation_id") or message.entity_id
        )

        if not _dispatch_entity_search(message, settings, repository, correlation_id):
            continue

        processed += 1

    return {"processed": processed}


def _dispatch_entity_search(
    message: EntitySearchMessage,
    settings: Any,
    repository: Any,
    correlation_id: str,
) -> bool:
    if message.entity_type == "label":
        return _run_label_search(message, settings, repository, correlation_id)

    log_event(
        "WARNING",
        "search_entity_type_unsupported",
        correlation_id=correlation_id,
        entity_type=message.entity_type,
        entity_id=message.entity_id,
        prompt_slug=message.prompt_slug,
    )
    return False


def _run_label_search(
    message: EntitySearchMessage,
    settings: Any,
    repository: Any,
    correlation_id: str,
) -> bool:
    label_name = str(message.context.get("label_name", "")).strip()
    styles = str(message.context.get("styles", "")).strip()
    if not label_name or not styles:
        log_event(
            "ERROR",
            "search_label_context_missing",
            correlation_id=correlation_id,
            entity_id=message.entity_id,
            prompt_slug=message.prompt_slug,
        )
        return False

    log_event(
        "INFO",
        "label_search_started",
        correlation_id=correlation_id,
        entity_id=message.entity_id,
        label_name=label_name,
        styles=styles,
        prompt_slug=message.prompt_slug,
        prompt_version=message.prompt_version,
    )

    try:
        prompt_config = get_prompt(message.prompt_slug, message.prompt_version)
        result = search_label(
            label_name=label_name,
            style=styles,
            config=prompt_config,
            api_key=settings.perplexity_api_key,
        )
        repository.save_search_result(
            result_id=str(uuid4()),
            entity_type="label",
            entity_id=message.entity_id,
            prompt_slug=message.prompt_slug,
            prompt_version=message.prompt_version,
            result=result.model_dump(),
            searched_at=utc_now(),
        )
        log_event(
            "INFO",
            "label_search_completed",
            correlation_id=correlation_id,
            entity_id=message.entity_id,
            label_name=label_name,
            prompt_slug=message.prompt_slug,
            prompt_version=message.prompt_version,
            status_code=200,
        )
        return True
    except Exception as exc:
        is_permanent = isinstance(exc, (ValueError, TypeError, KeyError))
        error_code = (
            "search_permanent_failure"
            if is_permanent
            else "search_transient_failure"
        )
        log_event(
            "ERROR",
            "label_search_failed",
            correlation_id=correlation_id,
            entity_id=message.entity_id,
            label_name=label_name,
            error_code=error_code,
            error_type=exc.__class__.__name__,
            error_message=str(exc)[:500],
            status_code=500,
        )
        if is_permanent:
            return False
        raise


def _extract_message_attribute(record: Mapping[str, Any], key: str) -> str | None:
    attributes = record.get("messageAttributes")
    if not isinstance(attributes, Mapping):
        return None
    value = attributes.get(key)
    if isinstance(value, Mapping):
        candidate = value.get("stringValue")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_search_handler.py tests/unit/test_entity_search_message.py -q
```

Expected: all pre-existing tests still pass plus the 2 new tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/collector/search_handler.py tests/unit/test_search_handler.py
git commit -m "<caveman-commit output>"
```

---

## Task 4: Add SSM Parameter Store fetcher module

**Files:**

- Create: `src/collector/secrets.py`
- Test: `tests/unit/test_secrets.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_secrets.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_fetch_ssm_parameter_decrypts_and_returns_string(monkeypatch) -> None:
    from collector import secrets

    fake_client = MagicMock()
    fake_client.get_parameter.return_value = {
        "Parameter": {"Value": "secret-value"}
    }
    monkeypatch.setattr(secrets, "_ssm_client", lambda: fake_client)
    secrets._fetch_ssm_parameter.cache_clear()

    result = secrets._fetch_ssm_parameter("/clouder/test/key")

    assert result == "secret-value"
    fake_client.get_parameter.assert_called_once_with(
        Name="/clouder/test/key", WithDecryption=True
    )


def test_fetch_ssm_parameter_is_cached(monkeypatch) -> None:
    from collector import secrets

    fake_client = MagicMock()
    fake_client.get_parameter.return_value = {
        "Parameter": {"Value": "cached-value"}
    }
    monkeypatch.setattr(secrets, "_ssm_client", lambda: fake_client)
    secrets._fetch_ssm_parameter.cache_clear()

    secrets._fetch_ssm_parameter("/clouder/test/key2")
    secrets._fetch_ssm_parameter("/clouder/test/key2")

    assert fake_client.get_parameter.call_count == 1


def test_fetch_ssm_parameter_rejects_empty_value(monkeypatch) -> None:
    from collector import secrets

    fake_client = MagicMock()
    fake_client.get_parameter.return_value = {"Parameter": {"Value": ""}}
    monkeypatch.setattr(secrets, "_ssm_client", lambda: fake_client)
    secrets._fetch_ssm_parameter.cache_clear()

    with pytest.raises(RuntimeError, match="empty"):
        secrets._fetch_ssm_parameter("/clouder/empty")


def test_fetch_ssm_parameter_rejects_missing_parameter_field(monkeypatch) -> None:
    from collector import secrets

    fake_client = MagicMock()
    fake_client.get_parameter.return_value = {}
    monkeypatch.setattr(secrets, "_ssm_client", lambda: fake_client)
    secrets._fetch_ssm_parameter.cache_clear()

    with pytest.raises(RuntimeError, match="malformed"):
        secrets._fetch_ssm_parameter("/clouder/missing")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_secrets.py -q
```

Expected: 4 tests FAIL with `ModuleNotFoundError: No module named 'collector.secrets'`.

- [ ] **Step 3: Implement the module**

Create `src/collector/secrets.py`:

```python
"""AWS SSM Parameter Store fetch helpers.

Service-level API keys and OAuth client creds live as SSM SecureString
parameters. The Standard tier is free (up to 10 000 parameters, 4 KB each,
KMS-encrypted via the AWS-managed key). Fetches are cached per container
lifetime — rotating a parameter requires a Lambda recycle, same trade-off
as the previous Secrets Manager-based implementation.
"""

from __future__ import annotations

import functools


def _ssm_client():
    import boto3

    return boto3.client("ssm")


@functools.lru_cache(maxsize=64)
def _fetch_ssm_parameter(name: str) -> str:
    response = _ssm_client().get_parameter(Name=name, WithDecryption=True)
    parameter = response.get("Parameter")
    if not isinstance(parameter, dict):
        raise RuntimeError(
            f"ssm response malformed, missing Parameter field (name={name})"
        )
    value = parameter.get("Value")
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"ssm parameter is empty or not a string (name={name})")
    return value


def reset_cache() -> None:
    _fetch_ssm_parameter.cache_clear()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_secrets.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/collector/secrets.py tests/unit/test_secrets.py
git commit -m "<caveman-commit output>"
```

---

## Task 5: Wire SSM into `settings.py` with env > SSM > Secrets Manager precedence

**Files:**

- Modify: `src/collector/settings.py:35-67, 166-192`
- Test: `tests/unit/test_settings.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_settings.py`:

```python
def test_perplexity_resolved_from_ssm_when_env_absent(monkeypatch):
    from collector import settings as s
    from collector import secrets

    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("PERPLEXITY_API_KEY_SECRET_ARN", raising=False)
    monkeypatch.setenv(
        "PERPLEXITY_API_KEY_SSM_PARAMETER", "/clouder/perplexity/api_key"
    )

    fetched = {"names": []}

    def fake_ssm(name: str) -> str:
        fetched["names"].append(name)
        return "pplx-ssm-value"

    monkeypatch.setattr(secrets, "_fetch_ssm_parameter", fake_ssm)
    s.reset_settings_cache()

    settings = s.get_search_worker_settings()
    assert settings.perplexity_api_key == "pplx-ssm-value"
    assert fetched["names"] == ["/clouder/perplexity/api_key"]

    s.reset_settings_cache()


def test_perplexity_direct_env_wins_over_ssm(monkeypatch):
    from collector import settings as s
    from collector import secrets

    monkeypatch.setenv("PERPLEXITY_API_KEY", "direct-key")
    monkeypatch.setenv(
        "PERPLEXITY_API_KEY_SSM_PARAMETER", "/clouder/perplexity/api_key"
    )

    def must_not_call(_name: str) -> str:
        raise AssertionError("should not fetch SSM when direct env set")

    monkeypatch.setattr(secrets, "_fetch_ssm_parameter", must_not_call)
    s.reset_settings_cache()

    settings = s.get_search_worker_settings()
    assert settings.perplexity_api_key == "direct-key"

    s.reset_settings_cache()


def test_perplexity_ssm_wins_over_secrets_manager_fallback(monkeypatch):
    from collector import settings as s
    from collector import secrets

    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setenv(
        "PERPLEXITY_API_KEY_SECRET_ARN",
        "arn:aws:secretsmanager:us-east-1:123:secret:p-abc",
    )
    monkeypatch.setenv(
        "PERPLEXITY_API_KEY_SSM_PARAMETER", "/clouder/perplexity/api_key"
    )

    def fake_ssm(_name: str) -> str:
        return "ssm-wins"

    def must_not_call(_arn: str) -> str:
        raise AssertionError("should not fall back to Secrets Manager when SSM set")

    monkeypatch.setattr(secrets, "_fetch_ssm_parameter", fake_ssm)
    monkeypatch.setattr(s, "_fetch_secret_string", must_not_call)
    s.reset_settings_cache()

    settings = s.get_search_worker_settings()
    assert settings.perplexity_api_key == "ssm-wins"

    s.reset_settings_cache()


def test_spotify_creds_from_ssm(monkeypatch):
    from collector import settings as s
    from collector import secrets

    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv(
        "SPOTIFY_CLIENT_ID_SSM_PARAMETER", "/clouder/spotify/client_id"
    )
    monkeypatch.setenv(
        "SPOTIFY_CLIENT_SECRET_SSM_PARAMETER", "/clouder/spotify/client_secret"
    )

    def fake_ssm(name: str) -> str:
        return {
            "/clouder/spotify/client_id": "cid-ssm",
            "/clouder/spotify/client_secret": "csecret-ssm",
        }[name]

    monkeypatch.setattr(secrets, "_fetch_ssm_parameter", fake_ssm)
    s.reset_settings_cache()

    settings = s.get_spotify_worker_settings()
    assert settings.spotify_client_id == "cid-ssm"
    assert settings.spotify_client_secret == "csecret-ssm"

    s.reset_settings_cache()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_settings.py -q
```

Expected: 4 new tests FAIL (existing tests still pass).

- [ ] **Step 3: Implement SSM code path in settings**

Replace `_resolve_simple_secret` in `src/collector/settings.py` with:

```python
def _resolve_simple_secret(env_key: str, arn_env_key: str) -> str:
    """Resolve a scalar secret with precedence: direct env > SSM > Secrets Manager.

    For a given env_key "PERPLEXITY_API_KEY" the helpers checks:
        1. env var PERPLEXITY_API_KEY (direct value)
        2. env var PERPLEXITY_API_KEY_SSM_PARAMETER (SSM param name)
        3. env var PERPLEXITY_API_KEY_SECRET_ARN (legacy Secrets Manager)

    Returns "" when none of them resolve.
    """
    from collector import secrets

    direct = os.environ.get(env_key, "").strip()
    if direct:
        return direct

    ssm_env_key = f"{env_key}_SSM_PARAMETER"
    ssm_name = os.environ.get(ssm_env_key, "").strip()
    if ssm_name:
        return secrets._fetch_ssm_parameter(ssm_name)

    arn = os.environ.get(arn_env_key, "").strip()
    if arn:
        return _fetch_secret_string(arn)

    return ""
```

Replace `_resolve_spotify_credentials` in `src/collector/settings.py` with:

```python
def _resolve_spotify_credentials() -> tuple[str, str]:
    """Resolve (client_id, client_secret) with precedence: direct env > SSM > SM.

    SSM layout stores client_id and client_secret as TWO SecureString parameters
    to avoid JSON marshalling issues and to allow per-field rotation.
    """
    from collector import secrets

    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return client_id, client_secret

    ssm_id_name = os.environ.get("SPOTIFY_CLIENT_ID_SSM_PARAMETER", "").strip()
    ssm_secret_name = os.environ.get("SPOTIFY_CLIENT_SECRET_SSM_PARAMETER", "").strip()
    if ssm_id_name and ssm_secret_name:
        client_id = client_id or secrets._fetch_ssm_parameter(ssm_id_name)
        client_secret = client_secret or secrets._fetch_ssm_parameter(ssm_secret_name)
        return client_id, client_secret

    arn = os.environ.get("SPOTIFY_CREDENTIALS_SECRET_ARN", "").strip()
    if arn:
        raw = _fetch_secret_string(arn)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"spotify credentials secret is not valid JSON (arn={arn}): {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise RuntimeError(
                f"spotify credentials secret JSON must be an object (arn={arn})"
            )
        client_id = client_id or str(data.get("client_id", ""))
        client_secret = client_secret or str(data.get("client_secret", ""))

    return client_id, client_secret
```

Extend `reset_settings_cache` in `src/collector/settings.py`:

```python
def reset_settings_cache() -> None:
    get_api_settings.cache_clear()
    get_worker_settings.cache_clear()
    get_migration_settings.cache_clear()
    get_data_api_settings.cache_clear()
    get_logging_settings.cache_clear()
    get_search_worker_settings.cache_clear()
    get_spotify_worker_settings.cache_clear()
    if hasattr(_fetch_secret_string, "cache_clear"):
        _fetch_secret_string.cache_clear()

    from collector import secrets as _secrets_module

    _secrets_module.reset_cache()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_settings.py -q
```

Expected: all tests pass, including the four new SSM tests and the existing Secrets Manager tests.

- [ ] **Step 5: Commit**

```bash
git add src/collector/settings.py tests/unit/test_settings.py
git commit -m "<caveman-commit output>"
```

---

## Task 6: Terraform — SSM resources and IAM permissions

**Files:**

- Modify: `infra/variables.tf` (add SSM variables)
- Modify: `infra/iam.tf` (add `ssm:GetParameter` statement)
- Modify: `infra/lambda.tf` (pass SSM param names to search + spotify Lambdas)
- Modify: `infra/terraform.tfvars.example`

- [ ] **Step 1: Add variables**

Append to `infra/variables.tf`:

```hcl
variable "perplexity_api_key_ssm_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the Perplexity API key. Takes precedence over perplexity_api_key_secret_arn."
  type        = string
  default     = ""
}

variable "spotify_client_id_ssm_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the Spotify client_id."
  type        = string
  default     = ""
}

variable "spotify_client_secret_ssm_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the Spotify client_secret."
  type        = string
  default     = ""
}
```

Update the validation on `perplexity_api_key_secret_arn` and `spotify_credentials_secret_arn` so an empty string is accepted (needed once SSM takes over):

```hcl
variable "perplexity_api_key_secret_arn" {
  description = "Legacy Secrets Manager ARN for the Perplexity API key. Empty when SSM is used."
  type        = string
  default     = ""

  validation {
    condition     = var.perplexity_api_key_secret_arn == "" || can(regex("^arn:aws:secretsmanager:", var.perplexity_api_key_secret_arn))
    error_message = "perplexity_api_key_secret_arn must be empty or a valid Secrets Manager ARN."
  }
}
```

Apply the same relaxation to `spotify_credentials_secret_arn`. (Update lines `207-214` and `224-231`.)

- [ ] **Step 2: Add IAM permissions**

Append a new statement to the search-worker IAM policy in `infra/iam.tf` (the block that currently lists `perplexity_api_key_secret_arn` around line 131):

```hcl
  statement {
    sid    = "AllowReadSearchWorkerSsmParameters"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
    ]
    resources = compact([
      var.perplexity_api_key_ssm_parameter != "" ? "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.perplexity_api_key_ssm_parameter}" : "",
    ])
  }

  statement {
    sid    = "AllowReadSsmKmsForSecureString"
    effect = "Allow"
    actions = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }
```

Add a matching policy block to the Spotify worker IAM policy (around the `spotify_credentials_secret_arn` block):

```hcl
  statement {
    sid    = "AllowReadSpotifyWorkerSsmParameters"
    effect = "Allow"
    actions = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = compact([
      var.spotify_client_id_ssm_parameter != "" ? "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.spotify_client_id_ssm_parameter}" : "",
      var.spotify_client_secret_ssm_parameter != "" ? "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.spotify_client_secret_ssm_parameter}" : "",
    ])
  }
```

If `data "aws_caller_identity" "current"` is not yet declared in `iam.tf`, add at the top:

```hcl
data "aws_caller_identity" "current" {}
```

- [ ] **Step 3: Pass SSM names to Lambdas**

In `infra/lambda.tf`, locate the search worker resource block (around line 116 where `PERPLEXITY_API_KEY_SECRET_ARN` is set) and add:

```hcl
      PERPLEXITY_API_KEY_SSM_PARAMETER = var.perplexity_api_key_ssm_parameter
```

Locate the Spotify worker block (around line 150) and add:

```hcl
      SPOTIFY_CLIENT_ID_SSM_PARAMETER     = var.spotify_client_id_ssm_parameter
      SPOTIFY_CLIENT_SECRET_SSM_PARAMETER = var.spotify_client_secret_ssm_parameter
```

- [ ] **Step 4: Document tfvars**

Append to `infra/terraform.tfvars.example`:

```hcl
# --- New preferred path (SSM Parameter Store SecureString) ---
# When these are set, the legacy _secret_arn variables can be empty.
perplexity_api_key_ssm_parameter    = "/clouder/perplexity/api_key"
spotify_client_id_ssm_parameter     = "/clouder/spotify/client_id"
spotify_client_secret_ssm_parameter = "/clouder/spotify/client_secret"
```

- [ ] **Step 5: Validate and commit**

```bash
cd infra
terraform fmt
terraform init -backend=false
terraform validate
cd ..
git add infra/variables.tf infra/iam.tf infra/lambda.tf infra/terraform.tfvars.example
git commit -m "<caveman-commit output>"
```

Expected: `terraform validate` succeeds.

> **Operator note (not a code step):** the actual SSM Parameter Store entries `/clouder/perplexity/api_key`, `/clouder/spotify/client_id`, `/clouder/spotify/client_secret` must be created out-of-band (AWS Console or `aws ssm put-parameter --type SecureString`) before the next `terraform apply`. Leave the existing Secrets Manager entries in place — the fallback path still honours them for the rollout window.

---

## Task 7: Enable SSM in the tfvars of the deploy environment

**Files:**

- Modify: `infra/terraform.tfvars` (operator-local, not committed)

This is a one-off deploy step, not a TDD task. Performed by the operator once the SSM parameters (Task 6 operator note) exist.

- [ ] **Step 1: Populate tfvars with SSM names**

In the operator-local `infra/terraform.tfvars`:

```hcl
perplexity_api_key_ssm_parameter    = "/clouder/perplexity/api_key"
spotify_client_id_ssm_parameter     = "/clouder/spotify/client_id"
spotify_client_secret_ssm_parameter = "/clouder/spotify/client_secret"

# Legacy, kept until rollout window closes:
perplexity_api_key_secret_arn   = "arn:aws:secretsmanager:us-east-1:...:secret:p-abc"
spotify_credentials_secret_arn  = "arn:aws:secretsmanager:us-east-1:...:secret:s-abc"
```

- [ ] **Step 2: Plan and apply**

```bash
cd infra
terraform plan -out plan.out
# Review: the plan should add ssm:GetParameter permissions and
# set PERPLEXITY_API_KEY_SSM_PARAMETER / SPOTIFY_CLIENT_*_SSM_PARAMETER env vars.
terraform apply plan.out
cd ..
```

- [ ] **Step 3: Smoke-test**

Invoke a label-search message end-to-end:

```bash
aws lambda invoke --function-name "$(cd infra && terraform output -raw search_worker_lambda_function_name)" \
  --payload '{"Records":[{"body":"{\"entity_type\":\"label\",\"entity_id\":\"smoke-1\",\"prompt_slug\":\"label_info\",\"prompt_version\":\"v1\",\"context\":{\"label_name\":\"Smoke\",\"styles\":\"Techno\"}}}"}]}' \
  /tmp/lambda-out.json --cli-binary-format raw-in-base64-out
cat /tmp/lambda-out.json
```

Expected: `{"processed":1}` (or 0 if Perplexity rejects the smoke request — look for the log event `label_search_completed` or `label_search_failed`). The key invariant is that the Lambda did not fail to resolve the Perplexity API key.

- [ ] **Step 4: Record the cutover**

Commit only the documentation note (no runtime code changes here):

```bash
# No git changes expected from this task — operator deploy only.
```

If you want a checklist artifact for the team, append a bullet to `docs/data-model.md` or to an ops log; otherwise skip.

---

## Task 8: Alembic migration — bootstrap `clouder_migrator` DB role

**Files:**

- Create: `alembic/versions/20260419_07_bootstrap_iam_auth.py`
- Test: `tests/unit/test_migration_07_sql.py` (new, inspects the migration SQL text)

- [ ] **Step 1: Write a failing test that the migration module is importable and declares the expected revision chain**

Create `tests/unit/test_migration_07_sql.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration(filename: str):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("migration_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_07_revision_chain() -> None:
    module = _load_migration("20260419_07_bootstrap_iam_auth.py")
    assert module.revision == "20260419_07"
    assert module.down_revision == "20260315_06"


def test_migration_07_creates_role_and_grants_rds_iam() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260419_07_bootstrap_iam_auth.py"
    )
    text = path.read_text()
    assert "clouder_migrator" in text
    assert "rds_iam" in text
    assert "LOGIN" in text or "CREATE USER" in text
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/unit/test_migration_07_sql.py -q
```

Expected: FAIL with `FileNotFoundError` or spec-loading error.

- [ ] **Step 3: Write the migration**

Create `alembic/versions/20260419_07_bootstrap_iam_auth.py`:

```python
"""bootstrap clouder_migrator DB role with rds_iam grant for IAM auth

Revision ID: 20260419_07
Revises: 20260315_06
Create Date: 2026-04-19 00:00:00
"""

from __future__ import annotations

from alembic import op

revision = "20260419_07"
down_revision = "20260315_06"
branch_labels = None
depends_on = None


UPGRADE_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'clouder_migrator') THEN
        CREATE ROLE clouder_migrator WITH LOGIN;
    END IF;
END
$$;

GRANT rds_iam TO clouder_migrator;

GRANT CONNECT ON DATABASE :"database_name" TO clouder_migrator;
GRANT USAGE, CREATE ON SCHEMA public TO clouder_migrator;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO clouder_migrator;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO clouder_migrator;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL PRIVILEGES ON TABLES TO clouder_migrator;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL PRIVILEGES ON SEQUENCES TO clouder_migrator;
"""

DOWNGRADE_SQL = """
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM clouder_migrator;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM clouder_migrator;
REVOKE USAGE, CREATE ON SCHEMA public FROM clouder_migrator;
REVOKE CONNECT ON DATABASE :"database_name" FROM clouder_migrator;
REVOKE rds_iam FROM clouder_migrator;
DROP ROLE IF EXISTS clouder_migrator;
"""


def upgrade() -> None:
    bind = op.get_bind()
    database_name = bind.engine.url.database
    op.execute(UPGRADE_SQL.replace(':"database_name"', f'"{database_name}"'))


def downgrade() -> None:
    bind = op.get_bind()
    database_name = bind.engine.url.database
    op.execute(DOWNGRADE_SQL.replace(':"database_name"', f'"{database_name}"'))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_migration_07_sql.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Run alembic locally to verify the migration applies**

```bash
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Expected: no errors. (If running Postgres locally does not have `rds_iam` — which is RDS-specific — the `GRANT rds_iam` statement fails. Guard the local case:)

If your local Postgres does not have the `rds_iam` role, add a guard at the top of `UPGRADE_SQL`:

```sql
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam') THEN
        GRANT rds_iam TO clouder_migrator;
    END IF;
END
$$;
```

Adjust the assertion in the test accordingly — the SQL still contains `rds_iam`, only the grant is gated.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/20260419_07_bootstrap_iam_auth.py tests/unit/test_migration_07_sql.py
git commit -m "<caveman-commit output>"
```

---

## Task 9: Migration Lambda — support IAM auth mode

**Files:**

- Modify: `src/collector/migration_handler.py:74-104`
- Modify: `src/collector/settings.py` (add two fields)
- Test: `tests/unit/test_migration_handler_iam.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_migration_handler_iam.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_iam_mode_uses_generate_db_auth_token(monkeypatch) -> None:
    from collector import migration_handler as mh
    from collector import settings as s

    monkeypatch.setenv("AURORA_AUTH_MODE", "iam")
    monkeypatch.setenv("AURORA_WRITER_ENDPOINT", "writer.example")
    monkeypatch.setenv("AURORA_PORT", "5432")
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    monkeypatch.setenv("AURORA_DB_USER", "clouder_migrator")
    monkeypatch.setenv("AURORA_SECRET_ARN", "arn:aws:secretsmanager:::dummy")
    s.reset_settings_cache()

    fake_rds = MagicMock()
    fake_rds.generate_db_auth_token.return_value = "iam-token-value"
    monkeypatch.setattr(mh, "_rds_client", lambda: fake_rds)

    url = mh._build_alembic_database_url()

    assert "iam-token-value" in url
    assert "clouder_migrator" in url
    fake_rds.generate_db_auth_token.assert_called_once_with(
        DBHostname="writer.example",
        Port=5432,
        DBUsername="clouder_migrator",
    )
    s.reset_settings_cache()


def test_password_mode_falls_back_to_secrets_manager(monkeypatch) -> None:
    from collector import migration_handler as mh
    from collector import settings as s

    monkeypatch.setenv("AURORA_AUTH_MODE", "password")
    monkeypatch.setenv("AURORA_WRITER_ENDPOINT", "writer.example")
    monkeypatch.setenv("AURORA_PORT", "5432")
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    monkeypatch.setenv("AURORA_SECRET_ARN", "arn:aws:secretsmanager:::real")
    s.reset_settings_cache()

    def fake_read_secret(arn: str) -> dict:
        assert arn == "arn:aws:secretsmanager:::real"
        return {"username": "master", "password": "pw"}

    monkeypatch.setattr(mh, "_read_secret", fake_read_secret)

    url = mh._build_alembic_database_url()

    assert "master" in url
    assert "pw" in url
    s.reset_settings_cache()


def test_default_mode_is_password(monkeypatch) -> None:
    from collector import migration_handler as mh
    from collector import settings as s

    monkeypatch.delenv("AURORA_AUTH_MODE", raising=False)
    monkeypatch.setenv("AURORA_WRITER_ENDPOINT", "writer.example")
    monkeypatch.setenv("AURORA_PORT", "5432")
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    monkeypatch.setenv("AURORA_SECRET_ARN", "arn:aws:secretsmanager:::real")
    s.reset_settings_cache()

    def fake_read_secret(_arn: str) -> dict:
        return {"username": "master", "password": "pw"}

    monkeypatch.setattr(mh, "_read_secret", fake_read_secret)

    url = mh._build_alembic_database_url()
    assert "master" in url
    s.reset_settings_cache()


def test_iam_mode_missing_db_user_raises(monkeypatch) -> None:
    from collector import migration_handler as mh
    from collector import settings as s

    monkeypatch.setenv("AURORA_AUTH_MODE", "iam")
    monkeypatch.setenv("AURORA_WRITER_ENDPOINT", "writer.example")
    monkeypatch.setenv("AURORA_PORT", "5432")
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    monkeypatch.setenv("AURORA_SECRET_ARN", "arn:aws:secretsmanager:::dummy")
    monkeypatch.delenv("AURORA_DB_USER", raising=False)
    s.reset_settings_cache()

    with pytest.raises(RuntimeError, match="AURORA_DB_USER"):
        mh._build_alembic_database_url()

    s.reset_settings_cache()
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/unit/test_migration_handler_iam.py -q
```

Expected: all four tests FAIL (`_rds_client`/`AURORA_AUTH_MODE` unknown).

- [ ] **Step 3: Extend `MigrationSettings`**

In `src/collector/settings.py`, replace the `MigrationSettings` class:

```python
class MigrationSettings(_SettingsBase):
    aurora_secret_arn: str = Field(default="", alias="AURORA_SECRET_ARN")
    aurora_writer_endpoint: str = Field(alias="AURORA_WRITER_ENDPOINT")
    aurora_database: str = Field(alias="AURORA_DATABASE")
    aurora_port: int = Field(default=5432, alias="AURORA_PORT")
    aurora_auth_mode: str = Field(default="password", alias="AURORA_AUTH_MODE")
    aurora_db_user: str = Field(default="", alias="AURORA_DB_USER")
```

- [ ] **Step 4: Implement the IAM branch in `migration_handler.py`**

Replace `_build_alembic_database_url` in `src/collector/migration_handler.py` with:

```python
def _rds_client():
    import boto3

    return boto3.client("rds")


def _build_alembic_database_url() -> str:
    settings = get_migration_settings()
    mode = settings.aurora_auth_mode.strip().lower()

    if mode == "iam":
        username = settings.aurora_db_user.strip()
        if not username:
            raise RuntimeError(
                "AURORA_DB_USER is required when AURORA_AUTH_MODE=iam"
            )
        token = _rds_client().generate_db_auth_token(
            DBHostname=settings.aurora_writer_endpoint,
            Port=settings.aurora_port,
            DBUsername=username,
        )
        return (
            f"postgresql+psycopg://{quote_plus(username)}:{quote_plus(token)}"
            f"@{settings.aurora_writer_endpoint}:{settings.aurora_port}"
            f"/{settings.aurora_database}?sslmode=require"
        )

    if not settings.aurora_secret_arn.strip():
        raise RuntimeError(
            "AURORA_SECRET_ARN is required when AURORA_AUTH_MODE=password"
        )

    secret = _read_secret(settings.aurora_secret_arn)
    username = str(secret.get("username", "")).strip()
    password = str(secret.get("password", "")).strip()
    if not username or not password:
        raise RuntimeError("username/password are missing in Aurora secret")

    return (
        f"postgresql+psycopg://{quote_plus(username)}:{quote_plus(password)}"
        f"@{settings.aurora_writer_endpoint}:{settings.aurora_port}/{settings.aurora_database}?sslmode=require"
    )
```

Remove or leave the original `_read_secret` function as-is below — it is still called in password mode.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_migration_handler_iam.py tests/unit/test_settings.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/collector/settings.py src/collector/migration_handler.py tests/unit/test_migration_handler_iam.py
git commit -m "<caveman-commit output>"
```

---

## Task 10: Terraform — `rds-db:connect` permission + `AURORA_AUTH_MODE` env

**Files:**

- Modify: `infra/iam.tf` (migration Lambda role)
- Modify: `infra/lambda.tf` (migration Lambda env)
- Modify: `infra/variables.tf` (add `migration_db_user`)

- [ ] **Step 1: Add variable**

Append to `infra/variables.tf`:

```hcl
variable "migration_db_user" {
  description = "PostgreSQL role name used by the migration Lambda when AURORA_AUTH_MODE=iam. Must have rds_iam granted."
  type        = string
  default     = "clouder_migrator"
}

variable "migration_aurora_auth_mode" {
  description = "Auth mode for the migration Lambda: 'password' (default, reads AURORA_SECRET_ARN from Secrets Manager) or 'iam' (generates an RDS IAM token)."
  type        = string
  default     = "password"

  validation {
    condition     = contains(["password", "iam"], var.migration_aurora_auth_mode)
    error_message = "migration_aurora_auth_mode must be either 'password' or 'iam'."
  }
}
```

- [ ] **Step 2: Add IAM permission statement**

In `infra/iam.tf`, locate the migration Lambda policy document (look for the block that grants `secretsmanager:GetSecretValue` on the Aurora secret — around line 123). Append a new statement to the same policy:

```hcl
  statement {
    sid     = "AllowRdsDbConnectForMigration"
    effect  = "Allow"
    actions = ["rds-db:connect"]
    resources = [
      "arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_rds_cluster.aurora.cluster_resource_id}/${var.migration_db_user}"
    ]
  }
```

- [ ] **Step 3: Pass the env vars to the migration Lambda**

In `infra/lambda.tf`, locate the migration Lambda resource (the one with `AURORA_WRITER_ENDPOINT` — around line 85). Add to its `environment.variables` block:

```hcl
      AURORA_AUTH_MODE = var.migration_aurora_auth_mode
      AURORA_DB_USER   = var.migration_db_user
```

- [ ] **Step 4: Validate**

```bash
cd infra
terraform fmt
terraform init -backend=false
terraform validate
cd ..
```

Expected: success.

- [ ] **Step 5: Commit**

```bash
git add infra/variables.tf infra/iam.tf infra/lambda.tf
git commit -m "<caveman-commit output>"
```

---

## Task 11: Cutover — switch migration Lambda to IAM mode, remove VPC endpoint

**Files:**

- Modify: `infra/terraform.tfvars` (operator-local)
- Modify: `infra/iam.tf` (remove Secrets Manager permission from migration Lambda, gated)
- Modify: `infra/network.tf` (remove the VPC endpoint when `enable_secretsmanager_vpc_endpoint = false`)

This task has two deploys: first a rehearsal in IAM mode while the VPC endpoint is still present, then the cleanup deploy that removes the endpoint.

- [ ] **Step 1: Deploy A — enable IAM mode, keep VPC endpoint**

In `infra/terraform.tfvars`:

```hcl
migration_aurora_auth_mode    = "iam"
migration_db_user             = "clouder_migrator"
enable_secretsmanager_vpc_endpoint = true
```

Apply:

```bash
cd infra
terraform plan -out plan.out
terraform apply plan.out
cd ..
```

- [ ] **Step 2: Rehearsal — run one migration in IAM mode**

Invoke the migration Lambda with a no-op `upgrade head` (migration 07 is idempotent because of `IF NOT EXISTS`):

```bash
aws lambda invoke --function-name "$(cd infra && terraform output -raw migration_lambda_function_name)" \
  --payload '{"action":"upgrade","revision":"head"}' /tmp/mig-out.json \
  --cli-binary-format raw-in-base64-out
cat /tmp/mig-out.json
```

Expected: `{"status":"ok", ...}`. If this fails, **do not proceed** — the `rds_iam` grant or the IAM policy on the Lambda role is wrong. Revert `migration_aurora_auth_mode` to `password` and investigate.

- [ ] **Step 3: Remove Secrets Manager permission from migration Lambda**

In `infra/iam.tf`, delete the statement that grants `secretsmanager:GetSecretValue` on the Aurora master secret from the migration Lambda policy (the block near line 123):

```diff
-  statement {
-    sid       = "AllowReadAuroraSecret"
-    effect    = "Allow"
-    actions   = ["secretsmanager:GetSecretValue"]
-    resources = [try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "*")]
-  }
```

(Keep the permission for other Lambdas that still need it — verify by grepping for `master_user_secret` first.)

- [ ] **Step 4: Deploy B — remove VPC endpoint**

In `infra/terraform.tfvars`:

```hcl
enable_secretsmanager_vpc_endpoint = false
```

Apply:

```bash
cd infra
terraform plan -out plan.out
# Review: expect destroy of aws_vpc_endpoint.secretsmanager[0] and related SG / DNS.
terraform apply plan.out
cd ..
```

Expected: the VPC endpoint resource is destroyed. Post-apply `terraform output` should no longer report it.

- [ ] **Step 5: Smoke test**

```bash
aws lambda invoke --function-name "$(cd infra && terraform output -raw migration_lambda_function_name)" \
  --payload '{"action":"upgrade","revision":"head"}' /tmp/mig-out.json \
  --cli-binary-format raw-in-base64-out
cat /tmp/mig-out.json
```

Expected: `{"status":"ok", ...}`. Migration Lambda runs without the VPC endpoint or Secrets Manager access.

- [ ] **Step 6: Commit the code changes**

```bash
git add infra/iam.tf
git commit -m "<caveman-commit output>"
```

(No code change for the tfvars — those are operator-local.)

---

## Self-Review Notes

This plan covers spec sections:

- §6.4 (Generic search worker) → Tasks 1-3.
- §8.1 (SSM migration) → Tasks 4-7.
- §8.2 (Aurora IAM auth + VPC endpoint removal) → Tasks 8-11.

Not covered (intentionally — belongs to later plans):

- Any `clouder_*` column additions (Plan 2).
- `providers/` package and registry (Plan 3).
- `vendor_track_map`, `match_review_queue` tables (Plan 4). (`user_vendor_tokens` / `release_mirror_runs` were Plan 5 — cancelled.)

Sanity checks performed:

- `EntitySearchMessage` field names (`entity_type`, `entity_id`, `prompt_slug`, `prompt_version`, `context`) are used consistently across Tasks 1-3.
- `coerce_search_message` handles both shapes, preserved across Tasks 2-3.
- SSM env var naming (`<NAME>_SSM_PARAMETER`) is consistent in `settings.py`, tests, and Terraform.
- `AURORA_AUTH_MODE` and `AURORA_DB_USER` env var names match between migration handler, settings, Terraform, and tests.
- `clouder_migrator` is the single canonical DB role name used in the migration, Terraform var default, and IAM policy resource.
