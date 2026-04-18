# Vendor-Sync Plan 5 — Release Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the vendor-sync loop: user creates a playlist on Spotify, hits `POST /release_mirror`, and the service creates mirrored playlists on all enabled vendors (YT Music, Deezer, Apple, Tidal, plus Spotify). Matching done inline via Plan 4 logic (with cache reads), missing matches logged per-vendor.

**Architecture:** New `release_mirror_worker` Lambda is SQS-triggered. It reads Spotify playlist (user OAuth token from `user_vendor_tokens`, KMS envelope-decrypted), maps each Spotify track → canonical via `identity_map`, then for each target vendor checks `vendor_track_map` / falls back to inline lookup, finally calls `ExportProvider.create_playlist`. Writes `release_mirror_runs` with per-vendor results. User OAuth flow is NOT implemented; tokens are seeded manually for testing.

**Tech Stack:** Python 3.12, boto3 (SQS, KMS, Lambda), pydantic v2, AES-GCM via `cryptography`, API Gateway HTTP.

**Spec:** [docs/superpowers/specs/2026-04-18-vendor-sync-readiness-design.md](../specs/2026-04-18-vendor-sync-readiness-design.md) §5.1 (user_vendor_tokens, release_mirror_runs), §7.2 (release workflow), §7.3 (API), §7.4 (user tokens), §8.3 (KMS envelope), §8.5 partial (DLQ).

**Prereqs:** Plans 1, 2, 3, 4 merged. `VendorTrackRef`, `ExportProvider`, registry accessors, match cache, error classes all available.

---

## File Structure

New files:
- `alembic/versions/20260422_11_release_mirror_tables.py`
- `src/collector/crypto.py` — KMS envelope encrypt/decrypt.
- `src/collector/release_mirror_handler.py` — SQS-triggered mirror worker.
- `src/collector/schemas.py` — add `ReleaseMirrorMessage`, `ReleaseMirrorRequestIn`.
- `scripts/store_user_token.py` — dev CLI to seed `user_vendor_tokens`.
- `tests/unit/test_migration_11_sql.py`
- `tests/unit/test_crypto_envelope.py`
- `tests/unit/test_release_mirror_handler.py`
- `tests/integration/test_release_mirror_flow.py`

Modified files:
- `src/collector/db_models.py` — `UserVendorToken`, `ReleaseMirrorRun` models.
- `src/collector/repositories.py` — token CRUD + mirror_runs CRUD.
- `src/collector/handler.py` — `POST /release_mirror` + `GET /release_mirror/{run_id}`.
- `src/collector/providers/spotify/lookup.py` — add `fetch_playlist(user_token, playlist_id)` method (user OAuth-scoped Spotify call).
- `infra/lambda.tf` — add `aws_lambda_function.release_mirror_worker` + event source mapping.
- `infra/sqs.tf` — new queue + DLQ.
- `infra/iam.tf` — KMS encrypt/decrypt + new SQS queue in statements.
- `infra/api_gateway.tf` — new routes.
- `infra/main.tf` — locals for queue / function names.
- `infra/variables.tf` — mirror queue settings.
- `infra/kms.tf` (new) — `alias/clouder-user-tokens` CMK.
- `infra/outputs.tf` — output function name + route URL.
- `infra/logging.tf` — DLQ alarm.
- `src/collector/errors.py` — already has `UserTokenMissingError` from Plan 4.
- `requirements-lambda.txt` — add `cryptography`.

---

## Task 1: Alembic migration — `user_vendor_tokens` + `release_mirror_runs`

**Files:**
- Create: `alembic/versions/20260422_11_release_mirror_tables.py`
- Test: `tests/unit/test_migration_11_sql.py`

- [ ] **Step 1: Test (same pattern as migrations 09/10)**

```python
from pathlib import Path

def test_migration_11_revision_chain():
    # revision == "20260422_11", down_revision == "20260421_10"
    ...

def test_migration_11_tables_and_columns():
    text = (Path(__file__).resolve().parents[2]
            / "alembic/versions/20260422_11_release_mirror_tables.py").read_text()
    for token in [
        "user_vendor_tokens", "release_mirror_runs",
        "access_token_enc", "refresh_token_enc", "data_key_enc",
        "source_playlist_id", "target_vendors", "results",
    ]:
        assert token in text
```

