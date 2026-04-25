# Spec-A — User & Auth Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a working Spotify OAuth login flow that issues stateful JWTs, persists per-user vendor refresh tokens under KMS envelope encryption, gates ingest endpoints to admins, and exposes a Lambda Authorizer that surfaces `(user_id, is_admin)` to all downstream handlers.

**Architecture:** Two new Lambdas (`auth_handler`, `auth_authorizer`) plus three new Aurora tables (`users`, `user_sessions`, `user_vendor_tokens`). The auth handler runs the OAuth flow, manages sessions, and stores Spotify refresh tokens encrypted via KMS envelope (data key generated per write, plaintext cached 5 min in Lambda memory). The authorizer is a thin Lambda invoked by API Gateway HTTP API (TTL 300s) that validates HS256 JWTs against an SSM-resolved secret. Existing routes get the authorizer attached; ingest routes additionally check `is_admin`.

**Tech Stack:** Python 3.12, pydantic v2, PyJWT, `cryptography` (AES-GCM for envelope), boto3 (`kms`, `ssm`, `secretsmanager`, `rds-data`), SQLAlchemy 2 + Alembic, Terraform AWS provider, pytest with `monkeypatch` and `moto`.

**Spec:** [docs/superpowers/specs/2026-04-25-spec-A-user-auth-design.md](../specs/2026-04-25-spec-A-user-auth-design.md)

---

## File Structure

Files this plan creates:

- `src/collector/auth/__init__.py` — empty package marker.
- `src/collector/auth/jwt_utils.py` — HS256 issue / verify functions with claim schemas.
- `src/collector/auth/pkce.py` — PKCE `code_verifier` / `code_challenge` generators.
- `src/collector/auth/kms_envelope.py` — KMS-wrapped data key envelope encryption (AES-GCM) with 5-min in-memory data-key cache.
- `src/collector/auth/spotify_oauth.py` — Spotify OAuth client (token exchange, `/me` profile, refresh-grant).
- `src/collector/auth/auth_settings.py` — `AuthSettings` with SSM/env var resolution + admin Spotify IDs parser.
- `src/collector/auth/auth_repository.py` — `AuthRepository` over Data API for `users`, `user_sessions`, `user_vendor_tokens`.
- `src/collector/auth_handler.py` — API Lambda for `/auth/*`, `/me`, `/me/sessions/{id}` routes.
- `src/collector/auth_authorizer.py` — API Gateway Lambda Authorizer.
- `alembic/versions/20260426_11_users.py` — `users` table migration.
- `alembic/versions/20260426_12_user_sessions.py` — `user_sessions` table migration.
- `alembic/versions/20260426_13_user_vendor_tokens.py` — `user_vendor_tokens` table migration.
- `infra/auth.tf` — KMS key, SSM params, auth Lambdas + log groups, API Gateway authorizer + routes, IAM additions.
- `tests/unit/test_jwt_utils.py`
- `tests/unit/test_pkce.py`
- `tests/unit/test_kms_envelope.py`
- `tests/unit/test_spotify_oauth.py`
- `tests/unit/test_auth_settings.py`
- `tests/unit/test_auth_repository.py`
- `tests/unit/test_auth_handler_login.py`
- `tests/unit/test_auth_handler_callback.py`
- `tests/unit/test_auth_handler_refresh.py`
- `tests/unit/test_auth_handler_logout.py`
- `tests/unit/test_auth_handler_me.py`
- `tests/unit/test_auth_authorizer.py`
- `tests/unit/test_handler_admin_gating.py`
- `tests/integration/test_auth_flow.py` — login → callback → /me → refresh → logout end-to-end with FakeRepo, FakeSpotifyOAuth, mocked KMS.
- `tests/unit/test_migration_11_sql.py`
- `tests/unit/test_migration_12_sql.py`
- `tests/unit/test_migration_13_sql.py`

Files this plan modifies:

- `src/collector/db_models.py` — add `User`, `UserSession`, `UserVendorToken` SQLAlchemy classes.
- `src/collector/errors.py` — add new auth error classes.
- `src/collector/handler.py` — admin gating for `POST /collect_bp_releases` and `GET /tracks/spotify-not-found`.
- `src/collector/requirements.txt` — add `pyjwt>=2.10`, `cryptography>=44`.
- `requirements-lambda.txt` — same additions (so packaging picks them up).
- `requirements-dev.txt` — add `moto[kms,ssm]` for tests.
- `infra/variables.tf` — new variables for OAuth, JWT, KMS, admin list, allowed redirects.
- `infra/terraform.tfvars.example` — placeholders for new variables.
- `infra/iam.tf` — extend collector_lambda policy for KMS/SSM access (auth_handler shares the role; if isolating, see Task 20 note).

Files this plan does NOT touch:

- `src/collector/data_api.py` — already provides everything needed.
- `src/collector/repositories.py` — `AuthRepository` lives in a new module to avoid bloating the existing 1200-line file.
- `src/collector/worker_handler.py`, `search_handler.py`, `spotify_handler.py`, `vendor_match_handler.py` — these run from SQS triggers, not API Gateway, so authorizer changes do not affect them.

---

## Task 1: Add JWT and crypto dependencies

**Files:**
- Modify: `src/collector/requirements.txt`
- Modify: `requirements-lambda.txt`
- Modify: `requirements-dev.txt`

- [ ] **Step 1: Append PyJWT and cryptography to `src/collector/requirements.txt`**

Append these lines at the end of the file:

```
pyjwt>=2.10
cryptography>=44
```

- [ ] **Step 2: Append the same to `requirements-lambda.txt`**

```
pyjwt>=2.10
cryptography>=44
```

- [ ] **Step 3: Append moto extras to `requirements-dev.txt`**

```
pyjwt>=2.10
cryptography>=44
moto[kms,ssm,secretsmanager]>=5
```

- [ ] **Step 4: Install locally and verify import**

Run:

```bash
python -m pip install -r requirements-dev.txt
python -c "import jwt; from cryptography.hazmat.primitives.ciphers.aead import AESGCM; print(jwt.__version__)"
```

Expected: prints PyJWT version (e.g. `2.8.0`), no ImportError.

- [ ] **Step 5: Commit**

```bash
git add src/collector/requirements.txt requirements-lambda.txt requirements-dev.txt
git commit -m "chore(auth): add pyjwt and cryptography for spec-A"
```

---

## Task 2: Migration — `users` table

**Files:**
- Create: `alembic/versions/20260426_11_users.py`
- Modify: `src/collector/db_models.py`
- Test: `tests/unit/test_migration_11_sql.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_migration_11_sql.py`:

```python
"""Test that the users migration creates the expected schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration_module():
    path = Path("alembic/versions/20260426_11_users.py")
    spec = importlib.util.spec_from_file_location("mig11", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_metadata() -> None:
    mig = _load_migration_module()
    assert mig.revision == "20260426_11"
    assert mig.down_revision == "20260421_10"


def test_upgrade_creates_users_table() -> None:
    mig = _load_migration_module()
    src = Path("alembic/versions/20260426_11_users.py").read_text()
    assert 'create_table(\n        "users"' in src
    assert '"spotify_id"' in src
    assert '"is_admin"' in src
    assert "idx_users_spotify_id" in src
    assert "unique=True" in src
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_migration_11_sql.py -q`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Create the migration**

Create `alembic/versions/20260426_11_users.py`:

```python
"""users table

Revision ID: 20260426_11
Revises: 20260421_10
Create Date: 2026-04-26 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_11"
down_revision = "20260421_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("spotify_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_users_spotify_id",
        "users",
        ["spotify_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_users_spotify_id", table_name="users")
    op.drop_table("users")
```

- [ ] **Step 4: Add `User` SQLAlchemy model**

Append to `src/collector/db_models.py`:

```python
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_spotify_id", "spotify_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    spotify_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/unit/test_migration_11_sql.py -q`
Expected: PASS.

- [ ] **Step 6: Apply migration locally**

```bash
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head
```

Expected: alembic logs `Running upgrade 20260421_10 -> 20260426_11, users table`.

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/20260426_11_users.py src/collector/db_models.py tests/unit/test_migration_11_sql.py
git commit -m "feat(auth): add users table migration"
```

---

## Task 3: Migration — `user_sessions` table

**Files:**
- Create: `alembic/versions/20260426_12_user_sessions.py`
- Modify: `src/collector/db_models.py`
- Test: `tests/unit/test_migration_12_sql.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_migration_12_sql.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration_module():
    path = Path("alembic/versions/20260426_12_user_sessions.py")
    spec = importlib.util.spec_from_file_location("mig12", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_metadata() -> None:
    mig = _load_migration_module()
    assert mig.revision == "20260426_12"
    assert mig.down_revision == "20260426_11"


def test_upgrade_creates_user_sessions_table() -> None:
    src = Path("alembic/versions/20260426_12_user_sessions.py").read_text()
    assert 'create_table(\n        "user_sessions"' in src
    assert '"refresh_token_hash"' in src
    assert '"revoked_at"' in src
    assert "idx_user_sessions_user" in src
    assert "idx_user_sessions_expires" in src
    assert 'ForeignKeyConstraint(["user_id"], ["users.id"])' in src
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_migration_12_sql.py -q`
Expected: FAIL — file missing.

- [ ] **Step 3: Create the migration**

Create `alembic/versions/20260426_12_user_sessions.py`:

```python
"""user_sessions table

Revision ID: 20260426_12
Revises: 20260426_11
Create Date: 2026-04-26 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_12"
down_revision = "20260426_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_user_sessions_user", "user_sessions", ["user_id"])
    op.create_index(
        "idx_user_sessions_expires", "user_sessions", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_user_sessions_expires", table_name="user_sessions")
    op.drop_index("idx_user_sessions_user", table_name="user_sessions")
    op.drop_table("user_sessions")
```

- [ ] **Step 4: Add `UserSession` model**

Append to `src/collector/db_models.py`:

```python
class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("idx_user_sessions_user", "user_id"),
        Index("idx_user_sessions_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 5: Run the test, apply migration, commit**

```bash
pytest tests/unit/test_migration_12_sql.py -q
alembic upgrade head
git add alembic/versions/20260426_12_user_sessions.py src/collector/db_models.py tests/unit/test_migration_12_sql.py
git commit -m "feat(auth): add user_sessions table migration"
```

Expected: pytest PASS, alembic logs `Running upgrade 20260426_11 -> 20260426_12`.

---

## Task 4: Migration — `user_vendor_tokens` table

**Files:**
- Create: `alembic/versions/20260426_13_user_vendor_tokens.py`
- Modify: `src/collector/db_models.py`
- Test: `tests/unit/test_migration_13_sql.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_migration_13_sql.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration_module():
    path = Path("alembic/versions/20260426_13_user_vendor_tokens.py")
    spec = importlib.util.spec_from_file_location("mig13", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_metadata() -> None:
    mig = _load_migration_module()
    assert mig.revision == "20260426_13"
    assert mig.down_revision == "20260426_12"


def test_upgrade_creates_user_vendor_tokens_table() -> None:
    src = Path("alembic/versions/20260426_13_user_vendor_tokens.py").read_text()
    assert 'create_table(\n        "user_vendor_tokens"' in src
    assert '"access_token_enc"' in src
    assert '"refresh_token_enc"' in src
    assert '"data_key_enc"' in src
    assert 'PrimaryKeyConstraint("user_id", "vendor"' in src
    assert 'ForeignKeyConstraint(["user_id"], ["users.id"])' in src
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_migration_13_sql.py -q`
Expected: FAIL.

- [ ] **Step 3: Create the migration**

Create `alembic/versions/20260426_13_user_vendor_tokens.py`:

```python
"""user_vendor_tokens table

Revision ID: 20260426_13
Revises: 20260426_12
Create Date: 2026-04-26 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_13"
down_revision = "20260426_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_vendor_tokens",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("vendor", sa.String(length=32), nullable=False),
        sa.Column("access_token_enc", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_enc", sa.LargeBinary(), nullable=True),
        sa.Column("data_key_enc", sa.LargeBinary(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "vendor", name="pk_user_vendor_tokens"),
    )


def downgrade() -> None:
    op.drop_table("user_vendor_tokens")
```

- [ ] **Step 4: Add `UserVendorToken` model**

Append to `src/collector/db_models.py`:

```python
from sqlalchemy import LargeBinary  # add to imports if not already present


class UserVendorToken(Base):
    __tablename__ = "user_vendor_tokens"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "vendor", name="pk_user_vendor_tokens"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    vendor: Mapped[str] = mapped_column(String(32), nullable=False)
    access_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    data_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scope: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
```

- [ ] **Step 5: Run, apply, commit**

```bash
pytest tests/unit/test_migration_13_sql.py -q
alembic upgrade head
git add alembic/versions/20260426_13_user_vendor_tokens.py src/collector/db_models.py tests/unit/test_migration_13_sql.py
git commit -m "feat(auth): add user_vendor_tokens table migration"
```

Expected: PASS; alembic logs `Running upgrade 20260426_12 -> 20260426_13`.

---

## Task 5: `auth/jwt_utils.py` — issue and verify HS256 tokens

**Files:**
- Create: `src/collector/auth/__init__.py`
- Create: `src/collector/auth/jwt_utils.py`
- Test: `tests/unit/test_jwt_utils.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_jwt_utils.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from collector.auth.jwt_utils import (
    AccessClaims,
    InvalidTokenError,
    RefreshClaims,
    issue_access_token,
    issue_refresh_token,
    verify_access_token,
    verify_refresh_token,
)


SECRET = "0" * 32


def test_access_token_round_trip() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret=SECRET,
        user_id="u-1",
        session_id="s-1",
        is_admin=True,
        ttl_seconds=1800,
        now=now,
    )
    claims = verify_access_token(token=token, secret=SECRET, now=now)
    assert isinstance(claims, AccessClaims)
    assert claims.user_id == "u-1"
    assert claims.session_id == "s-1"
    assert claims.is_admin is True


def test_access_token_expired_rejected() -> None:
    issued_at = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret=SECRET,
        user_id="u-1",
        session_id="s-1",
        is_admin=False,
        ttl_seconds=60,
        now=issued_at,
    )
    later = issued_at + timedelta(seconds=120)
    with pytest.raises(InvalidTokenError):
        verify_access_token(token=token, secret=SECRET, now=later)


def test_access_token_tampered_signature_rejected() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret=SECRET, user_id="u", session_id="s", is_admin=False,
        ttl_seconds=60, now=now,
    )
    tampered = token[:-4] + "AAAA"
    with pytest.raises(InvalidTokenError):
        verify_access_token(token=tampered, secret=SECRET, now=now)


def test_access_token_wrong_secret_rejected() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret=SECRET, user_id="u", session_id="s", is_admin=False,
        ttl_seconds=60, now=now,
    )
    with pytest.raises(InvalidTokenError):
        verify_access_token(token=token, secret="X" * 32, now=now)


def test_refresh_token_round_trip() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_refresh_token(
        secret=SECRET, user_id="u", session_id="s", ttl_seconds=604800, now=now,
    )
    claims = verify_refresh_token(token=token, secret=SECRET, now=now)
    assert isinstance(claims, RefreshClaims)
    assert claims.user_id == "u"
    assert claims.session_id == "s"


def test_refresh_token_token_type_mismatch_rejected() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    access = issue_access_token(
        secret=SECRET, user_id="u", session_id="s", is_admin=False,
        ttl_seconds=60, now=now,
    )
    with pytest.raises(InvalidTokenError):
        verify_refresh_token(token=access, secret=SECRET, now=now)
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_jwt_utils.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Create the package marker**

Create `src/collector/auth/__init__.py` (empty file):

```python
```

- [ ] **Step 4: Implement the JWT module**

Create `src/collector/auth/jwt_utils.py`:

```python
"""HS256 JWT issue / verify helpers for spec-A access and refresh tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt


_ALGO = "HS256"
_TYPE_ACCESS = "access"
_TYPE_REFRESH = "refresh"


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    session_id: str
    is_admin: bool


@dataclass(frozen=True)
class RefreshClaims:
    user_id: str
    session_id: str


def issue_access_token(
    *,
    secret: str,
    user_id: str,
    session_id: str,
    is_admin: bool,
    ttl_seconds: int,
    now: datetime,
) -> str:
    payload = {
        "sub": user_id,
        "session_id": session_id,
        "is_admin": is_admin,
        "typ": _TYPE_ACCESS,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALGO)


def issue_refresh_token(
    *,
    secret: str,
    user_id: str,
    session_id: str,
    ttl_seconds: int,
    now: datetime,
) -> str:
    payload = {
        "sub": user_id,
        "session_id": session_id,
        "typ": _TYPE_REFRESH,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALGO)


def verify_access_token(
    *, token: str, secret: str, now: datetime
) -> AccessClaims:
    payload = _decode(token=token, secret=secret, now=now, expected_type=_TYPE_ACCESS)
    try:
        return AccessClaims(
            user_id=str(payload["sub"]),
            session_id=str(payload["session_id"]),
            is_admin=bool(payload.get("is_admin", False)),
        )
    except KeyError as exc:
        raise InvalidTokenError(f"missing claim: {exc}") from exc


def verify_refresh_token(
    *, token: str, secret: str, now: datetime
) -> RefreshClaims:
    payload = _decode(token=token, secret=secret, now=now, expected_type=_TYPE_REFRESH)
    try:
        return RefreshClaims(
            user_id=str(payload["sub"]),
            session_id=str(payload["session_id"]),
        )
    except KeyError as exc:
        raise InvalidTokenError(f"missing claim: {exc}") from exc


def _decode(
    *, token: str, secret: str, now: datetime, expected_type: str
) -> dict:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[_ALGO],
            options={"require": ["exp", "iat", "sub", "typ", "session_id"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("typ") != expected_type:
        raise InvalidTokenError(
            f"token type mismatch: expected {expected_type}, got {payload.get('typ')}"
        )

    exp = int(payload["exp"])
    if int(now.astimezone(timezone.utc).timestamp()) >= exp:
        raise InvalidTokenError("token expired")

    return payload
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/unit/test_jwt_utils.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/collector/auth/__init__.py src/collector/auth/jwt_utils.py tests/unit/test_jwt_utils.py
git commit -m "feat(auth): add HS256 JWT issue/verify helpers"
```

---

## Task 6: `auth/pkce.py` — PKCE code_verifier / code_challenge

**Files:**
- Create: `src/collector/auth/pkce.py`
- Test: `tests/unit/test_pkce.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_pkce.py`:

```python
from __future__ import annotations

import re

from collector.auth.pkce import (
    derive_code_challenge,
    generate_code_verifier,
)


_BASE64URL_NOPAD = re.compile(r"^[A-Za-z0-9_-]+$")


def test_generate_code_verifier_is_base64url_no_padding() -> None:
    verifier = generate_code_verifier()
    assert _BASE64URL_NOPAD.match(verifier)
    # 32 bytes of entropy → 43 base64url chars (no padding).
    assert len(verifier) == 43


def test_derive_code_challenge_known_vector() -> None:
    # RFC 7636 Appendix B test vector
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert derive_code_challenge(verifier) == expected


def test_derive_code_challenge_is_base64url_no_padding() -> None:
    challenge = derive_code_challenge(generate_code_verifier())
    assert _BASE64URL_NOPAD.match(challenge)
    # SHA-256 → 32 bytes → 43 base64url chars.
    assert len(challenge) == 43
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_pkce.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `src/collector/auth/pkce.py`:

```python
"""PKCE helpers for Spotify OAuth (RFC 7636)."""

from __future__ import annotations

import base64
import hashlib
import os


def generate_code_verifier(num_bytes: int = 32) -> str:
    return _b64url_nopad(os.urandom(num_bytes))


def derive_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return _b64url_nopad(digest)


def _b64url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/unit/test_pkce.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth/pkce.py tests/unit/test_pkce.py
git commit -m "feat(auth): add PKCE code_verifier and code_challenge helpers"
```

---

## Task 7: `auth/kms_envelope.py` — KMS envelope encryption

**Files:**
- Create: `src/collector/auth/kms_envelope.py`
- Test: `tests/unit/test_kms_envelope.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_kms_envelope.py`:

```python
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from collector.auth.kms_envelope import KmsEnvelope, EnvelopePayload


def _make_kms_client(plaintext_key: bytes) -> MagicMock:
    client = MagicMock()
    client.generate_data_key.return_value = {
        "Plaintext": plaintext_key,
        "CiphertextBlob": b"wrapped:" + plaintext_key,
    }
    client.decrypt.return_value = {"Plaintext": plaintext_key}
    return client


def test_encrypt_decrypt_round_trip() -> None:
    key = b"\x00" * 32
    client = _make_kms_client(key)
    envelope = KmsEnvelope(kms_client=client, key_arn="arn:k", cache_ttl_seconds=300)

    payload = envelope.encrypt(b"sekret-token-bytes")
    assert payload.ciphertext != b"sekret-token-bytes"
    assert payload.data_key_enc == b"wrapped:" + key

    plaintext = envelope.decrypt(payload)
    assert plaintext == b"sekret-token-bytes"


def test_encrypt_caches_data_key_within_ttl() -> None:
    key = b"\x01" * 32
    client = _make_kms_client(key)
    envelope = KmsEnvelope(kms_client=client, key_arn="arn:k", cache_ttl_seconds=300)

    envelope.encrypt(b"a")
    envelope.encrypt(b"b")

    assert client.generate_data_key.call_count == 1


def test_encrypt_refreshes_data_key_after_ttl() -> None:
    key = b"\x02" * 32
    client = _make_kms_client(key)
    clock = [0.0]

    def fake_monotonic() -> float:
        return clock[0]

    envelope = KmsEnvelope(
        kms_client=client,
        key_arn="arn:k",
        cache_ttl_seconds=10,
        monotonic=fake_monotonic,
    )

    envelope.encrypt(b"a")
    clock[0] = 11.0
    envelope.encrypt(b"b")

    assert client.generate_data_key.call_count == 2


def test_decrypt_caches_unwrapped_data_key() -> None:
    key = b"\x03" * 32
    client = _make_kms_client(key)
    envelope = KmsEnvelope(kms_client=client, key_arn="arn:k", cache_ttl_seconds=300)

    payload = envelope.encrypt(b"first")
    envelope.decrypt(payload)
    envelope.decrypt(payload)

    # First decrypt populates cache; second uses cache.
    assert client.decrypt.call_count == 1


def test_payload_serialize_round_trip() -> None:
    payload = EnvelopePayload(data_key_enc=b"\xaa\xbb", nonce=b"n" * 12, ciphertext=b"c")
    blob = payload.serialize()
    parsed = EnvelopePayload.deserialize(blob)
    assert parsed == payload
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_kms_envelope.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `src/collector/auth/kms_envelope.py`:

```python
"""KMS envelope encryption with AES-GCM and a 5-min in-memory data-key cache."""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class EnvelopePayload:
    data_key_enc: bytes
    nonce: bytes
    ciphertext: bytes

    def serialize(self) -> bytes:
        return (
            struct.pack(">I", len(self.data_key_enc))
            + self.data_key_enc
            + self.nonce
            + self.ciphertext
        )

    @classmethod
    def deserialize(cls, blob: bytes) -> "EnvelopePayload":
        (key_len,) = struct.unpack(">I", blob[:4])
        offset = 4
        data_key_enc = blob[offset : offset + key_len]
        offset += key_len
        nonce = blob[offset : offset + 12]
        offset += 12
        ciphertext = blob[offset:]
        return cls(data_key_enc=data_key_enc, nonce=nonce, ciphertext=ciphertext)


class KmsEnvelope:
    """Wraps KMS GenerateDataKey/Decrypt with AES-GCM and a small TTL cache."""

    def __init__(
        self,
        kms_client: Any,
        key_arn: str,
        cache_ttl_seconds: int = 300,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._kms = kms_client
        self._key_arn = key_arn
        self._cache_ttl_seconds = cache_ttl_seconds
        self._monotonic = monotonic
        # Encryption-side cache: (plaintext_key, data_key_enc, expires_at_monotonic).
        self._enc_cache: tuple[bytes, bytes, float] | None = None
        # Decryption-side cache: data_key_enc -> (plaintext_key, expires_at_monotonic).
        self._dec_cache: dict[bytes, tuple[bytes, float]] = {}

    def encrypt(self, plaintext: bytes) -> EnvelopePayload:
        key, data_key_enc = self._fresh_data_key()
        nonce = os.urandom(12)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
        return EnvelopePayload(
            data_key_enc=data_key_enc, nonce=nonce, ciphertext=ciphertext
        )

    def decrypt(self, payload: EnvelopePayload) -> bytes:
        key = self._unwrap_data_key(payload.data_key_enc)
        return AESGCM(key).decrypt(payload.nonce, payload.ciphertext, associated_data=None)

    def _fresh_data_key(self) -> tuple[bytes, bytes]:
        now = self._monotonic()
        if self._enc_cache is not None:
            key, wrapped, expires = self._enc_cache
            if now < expires:
                return key, wrapped
        response = self._kms.generate_data_key(
            KeyId=self._key_arn, KeySpec="AES_256"
        )
        key = response["Plaintext"]
        wrapped = response["CiphertextBlob"]
        self._enc_cache = (key, wrapped, now + self._cache_ttl_seconds)
        return key, wrapped

    def _unwrap_data_key(self, data_key_enc: bytes) -> bytes:
        now = self._monotonic()
        cached = self._dec_cache.get(data_key_enc)
        if cached is not None:
            key, expires = cached
            if now < expires:
                return key
        response = self._kms.decrypt(CiphertextBlob=data_key_enc)
        key = response["Plaintext"]
        self._dec_cache[data_key_enc] = (key, now + self._cache_ttl_seconds)
        return key
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/unit/test_kms_envelope.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth/kms_envelope.py tests/unit/test_kms_envelope.py
git commit -m "feat(auth): add KMS envelope encryption helper with AES-GCM"
```

---

## Task 8: `auth/spotify_oauth.py` — OAuth client

**Files:**
- Create: `src/collector/auth/spotify_oauth.py`
- Test: `tests/unit/test_spotify_oauth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_spotify_oauth.py`:

```python
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from collector.auth.spotify_oauth import (
    SpotifyOAuthClient,
    SpotifyOAuthError,
    SpotifyProfile,
    SpotifyTokenSet,
    SpotifyTokenRevokedError,
)


class FakeResponse:
    def __init__(self, status: int, body: dict | str) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        if isinstance(self._body, dict):
            return json.dumps(self._body).encode()
        return self._body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_exchange_code_returns_tokens() -> None:
    captured: dict = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["data"] = request.data.decode()
        captured["auth"] = request.get_header("Authorization")
        return FakeResponse(
            200,
            {
                "access_token": "AT",
                "refresh_token": "RT",
                "expires_in": 3600,
                "scope": "user-read-email",
            },
        )

    client = SpotifyOAuthClient(
        client_id="cid",
        client_secret="csec",
        redirect_uri="https://x/cb",
        urlopen=opener,
    )

    tokens = client.exchange_code(code="AUTH_CODE", code_verifier="VERIFIER")

    assert isinstance(tokens, SpotifyTokenSet)
    assert tokens.access_token == "AT"
    assert tokens.refresh_token == "RT"
    assert tokens.expires_in == 3600
    assert tokens.scope == "user-read-email"
    assert "code=AUTH_CODE" in captured["data"]
    assert "code_verifier=VERIFIER" in captured["data"]
    assert captured["auth"].startswith("Basic ")


def test_exchange_code_http_error_raises_oauth_exchange_failed() -> None:
    def opener(request, timeout):
        return FakeResponse(400, {"error": "invalid_request"})

    client = SpotifyOAuthClient(
        client_id="cid", client_secret="csec",
        redirect_uri="https://x/cb", urlopen=opener,
    )

    with pytest.raises(SpotifyOAuthError):
        client.exchange_code(code="X", code_verifier="V")


def test_get_me_parses_profile() -> None:
    def opener(request, timeout):
        assert request.full_url == "https://api.spotify.com/v1/me"
        assert request.get_header("Authorization") == "Bearer AT"
        return FakeResponse(
            200,
            {
                "id": "spotify_user_1",
                "display_name": "Roman",
                "email": "r@example.com",
                "product": "premium",
            },
        )

    client = SpotifyOAuthClient(
        client_id="cid", client_secret="csec",
        redirect_uri="https://x/cb", urlopen=opener,
    )

    profile = client.get_me(access_token="AT")

    assert isinstance(profile, SpotifyProfile)
    assert profile.spotify_id == "spotify_user_1"
    assert profile.display_name == "Roman"
    assert profile.email == "r@example.com"
    assert profile.product == "premium"


def test_refresh_invalid_grant_raises_revoked() -> None:
    def opener(request, timeout):
        return FakeResponse(400, {"error": "invalid_grant"})

    client = SpotifyOAuthClient(
        client_id="cid", client_secret="csec",
        redirect_uri="https://x/cb", urlopen=opener,
    )

    with pytest.raises(SpotifyTokenRevokedError):
        client.refresh(refresh_token="OLD")


def test_refresh_returns_new_tokens() -> None:
    def opener(request, timeout):
        return FakeResponse(
            200,
            {
                "access_token": "NEW_AT",
                "expires_in": 3600,
                "scope": "user-read-email",
                # Spotify may or may not return a new refresh_token
            },
        )

    client = SpotifyOAuthClient(
        client_id="cid", client_secret="csec",
        redirect_uri="https://x/cb", urlopen=opener,
    )

    tokens = client.refresh(refresh_token="OLD")

    assert tokens.access_token == "NEW_AT"
    assert tokens.refresh_token == "OLD"  # falls back to the existing refresh
    assert tokens.expires_in == 3600
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_spotify_oauth.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `src/collector/auth/spotify_oauth.py`:

```python
"""Spotify OAuth client (authorization-code + PKCE, /me, refresh-grant)."""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from urllib.error import HTTPError, URLError


TOKEN_URL = "https://accounts.spotify.com/api/token"
ME_URL = "https://api.spotify.com/v1/me"


class SpotifyOAuthError(Exception):
    pass


class SpotifyTokenRevokedError(SpotifyOAuthError):
    """Raised when Spotify returns invalid_grant on refresh — user must re-OAuth."""


@dataclass(frozen=True)
class SpotifyTokenSet:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str | None


@dataclass(frozen=True)
class SpotifyProfile:
    spotify_id: str
    display_name: str | None
    email: str | None
    product: str  # "premium" | "free" | "open"


class SpotifyOAuthClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        timeout_seconds: float = 15.0,
        urlopen: Callable[[urllib.request.Request, float], Any] | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._timeout = timeout_seconds
        self._urlopen = urlopen or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))

    def authorize_url(self, *, state: str, code_challenge: str, scopes: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
            "scope": scopes,
        }
        return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)

    def exchange_code(self, *, code: str, code_verifier: str) -> SpotifyTokenSet:
        body = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        payload = self._post_token(body)
        return self._token_set_from_payload(payload, fallback_refresh=None)

    def refresh(self, *, refresh_token: str) -> SpotifyTokenSet:
        body = urllib.parse.urlencode(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        payload = self._post_token(body)
        return self._token_set_from_payload(payload, fallback_refresh=refresh_token)

    def get_me(self, *, access_token: str) -> SpotifyProfile:
        request = urllib.request.Request(
            url=ME_URL,
            method="GET",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        try:
            with self._urlopen(request, self._timeout) as response:
                status = getattr(response, "status", 200)
                body = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise SpotifyOAuthError(f"spotify /me request failed: {exc}") from exc

        if status != 200:
            raise SpotifyOAuthError(f"spotify /me returned HTTP {status}: {body[:200]}")

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SpotifyOAuthError("spotify /me returned non-JSON") from exc

        return SpotifyProfile(
            spotify_id=str(parsed["id"]),
            display_name=parsed.get("display_name"),
            email=parsed.get("email"),
            product=str(parsed.get("product", "open")),
        )

    def _post_token(self, body: str) -> dict:
        credentials = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        request = urllib.request.Request(
            url=TOKEN_URL,
            data=body.encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with self._urlopen(request, self._timeout) as response:
                status = getattr(response, "status", 200)
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise SpotifyOAuthError(f"spotify token request failed: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SpotifyOAuthError("spotify token response was not JSON") from exc

        if status != 200:
            error_code = parsed.get("error") if isinstance(parsed, dict) else None
            if error_code == "invalid_grant":
                raise SpotifyTokenRevokedError(
                    f"spotify token endpoint reported invalid_grant: {parsed}"
                )
            raise SpotifyOAuthError(
                f"spotify token endpoint returned HTTP {status}: {parsed}"
            )

        return parsed

    def _token_set_from_payload(
        self, payload: dict, fallback_refresh: str | None
    ) -> SpotifyTokenSet:
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise SpotifyOAuthError("spotify token response missing access_token")
        refresh = payload.get("refresh_token") or fallback_refresh
        if not isinstance(refresh, str) or not refresh:
            raise SpotifyOAuthError("spotify token response missing refresh_token")
        return SpotifyTokenSet(
            access_token=access,
            refresh_token=refresh,
            expires_in=int(payload.get("expires_in", 3600)),
            scope=payload.get("scope"),
        )
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/unit/test_spotify_oauth.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth/spotify_oauth.py tests/unit/test_spotify_oauth.py
git commit -m "feat(auth): add Spotify OAuth client (PKCE, /me, refresh)"
```

---

## Task 9: `auth/auth_settings.py` — settings + secret resolution

**Files:**
- Create: `src/collector/auth/auth_settings.py`
- Test: `tests/unit/test_auth_settings.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_settings.py`:

```python
from __future__ import annotations

import pytest

from collector.auth import auth_settings as mod


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    mod.reset_auth_settings_cache()
    yield
    mod.reset_auth_settings_cache()


def test_admin_ids_parsed_to_set(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "alice, bob ,charlie")
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://x/cb")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/,/dashboard")

    settings = mod.get_auth_settings()

    assert settings.admin_spotify_ids == {"alice", "bob", "charlie"}
    assert settings.is_admin("alice") is True
    assert settings.is_admin("dave") is False


def test_default_token_ttls(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://x/cb")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")

    settings = mod.get_auth_settings()

    assert settings.access_token_ttl_seconds == 1800
    assert settings.refresh_token_ttl_seconds == 604800


def test_overridden_ttls(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://x/cb")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")
    monkeypatch.setenv("JWT_ACCESS_TOKEN_TTL_SECONDS", "60")
    monkeypatch.setenv("JWT_REFRESH_TOKEN_TTL_SECONDS", "120")

    settings = mod.get_auth_settings()

    assert settings.access_token_ttl_seconds == 60
    assert settings.refresh_token_ttl_seconds == 120


def test_allowed_redirect_check(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://x/cb")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/, /dashboard, /me")

    settings = mod.get_auth_settings()

    assert settings.allows_redirect("/") is True
    assert settings.allows_redirect("/dashboard") is True
    assert settings.allows_redirect("/evil") is False


def test_resolve_jwt_signing_key_via_env(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SIGNING_KEY", "raw-secret-32-bytes-here-please-ok")

    assert mod.resolve_jwt_signing_key() == "raw-secret-32-bytes-here-please-ok"


def test_resolve_jwt_signing_key_via_ssm(monkeypatch) -> None:
    monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
    monkeypatch.setenv("JWT_SIGNING_KEY_SSM_PARAMETER", "/clouder/auth/jwt_signing_key")

    fetched = {}

    def fake_fetch(name: str) -> str:
        fetched["name"] = name
        return "from-ssm"

    monkeypatch.setattr("collector.secrets._fetch_ssm_parameter", fake_fetch)

    assert mod.resolve_jwt_signing_key() == "from-ssm"
    assert fetched["name"] == "/clouder/auth/jwt_signing_key"


def test_resolve_oauth_client_credentials_env(monkeypatch) -> None:
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid-env")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec-env")

    cid, csec = mod.resolve_oauth_client_credentials()
    assert cid == "cid-env"
    assert csec == "csec-env"


def test_resolve_oauth_client_credentials_ssm(monkeypatch) -> None:
    monkeypatch.delenv("SPOTIFY_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID_SSM_PARAMETER", "/c/id")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET_SSM_PARAMETER", "/c/secret")

    fetched = []

    def fake_fetch(name: str) -> str:
        fetched.append(name)
        return {"/c/id": "cid-ssm", "/c/secret": "csec-ssm"}[name]

    monkeypatch.setattr("collector.secrets._fetch_ssm_parameter", fake_fetch)

    cid, csec = mod.resolve_oauth_client_credentials()
    assert cid == "cid-ssm"
    assert csec == "csec-ssm"
    assert sorted(fetched) == ["/c/id", "/c/secret"]
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_auth_settings.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `src/collector/auth/auth_settings.py`:

```python
"""Auth Lambda settings + secret resolution."""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthSettings:
    kms_user_tokens_key_arn: str
    spotify_oauth_redirect_uri: str
    allowed_frontend_redirects: frozenset[str]
    admin_spotify_ids: frozenset[str]
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int

    def is_admin(self, spotify_id: str) -> bool:
        return spotify_id in self.admin_spotify_ids

    def allows_redirect(self, path: str) -> bool:
        return path in self.allowed_frontend_redirects


def _parse_csv(raw: str) -> frozenset[str]:
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


@functools.lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    return AuthSettings(
        kms_user_tokens_key_arn=os.environ["KMS_USER_TOKENS_KEY_ARN"],
        spotify_oauth_redirect_uri=os.environ["SPOTIFY_OAUTH_REDIRECT_URI"],
        allowed_frontend_redirects=_parse_csv(os.environ["ALLOWED_FRONTEND_REDIRECTS"]),
        admin_spotify_ids=_parse_csv(os.environ.get("ADMIN_SPOTIFY_IDS", "")),
        access_token_ttl_seconds=int(
            os.environ.get("JWT_ACCESS_TOKEN_TTL_SECONDS", "1800")
        ),
        refresh_token_ttl_seconds=int(
            os.environ.get("JWT_REFRESH_TOKEN_TTL_SECONDS", "604800")
        ),
    )


def reset_auth_settings_cache() -> None:
    get_auth_settings.cache_clear()


def resolve_jwt_signing_key() -> str:
    from collector import secrets

    direct = os.environ.get("JWT_SIGNING_KEY", "").strip()
    if direct:
        return direct
    ssm_name = os.environ.get("JWT_SIGNING_KEY_SSM_PARAMETER", "").strip()
    if ssm_name:
        return secrets._fetch_ssm_parameter(ssm_name)
    raise RuntimeError(
        "JWT signing key not configured: set JWT_SIGNING_KEY or JWT_SIGNING_KEY_SSM_PARAMETER"
    )


def resolve_oauth_client_credentials() -> tuple[str, str]:
    from collector import secrets

    cid = os.environ.get("SPOTIFY_OAUTH_CLIENT_ID", "").strip()
    csec = os.environ.get("SPOTIFY_OAUTH_CLIENT_SECRET", "").strip()
    if cid and csec:
        return cid, csec

    ssm_id = os.environ.get("SPOTIFY_OAUTH_CLIENT_ID_SSM_PARAMETER", "").strip()
    ssm_sec = os.environ.get("SPOTIFY_OAUTH_CLIENT_SECRET_SSM_PARAMETER", "").strip()
    if ssm_id and ssm_sec:
        return (
            cid or secrets._fetch_ssm_parameter(ssm_id),
            csec or secrets._fetch_ssm_parameter(ssm_sec),
        )

    raise RuntimeError(
        "Spotify OAuth credentials not configured: set "
        "SPOTIFY_OAUTH_CLIENT_ID/SECRET or *_SSM_PARAMETER pair"
    )
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/unit/test_auth_settings.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth/auth_settings.py tests/unit/test_auth_settings.py
git commit -m "feat(auth): add AuthSettings with env/SSM secret resolution"
```

---

## Task 10: `auth/auth_repository.py` — Aurora data access

**Files:**
- Create: `src/collector/auth/auth_repository.py`
- Test: `tests/unit/test_auth_repository.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_repository.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from collector.auth.auth_repository import (
    AuthRepository,
    SessionRow,
    UpsertUserCmd,
    UpsertVendorTokenCmd,
    UserRow,
    VendorTokenRow,
)


def _make() -> tuple[AuthRepository, MagicMock]:
    data_api = MagicMock()
    return AuthRepository(data_api=data_api), data_api


def test_upsert_user_emits_insert_on_conflict() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.upsert_user(
        UpsertUserCmd(
            id="u-1",
            spotify_id="sp-1",
            display_name="Roman",
            email="r@x",
            is_admin=True,
            now=now,
        )
    )

    sql = data_api.execute.call_args.args[0]
    params = data_api.execute.call_args.args[1]
    assert "INSERT INTO users" in sql
    assert "ON CONFLICT (spotify_id) DO UPDATE SET" in sql
    assert params["spotify_id"] == "sp-1"
    assert params["is_admin"] is True


def test_get_user_by_spotify_id_returns_user_row() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    data_api.execute.return_value = [
        {
            "id": "u-1",
            "spotify_id": "sp-1",
            "display_name": "Roman",
            "email": "r@x",
            "is_admin": True,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    ]

    user = repo.get_user_by_spotify_id("sp-1")
    assert isinstance(user, UserRow)
    assert user.id == "u-1"
    assert user.is_admin is True


def test_create_session_inserts_row() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.create_session(
        session_id="s-1",
        user_id="u-1",
        refresh_token_hash="hash",
        user_agent="ua",
        ip_address="1.2.3.4",
        created_at=now,
        expires_at=now,
    )

    sql = data_api.execute.call_args.args[0]
    params = data_api.execute.call_args.args[1]
    assert "INSERT INTO user_sessions" in sql
    assert params["id"] == "s-1"
    assert params["refresh_token_hash"] == "hash"


def test_get_active_session_filters_by_revoked_and_expiry() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    data_api.execute.return_value = [
        {
            "id": "s-1",
            "user_id": "u-1",
            "refresh_token_hash": "h1",
            "user_agent": "ua",
            "ip_address": "1.2.3.4",
            "created_at": now.isoformat(),
            "last_used_at": now.isoformat(),
            "expires_at": now.isoformat(),
            "revoked_at": None,
        }
    ]

    session = repo.get_active_session("s-1", now=now)

    assert isinstance(session, SessionRow)
    assert session.id == "s-1"
    sql = data_api.execute.call_args.args[0]
    assert "revoked_at IS NULL" in sql
    assert "expires_at > :now" in sql


def test_rotate_session_updates_hash_and_last_used() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.rotate_session(
        session_id="s-1", new_hash="h2", last_used_at=now
    )

    sql = data_api.execute.call_args.args[0]
    params = data_api.execute.call_args.args[1]
    assert "UPDATE user_sessions" in sql
    assert "SET refresh_token_hash = :hash" in sql
    assert params["id"] == "s-1"
    assert params["hash"] == "h2"


def test_revoke_session_sets_revoked_at() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.revoke_session("s-1", revoked_at=now)

    sql = data_api.execute.call_args.args[0]
    assert "UPDATE user_sessions" in sql
    assert "SET revoked_at = :revoked_at" in sql


def test_revoke_all_sessions_for_user() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.revoke_all_user_sessions("u-1", revoked_at=now)

    sql = data_api.execute.call_args.args[0]
    assert "WHERE user_id = :user_id" in sql
    assert "revoked_at IS NULL" in sql


def test_list_user_sessions_returns_active_only() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    data_api.execute.return_value = []

    repo.list_active_sessions(user_id="u-1", now=now)

    sql = data_api.execute.call_args.args[0]
    assert "WHERE user_id = :user_id" in sql
    assert "revoked_at IS NULL" in sql
    assert "expires_at > :now" in sql


def test_upsert_vendor_token_serializes_bytes() -> None:
    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    repo.upsert_vendor_token(
        UpsertVendorTokenCmd(
            user_id="u-1",
            vendor="spotify",
            access_token_enc=b"\x01\x02",
            refresh_token_enc=b"\x03\x04",
            data_key_enc=b"\x05",
            scope="user-read-email",
            expires_at=now,
            updated_at=now,
        )
    )

    sql = data_api.execute.call_args.args[0]
    params = data_api.execute.call_args.args[1]
    assert "INSERT INTO user_vendor_tokens" in sql
    assert "ON CONFLICT (user_id, vendor) DO UPDATE SET" in sql
    # Bytes are base64-encoded for the Data API stringValue serializer.
    assert isinstance(params["access_token_enc"], str)
    assert isinstance(params["data_key_enc"], str)


def test_get_vendor_token_decodes_bytes() -> None:
    import base64

    repo, data_api = _make()
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    data_api.execute.return_value = [
        {
            "user_id": "u-1",
            "vendor": "spotify",
            "access_token_enc": base64.b64encode(b"\x01\x02").decode(),
            "refresh_token_enc": base64.b64encode(b"\x03\x04").decode(),
            "data_key_enc": base64.b64encode(b"\x05").decode(),
            "scope": "user-read-email",
            "expires_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    ]

    row = repo.get_vendor_token(user_id="u-1", vendor="spotify")
    assert isinstance(row, VendorTokenRow)
    assert row.access_token_enc == b"\x01\x02"
    assert row.refresh_token_enc == b"\x03\x04"
    assert row.data_key_enc == b"\x05"


def test_delete_vendor_token() -> None:
    repo, _ = _make()

    repo.delete_vendor_token(user_id="u-1", vendor="spotify")

    sql = repo._data_api.execute.call_args.args[0]
    assert "DELETE FROM user_vendor_tokens" in sql
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_auth_repository.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `src/collector/auth/auth_repository.py`:

```python
"""Aurora Data API repository for users / sessions / vendor tokens.

Bytea columns must round-trip through the Data API stringValue field. We
base64-encode bytes on the way in and decode on the way out — Data API does
not natively support BYTEA parameters.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from collector.data_api import DataAPIClient


@dataclass(frozen=True)
class UserRow:
    id: str
    spotify_id: str
    display_name: str | None
    email: str | None
    is_admin: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class SessionRow:
    id: str
    user_id: str
    refresh_token_hash: str
    user_agent: str | None
    ip_address: str | None
    created_at: str
    last_used_at: str
    expires_at: str
    revoked_at: str | None


@dataclass(frozen=True)
class VendorTokenRow:
    user_id: str
    vendor: str
    access_token_enc: bytes
    refresh_token_enc: bytes | None
    data_key_enc: bytes
    scope: str | None
    expires_at: str | None
    updated_at: str


@dataclass(frozen=True)
class UpsertUserCmd:
    id: str
    spotify_id: str
    display_name: str | None
    email: str | None
    is_admin: bool
    now: datetime


@dataclass(frozen=True)
class UpsertVendorTokenCmd:
    user_id: str
    vendor: str
    access_token_enc: bytes
    refresh_token_enc: bytes | None
    data_key_enc: bytes
    scope: str | None
    expires_at: datetime | None
    updated_at: datetime


def _b64e(value: bytes | None) -> str | None:
    if value is None:
        return None
    return base64.b64encode(value).decode("ascii")


def _b64d(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if value is None:
        return b""
    return base64.b64decode(value)


def _b64d_optional(value: Any) -> bytes | None:
    if value is None:
        return None
    return _b64d(value)


class AuthRepository:
    def __init__(self, *, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    # ── users ────────────────────────────────────────────────────────

    def upsert_user(self, cmd: UpsertUserCmd) -> None:
        self._data_api.execute(
            """
            INSERT INTO users (
                id, spotify_id, display_name, email, is_admin,
                created_at, updated_at
            ) VALUES (
                :id, :spotify_id, :display_name, :email, :is_admin,
                :now, :now
            )
            ON CONFLICT (spotify_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                email = EXCLUDED.email,
                is_admin = EXCLUDED.is_admin,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "id": cmd.id,
                "spotify_id": cmd.spotify_id,
                "display_name": cmd.display_name,
                "email": cmd.email,
                "is_admin": cmd.is_admin,
                "now": cmd.now,
            },
        )

    def get_user_by_spotify_id(self, spotify_id: str) -> UserRow | None:
        rows = self._data_api.execute(
            """
            SELECT id, spotify_id, display_name, email, is_admin,
                   created_at, updated_at
            FROM users
            WHERE spotify_id = :spotify_id
            """,
            {"spotify_id": spotify_id},
        )
        return _to_user_row(rows[0]) if rows else None

    def get_user_by_id(self, user_id: str) -> UserRow | None:
        rows = self._data_api.execute(
            """
            SELECT id, spotify_id, display_name, email, is_admin,
                   created_at, updated_at
            FROM users
            WHERE id = :id
            """,
            {"id": user_id},
        )
        return _to_user_row(rows[0]) if rows else None

    # ── sessions ─────────────────────────────────────────────────────

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        refresh_token_hash: str,
        user_agent: str | None,
        ip_address: str | None,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO user_sessions (
                id, user_id, refresh_token_hash, user_agent, ip_address,
                created_at, last_used_at, expires_at
            ) VALUES (
                :id, :user_id, :refresh_token_hash, :user_agent, :ip_address,
                :created_at, :created_at, :expires_at
            )
            """,
            {
                "id": session_id,
                "user_id": user_id,
                "refresh_token_hash": refresh_token_hash,
                "user_agent": user_agent,
                "ip_address": ip_address,
                "created_at": created_at,
                "expires_at": expires_at,
            },
        )

    def get_active_session(
        self, session_id: str, *, now: datetime
    ) -> SessionRow | None:
        rows = self._data_api.execute(
            """
            SELECT id, user_id, refresh_token_hash, user_agent, ip_address,
                   created_at, last_used_at, expires_at, revoked_at
            FROM user_sessions
            WHERE id = :id
              AND revoked_at IS NULL
              AND expires_at > :now
            """,
            {"id": session_id, "now": now},
        )
        return _to_session_row(rows[0]) if rows else None

    def rotate_session(
        self, *, session_id: str, new_hash: str, last_used_at: datetime
    ) -> None:
        self._data_api.execute(
            """
            UPDATE user_sessions
            SET refresh_token_hash = :hash,
                last_used_at = :last_used_at
            WHERE id = :id
            """,
            {"id": session_id, "hash": new_hash, "last_used_at": last_used_at},
        )

    def revoke_session(self, session_id: str, *, revoked_at: datetime) -> None:
        self._data_api.execute(
            """
            UPDATE user_sessions
            SET revoked_at = :revoked_at
            WHERE id = :id AND revoked_at IS NULL
            """,
            {"id": session_id, "revoked_at": revoked_at},
        )

    def revoke_all_user_sessions(
        self, user_id: str, *, revoked_at: datetime
    ) -> None:
        self._data_api.execute(
            """
            UPDATE user_sessions
            SET revoked_at = :revoked_at
            WHERE user_id = :user_id AND revoked_at IS NULL
            """,
            {"user_id": user_id, "revoked_at": revoked_at},
        )

    def list_active_sessions(
        self, *, user_id: str, now: datetime
    ) -> list[SessionRow]:
        rows = self._data_api.execute(
            """
            SELECT id, user_id, refresh_token_hash, user_agent, ip_address,
                   created_at, last_used_at, expires_at, revoked_at
            FROM user_sessions
            WHERE user_id = :user_id
              AND revoked_at IS NULL
              AND expires_at > :now
            ORDER BY last_used_at DESC
            """,
            {"user_id": user_id, "now": now},
        )
        return [_to_session_row(row) for row in rows]

    # ── vendor tokens ────────────────────────────────────────────────

    def upsert_vendor_token(self, cmd: UpsertVendorTokenCmd) -> None:
        self._data_api.execute(
            """
            INSERT INTO user_vendor_tokens (
                user_id, vendor, access_token_enc, refresh_token_enc,
                data_key_enc, scope, expires_at, updated_at
            ) VALUES (
                :user_id, :vendor,
                decode(:access_token_enc, 'base64'),
                decode(:refresh_token_enc, 'base64'),
                decode(:data_key_enc, 'base64'),
                :scope, :expires_at, :updated_at
            )
            ON CONFLICT (user_id, vendor) DO UPDATE SET
                access_token_enc = EXCLUDED.access_token_enc,
                refresh_token_enc = EXCLUDED.refresh_token_enc,
                data_key_enc = EXCLUDED.data_key_enc,
                scope = EXCLUDED.scope,
                expires_at = EXCLUDED.expires_at,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "user_id": cmd.user_id,
                "vendor": cmd.vendor,
                "access_token_enc": _b64e(cmd.access_token_enc),
                "refresh_token_enc": _b64e(cmd.refresh_token_enc),
                "data_key_enc": _b64e(cmd.data_key_enc),
                "scope": cmd.scope,
                "expires_at": cmd.expires_at,
                "updated_at": cmd.updated_at,
            },
        )

    def get_vendor_token(
        self, *, user_id: str, vendor: str
    ) -> VendorTokenRow | None:
        rows = self._data_api.execute(
            """
            SELECT user_id, vendor,
                   encode(access_token_enc, 'base64')  AS access_token_enc,
                   encode(refresh_token_enc, 'base64') AS refresh_token_enc,
                   encode(data_key_enc, 'base64')      AS data_key_enc,
                   scope, expires_at, updated_at
            FROM user_vendor_tokens
            WHERE user_id = :user_id AND vendor = :vendor
            """,
            {"user_id": user_id, "vendor": vendor},
        )
        return _to_vendor_token_row(rows[0]) if rows else None

    def delete_vendor_token(self, *, user_id: str, vendor: str) -> None:
        self._data_api.execute(
            """
            DELETE FROM user_vendor_tokens
            WHERE user_id = :user_id AND vendor = :vendor
            """,
            {"user_id": user_id, "vendor": vendor},
        )


def _to_user_row(row: Mapping[str, Any]) -> UserRow:
    return UserRow(
        id=str(row["id"]),
        spotify_id=str(row["spotify_id"]),
        display_name=row.get("display_name"),
        email=row.get("email"),
        is_admin=bool(row.get("is_admin", False)),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _to_session_row(row: Mapping[str, Any]) -> SessionRow:
    return SessionRow(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        refresh_token_hash=str(row["refresh_token_hash"]),
        user_agent=row.get("user_agent"),
        ip_address=row.get("ip_address"),
        created_at=str(row["created_at"]),
        last_used_at=str(row["last_used_at"]),
        expires_at=str(row["expires_at"]),
        revoked_at=row.get("revoked_at"),
    )


def _to_vendor_token_row(row: Mapping[str, Any]) -> VendorTokenRow:
    return VendorTokenRow(
        user_id=str(row["user_id"]),
        vendor=str(row["vendor"]),
        access_token_enc=_b64d(row["access_token_enc"]),
        refresh_token_enc=_b64d_optional(row.get("refresh_token_enc")),
        data_key_enc=_b64d(row["data_key_enc"]),
        scope=row.get("scope"),
        expires_at=row.get("expires_at"),
        updated_at=str(row["updated_at"]),
    )
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/unit/test_auth_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth/auth_repository.py tests/unit/test_auth_repository.py
git commit -m "feat(auth): add AuthRepository for users/sessions/vendor_tokens"
```

---

## Task 11: Add auth-specific error classes

**Files:**
- Modify: `src/collector/errors.py`
- Test: extend existing `tests/unit/test_vendor_errors.py` is fine, but to keep this task self-contained we add a focused unit test.
- Test: `tests/unit/test_auth_errors.py` (new — small)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_errors.py`:

```python
from __future__ import annotations

from collector.errors import (
    AdminRequiredError,
    CannotRevokeCurrentSessionError,
    CsrfStateMismatchError,
    OAuthExchangeFailedError,
    PremiumRequiredError,
    RefreshInvalidError,
    RefreshReplayDetectedError,
    SpotifyRevokedError,
)


def test_premium_required_error_shape() -> None:
    err = PremiumRequiredError(upgrade_url="https://www.spotify.com/premium/")
    assert err.status_code == 403
    assert err.error_code == "premium_required"
    assert err.upgrade_url == "https://www.spotify.com/premium/"


def test_csrf_state_mismatch_is_400() -> None:
    err = CsrfStateMismatchError()
    assert err.status_code == 400
    assert err.error_code == "csrf_state_mismatch"


def test_oauth_exchange_failed_is_502() -> None:
    err = OAuthExchangeFailedError("Spotify down")
    assert err.status_code == 502
    assert err.error_code == "oauth_exchange_failed"


def test_refresh_invalid_is_401() -> None:
    err = RefreshInvalidError()
    assert err.status_code == 401
    assert err.error_code == "refresh_invalid"


def test_refresh_replay_detected_is_401() -> None:
    err = RefreshReplayDetectedError()
    assert err.status_code == 401
    assert err.error_code == "refresh_replay_detected"


def test_spotify_revoked_is_401() -> None:
    err = SpotifyRevokedError()
    assert err.status_code == 401
    assert err.error_code == "spotify_revoked"


def test_admin_required_is_403() -> None:
    err = AdminRequiredError()
    assert err.status_code == 403
    assert err.error_code == "admin_required"


def test_cannot_revoke_current_is_400() -> None:
    err = CannotRevokeCurrentSessionError()
    assert err.status_code == 400
    assert err.error_code == "cannot_revoke_current"
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_auth_errors.py -q`
Expected: FAIL — names not yet defined.

- [ ] **Step 3: Append new error classes**

Append to `src/collector/errors.py`:

```python
class PremiumRequiredError(AppError):
    def __init__(
        self,
        *,
        upgrade_url: str = "https://www.spotify.com/premium/",
        message: str = "Spotify Premium required",
    ) -> None:
        super().__init__(
            status_code=403, error_code="premium_required", message=message
        )
        self.upgrade_url = upgrade_url


class CsrfStateMismatchError(AppError):
    def __init__(self, message: str = "OAuth state mismatch") -> None:
        super().__init__(
            status_code=400, error_code="csrf_state_mismatch", message=message
        )


class OAuthExchangeFailedError(AppError):
    def __init__(self, message: str = "OAuth code exchange failed") -> None:
        super().__init__(
            status_code=502, error_code="oauth_exchange_failed", message=message
        )


class SpotifyRevokedError(AppError):
    def __init__(
        self, message: str = "Spotify refresh token revoked, re-authentication required"
    ) -> None:
        super().__init__(
            status_code=401, error_code="spotify_revoked", message=message
        )


class RefreshInvalidError(AppError):
    def __init__(self, message: str = "Refresh token missing or invalid") -> None:
        super().__init__(
            status_code=401, error_code="refresh_invalid", message=message
        )


class RefreshReplayDetectedError(AppError):
    def __init__(
        self, message: str = "Refresh-token replay detected, session revoked"
    ) -> None:
        super().__init__(
            status_code=401,
            error_code="refresh_replay_detected",
            message=message,
        )


class AdminRequiredError(AppError):
    def __init__(self, message: str = "Admin privileges required") -> None:
        super().__init__(
            status_code=403, error_code="admin_required", message=message
        )


class CannotRevokeCurrentSessionError(AppError):
    def __init__(
        self, message: str = "Cannot revoke the current session — use logout"
    ) -> None:
        super().__init__(
            status_code=400,
            error_code="cannot_revoke_current",
            message=message,
        )
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/unit/test_auth_errors.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/errors.py tests/unit/test_auth_errors.py
git commit -m "feat(auth): add auth-specific error classes"
```

---

## Task 12: `auth_handler.py` skeleton + `GET /auth/login`

**Files:**
- Create: `src/collector/auth_handler.py`
- Test: `tests/unit/test_auth_handler_login.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_handler_login.py`:

```python
from __future__ import annotations

import json
import urllib.parse
from types import SimpleNamespace

import pytest

from collector.auth import auth_settings
from collector.auth_handler import lambda_handler


def _event(query: dict | None = None) -> dict:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "api-req-login",
            "routeKey": "GET /auth/login",
        },
        "headers": {"x-correlation-id": "cid-login"},
        "queryStringParameters": query,
        "body": None,
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/, /dashboard")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def test_login_returns_302_with_state_and_verifier_cookies() -> None:
    response = lambda_handler(_event(), SimpleNamespace(aws_request_id="L"))

    assert response["statusCode"] == 302
    location = response["headers"]["location"]
    assert location.startswith("https://accounts.spotify.com/authorize?")

    parsed = urllib.parse.urlparse(location)
    qs = urllib.parse.parse_qs(parsed.query)
    assert qs["client_id"] == ["cid"]
    assert qs["redirect_uri"] == ["https://app.x/auth/callback"]
    assert qs["response_type"] == ["code"]
    assert qs["code_challenge_method"] == ["S256"]
    assert "code_challenge" in qs
    assert "state" in qs
    assert "user-read-email" in qs["scope"][0]
    assert "streaming" in qs["scope"][0]

    cookies = response.get("cookies") or []
    cookie_pairs = {c.split("=")[0]: c for c in cookies}
    assert "oauth_state" in cookie_pairs
    assert "oauth_verifier" in cookie_pairs
    assert "HttpOnly" in cookie_pairs["oauth_state"]
    assert "Secure" in cookie_pairs["oauth_state"]
    assert "SameSite=Lax" in cookie_pairs["oauth_state"]


def test_login_rejects_unknown_redirect_uri() -> None:
    response = lambda_handler(
        _event({"redirect_uri": "/evil"}),
        SimpleNamespace(aws_request_id="L"),
    )
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "validation_error"


def test_login_unknown_route_returns_404() -> None:
    event = _event()
    event["requestContext"]["routeKey"] = "GET /unknown"
    response = lambda_handler(event, SimpleNamespace(aws_request_id="L"))
    assert response["statusCode"] == 404
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_auth_handler_login.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement skeleton + login route**

Create `src/collector/auth_handler.py`:

```python
"""Auth Lambda — /auth/login, /auth/callback, /auth/refresh, /auth/logout, /me."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

from .auth.auth_settings import (
    get_auth_settings,
    resolve_oauth_client_credentials,
)
from .auth.pkce import derive_code_challenge, generate_code_verifier
from .auth.spotify_oauth import SpotifyOAuthClient
from .errors import AppError, ValidationError
from .logging_utils import log_event


SPOTIFY_SCOPES = (
    "user-read-email user-read-private "
    "playlist-modify-public playlist-modify-private "
    "streaming user-read-playback-state user-modify-playback-state"
)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    correlation_id = _correlation_id(event)
    try:
        return _route(event, context, correlation_id)
    except AppError as exc:
        log_event(
            "ERROR",
            "auth_request_failed",
            correlation_id=correlation_id,
            error_code=exc.error_code,
            status_code=exc.status_code,
            error_type=exc.__class__.__name__,
        )
        return _error_response(exc, correlation_id)
    except Exception as exc:  # pragma: no cover
        log_event(
            "ERROR",
            "auth_request_failed_unexpected",
            correlation_id=correlation_id,
            error_type=exc.__class__.__name__,
            error_message=str(exc)[:500],
        )
        return _json_response(
            500,
            {"error_code": "internal_error", "message": "Internal server error",
             "correlation_id": correlation_id},
            correlation_id,
        )


def _route(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    route = _route_key(event)
    if route == "GET /auth/login":
        return _handle_login(event, correlation_id)
    return _json_response(
        404,
        {"error_code": "not_found", "message": "Route not found",
         "correlation_id": correlation_id},
        correlation_id,
    )


def _handle_login(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    settings = get_auth_settings()
    query = event.get("queryStringParameters") or {}
    redirect = query.get("redirect_uri") if isinstance(query, Mapping) else None
    if redirect is not None and not settings.allows_redirect(redirect):
        raise ValidationError("redirect_uri not in allow-list")

    state = uuid.uuid4().hex
    verifier = generate_code_verifier()
    challenge = derive_code_challenge(verifier)

    cid, csec = resolve_oauth_client_credentials()
    oauth = SpotifyOAuthClient(
        client_id=cid,
        client_secret=csec,
        redirect_uri=settings.spotify_oauth_redirect_uri,
    )
    location = oauth.authorize_url(
        state=state, code_challenge=challenge, scopes=SPOTIFY_SCOPES
    )

    log_event(
        "INFO",
        "auth_login_redirect_issued",
        correlation_id=correlation_id,
    )

    cookies = [
        _short_cookie("oauth_state", state, max_age=600),
        _short_cookie("oauth_verifier", verifier, max_age=600),
    ]
    if redirect:
        cookies.append(_short_cookie("oauth_redirect", redirect, max_age=600))

    return {
        "statusCode": 302,
        "headers": {
            "location": location,
            "x-correlation-id": correlation_id,
        },
        "cookies": cookies,
        "body": "",
    }


def _short_cookie(name: str, value: str, *, max_age: int) -> str:
    return (
        f"{name}={value}; Path=/; HttpOnly; Secure; SameSite=Lax; "
        f"Max-Age={max_age}"
    )


def _correlation_id(event: Mapping[str, Any]) -> str:
    headers = event.get("headers") or {}
    if isinstance(headers, Mapping):
        for k, v in headers.items():
            if isinstance(k, str) and k.lower() == "x-correlation-id" and isinstance(v, str) and v:
                return v
    return uuid.uuid4().hex


def _route_key(event: Mapping[str, Any]) -> str:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        rk = rc.get("routeKey")
        if isinstance(rk, str):
            return rk
    return ""


def _error_response(exc: AppError, correlation_id: str) -> dict[str, Any]:
    body = {
        "error_code": exc.error_code,
        "message": exc.message,
        "correlation_id": correlation_id,
    }
    upgrade_url = getattr(exc, "upgrade_url", None)
    if upgrade_url is not None:
        body["upgrade_url"] = upgrade_url
    return _json_response(exc.status_code, body, correlation_id)


def _json_response(
    status_code: int, payload: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/unit/test_auth_handler_login.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth_handler.py tests/unit/test_auth_handler_login.py
git commit -m "feat(auth): add auth_handler skeleton with /auth/login"
```

---

## Task 13: `auth_handler.py` — `GET /auth/callback`

**Files:**
- Modify: `src/collector/auth_handler.py`
- Test: `tests/unit/test_auth_handler_callback.py`

This task introduces a small `AuthDependencies` factory at the top of `auth_handler.py` so tests can inject a fake repository, fake OAuth client, fake KMS envelope, and a fixed clock without monkeypatching half the module. All later auth_handler tasks reuse this seam.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_handler_callback.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.auth import auth_settings
from collector.auth.auth_repository import UserRow
from collector.auth.kms_envelope import EnvelopePayload
from collector.auth.spotify_oauth import (
    SpotifyOAuthError,
    SpotifyProfile,
    SpotifyTokenSet,
)
from collector import auth_handler


def _event(*, code: str, state: str, cookies: list[str]) -> dict:
    return {
        "version": "2.0",
        "requestContext": {"requestId": "req", "routeKey": "GET /auth/callback"},
        "headers": {"x-correlation-id": "cid"},
        "queryStringParameters": {"code": code, "state": state},
        "cookies": cookies,
        "body": None,
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "sp-admin")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SIGNING_KEY", "0" * 32)
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def _wire(monkeypatch, *, oauth, repo, envelope, now):
    monkeypatch.setattr(auth_handler, "_build_oauth_client", lambda: oauth)
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_build_kms_envelope", lambda: envelope)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)


def test_callback_premium_user_creates_session_and_returns_jwt(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    oauth = MagicMock()
    oauth.exchange_code.return_value = SpotifyTokenSet(
        access_token="AT", refresh_token="RT", expires_in=3600,
        scope="user-read-email",
    )
    oauth.get_me.return_value = SpotifyProfile(
        spotify_id="sp-user", display_name="Roman", email="r@x", product="premium",
    )
    repo = MagicMock()
    envelope = MagicMock()
    envelope.encrypt.return_value = EnvelopePayload(
        data_key_enc=b"K", nonce=b"n" * 12, ciphertext=b"C",
    )
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(code="X", state="STATE", cookies=["oauth_state=STATE", "oauth_verifier=V"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["spotify_access_token"] == "AT"
    assert body["expires_in"] == 1800
    assert body["user"]["spotify_id"] == "sp-user"
    assert body["user"]["is_admin"] is False
    assert "access_token" in body

    cookies = response.get("cookies") or []
    refresh_cookie = next(c for c in cookies if c.startswith("refresh_token="))
    assert "HttpOnly" in refresh_cookie
    assert "Secure" in refresh_cookie
    assert "SameSite=Strict" in refresh_cookie
    assert "Path=/auth/refresh" in refresh_cookie

    repo.upsert_user.assert_called_once()
    repo.create_session.assert_called_once()
    repo.upsert_vendor_token.assert_called_once()


def test_callback_admin_user_gets_is_admin_true(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    oauth = MagicMock()
    oauth.exchange_code.return_value = SpotifyTokenSet(
        access_token="AT", refresh_token="RT", expires_in=3600, scope=None,
    )
    oauth.get_me.return_value = SpotifyProfile(
        spotify_id="sp-admin", display_name=None, email=None, product="premium",
    )
    repo = MagicMock()
    envelope = MagicMock()
    envelope.encrypt.return_value = EnvelopePayload(
        data_key_enc=b"K", nonce=b"n" * 12, ciphertext=b"C",
    )
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(code="X", state="STATE", cookies=["oauth_state=STATE", "oauth_verifier=V"]),
        SimpleNamespace(aws_request_id="L"),
    )

    body = json.loads(response["body"])
    assert body["user"]["is_admin"] is True
    upsert_cmd = repo.upsert_user.call_args.args[0]
    assert upsert_cmd.is_admin is True


def test_callback_non_premium_returns_403_without_db_writes(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    oauth = MagicMock()
    oauth.exchange_code.return_value = SpotifyTokenSet(
        access_token="AT", refresh_token="RT", expires_in=3600, scope=None,
    )
    oauth.get_me.return_value = SpotifyProfile(
        spotify_id="sp-free", display_name="Free", email="f@x", product="free",
    )
    repo = MagicMock()
    envelope = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(code="X", state="STATE", cookies=["oauth_state=STATE", "oauth_verifier=V"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "premium_required"
    assert body["upgrade_url"].startswith("https://")
    repo.upsert_user.assert_not_called()
    repo.create_session.assert_not_called()
    repo.upsert_vendor_token.assert_not_called()


def test_callback_state_mismatch_returns_400(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    oauth = MagicMock()
    repo = MagicMock()
    envelope = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(code="X", state="WRONG", cookies=["oauth_state=RIGHT", "oauth_verifier=V"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "csrf_state_mismatch"
    oauth.exchange_code.assert_not_called()


def test_callback_oauth_exchange_failure_returns_502(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    oauth = MagicMock()
    oauth.exchange_code.side_effect = SpotifyOAuthError("boom")
    repo = MagicMock()
    envelope = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(code="X", state="STATE", cookies=["oauth_state=STATE", "oauth_verifier=V"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert body["error_code"] == "oauth_exchange_failed"
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_auth_handler_callback.py -q`
Expected: FAIL — callback route + builders missing.

- [ ] **Step 3: Implement callback**

Update `src/collector/auth_handler.py`. Add the imports near the top:

```python
import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone

from .auth.auth_repository import (
    AuthRepository,
    UpsertUserCmd,
    UpsertVendorTokenCmd,
)
from .auth.auth_settings import resolve_jwt_signing_key
from .auth.jwt_utils import issue_access_token, issue_refresh_token
from .auth.kms_envelope import KmsEnvelope
from .auth.spotify_oauth import (
    SpotifyOAuthError,
    SpotifyOAuthClient,
    SpotifyTokenRevokedError,
)
from .data_api import create_default_data_api_client
from .errors import (
    CsrfStateMismatchError,
    OAuthExchangeFailedError,
    PremiumRequiredError,
)
from .settings import get_data_api_settings
```

Add factory builders (these are the seams patched by tests):

```python
def _build_oauth_client() -> SpotifyOAuthClient:
    settings = get_auth_settings()
    cid, csec = resolve_oauth_client_credentials()
    return SpotifyOAuthClient(
        client_id=cid,
        client_secret=csec,
        redirect_uri=settings.spotify_oauth_redirect_uri,
    )


def _build_auth_repository() -> AuthRepository:
    db = get_data_api_settings()
    if not db.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    return AuthRepository(
        data_api=create_default_data_api_client(
            resource_arn=str(db.aurora_cluster_arn),
            secret_arn=str(db.aurora_secret_arn),
            database=db.aurora_database,
        )
    )


def _build_kms_envelope() -> KmsEnvelope:
    import boto3

    settings = get_auth_settings()
    return KmsEnvelope(
        kms_client=boto3.client("kms"),
        key_arn=settings.kms_user_tokens_key_arn,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
```

Extend `_route` to dispatch the callback:

```python
def _route(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    route = _route_key(event)
    if route == "GET /auth/login":
        return _handle_login(event, correlation_id)
    if route == "GET /auth/callback":
        return _handle_callback(event, correlation_id)
    return _json_response(
        404,
        {"error_code": "not_found", "message": "Route not found",
         "correlation_id": correlation_id},
        correlation_id,
    )
```

Add the handler:

```python
def _parse_cookies(event: Mapping[str, Any]) -> dict[str, str]:
    raw = event.get("cookies") or []
    out: dict[str, str] = {}
    for entry in raw:
        if isinstance(entry, str) and "=" in entry:
            k, v = entry.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _handle_callback(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    settings = get_auth_settings()
    query = event.get("queryStringParameters") or {}
    code = query.get("code") if isinstance(query, Mapping) else None
    state = query.get("state") if isinstance(query, Mapping) else None
    if not code or not state:
        raise ValidationError("code and state are required")

    cookies = _parse_cookies(event)
    if cookies.get("oauth_state") != state:
        raise CsrfStateMismatchError()
    verifier = cookies.get("oauth_verifier")
    if not verifier:
        raise CsrfStateMismatchError("missing oauth_verifier cookie")

    oauth = _build_oauth_client()
    try:
        tokens = oauth.exchange_code(code=code, code_verifier=verifier)
        profile = oauth.get_me(access_token=tokens.access_token)
    except SpotifyOAuthError as exc:
        raise OAuthExchangeFailedError(str(exc)) from exc

    if profile.product != "premium":
        raise PremiumRequiredError()

    repo = _build_auth_repository()
    envelope = _build_kms_envelope()
    now = _now()

    user_id = _resolve_user_id(repo, profile.spotify_id)
    is_admin = settings.is_admin(profile.spotify_id)
    repo.upsert_user(
        UpsertUserCmd(
            id=user_id,
            spotify_id=profile.spotify_id,
            display_name=profile.display_name,
            email=profile.email,
            is_admin=is_admin,
            now=now,
        )
    )

    access_payload = envelope.encrypt(tokens.access_token.encode("utf-8"))
    refresh_payload = envelope.encrypt(tokens.refresh_token.encode("utf-8"))
    repo.upsert_vendor_token(
        UpsertVendorTokenCmd(
            user_id=user_id,
            vendor="spotify",
            access_token_enc=access_payload.serialize(),
            refresh_token_enc=refresh_payload.serialize(),
            data_key_enc=access_payload.data_key_enc,
            scope=tokens.scope,
            expires_at=now + timedelta(seconds=tokens.expires_in),
            updated_at=now,
        )
    )

    session_id = uuid.uuid4().hex
    secret = resolve_jwt_signing_key()
    refresh_jwt = issue_refresh_token(
        secret=secret,
        user_id=user_id,
        session_id=session_id,
        ttl_seconds=settings.refresh_token_ttl_seconds,
        now=now,
    )
    refresh_hash = _sha256_hex(refresh_jwt)
    repo.create_session(
        session_id=session_id,
        user_id=user_id,
        refresh_token_hash=refresh_hash,
        user_agent=_header(event, "user-agent"),
        ip_address=_source_ip(event),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
    )

    access_jwt = issue_access_token(
        secret=secret,
        user_id=user_id,
        session_id=session_id,
        is_admin=is_admin,
        ttl_seconds=settings.access_token_ttl_seconds,
        now=now,
    )

    response_body = {
        "access_token": access_jwt,
        "spotify_access_token": tokens.access_token,
        "expires_in": settings.access_token_ttl_seconds,
        "user": {
            "id": user_id,
            "spotify_id": profile.spotify_id,
            "display_name": profile.display_name,
            "is_admin": is_admin,
        },
        "correlation_id": correlation_id,
    }

    log_event(
        "INFO",
        "auth_callback_success",
        correlation_id=correlation_id,
        user_id=user_id,
        is_admin=is_admin,
    )

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "cookies": [
            _refresh_cookie(refresh_jwt, max_age=settings.refresh_token_ttl_seconds),
            _short_cookie("oauth_state", "", max_age=0),
            _short_cookie("oauth_verifier", "", max_age=0),
        ],
        "body": json.dumps(response_body, ensure_ascii=False),
    }


def _resolve_user_id(repo: AuthRepository, spotify_id: str) -> str:
    existing = repo.get_user_by_spotify_id(spotify_id)
    return existing.id if existing else uuid.uuid4().hex


def _refresh_cookie(value: str, *, max_age: int) -> str:
    return (
        f"refresh_token={value}; Path=/auth/refresh; HttpOnly; Secure; "
        f"SameSite=Strict; Max-Age={max_age}"
    )


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _header(event: Mapping[str, Any], name: str) -> str | None:
    headers = event.get("headers") or {}
    if isinstance(headers, Mapping):
        for k, v in headers.items():
            if isinstance(k, str) and k.lower() == name and isinstance(v, str):
                return v
    return None


def _source_ip(event: Mapping[str, Any]) -> str | None:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        http = rc.get("http")
        if isinstance(http, Mapping):
            ip = http.get("sourceIp")
            if isinstance(ip, str):
                return ip
    return None
```

- [ ] **Step 4: Run callback tests + login tests**

Run: `pytest tests/unit/test_auth_handler_login.py tests/unit/test_auth_handler_callback.py -q`
Expected: PASS for both.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth_handler.py tests/unit/test_auth_handler_callback.py
git commit -m "feat(auth): implement /auth/callback with PKCE + Premium gate"
```

---

## Task 14: `auth_handler.py` — `POST /auth/refresh`

**Files:**
- Modify: `src/collector/auth_handler.py`
- Test: `tests/unit/test_auth_handler_refresh.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_handler_refresh.py`:

```python
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.auth import auth_settings
from collector.auth.auth_repository import SessionRow, VendorTokenRow
from collector.auth.jwt_utils import issue_refresh_token
from collector.auth.kms_envelope import EnvelopePayload
from collector.auth.spotify_oauth import (
    SpotifyTokenRevokedError,
    SpotifyTokenSet,
)
from collector import auth_handler


SECRET = "0" * 32


def _event(*, cookies: list[str]) -> dict:
    return {
        "version": "2.0",
        "requestContext": {"requestId": "req", "routeKey": "POST /auth/refresh"},
        "headers": {"x-correlation-id": "cid"},
        "queryStringParameters": None,
        "cookies": cookies,
        "body": "",
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SIGNING_KEY", SECRET)
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def _wire(monkeypatch, *, oauth, repo, envelope, now):
    monkeypatch.setattr(auth_handler, "_build_oauth_client", lambda: oauth)
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_build_kms_envelope", lambda: envelope)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)


def _refresh_jwt(now: datetime, *, user_id: str = "u-1", session_id: str = "s-1") -> str:
    return issue_refresh_token(
        secret=SECRET,
        user_id=user_id,
        session_id=session_id,
        ttl_seconds=604800,
        now=now,
    )


def _stored_session(now: datetime, *, hash_str: str) -> SessionRow:
    return SessionRow(
        id="s-1", user_id="u-1", refresh_token_hash=hash_str,
        user_agent=None, ip_address=None,
        created_at=now.isoformat(), last_used_at=now.isoformat(),
        expires_at=(now + timedelta(days=7)).isoformat(),
        revoked_at=None,
    )


def _vendor_token(now: datetime) -> VendorTokenRow:
    return VendorTokenRow(
        user_id="u-1", vendor="spotify",
        access_token_enc=EnvelopePayload(b"K", b"n" * 12, b"OLD-AT").serialize(),
        refresh_token_enc=EnvelopePayload(b"K", b"n" * 12, b"OLD-RT").serialize(),
        data_key_enc=b"K", scope=None,
        expires_at=now.isoformat(), updated_at=now.isoformat(),
    )


def test_refresh_happy_path_rotates_tokens(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    refresh = _refresh_jwt(now)
    repo = MagicMock()
    repo.get_active_session.return_value = _stored_session(
        now, hash_str=hashlib.sha256(refresh.encode()).hexdigest()
    )
    repo.get_vendor_token.return_value = _vendor_token(now)

    envelope = MagicMock()
    envelope.decrypt.return_value = b"OLD-RT"
    envelope.encrypt.return_value = EnvelopePayload(b"K2", b"n" * 12, b"NEW")

    oauth = MagicMock()
    oauth.refresh.return_value = SpotifyTokenSet(
        access_token="NEW-AT", refresh_token="NEW-RT", expires_in=3600, scope=None,
    )

    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(cookies=[f"refresh_token={refresh}"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["spotify_access_token"] == "NEW-AT"
    assert "access_token" in body

    repo.rotate_session.assert_called_once()
    rotate_kwargs = repo.rotate_session.call_args.kwargs
    assert rotate_kwargs["session_id"] == "s-1"
    assert rotate_kwargs["new_hash"] != hashlib.sha256(refresh.encode()).hexdigest()


def test_refresh_missing_cookie_returns_401(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    envelope = MagicMock()
    oauth = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(cookies=[]), SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error_code"] == "refresh_invalid"


def test_refresh_replay_revokes_session_family(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    refresh = _refresh_jwt(now)
    repo = MagicMock()
    # Stored hash does NOT match the inbound refresh — replay signal.
    repo.get_active_session.return_value = _stored_session(now, hash_str="WRONG")

    envelope = MagicMock()
    oauth = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(cookies=[f"refresh_token={refresh}"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error_code"] == "refresh_replay_detected"
    repo.revoke_all_user_sessions.assert_called_once()


def test_refresh_spotify_invalid_grant_clears_vendor_token(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    refresh = _refresh_jwt(now)
    repo = MagicMock()
    repo.get_active_session.return_value = _stored_session(
        now, hash_str=hashlib.sha256(refresh.encode()).hexdigest()
    )
    repo.get_vendor_token.return_value = _vendor_token(now)
    envelope = MagicMock()
    envelope.decrypt.return_value = b"OLD-RT"

    oauth = MagicMock()
    oauth.refresh.side_effect = SpotifyTokenRevokedError("invalid_grant")

    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(cookies=[f"refresh_token={refresh}"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error_code"] == "spotify_revoked"
    repo.revoke_session.assert_called_once()
    repo.delete_vendor_token.assert_called_once()


def test_refresh_session_not_found_returns_401(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    refresh = _refresh_jwt(now)
    repo = MagicMock()
    repo.get_active_session.return_value = None
    envelope = MagicMock()
    oauth = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(cookies=[f"refresh_token={refresh}"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error_code"] == "refresh_invalid"
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_auth_handler_refresh.py -q`
Expected: FAIL — refresh route missing.

- [ ] **Step 3: Implement refresh**

Add to `_route` dispatch in `src/collector/auth_handler.py`:

```python
    if route == "POST /auth/refresh":
        return _handle_refresh(event, correlation_id)
```

Add new imports near the top:

```python
from .auth.jwt_utils import (
    InvalidTokenError,
    issue_access_token,
    issue_refresh_token,
    verify_refresh_token,
)
from .auth.kms_envelope import EnvelopePayload
from .errors import (
    RefreshInvalidError,
    RefreshReplayDetectedError,
    SpotifyRevokedError,
)
```

Add the handler:

```python
def _handle_refresh(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    cookies = _parse_cookies(event)
    refresh_token = cookies.get("refresh_token")
    if not refresh_token:
        raise RefreshInvalidError()

    secret = resolve_jwt_signing_key()
    now = _now()
    try:
        claims = verify_refresh_token(token=refresh_token, secret=secret, now=now)
    except InvalidTokenError as exc:
        raise RefreshInvalidError() from exc

    repo = _build_auth_repository()
    session = repo.get_active_session(claims.session_id, now=now)
    if session is None or session.user_id != claims.user_id:
        raise RefreshInvalidError()

    inbound_hash = _sha256_hex(refresh_token)
    if session.refresh_token_hash != inbound_hash:
        repo.revoke_all_user_sessions(claims.user_id, revoked_at=now)
        raise RefreshReplayDetectedError()

    vendor_token = repo.get_vendor_token(user_id=claims.user_id, vendor="spotify")
    if vendor_token is None or vendor_token.refresh_token_enc is None:
        repo.revoke_session(claims.session_id, revoked_at=now)
        raise SpotifyRevokedError()

    envelope = _build_kms_envelope()
    refresh_payload = EnvelopePayload.deserialize(vendor_token.refresh_token_enc)
    spotify_refresh_token = envelope.decrypt(refresh_payload).decode("utf-8")

    oauth = _build_oauth_client()
    settings = get_auth_settings()
    try:
        new_tokens = oauth.refresh(refresh_token=spotify_refresh_token)
    except SpotifyTokenRevokedError as exc:
        repo.revoke_session(claims.session_id, revoked_at=now)
        repo.delete_vendor_token(user_id=claims.user_id, vendor="spotify")
        raise SpotifyRevokedError() from exc
    except SpotifyOAuthError as exc:
        raise OAuthExchangeFailedError(str(exc)) from exc

    user = repo.get_user_by_id(claims.user_id)
    is_admin = user.is_admin if user is not None else False

    new_access_payload = envelope.encrypt(new_tokens.access_token.encode("utf-8"))
    new_refresh_payload = envelope.encrypt(new_tokens.refresh_token.encode("utf-8"))
    repo.upsert_vendor_token(
        UpsertVendorTokenCmd(
            user_id=claims.user_id,
            vendor="spotify",
            access_token_enc=new_access_payload.serialize(),
            refresh_token_enc=new_refresh_payload.serialize(),
            data_key_enc=new_access_payload.data_key_enc,
            scope=new_tokens.scope or vendor_token.scope,
            expires_at=now + timedelta(seconds=new_tokens.expires_in),
            updated_at=now,
        )
    )

    new_refresh_jwt = issue_refresh_token(
        secret=secret,
        user_id=claims.user_id,
        session_id=claims.session_id,
        ttl_seconds=settings.refresh_token_ttl_seconds,
        now=now,
    )
    repo.rotate_session(
        session_id=claims.session_id,
        new_hash=_sha256_hex(new_refresh_jwt),
        last_used_at=now,
    )

    new_access_jwt = issue_access_token(
        secret=secret,
        user_id=claims.user_id,
        session_id=claims.session_id,
        is_admin=is_admin,
        ttl_seconds=settings.access_token_ttl_seconds,
        now=now,
    )

    log_event(
        "INFO",
        "auth_refresh_success",
        correlation_id=correlation_id,
        user_id=claims.user_id,
    )

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "cookies": [
            _refresh_cookie(new_refresh_jwt, max_age=settings.refresh_token_ttl_seconds),
        ],
        "body": json.dumps(
            {
                "access_token": new_access_jwt,
                "spotify_access_token": new_tokens.access_token,
                "expires_in": settings.access_token_ttl_seconds,
                "correlation_id": correlation_id,
            },
            ensure_ascii=False,
        ),
    }
```

- [ ] **Step 4: Run all auth_handler tests**

Run: `pytest tests/unit/test_auth_handler_login.py tests/unit/test_auth_handler_callback.py tests/unit/test_auth_handler_refresh.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth_handler.py tests/unit/test_auth_handler_refresh.py
git commit -m "feat(auth): implement /auth/refresh with rotation and replay detection"
```

---

## Task 15: `auth_handler.py` — `POST /auth/logout`

**Files:**
- Modify: `src/collector/auth_handler.py`
- Test: `tests/unit/test_auth_handler_logout.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_handler_logout.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.auth import auth_settings
from collector.auth.jwt_utils import issue_refresh_token
from collector import auth_handler


SECRET = "0" * 32


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SIGNING_KEY", SECRET)
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def _event(*, cookies: list[str]) -> dict:
    return {
        "version": "2.0",
        "requestContext": {"requestId": "req", "routeKey": "POST /auth/logout"},
        "headers": {"x-correlation-id": "cid"},
        "cookies": cookies,
        "body": "",
    }


def test_logout_revokes_session_and_clears_cookie(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_refresh_token(
        secret=SECRET, user_id="u", session_id="s", ttl_seconds=600, now=now,
    )
    repo = MagicMock()
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(cookies=[f"refresh_token={token}"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 204
    repo.revoke_session.assert_called_once_with("s", revoked_at=now)
    cookies = response.get("cookies") or []
    assert any(c.startswith("refresh_token=;") and "Max-Age=0" in c for c in cookies)


def test_logout_without_cookie_still_returns_204(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(cookies=[]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 204
    repo.revoke_session.assert_not_called()


def test_logout_invalid_token_silently_succeeds(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(cookies=["refresh_token=garbage"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 204
    repo.revoke_session.assert_not_called()
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_auth_handler_logout.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement logout**

Add to `_route` dispatch:

```python
    if route == "POST /auth/logout":
        return _handle_logout(event, correlation_id)
```

Add the handler in `auth_handler.py`:

```python
def _handle_logout(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    cookies = _parse_cookies(event)
    token = cookies.get("refresh_token")
    if token:
        try:
            claims = verify_refresh_token(
                token=token, secret=resolve_jwt_signing_key(), now=_now()
            )
        except InvalidTokenError:
            claims = None
        if claims is not None:
            repo = _build_auth_repository()
            repo.revoke_session(claims.session_id, revoked_at=_now())
            log_event(
                "INFO",
                "auth_logout",
                correlation_id=correlation_id,
                user_id=claims.user_id,
            )

    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "cookies": [_refresh_cookie("", max_age=0)],
        "body": "",
    }
```

- [ ] **Step 4: Run all auth_handler tests**

Run: `pytest tests/unit/test_auth_handler_login.py tests/unit/test_auth_handler_callback.py tests/unit/test_auth_handler_refresh.py tests/unit/test_auth_handler_logout.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth_handler.py tests/unit/test_auth_handler_logout.py
git commit -m "feat(auth): implement /auth/logout"
```

---

## Task 16: `auth_handler.py` — `GET /me` and `DELETE /me/sessions/{session_id}`

**Files:**
- Modify: `src/collector/auth_handler.py`
- Test: `tests/unit/test_auth_handler_me.py`

`GET /me` and the session-revoke route are authorizer-protected, so the handler reads `(user_id, session_id, is_admin)` out of `event.requestContext.authorizer.lambda` (HTTP API simple-format authorizer puts the context there).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_handler_me.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.auth import auth_settings
from collector.auth.auth_repository import SessionRow, UserRow
from collector import auth_handler


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SIGNING_KEY", "0" * 32)
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def _event(*, route: str, user_id: str, session_id: str, is_admin: bool,
           path_params: dict | None = None) -> dict:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": route,
            "authorizer": {
                "lambda": {
                    "user_id": user_id,
                    "session_id": session_id,
                    "is_admin": is_admin,
                }
            },
        },
        "headers": {"x-correlation-id": "cid"},
        "pathParameters": path_params,
        "body": None,
    }


def test_get_me_returns_user_and_sessions(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    repo.get_user_by_id.return_value = UserRow(
        id="u-1", spotify_id="sp-1", display_name="Roman",
        email="r@x", is_admin=False,
        created_at=now.isoformat(), updated_at=now.isoformat(),
    )
    repo.list_active_sessions.return_value = [
        SessionRow(
            id="s-1", user_id="u-1", refresh_token_hash="h",
            user_agent="ua", ip_address="1.2.3.4",
            created_at=now.isoformat(), last_used_at=now.isoformat(),
            expires_at=now.isoformat(), revoked_at=None,
        ),
        SessionRow(
            id="s-2", user_id="u-1", refresh_token_hash="h",
            user_agent=None, ip_address=None,
            created_at=now.isoformat(), last_used_at=now.isoformat(),
            expires_at=now.isoformat(), revoked_at=None,
        ),
    ]
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(route="GET /me", user_id="u-1", session_id="s-1", is_admin=False),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["id"] == "u-1"
    assert body["display_name"] == "Roman"
    assert body["is_admin"] is False
    sessions = body["sessions"]
    assert len(sessions) == 2
    current = next(s for s in sessions if s["id"] == "s-1")
    other = next(s for s in sessions if s["id"] == "s-2")
    assert current["current"] is True
    assert other["current"] is False


def test_delete_session_revokes_non_current(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    repo.get_active_session.return_value = SessionRow(
        id="s-2", user_id="u-1", refresh_token_hash="h",
        user_agent=None, ip_address=None,
        created_at=now.isoformat(), last_used_at=now.isoformat(),
        expires_at=now.isoformat(), revoked_at=None,
    )
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(
            route="DELETE /me/sessions/{session_id}",
            user_id="u-1",
            session_id="s-1",
            is_admin=False,
            path_params={"session_id": "s-2"},
        ),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 204
    repo.revoke_session.assert_called_once_with("s-2", revoked_at=now)


def test_delete_session_current_returns_400(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(
            route="DELETE /me/sessions/{session_id}",
            user_id="u-1",
            session_id="s-1",
            is_admin=False,
            path_params={"session_id": "s-1"},
        ),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "cannot_revoke_current"
    repo.revoke_session.assert_not_called()


def test_delete_session_belonging_to_other_user_returns_404(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    repo.get_active_session.return_value = SessionRow(
        id="s-2", user_id="u-OTHER", refresh_token_hash="h",
        user_agent=None, ip_address=None,
        created_at=now.isoformat(), last_used_at=now.isoformat(),
        expires_at=now.isoformat(), revoked_at=None,
    )
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(
            route="DELETE /me/sessions/{session_id}",
            user_id="u-1",
            session_id="s-1",
            is_admin=False,
            path_params={"session_id": "s-2"},
        ),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 404
    repo.revoke_session.assert_not_called()
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_auth_handler_me.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `/me` and session revoke**

Add new imports:

```python
from .errors import CannotRevokeCurrentSessionError
```

Extend `_route` dispatch:

```python
    if route == "GET /me":
        return _handle_me(event, correlation_id)
    if route == "DELETE /me/sessions/{session_id}":
        return _handle_revoke_session(event, correlation_id)
```

Add helpers + handlers:

```python
def _authorizer_context(event: Mapping[str, Any]) -> dict[str, Any]:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        authorizer = rc.get("authorizer")
        if isinstance(authorizer, Mapping):
            ctx = authorizer.get("lambda")
            if isinstance(ctx, Mapping):
                return dict(ctx)
    return {}


def _handle_me(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    ctx = _authorizer_context(event)
    user_id = ctx.get("user_id")
    current_session_id = ctx.get("session_id")
    if not user_id:
        raise RefreshInvalidError("authorizer context missing user_id")

    repo = _build_auth_repository()
    user = repo.get_user_by_id(str(user_id))
    if user is None:
        raise RefreshInvalidError("user not found")

    sessions = repo.list_active_sessions(user_id=str(user_id), now=_now())
    return _json_response(
        200,
        {
            "id": user.id,
            "spotify_id": user.spotify_id,
            "display_name": user.display_name,
            "email": user.email,
            "is_admin": user.is_admin,
            "sessions": [
                {
                    "id": s.id,
                    "created_at": s.created_at,
                    "last_used_at": s.last_used_at,
                    "user_agent": s.user_agent,
                    "current": s.id == current_session_id,
                }
                for s in sessions
            ],
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_revoke_session(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    ctx = _authorizer_context(event)
    user_id = ctx.get("user_id")
    current_session_id = ctx.get("session_id")
    if not user_id:
        raise RefreshInvalidError("authorizer context missing user_id")

    path = event.get("pathParameters") or {}
    target_id = path.get("session_id") if isinstance(path, Mapping) else None
    if not target_id:
        raise ValidationError("session_id is required")

    if target_id == current_session_id:
        raise CannotRevokeCurrentSessionError()

    repo = _build_auth_repository()
    target = repo.get_active_session(str(target_id), now=_now())
    if target is None or target.user_id != str(user_id):
        return _json_response(
            404,
            {"error_code": "not_found", "message": "Session not found",
             "correlation_id": correlation_id},
            correlation_id,
        )

    repo.revoke_session(str(target_id), revoked_at=_now())
    log_event(
        "INFO",
        "auth_session_revoked",
        correlation_id=correlation_id,
        user_id=str(user_id),
        revoked_session_id=str(target_id),
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/unit/test_auth_handler_me.py tests/unit/test_auth_handler_login.py tests/unit/test_auth_handler_callback.py tests/unit/test_auth_handler_refresh.py tests/unit/test_auth_handler_logout.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth_handler.py tests/unit/test_auth_handler_me.py
git commit -m "feat(auth): implement GET /me and DELETE /me/sessions/{id}"
```

---

## Task 17: `auth_authorizer.py` — Lambda Authorizer

**Files:**
- Create: `src/collector/auth_authorizer.py`
- Test: `tests/unit/test_auth_authorizer.py`

API Gateway HTTP API "simple" Lambda Authorizer expects a return shape of `{isAuthorized: bool, context: dict[str, str|bool|number]}` and identity sources include the `Authorization` header. TTL 300s lives in the Terraform config (Task 21), not here.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_auth_authorizer.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from collector.auth.jwt_utils import issue_access_token
from collector import auth_authorizer


SECRET = "0" * 32


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JWT_SIGNING_KEY", SECRET)
    auth_authorizer._reset_signing_key_cache()
    monkeypatch.setattr(auth_authorizer, "_now", lambda: datetime(
        2026, 4, 26, 12, 0, tzinfo=timezone.utc
    ))
    yield
    auth_authorizer._reset_signing_key_cache()


def _event(*, header: str | None) -> dict:
    return {
        "type": "REQUEST",
        "routeKey": "GET /me",
        "headers": {"authorization": header} if header is not None else {},
    }


def test_valid_token_authorized() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret=SECRET, user_id="u-1", session_id="s-1", is_admin=True,
        ttl_seconds=1800, now=now,
    )
    response = auth_authorizer.lambda_handler(
        _event(header=f"Bearer {token}"),
        SimpleNamespace(aws_request_id="A"),
    )
    assert response == {
        "isAuthorized": True,
        "context": {
            "user_id": "u-1",
            "session_id": "s-1",
            "is_admin": True,
        },
    }


def test_missing_authorization_header_unauthorized() -> None:
    response = auth_authorizer.lambda_handler(
        _event(header=None), SimpleNamespace(aws_request_id="A"),
    )
    assert response == {"isAuthorized": False}


def test_non_bearer_scheme_unauthorized() -> None:
    response = auth_authorizer.lambda_handler(
        _event(header="Basic xyz"), SimpleNamespace(aws_request_id="A"),
    )
    assert response == {"isAuthorized": False}


def test_invalid_token_unauthorized() -> None:
    response = auth_authorizer.lambda_handler(
        _event(header="Bearer not.a.token"),
        SimpleNamespace(aws_request_id="A"),
    )
    assert response == {"isAuthorized": False}


def test_wrong_secret_unauthorized() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret="X" * 32, user_id="u", session_id="s", is_admin=False,
        ttl_seconds=1800, now=now,
    )
    response = auth_authorizer.lambda_handler(
        _event(header=f"Bearer {token}"),
        SimpleNamespace(aws_request_id="A"),
    )
    assert response == {"isAuthorized": False}
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_auth_authorizer.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `src/collector/auth_authorizer.py`:

```python
"""API Gateway HTTP API Lambda Authorizer (simple-format) for spec-A JWTs."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Mapping

from .auth.auth_settings import resolve_jwt_signing_key
from .auth.jwt_utils import InvalidTokenError, verify_access_token
from .logging_utils import log_event


_SIGNING_KEY: tuple[str, float] | None = None
_KEY_TTL_SECONDS = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reset_signing_key_cache() -> None:
    global _SIGNING_KEY
    _SIGNING_KEY = None


def _cached_signing_key() -> str:
    global _SIGNING_KEY
    now_mono = time.monotonic()
    if _SIGNING_KEY is not None:
        key, expires = _SIGNING_KEY
        if now_mono < expires:
            return key
    key = resolve_jwt_signing_key()
    _SIGNING_KEY = (key, now_mono + _KEY_TTL_SECONDS)
    return key


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    auth_header = _read_authorization(event)
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return {"isAuthorized": False}
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return {"isAuthorized": False}

    try:
        secret = _cached_signing_key()
        claims = verify_access_token(token=token, secret=secret, now=_now())
    except (InvalidTokenError, RuntimeError) as exc:
        log_event(
            "INFO",
            "authorizer_rejected",
            error_type=exc.__class__.__name__,
        )
        return {"isAuthorized": False}

    return {
        "isAuthorized": True,
        "context": {
            "user_id": claims.user_id,
            "session_id": claims.session_id,
            "is_admin": claims.is_admin,
        },
    }


def _read_authorization(event: Mapping[str, Any]) -> str | None:
    headers = event.get("headers") or {}
    if not isinstance(headers, Mapping):
        return None
    for k, v in headers.items():
        if isinstance(k, str) and k.lower() == "authorization" and isinstance(v, str):
            return v
    return None
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/unit/test_auth_authorizer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/auth_authorizer.py tests/unit/test_auth_authorizer.py
git commit -m "feat(auth): add API Gateway Lambda Authorizer"
```

---

## Task 18: Admin gating in `handler.py`

**Files:**
- Modify: `src/collector/handler.py`
- Test: `tests/unit/test_handler_admin_gating.py`

The authorizer surfaces `is_admin` in `event.requestContext.authorizer.lambda`. Add a small gate that the collector handler calls for admin-only routes.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_handler_admin_gating.py`:

```python
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from collector.handler import lambda_handler
from collector.providers import registry
from collector.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    yield
    reset_settings_cache()
    registry.reset_cache()


def _collect_event(*, is_admin: bool | None) -> dict:
    authorizer: dict | None = None
    if is_admin is not None:
        authorizer = {"lambda": {"user_id": "u", "session_id": "s", "is_admin": is_admin}}
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "POST /collect_bp_releases",
            **({"authorizer": authorizer} if authorizer is not None else {}),
        },
        "headers": {"x-correlation-id": "cid"},
        "body": json.dumps(
            {"bp_token": "x", "style_id": 5, "iso_year": 2026, "iso_week": 9}
        ),
    }


def test_collect_without_authorizer_context_returns_403(monkeypatch) -> None:
    response = lambda_handler(
        _collect_event(is_admin=None),
        SimpleNamespace(aws_request_id="L"),
    )
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "admin_required"


def test_collect_non_admin_returns_403(monkeypatch) -> None:
    response = lambda_handler(
        _collect_event(is_admin=False),
        SimpleNamespace(aws_request_id="L"),
    )
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "admin_required"


def test_spotify_not_found_route_requires_admin(monkeypatch) -> None:
    event = {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "GET /tracks/spotify-not-found",
            "authorizer": {
                "lambda": {"user_id": "u", "session_id": "s", "is_admin": False}
            },
        },
        "headers": {"x-correlation-id": "cid"},
        "body": None,
    }
    response = lambda_handler(event, SimpleNamespace(aws_request_id="L"))
    assert response["statusCode"] == 403


def test_list_tracks_does_not_require_admin(monkeypatch) -> None:
    class FakeRepo:
        def list_tracks(self, limit, offset, search):
            return []

        def count_tracks(self, search):
            return 0

    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: FakeRepo()
    )

    event = {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "GET /tracks",
            "authorizer": {
                "lambda": {"user_id": "u", "session_id": "s", "is_admin": False}
            },
        },
        "headers": {"x-correlation-id": "cid"},
        "queryStringParameters": None,
        "body": None,
    }
    response = lambda_handler(event, SimpleNamespace(aws_request_id="L"))
    assert response["statusCode"] == 200
```

- [ ] **Step 2: Run, fails**

Run: `pytest tests/unit/test_handler_admin_gating.py -q`
Expected: FAIL — admin gate not yet wired.

- [ ] **Step 3: Add admin gate**

In `src/collector/handler.py`, add the helper near the route table:

```python
from .errors import AdminRequiredError


_ADMIN_ROUTES = frozenset({
    "POST /collect_bp_releases",
    "GET /tracks/spotify-not-found",
})


def _require_admin(event: Mapping[str, Any]) -> None:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        authorizer = rc.get("authorizer")
        if isinstance(authorizer, Mapping):
            ctx = authorizer.get("lambda")
            if isinstance(ctx, Mapping) and bool(ctx.get("is_admin")):
                return
    raise AdminRequiredError()
```

Wire it into `_route` before dispatching admin endpoints:

```python
def _route(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    route_key = _extract_route_key(event)
    if route_key in _ADMIN_ROUTES:
        _require_admin(event)
    if route_key == "GET /runs/{run_id}":
        return _handle_get_run(event, context)
    if route_key in ("POST /collect_bp_releases", ""):
        return _handle_collect(event, context)
    if route_key == "GET /tracks/spotify-not-found":
        return _handle_spotify_not_found(event)
    if route_key in _LIST_ROUTES:
        return _handle_list(event, route_key)
    return _json_response(
        404,
        {"error_code": "not_found", "message": "Route not found"},
        correlation_id,
    )
```

The blank-route fallback (`""`) was treated as collect — keep that behaviour, but require admin for it too. That fallback only fires in non-routed local invocations, which we treat as admin-equivalent gated by deployment.

- [ ] **Step 4: Run, pass**

Run: `pytest tests/unit/test_handler_admin_gating.py tests/integration/test_handler.py -q`
Expected: PASS — existing integration tests do not set authorizer context, so update them in the same task to pass `is_admin=True`.

Edit the helpers `_event` and `_get_run_event` in `tests/integration/test_handler.py` to add the authorizer block. Replace the dict literal with:

```python
def _event(body: dict, correlation_id: str | None = None) -> dict:
    headers = {}
    if correlation_id:
        headers["x-correlation-id"] = correlation_id
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "api-req-1",
            "routeKey": "POST /collect_bp_releases",
            "authorizer": {
                "lambda": {"user_id": "admin", "session_id": "s", "is_admin": True}
            },
        },
        "headers": headers,
        "body": json.dumps(body),
    }
```

And in `test_invalid_body_returns_validation_error`, add the same authorizer block to the inline event dict. The list-route helper `_list_event` should also include `"authorizer": {"lambda": {"user_id": "u", "session_id": "s", "is_admin": False}}` (list routes are not admin-gated, but the authorizer must be present in real traffic).

Re-run: `pytest tests/integration/test_handler.py tests/unit/test_handler_admin_gating.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/collector/handler.py tests/unit/test_handler_admin_gating.py tests/integration/test_handler.py
git commit -m "feat(auth): admin-gate collect_bp_releases and spotify-not-found"
```

---

## Task 19: Terraform — KMS key + SSM parameters + Terraform variables

**Files:**
- Create: `infra/auth.tf`
- Modify: `infra/variables.tf`
- Modify: `infra/terraform.tfvars.example`

This task adds the new variables and the KMS / SSM resources only. Lambda + API Gateway resources land in Tasks 20–21.

- [ ] **Step 1: Add variables**

Append to `infra/variables.tf`:

```hcl
# ── Spec-A user auth ───────────────────────────────────────────────

variable "admin_spotify_ids" {
  description = "Comma-separated list of Spotify user IDs that get is_admin=true on login"
  type        = string
  default     = ""
}

variable "spotify_oauth_redirect_uri" {
  description = "Full URL Spotify redirects to after consent (must be registered in the Spotify Developer Dashboard)"
  type        = string
}

variable "spotify_oauth_client_id_ssm_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the Spotify OAuth client_id used for user login"
  type        = string
  default     = "/clouder/spotify/oauth_client_id"
}

variable "spotify_oauth_client_secret_ssm_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the Spotify OAuth client_secret used for user login"
  type        = string
  default     = "/clouder/spotify/oauth_client_secret"
}

variable "jwt_signing_key_ssm_parameter" {
  description = "SSM Parameter Store name (SecureString) holding the HS256 secret for JWTs"
  type        = string
  default     = "/clouder/auth/jwt_signing_key"
}

variable "allowed_frontend_redirects" {
  description = "Comma-separated allow-list of relative redirect_uri paths accepted by /auth/login"
  type        = string
  default     = "/"
}

variable "jwt_access_token_ttl_seconds" {
  description = "Access-token TTL"
  type        = number
  default     = 1800
}

variable "jwt_refresh_token_ttl_seconds" {
  description = "Refresh-token TTL"
  type        = number
  default     = 604800
}

variable "auth_handler_lambda_timeout_seconds" {
  description = "Auth Lambda timeout (seconds)"
  type        = number
  default     = 30
}

variable "auth_handler_lambda_memory_mb" {
  description = "Auth Lambda memory size in MB"
  type        = number
  default     = 512
}

variable "auth_authorizer_lambda_timeout_seconds" {
  description = "Authorizer Lambda timeout (seconds)"
  type        = number
  default     = 5
}

variable "auth_authorizer_lambda_memory_mb" {
  description = "Authorizer Lambda memory size in MB"
  type        = number
  default     = 256
}

variable "auth_authorizer_cache_ttl_seconds" {
  description = "API Gateway authorizer result-cache TTL (seconds)"
  type        = number
  default     = 300
}
```

- [ ] **Step 2: Append example values**

Append to `infra/terraform.tfvars.example`:

```hcl
admin_spotify_ids                    = "your_spotify_id_here"
spotify_oauth_redirect_uri           = "https://app.example.com/auth/callback"
allowed_frontend_redirects           = "/, /dashboard"
```

- [ ] **Step 3: Create `infra/auth.tf` with KMS + SSM resources**

Create `infra/auth.tf`:

```hcl
# ── KMS CMK for user_vendor_tokens envelope encryption ──────────────

resource "aws_kms_key" "user_tokens" {
  description             = "Envelope encryption for user_vendor_tokens (spec-A)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "user_tokens" {
  name          = "alias/${local.name_prefix}-user-tokens"
  target_key_id = aws_kms_key.user_tokens.key_id
}

# ── SSM SecureString parameters ─────────────────────────────────────

resource "random_password" "jwt_signing_key" {
  length  = 64
  special = false
}

resource "aws_ssm_parameter" "jwt_signing_key" {
  name        = var.jwt_signing_key_ssm_parameter
  description = "HS256 secret used by auth_handler and auth_authorizer (spec-A)"
  type        = "SecureString"
  value       = random_password.jwt_signing_key.result

  lifecycle {
    ignore_changes = [value]
  }
}

# Client_id and client_secret are uploaded out of band (terraform creates
# the parameter shells as empty SecureStrings; operator sets the value
# via `aws ssm put-parameter`). lifecycle.ignore_changes makes terraform
# tolerate the externally-managed value.

resource "aws_ssm_parameter" "spotify_oauth_client_id" {
  name        = var.spotify_oauth_client_id_ssm_parameter
  description = "Spotify OAuth client_id for user login (spec-A)"
  type        = "SecureString"
  value       = "REPLACE_AFTER_APPLY"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "spotify_oauth_client_secret" {
  name        = var.spotify_oauth_client_secret_ssm_parameter
  description = "Spotify OAuth client_secret for user login (spec-A)"
  type        = "SecureString"
  value       = "REPLACE_AFTER_APPLY"

  lifecycle {
    ignore_changes = [value]
  }
}
```

Add `random` provider to `infra/providers.tf` if not already present:

```hcl
terraform {
  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
```

- [ ] **Step 4: Validate**

```bash
cd infra && terraform fmt && terraform init && terraform validate
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 5: Commit**

```bash
git add infra/auth.tf infra/variables.tf infra/terraform.tfvars.example infra/providers.tf
git commit -m "feat(auth): add KMS CMK and SSM parameters for spec-A"
```

---

## Task 20: Terraform — auth Lambdas + log groups

**Files:**
- Modify: `infra/auth.tf`
- Modify: `infra/main.tf` (locals: lambda names + log group names)
- Modify: `infra/logging.tf`
- Modify: `infra/iam.tf`

The two auth Lambdas reuse the existing `collector_lambda` IAM role for simplicity (this matches the spec's note that auth_handler and the existing collector run in the same AWS account; isolating roles is non-goal in spec-A). We add KMS, SSM, and the new log groups to that role's policy. The authorizer technically only needs SSM read for `jwt_signing_key`, so we add a separate, narrower role for it.

- [ ] **Step 1: Add locals**

Append to `infra/main.tf` `locals` block:

```hcl
  auth_handler_lambda_name    = "${local.name_prefix}-auth-handler"
  auth_authorizer_lambda_name = "${local.name_prefix}-auth-authorizer"
```

- [ ] **Step 2: Add log groups**

Append to `infra/logging.tf`:

```hcl
resource "aws_cloudwatch_log_group" "auth_handler" {
  name              = "/aws/lambda/${local.auth_handler_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "auth_authorizer" {
  name              = "/aws/lambda/${local.auth_authorizer_lambda_name}"
  retention_in_days = var.log_retention_days
}
```

- [ ] **Step 3: Add Lambdas + dedicated authorizer role**

Append to `infra/auth.tf`:

```hcl
# ── auth_handler Lambda (reuses collector_lambda role) ──────────────

resource "aws_lambda_function" "auth_handler" {
  function_name = local.auth_handler_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.auth_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.auth_handler_lambda_timeout_seconds
  memory_size   = var.auth_handler_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      AURORA_CLUSTER_ARN                       = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN                        = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                          = var.aurora_database_name
      KMS_USER_TOKENS_KEY_ARN                  = aws_kms_key.user_tokens.arn
      JWT_SIGNING_KEY_SSM_PARAMETER            = var.jwt_signing_key_ssm_parameter
      SPOTIFY_OAUTH_CLIENT_ID_SSM_PARAMETER    = var.spotify_oauth_client_id_ssm_parameter
      SPOTIFY_OAUTH_CLIENT_SECRET_SSM_PARAMETER = var.spotify_oauth_client_secret_ssm_parameter
      SPOTIFY_OAUTH_REDIRECT_URI               = var.spotify_oauth_redirect_uri
      ALLOWED_FRONTEND_REDIRECTS               = var.allowed_frontend_redirects
      ADMIN_SPOTIFY_IDS                        = var.admin_spotify_ids
      JWT_ACCESS_TOKEN_TTL_SECONDS             = tostring(var.jwt_access_token_ttl_seconds)
      JWT_REFRESH_TOKEN_TTL_SECONDS            = tostring(var.jwt_refresh_token_ttl_seconds)
      LOG_LEVEL                                = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.auth_handler]
}

# ── auth_authorizer Lambda (narrower IAM, SSM-only) ─────────────────

resource "aws_iam_role" "auth_authorizer" {
  name               = "${local.name_prefix}-auth-authorizer-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "auth_authorizer" {
  statement {
    sid     = "AllowCloudWatchLogs"
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.auth_authorizer.arn}:*"]
  }

  statement {
    sid       = "ReadJwtSigningKey"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.jwt_signing_key_ssm_parameter}"]
  }

  statement {
    sid       = "DecryptSsmParameters"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }
}

resource "aws_iam_role_policy" "auth_authorizer" {
  name   = "${local.name_prefix}-auth-authorizer-policy"
  role   = aws_iam_role.auth_authorizer.id
  policy = data.aws_iam_policy_document.auth_authorizer.json
}

resource "aws_lambda_function" "auth_authorizer" {
  function_name = local.auth_authorizer_lambda_name
  role          = aws_iam_role.auth_authorizer.arn
  runtime       = "python3.12"
  handler       = "collector.auth_authorizer.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.auth_authorizer_lambda_timeout_seconds
  memory_size   = var.auth_authorizer_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      JWT_SIGNING_KEY_SSM_PARAMETER = var.jwt_signing_key_ssm_parameter
      LOG_LEVEL                     = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.auth_authorizer]
}
```

- [ ] **Step 4: Extend collector_lambda IAM with KMS + auth-related SSM + new log groups**

In `infra/iam.tf`, add the auth log groups to the `AllowCloudWatchLogs` statement's resources list:

```hcl
    resources = [
      "${aws_cloudwatch_log_group.collector.arn}:*",
      "${aws_cloudwatch_log_group.canonicalization_worker.arn}:*",
      "${aws_cloudwatch_log_group.migration_lambda.arn}:*",
      "${aws_cloudwatch_log_group.ai_search_worker.arn}:*",
      "${aws_cloudwatch_log_group.spotify_search_worker.arn}:*",
      "${aws_cloudwatch_log_group.vendor_match_worker.arn}:*",
      "${aws_cloudwatch_log_group.auth_handler.arn}:*",
    ]
```

Add a new statement for KMS GenerateDataKey/Decrypt on the user-tokens key:

```hcl
  statement {
    sid    = "AllowKmsUserTokens"
    effect = "Allow"
    actions = [
      "kms:GenerateDataKey",
      "kms:Decrypt",
    ]
    resources = [aws_kms_key.user_tokens.arn]
  }
```

Add a new statement for auth-related SSM parameters:

```hcl
  statement {
    sid     = "AllowReadAuthSsmParameters"
    effect  = "Allow"
    actions = ["ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.jwt_signing_key_ssm_parameter}",
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.spotify_oauth_client_id_ssm_parameter}",
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.spotify_oauth_client_secret_ssm_parameter}",
    ]
  }
