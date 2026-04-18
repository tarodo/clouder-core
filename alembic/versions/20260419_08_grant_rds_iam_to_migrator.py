"""idempotently grant rds_iam to clouder_migrator

Runs as a safety-net for clusters where migration 20260419_07 applied while
rds_iam did not yet exist (e.g., because iam_database_authentication_enabled
was toggled on after the role was created). Re-granting is a no-op on clusters
that already have the grant.

Revision ID: 20260419_08
Revises: 20260419_07
Create Date: 2026-04-19 01:00:00
"""

from __future__ import annotations

from alembic import op

revision = "20260419_08"
down_revision = "20260419_07"
branch_labels = None
depends_on = None


UPGRADE_SQL = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_iam')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'clouder_migrator') THEN
        GRANT rds_iam TO clouder_migrator;
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    pass