- [ ] **Step 2: Implementation**

```python
# alembic/versions/20260422_11_release_mirror_tables.py
"""user_vendor_tokens + release_mirror_runs

Revision ID: 20260422_11
Revises: 20260421_10
Create Date: 2026-04-22 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, BYTEA
from alembic import op

revision = "20260422_11"
down_revision = "20260421_10"


def upgrade() -> None:
    op.create_table(
        "user_vendor_tokens",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("vendor", sa.String(32), nullable=False),
        sa.Column("access_token_enc", BYTEA, nullable=False),
        sa.Column("refresh_token_enc", BYTEA, nullable=True),
        sa.Column("data_key_enc", BYTEA, nullable=False),
        sa.Column("scope", sa.Text, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "vendor", name="pk_user_vendor_tokens"),
    )

    op.create_table(
        "release_mirror_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("source_vendor", sa.String(32), nullable=False),
        sa.Column("source_playlist_id", sa.String(128), nullable=False),
        sa.Column("target_vendors", JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("results", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_table("release_mirror_runs")
    op.drop_table("user_vendor_tokens")
```

- [ ] **Step 3: SQLAlchemy models in `db_models.py`**

```python
class UserVendorToken(Base):
    __tablename__ = "user_vendor_tokens"
    __table_args__ = (PrimaryKeyConstraint("user_id", "vendor"),)

    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    vendor: Mapped[str] = mapped_column(String(32), nullable=False)
    access_token_enc: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(BYTEA)
    data_key_enc: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    scope: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReleaseMirrorRun(Base):
    __tablename__ = "release_mirror_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_vendor: Mapped[str] = mapped_column(String(32), nullable=False)
    source_playlist_id: Mapped[str] = mapped_column(String(128), nullable=False)
    target_vendors: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    results: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
```

Import `BYTEA` from `sqlalchemy.dialects.postgresql`.

- [ ] **Step 4: Commit**

---

## Task 2: KMS CMK Terraform

**Files:**
- Create: `infra/kms.tf`
- Modify: `infra/variables.tf` — KMS deletion window.

- [ ] **Step 1: Write Terraform**

```hcl
# infra/kms.tf
resource "aws_kms_key" "user_tokens" {
  description             = "${local.name_prefix} — user vendor OAuth tokens (envelope encryption)"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "user_tokens" {
  name          = "alias/${local.name_prefix}-user-tokens"
  target_key_id = aws_kms_key.user_tokens.key_id
}
```

- [ ] **Step 2: Add IAM statement for Lambda role**

In `infra/iam.tf`, add to the shared policy document:

```hcl
  statement {
    sid     = "AllowKmsForUserTokens"
    effect  = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.user_tokens.arn]
  }
```

- [ ] **Step 3: `terraform fmt && terraform validate`**

- [ ] **Step 4: Commit**

---

## Task 3: `src/collector/crypto.py` — envelope encrypt/decrypt

**Files:**
- Create: `src/collector/crypto.py`
- Test: `tests/unit/test_crypto_envelope.py`
- Modify: `requirements-lambda.txt` + `requirements-dev.txt` — add `cryptography`

- [ ] **Step 1: Test (using `moto` KMS)**

```python
# tests/unit/test_crypto_envelope.py
from __future__ import annotations

import boto3
import pytest
from moto import mock_aws


@mock_aws
def test_envelope_roundtrip(monkeypatch) -> None:
    from collector import crypto

    kms = boto3.client("kms", region_name="us-east-1")
    key = kms.create_key()["KeyMetadata"]
    alias = f"alias/test-tokens"
    kms.create_alias(AliasName=alias, TargetKeyId=key["KeyId"])

    monkeypatch.setenv("CLOUDER_USER_TOKEN_KMS_ALIAS", alias)

    plaintext = b"secret-oauth-token-12345"
    ct, dek = crypto.encrypt_token(plaintext)
    decrypted = crypto.decrypt_token(ct, dek)
    assert decrypted == plaintext


@mock_aws
def test_tampered_ciphertext_fails(monkeypatch) -> None:
    from collector import crypto

    kms = boto3.client("kms", region_name="us-east-1")
    key = kms.create_key()["KeyMetadata"]
    alias = f"alias/test-tokens"
    kms.create_alias(AliasName=alias, TargetKeyId=key["KeyId"])

    monkeypatch.setenv("CLOUDER_USER_TOKEN_KMS_ALIAS", alias)

    ct, dek = crypto.encrypt_token(b"hello")
    tampered = ct[:-1] + bytes([ct[-1] ^ 0x01])
    with pytest.raises(Exception):
        crypto.decrypt_token(tampered, dek)
```

