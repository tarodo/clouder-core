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

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam') THEN
        GRANT rds_iam TO clouder_migrator;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE {database_name} TO clouder_migrator;
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
REVOKE CONNECT ON DATABASE {database_name} FROM clouder_migrator;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam') THEN
        REVOKE rds_iam FROM clouder_migrator;
    END IF;
END
$$;

DROP ROLE IF EXISTS clouder_migrator;
"""


def upgrade() -> None:
    bind = op.get_bind()
    database_name = bind.engine.url.database
    op.execute(UPGRADE_SQL.format(database_name=_quote_identifier(database_name)))


def downgrade() -> None:
    bind = op.get_bind()
    database_name = bind.engine.url.database
    op.execute(DOWNGRADE_SQL.format(database_name=_quote_identifier(database_name)))


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