```

Note the existing `AllowWorkerSsmKmsDecrypt` statement already permits `kms:Decrypt` on `alias/aws/ssm` for SSM SecureString reads — no change needed there.

- [ ] **Step 5: Validate, commit**

```bash
cd infra && terraform fmt && terraform validate
git add infra/auth.tf infra/main.tf infra/logging.tf infra/iam.tf
git commit -m "feat(auth): add auth_handler and auth_authorizer Lambdas"
```

Expected: terraform validate passes.

---

## Task 21: Terraform — API Gateway authorizer + new routes + attach to existing routes

**Files:**
- Modify: `infra/auth.tf` (authorizer + new routes)
- Modify: `infra/api_gateway.tf` (attach authorizer to existing routes)

The HTTP API authorizer with simple-format response receives `$request.header.Authorization` as identity source. Cache TTL is 300s.

- [ ] **Step 1: Add the authorizer + auth Lambda permission + new routes**

Append to `infra/auth.tf`:

```hcl
resource "aws_lambda_permission" "auth_handler_apigw" {
  statement_id  = "AllowExecutionFromApiGatewayAuth"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auth_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}

resource "aws_lambda_permission" "auth_authorizer_apigw" {
  statement_id  = "AllowExecutionFromApiGatewayAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auth_authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "auth_lambda" {
  api_id                 = aws_apigatewayv2_api.collector.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.auth_handler.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id                            = aws_apigatewayv2_api.collector.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.auth_authorizer.invoke_arn
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  identity_sources                  = ["$request.header.Authorization"]
  authorizer_result_ttl_in_seconds  = var.auth_authorizer_cache_ttl_seconds
  name                              = "${local.name_prefix}-jwt-authorizer"
}