- [ ] **Step 2: Implementation**

```python
# src/collector/crypto.py
"""KMS envelope encryption for user OAuth tokens.

Format: data key (256-bit AES) is generated via KMS. Plaintext is encrypted
with AES-GCM using the data key. Both the ciphertext and the KMS-wrapped
data key are stored in Postgres; decryption fetches the data key from KMS
then AES-GCM decrypts.
"""
from __future__ import annotations

import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _kms_client():
    import boto3
    return boto3.client("kms")


def _alias() -> str:
    alias = os.environ.get("CLOUDER_USER_TOKEN_KMS_ALIAS", "").strip()
    if not alias:
        raise RuntimeError("CLOUDER_USER_TOKEN_KMS_ALIAS env var is required")
    return alias


def encrypt_token(plaintext: bytes) -> tuple[bytes, bytes]:
    """Return (ciphertext_with_nonce, wrapped_data_key)."""
    resp = _kms_client().generate_data_key(KeyId=_alias(), KeySpec="AES_256")
    dek_plain = resp["Plaintext"]
    dek_wrapped = resp["CiphertextBlob"]

    nonce = secrets.token_bytes(12)
    aes = AESGCM(dek_plain)
    ct = aes.encrypt(nonce, plaintext, associated_data=None)
    return nonce + ct, dek_wrapped


def decrypt_token(ciphertext_with_nonce: bytes, wrapped_data_key: bytes) -> bytes:
    if len(ciphertext_with_nonce) < 12:
        raise ValueError("ciphertext too short")
    nonce = ciphertext_with_nonce[:12]
    ct = ciphertext_with_nonce[12:]

    dek_plain = _kms_client().decrypt(CiphertextBlob=wrapped_data_key)["Plaintext"]
    aes = AESGCM(dek_plain)
    return aes.decrypt(nonce, ct, associated_data=None)
```

- [ ] **Step 3: Add `cryptography` dep**

```bash
# requirements-lambda.txt
cryptography>=42.0

# requirements-dev.txt
cryptography>=42.0
moto>=5.0  # if not already present
```

Also update `scripts/package_lambda.sh` only if it does `pip install --target`; otherwise deps are handled by the packaging flow.

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

---

## Task 4: Repository CRUD for tokens + mirror runs

**Files:**
- Modify: `src/collector/repositories.py`
- Test: `tests/unit/test_repositories_mirror.py`

- [ ] Add methods:

```python
@dataclass(frozen=True)
class UserVendorTokenRow:
    user_id: str
    vendor: str
    access_token_enc: bytes
    refresh_token_enc: bytes | None
    data_key_enc: bytes
    scope: str | None
    expires_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class UpsertUserTokenCmd:
    user_id: str
    vendor: str
    access_token_enc: bytes
    refresh_token_enc: bytes | None
    data_key_enc: bytes
    scope: str | None
    expires_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class ReleaseMirrorRunRow:
    run_id: str
    user_id: str
    source_vendor: str
    source_playlist_id: str
    target_vendors: list
    status: str
    started_at: datetime
    finished_at: datetime | None
    results: dict


class ClouderRepository:
    def get_user_token(self, user_id: str, vendor: str) -> UserVendorTokenRow | None: ...
    def upsert_user_token(self, cmd: UpsertUserTokenCmd) -> None: ...
    def create_release_mirror_run(self, ...) -> None: ...
    def update_release_mirror_run(self, run_id, status, finished_at, results) -> None: ...
    def get_release_mirror_run(self, run_id: str) -> ReleaseMirrorRunRow | None: ...
```

Data API passes `BYTEA` as base64 — handle correctly on both insert and select paths. Tests must cover bytes round-trip.

