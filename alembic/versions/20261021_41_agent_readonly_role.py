"""Read-only role for a coding agent: SELECT on the catalog, no secrets, no writes

`clouder_agent_ro` reads every table except the token store and sessions, and
`users` without email. Tables added later are readable by default, so a new
table holding secrets must be closed here too (tests/db/test_agent_reader_role_pg.py
fails on any readable token/email-like column).

In production the migrator owns the tables but cannot create roles, so
scripts/create_agent_reader.py (master user) creates the role, makes it
read-only and sets its password first; this migration grants on the tables.
Local and CI databases create the role here (docs/ops/aurora.md).

Revision ID: 20261021_41
Revises: 20261016_40
Create Date: 2026-10-21 12:00:00
"""

from __future__ import annotations

from alembic import op

revision = "20261021_41"
down_revision = "20261016_40"
branch_labels = None
depends_on = None

ROLE = "clouder_agent_ro"
_CLOSED = "user_vendor_tokens, user_sessions, users"
_USERS_READABLE = "id, spotify_id, display_name, is_admin, created_at, updated_at"


UPGRADE_SQL = [
    f"""
    DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
            IF NOT (SELECT rolcreaterole OR rolsuper FROM pg_roles
                    WHERE rolname = current_user) THEN
                RAISE EXCEPTION 'role {ROLE} is missing: run '
                    'scripts/create_agent_reader.py first (docs/ops/aurora.md)';
            END IF;
            CREATE ROLE {ROLE} LOGIN;
        END IF;
    END $$
    """,
    # Schema USAGE comes from PUBLIC (the migrator could not grant it anyway).
    f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ROLE}",
    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {ROLE}",
    f"REVOKE ALL ON {_CLOSED} FROM {ROLE}",
    f"GRANT SELECT ({_USERS_READABLE}) ON users TO {ROLE}",
]

# Privileges only: the role belongs to the master user (create_agent_reader.py).
DOWNGRADE_SQL = [
    f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM {ROLE}",
    f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}",
]


def upgrade() -> None:
    for sql in UPGRADE_SQL:
        op.execute(sql)


def downgrade() -> None:
    for sql in DOWNGRADE_SQL:
        op.execute(sql)