# Public routes (no authorizer)

resource "aws_apigatewayv2_route" "auth_login" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "GET /auth/login"
  target    = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
}

resource "aws_apigatewayv2_route" "auth_callback" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "GET /auth/callback"
  target    = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
}

resource "aws_apigatewayv2_route" "auth_refresh" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "POST /auth/refresh"
  target    = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
}

resource "aws_apigatewayv2_route" "auth_logout" {
  api_id    = aws_apigatewayv2_api.collector.id
  route_key = "POST /auth/logout"
  target    = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
}

# Authorizer-protected routes that target auth_handler

resource "aws_apigatewayv2_route" "me" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "GET /me"
  target             = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_route" "me_session_revoke" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "DELETE /me/sessions/{session_id}"
  target             = "integrations/${aws_apigatewayv2_integration.auth_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 2: Switch existing routes from `AWS_IAM` to the new JWT authorizer**

Edit each route in `infra/api_gateway.tf` so that `authorization_type = "CUSTOM"` and `authorizer_id = aws_apigatewayv2_authorizer.jwt.id`. Apply this to:

- `aws_apigatewayv2_route.collect_bp_releases`
- `aws_apigatewayv2_route.get_run`
- `aws_apigatewayv2_route.list_tracks`
- `aws_apigatewayv2_route.list_artists`
- `aws_apigatewayv2_route.list_albums`
- `aws_apigatewayv2_route.list_labels`
- `aws_apigatewayv2_route.list_styles`
- `aws_apigatewayv2_route.spotify_not_found`