Commit.

---

## Task 5: `scripts/store_user_token.py` CLI

**Files:**
- Create: `scripts/store_user_token.py`

- [ ] **Step 1: CLI**

```python
#!/usr/bin/env python3
"""Seed a user vendor token row. Usage:

    PYTHONPATH=src python scripts/store_user_token.py \\
      --user-id u1 --vendor spotify --access-token ya29.xxx

Reads AURORA_* env to connect via Data API. CLOUDER_USER_TOKEN_KMS_ALIAS
required for encryption. Dev-only (OAuth flow will replace this later).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from collector.crypto import encrypt_token
from collector.repositories import (
    create_clouder_repository_from_env, UpsertUserTokenCmd,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--user-id", required=True)
    p.add_argument("--vendor", required=True)
    p.add_argument("--access-token", required=True)
    p.add_argument("--refresh-token", default=None)
    p.add_argument("--scope", default=None)
    p.add_argument("--expires-in-seconds", type=int, default=None)
    args = p.parse_args()

    ct_access, dek_access = encrypt_token(args.access_token.encode())
    ct_refresh = None
    if args.refresh_token:
        ct_refresh, _ = encrypt_token(args.refresh_token.encode())

    expires_at = None
    if args.expires_in_seconds is not None:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=args.expires_in_seconds)

    repo = create_clouder_repository_from_env()
    if repo is None:
        raise SystemExit("AURORA_* env vars required")

    repo.upsert_user_token(UpsertUserTokenCmd(
        user_id=args.user_id,
        vendor=args.vendor,
        access_token_enc=ct_access,
        refresh_token_enc=ct_refresh,
        data_key_enc=dek_access,
        scope=args.scope,
        expires_at=expires_at,
        updated_at=datetime.now(timezone.utc),
    ))
    print(f"Stored token for user={args.user_id} vendor={args.vendor}")


if __name__ == "__main__":
    main()
```

Note: the refresh token uses a separate DEK here for simplicity. Real implementation could share the DEK (single KMS call); decide by convenience.

- [ ] **Step 2: Commit**

---

## Task 6: Spotify playlist fetch

**Files:**
- Modify: `src/collector/providers/spotify/lookup.py` — add `fetch_playlist` (or create separate module)

- [ ] **Step 1: Method**

```python
class SpotifyLookup:
    # existing methods ...

    def fetch_playlist(self, user_token: str, playlist_id: str) -> list[VendorTrackRef]:
        """Fetch all tracks from a Spotify playlist owned by the user.

        Paginates through Spotify's /playlists/{id}/tracks endpoint with the
        user's OAuth bearer token. Each item is mapped to a VendorTrackRef.
        """
        # httpx GET https://api.spotify.com/v1/playlists/{id}/tracks with
        #   Authorization: Bearer <user_token>
        # Handle pagination via `next` field.
        ...
```

- [ ] **Step 2: Tests**

Mock `httpx.Client.get` to return a paginated playlist. Verify all tracks surfaced.

- [ ] **Step 3: Commit**

---

## Task 7: `ReleaseMirrorMessage` + `ReleaseMirrorRequestIn` schemas

**Files:**
- Modify: `src/collector/schemas.py`

- [ ] Schemas:

```python
class ReleaseMirrorRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    source_playlist_id: str = Field(min_length=1)
    target_vendors: list[str] = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1, max_length=200)

    @field_validator("target_vendors")
    @classmethod
    def _dedupe_and_validate(cls, v: list[str]) -> list[str]:
        cleaned = [x.strip() for x in v if x.strip()]
        if not cleaned:
            raise ValueError("at least one target vendor required")
        return list(dict.fromkeys(cleaned))  # dedupe preserve order


class ReleaseMirrorMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    user_id: str
    source_vendor: str = "spotify"
    source_playlist_id: str
    target_vendors: list[str]
    name: str
```

Tests mirror `EntitySearchMessage` pattern.

---

## Task 8: `release_mirror_handler.py`

**Files:**
- Create: `src/collector/release_mirror_handler.py`
- Test: `tests/unit/test_release_mirror_handler.py`

**Behaviour** (from spec §7.2):
1. Parse SQS → `ReleaseMirrorMessage`.
2. `repository.update_release_mirror_run(status="RUNNING")`.
3. Decrypt Spotify source token via `crypto.decrypt_token`.
4. `SpotifyLookup().fetch_playlist(token, source_playlist_id)` → list of Spotify VendorTrackRef.
5. Map each Spotify track → `clouder_track_id` via `identity_map(source="spotify", entity_type="track", external_id=spotify_id)`. Miss → append to `unmapped_in_canonical[vendor=<all targets>]`.
6. For each target vendor:
    a. For each matched `clouder_track_id`: check `vendor_track_map`. Cache hit → use; miss → inline lookup (ISRC then fuzzy), same scoring as Plan 4.
    b. Build list of `VendorTrackRef` (matched) + `missing_in_vendor` list.
    c. Decrypt per-vendor user token (from `user_vendor_tokens(user_id, vendor)`).
    d. `registry.get_exporter(vendor).create_playlist(user_token, name, refs)`.
    e. Record `{playlist_id, matched: N, missing_in_vendor, unmapped_in_canonical}`.
7. Aggregate status: all vendors ok → `COMPLETED`; some ok → `PARTIAL`; none → `FAILED`.
8. `update_release_mirror_run(status=..., finished_at=..., results={...})`.

Concurrency: use `asyncio.gather` with `asyncio.Semaphore(10)` over per-vendor tasks. Or simpler: sequential per-vendor loop, since vendors are few. Start sequential; optimize later.

- [ ] **Step 1: Tests** — use `FakeLookupProvider`, `FakeExporter`, fixture `crypto` and `registry`.
- [ ] **Step 2: Implementation** — long function, split into `_fetch_source_tracks`, `_match_to_vendor`, `_export_one_vendor`, `_aggregate_status` helpers.
- [ ] **Step 3: Tests pass, flake8 clean**.
- [ ] **Step 4: Commit**.

---

## Task 9: API endpoints `POST /release_mirror` + `GET /release_mirror/{run_id}`

**Files:**
- Modify: `src/collector/handler.py` — add new route handlers.
- Modify: `infra/api_gateway.tf` — add routes.

- [ ] **Step 1: Handler code**

In `handler.py`, dispatch by `path` and `httpMethod`:

```python
# POST /release_mirror
def _handle_release_mirror_post(event, repository) -> dict:
    body = _parse_json_body(event)
    try:
        req = ReleaseMirrorRequestIn.model_validate(body)
    except PydanticValidationError as e:
        return _error(400, "validation_error", validation_error_message(e))

    # Verify user has Spotify source token
    token = repository.get_user_token(req.user_id, "spotify")
    if token is None:
        raise UserTokenMissingError(req.user_id, "spotify")

    # Verify each target vendor is enabled + user has token
    for v in req.target_vendors:
        registry.get_exporter(v)  # raises VendorDisabledError if disabled
        if repository.get_user_token(req.user_id, v) is None:
            raise UserTokenMissingError(req.user_id, v)

    run_id = str(uuid4())
    correlation_id = _correlation_id_from_event(event)
    repository.create_release_mirror_run(
        run_id=run_id,
        user_id=req.user_id,
        source_vendor="spotify",
        source_playlist_id=req.source_playlist_id,
        target_vendors=req.target_vendors,
        status="QUEUED",
        started_at=utc_now(),
    )

    # Enqueue
    message = ReleaseMirrorMessage(
        run_id=run_id, user_id=req.user_id,
        source_playlist_id=req.source_playlist_id,
        target_vendors=req.target_vendors, name=req.name,
    )
    _sqs_send(get_settings().release_mirror_queue_url, message.model_dump_json())

    return _ok(202, {
        "run_id": run_id, "correlation_id": correlation_id,
        "status": "QUEUED",
    })


# GET /release_mirror/{run_id}
def _handle_release_mirror_status(event, repository) -> dict:
    run_id = event["pathParameters"]["run_id"]
    row = repository.get_release_mirror_run(run_id)
    if row is None:
        return _error(404, "not_found", "release_mirror_run not found")
    return _ok(200, {
        "run_id": row.run_id,
        "status": row.status,
        "target_vendors": row.target_vendors,
        "started_at": row.started_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "results": row.results,
    })
```