Example for one of them:

```hcl
resource "aws_apigatewayv2_route" "collect_bp_releases" {
  api_id             = aws_apigatewayv2_api.collector.id
  route_key          = "POST /collect_bp_releases"
  target             = "integrations/${aws_apigatewayv2_integration.collector_lambda.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 3: Validate**

```bash
cd infra && terraform fmt && terraform validate
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add infra/auth.tf infra/api_gateway.tf
git commit -m "feat(auth): add JWT authorizer and wire it into all routes"
```

---

## Task 22: Integration test — full auth flow

**Files:**
- Create: `tests/integration/test_auth_flow.py`

End-to-end smoke at unit-test fidelity: login → callback → /me → refresh → logout, with all dependencies wired through `auth_handler`'s factory seams. KMS is replaced with an in-memory fake; OAuth is replaced with a programmable stub; AuthRepository is replaced with an in-memory dict-backed fake. This exercises the contract between the modules without touching real Aurora or AWS.

- [ ] **Step 1: Create the integration test**

Create `tests/integration/test_auth_flow.py`:

```python
"""End-to-end auth flow with in-memory fakes for KMS, OAuth, repo."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from collector import auth_handler
from collector.auth import auth_settings
from collector.auth.auth_repository import (
    SessionRow,
    UpsertUserCmd,
    UpsertVendorTokenCmd,
    UserRow,
    VendorTokenRow,
)
from collector.auth.kms_envelope import EnvelopePayload
from collector.auth.spotify_oauth import (
    SpotifyProfile,
    SpotifyTokenSet,
)


SECRET = "0" * 32


class FakeKms:
    """In-memory KMS envelope: identity-encrypts. Sufficient to verify wiring."""

    def encrypt(self, plaintext: bytes) -> EnvelopePayload:
        return EnvelopePayload(data_key_enc=b"DK", nonce=b"\x00" * 12, ciphertext=plaintext)

    def decrypt(self, payload: EnvelopePayload) -> bytes:
        return payload.ciphertext


class FakeOAuth:
    def __init__(self) -> None:
        self.refresh_calls = 0

    def authorize_url(self, *, state, code_challenge, scopes):  # not used here
        return "https://accounts.spotify.com/authorize"

    def exchange_code(self, *, code, code_verifier):
        return SpotifyTokenSet(
            access_token="AT-1", refresh_token="RT-1",
            expires_in=3600, scope="user-read-email",
        )

    def get_me(self, *, access_token):
        return SpotifyProfile(
            spotify_id="sp-user", display_name="Roman",
            email="r@x", product="premium",
        )

    def refresh(self, *, refresh_token):
        self.refresh_calls += 1
        return SpotifyTokenSet(
            access_token=f"AT-{self.refresh_calls + 1}",
            refresh_token=f"RT-{self.refresh_calls + 1}",
            expires_in=3600, scope=None,
        )


class FakeRepo:
    def __init__(self) -> None:
        self.users: dict[str, UserRow] = {}
        self.users_by_spotify: dict[str, UserRow] = {}
        self.sessions: dict[str, SessionRow] = {}
        self.vendor_tokens: dict[tuple[str, str], VendorTokenRow] = {}

    def upsert_user(self, cmd: UpsertUserCmd) -> None:
        row = UserRow(
            id=cmd.id, spotify_id=cmd.spotify_id,
            display_name=cmd.display_name, email=cmd.email,
            is_admin=cmd.is_admin,
            created_at=cmd.now.isoformat(), updated_at=cmd.now.isoformat(),
        )
        self.users[row.id] = row
        self.users_by_spotify[row.spotify_id] = row

    def get_user_by_spotify_id(self, spotify_id):
        return self.users_by_spotify.get(spotify_id)

    def get_user_by_id(self, user_id):
        return self.users.get(user_id)

    def create_session(self, *, session_id, user_id, refresh_token_hash,
                       user_agent, ip_address, created_at, expires_at):
        self.sessions[session_id] = SessionRow(
            id=session_id, user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            user_agent=user_agent, ip_address=ip_address,
            created_at=created_at.isoformat(),
            last_used_at=created_at.isoformat(),
            expires_at=expires_at.isoformat(),
            revoked_at=None,
        )

    def get_active_session(self, session_id, *, now):
        s = self.sessions.get(session_id)
        if s is None or s.revoked_at is not None:
            return None
        return s

    def rotate_session(self, *, session_id, new_hash, last_used_at):
        s = self.sessions[session_id]
        self.sessions[session_id] = SessionRow(
            id=s.id, user_id=s.user_id,
            refresh_token_hash=new_hash,
            user_agent=s.user_agent, ip_address=s.ip_address,
            created_at=s.created_at,
            last_used_at=last_used_at.isoformat(),
            expires_at=s.expires_at,
            revoked_at=None,
        )

    def revoke_session(self, session_id, *, revoked_at):
        s = self.sessions.get(session_id)
        if s is None:
            return
        self.sessions[session_id] = SessionRow(
            **{**s.__dict__, "revoked_at": revoked_at.isoformat()},
        )

    def revoke_all_user_sessions(self, user_id, *, revoked_at):
        for sid, s in list(self.sessions.items()):
            if s.user_id == user_id and s.revoked_at is None:
                self.revoke_session(sid, revoked_at=revoked_at)

    def list_active_sessions(self, *, user_id, now):
        return [s for s in self.sessions.values()
                if s.user_id == user_id and s.revoked_at is None]

    def upsert_vendor_token(self, cmd: UpsertVendorTokenCmd) -> None:
        self.vendor_tokens[(cmd.user_id, cmd.vendor)] = VendorTokenRow(
            user_id=cmd.user_id, vendor=cmd.vendor,
            access_token_enc=cmd.access_token_enc,
            refresh_token_enc=cmd.refresh_token_enc,
            data_key_enc=cmd.data_key_enc, scope=cmd.scope,
            expires_at=cmd.expires_at.isoformat() if cmd.expires_at else None,
            updated_at=cmd.updated_at.isoformat(),
        )

    def get_vendor_token(self, *, user_id, vendor):
        return self.vendor_tokens.get((user_id, vendor))

    def delete_vendor_token(self, *, user_id, vendor):
        self.vendor_tokens.pop((user_id, vendor), None)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/, /dashboard")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SIGNING_KEY", SECRET)
    monkeypatch.setenv("JWT_REFRESH_TOKEN_TTL_SECONDS", "604800")
    monkeypatch.setenv("JWT_ACCESS_TOKEN_TTL_SECONDS", "1800")
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def _wire(monkeypatch, *, repo, oauth, kms, now):
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_build_oauth_client", lambda: oauth)
    monkeypatch.setattr(auth_handler, "_build_kms_envelope", lambda: kms)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="L")


def test_full_login_to_logout_flow(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = FakeRepo()
    oauth = FakeOAuth()
    kms = FakeKms()
    _wire(monkeypatch, repo=repo, oauth=oauth, kms=kms, now=now)

    # 1. /auth/login
    login_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "1", "routeKey": "GET /auth/login"},
            "headers": {"x-correlation-id": "cid"},
            "body": None,
        },
        _ctx(),
    )
    assert login_response["statusCode"] == 302
    state_cookie = next(c for c in login_response["cookies"] if c.startswith("oauth_state="))
    state = state_cookie.split("=", 1)[1].split(";")[0]
    verifier_cookie = next(c for c in login_response["cookies"] if c.startswith("oauth_verifier="))
    verifier = verifier_cookie.split("=", 1)[1].split(";")[0]

    # 2. /auth/callback
    callback_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "2", "routeKey": "GET /auth/callback"},
            "headers": {"x-correlation-id": "cid"},
            "queryStringParameters": {"code": "AUTHCODE", "state": state},
            "cookies": [
                f"oauth_state={state}",
                f"oauth_verifier={verifier}",
            ],
            "body": None,
        },
        _ctx(),
    )
    assert callback_response["statusCode"] == 200
    body = json.loads(callback_response["body"])
    access_token = body["access_token"]
    refresh_cookie = next(c for c in callback_response["cookies"] if c.startswith("refresh_token="))
    refresh_token = refresh_cookie.split("=", 1)[1].split(";")[0]
    assert len(repo.users) == 1
    user_id = next(iter(repo.users))
    assert ("sp-user", ) == (repo.users[user_id].spotify_id, )

    # 3. GET /me (simulate authorizer context)
    me_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {
                "requestId": "3",
                "routeKey": "GET /me",
                "authorizer": {
                    "lambda": {
                        "user_id": user_id,
                        "session_id": next(iter(repo.sessions)),
                        "is_admin": False,
                    }
                },
            },
            "headers": {"x-correlation-id": "cid", "authorization": f"Bearer {access_token}"},
            "body": None,
        },
        _ctx(),
    )
    assert me_response["statusCode"] == 200
    me_body = json.loads(me_response["body"])
    assert me_body["spotify_id"] == "sp-user"
    assert len(me_body["sessions"]) == 1
    assert me_body["sessions"][0]["current"] is True

    # 4. POST /auth/refresh
    refresh_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "4", "routeKey": "POST /auth/refresh"},
            "headers": {"x-correlation-id": "cid"},
            "cookies": [f"refresh_token={refresh_token}"],
            "body": "",
        },
        _ctx(),
    )
    assert refresh_response["statusCode"] == 200
    refresh_body = json.loads(refresh_response["body"])
    assert refresh_body["spotify_access_token"] == "AT-2"
    new_refresh_cookie = next(c for c in refresh_response["cookies"] if c.startswith("refresh_token="))
    new_refresh_token = new_refresh_cookie.split("=", 1)[1].split(";")[0]
    assert new_refresh_token != refresh_token

    # 5. Replay the OLD refresh token → family revoked
    replay_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "5", "routeKey": "POST /auth/refresh"},
            "headers": {"x-correlation-id": "cid"},
            "cookies": [f"refresh_token={refresh_token}"],
            "body": "",
        },
        _ctx(),
    )
    assert replay_response["statusCode"] == 401
    assert json.loads(replay_response["body"])["error_code"] == "refresh_replay_detected"
    assert all(s.revoked_at is not None for s in repo.sessions.values())

    # 6. POST /auth/logout — even with old session-revoked state, returns 204
    logout_response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "6", "routeKey": "POST /auth/logout"},
            "headers": {"x-correlation-id": "cid"},
            "cookies": [f"refresh_token={new_refresh_token}"],
            "body": "",
        },
        _ctx(),
    )
    assert logout_response["statusCode"] == 204


def test_non_premium_blocks_at_callback(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = FakeRepo()
    oauth = FakeOAuth()
    oauth.get_me = lambda *, access_token: SpotifyProfile(
        spotify_id="sp-free", display_name=None,
        email=None, product="free",
    )
    kms = FakeKms()
    _wire(monkeypatch, repo=repo, oauth=oauth, kms=kms, now=now)

    response = auth_handler.lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "1", "routeKey": "GET /auth/callback"},
            "headers": {"x-correlation-id": "cid"},
            "queryStringParameters": {"code": "X", "state": "S"},
            "cookies": ["oauth_state=S", "oauth_verifier=V"],
            "body": None,
        },
        _ctx(),
    )

    assert response["statusCode"] == 403
    assert json.loads(response["body"])["error_code"] == "premium_required"
    assert repo.users == {}
    assert repo.sessions == {}
    assert repo.vendor_tokens == {}
```

- [ ] **Step 2: Run all tests**

Run: `pytest -q`
Expected: all unit + integration tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_auth_flow.py
git commit -m "test(auth): add integration test for full login → logout flow"
```

---

## Task 23: Manual smoke checklist + acceptance verification

**Files:**
- (no code changes — verification only)

This task closes spec-A §12 acceptance criteria. Run each step and record the result in the PR description.

- [ ] **Step 1: Apply infrastructure**

```bash
cd infra && terraform apply
```

Then upload the OAuth secrets to SSM (the parameter shells are placeholders):

```bash
aws ssm put-parameter --name /clouder/spotify/oauth_client_id     --value "<CLIENT_ID>"     --type SecureString --overwrite
aws ssm put-parameter --name /clouder/spotify/oauth_client_secret --value "<CLIENT_SECRET>" --type SecureString --overwrite
```

Add the redirect URI from `var.spotify_oauth_redirect_uri` to the Spotify Developer Dashboard for the existing app.

- [ ] **Step 2: Premium login round-trip**

In a browser visit `https://<API>/auth/login` while logged into Spotify Premium. Expected: redirected to Spotify consent → bounced back → JSON response containing `access_token`, `spotify_access_token`, `user.spotify_id`.

- [ ] **Step 3: Non-Premium block**

Repeat with a free Spotify account. Expected: HTTP 403 with `error_code=premium_required` and `upgrade_url`. Verify in Aurora that no row exists in `users` for the free account's `spotify_id`.

- [ ] **Step 4: Authorizer gate**

```bash
curl -sS -X POST https://<API>/collect_bp_releases -d '{}'
# Expect: 401
curl -sS -X POST https://<API>/collect_bp_releases \
     -H "Authorization: Bearer <NON_ADMIN_JWT>" -d '{}'
# Expect: 403 admin_required
curl -sS -X POST https://<API>/collect_bp_releases \
     -H "Authorization: Bearer <ADMIN_JWT>" \
     -d '{"bp_token":"...", "style_id":5, "iso_year":2026, "iso_week":17}'
# Expect: 200
```

- [ ] **Step 5: Refresh-token rotation + replay**

Hit `/auth/refresh` twice with the same browser cookie. Expected: both 200. Then submit the FIRST refresh-token cookie a third time. Expected: 401 `refresh_replay_detected`. Verify `user_sessions.revoked_at IS NOT NULL` for the user via the Aurora Query Editor.

- [ ] **Step 6: KMS cost check**

After a day, check the KMS key's request metrics in CloudWatch. Expected: well under the 20 000 free-tier requests/month, well below the $1.50/month projection.

- [ ] **Step 7: Run full test suite + alembic + terraform validate**

```bash
pytest -q
cd infra && terraform validate
```

Expected: all green.

- [ ] **Step 8: Tick off acceptance criteria in the PR description**

Map each step above back to spec-A §12 items 1–8 and record verdict.

- [ ] **Step 9: Commit anything residual + push branch**

```bash
git status
git push -u origin <branch>
```