- [ ] **Step 2: Terraform routes**

```hcl
# infra/api_gateway.tf
resource "aws_apigatewayv2_route" "release_mirror_post" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "POST /release_mirror"
  target    = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
}

resource "aws_apigatewayv2_route" "release_mirror_status" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "GET /release_mirror/{run_id}"
  target    = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
}
```

- [ ] **Step 3: Tests**

Integration-style tests against `collector.handler.lambda_handler` with synthetic API Gateway events.

- [ ] **Step 4: Commit**

---

## Task 10: Terraform — SQS queue, Lambda, IAM, outputs, alarms

**Files:**
- `infra/sqs.tf` — `aws_sqs_queue.release_mirror` + DLQ, visibility timeout ≥ Lambda timeout.
- `infra/lambda.tf` — `aws_lambda_function.release_mirror_worker` + event source mapping.
- `infra/iam.tf` — add `release_mirror` queue ARN to existing SQS statements.
- `infra/main.tf` — `local.release_mirror_queue_name`, `local.release_mirror_dlq_name`, `local.release_mirror_worker_lambda_name`.
- `infra/variables.tf` — `release_mirror_worker_lambda_timeout_seconds` (default 300), visibility timeout matching.
- `infra/logging.tf` — DLQ alarm mirroring canonicalization DLQ.
- `infra/outputs.tf` — `release_mirror_worker_lambda_function_name`, `release_mirror_route`.

- [ ] Lambda env vars:
  - Existing Aurora env
  - `RELEASE_MIRROR_QUEUE_URL` (for enqueue from API Lambda)
  - `CLOUDER_USER_TOKEN_KMS_ALIAS`
  - `VENDORS_ENABLED`

- [ ] `terraform fmt && terraform validate`.
- [ ] Commit.

---

## Task 11: Integration test — full flow

**Files:**
- Create: `tests/integration/test_release_mirror_flow.py`

Use ephemeral Postgres + `moto` for KMS + `FakeSpotifyLookup` + `FakeExporter` per target vendor.

Scenarios:
1. Happy path — Spotify source → 2 target vendors (fake) → both succeed, status=COMPLETED, results populated.
2. Partial — one vendor export fails → status=PARTIAL.
3. Unmapped tracks — Spotify playlist has a track not in `identity_map` → recorded in `unmapped_in_canonical`.
4. Cache-miss matching — `vendor_track_map` empty → inline ISRC lookup populates cache.
5. User missing token for target vendor → `UserTokenMissingError` at POST time.
6. Target vendor disabled via `VENDORS_ENABLED` → POST returns 400 `vendor_disabled`.

Commit each or batch per file.

---

## Task 12: Docs + README

- `docs/data-model.md`: `user_vendor_tokens`, `release_mirror_runs` tables.
- `docs/release-mirror.md` (new): explains flow, API contract, operator notes (how to seed tokens via `store_user_token.py`).
- `README.md`: add Release Mirror section with `POST /release_mirror` example.
- `CLAUDE.md`:
  - Env vars for release mirror.
  - Gotchas: "User tokens KMS-encrypted via envelope; rotation requires re-encrypt, not just KMS key re-wrap."
  - New Lambda: `release_mirror_worker`.

Commit.

---

## Execution Order

1. Migration (Task 1)
2. KMS Terraform (Task 2)
3. Crypto module (Task 3)
4. Repositories (Task 4)
5. store_user_token CLI (Task 5)
6. Spotify playlist fetch (Task 6)
7. Schemas (Task 7)
8. Handler (Task 8)
9. API endpoints (Task 9)
10. Terraform SQS + Lambda (Task 10)
11. Integration test (Task 11)
12. Docs (Task 12)

**After this plan lands:**
- End-to-end vendor-sync loop is live.
- Real vendor bodies (YT Music / Deezer / Apple / Tidal implementations) become follow-up work, each vendor its own mini-plan:
  - Implement `<vendor>/lookup.py` with real API calls.
  - Implement `<vendor>/export.py` with real playlist creation.
  - Write contract tests.
  - Flip `VENDORS_ENABLED` to include the vendor.
- OAuth authorize/callback flow is future work when user-layer begins (out of roadmap scope).
