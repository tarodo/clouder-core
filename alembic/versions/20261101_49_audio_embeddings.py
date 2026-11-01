"""audio_embeddings: the similar-tracks vector, one per video and artifact version

A 256-dim pgvector embedding of each light-1 profile (MuLan + EffNet, PCA by the frozen artifact
`version`, e.g. 'sim-1'); the ML worker writes it, the similar-tracks routes rank by cosine distance.

Prod: pgvector is superuser-only on Aurora (trusted = false) and the migrator is not rds_superuser,
so the master user creates the extension once before this deploys (docs/ops/aurora.md). IF NOT
EXISTS checks for the extension before it checks privileges: a no-op after that step; CI and
local runs (a superuser) create it here.

Revision ID: 20261101_49
Revises: 20261029_48
Create Date: 2026-11-01 12:00:00
"""

from __future__ import annotations

from alembic import op

revision = "20261101_49"
down_revision = "20261029_48"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE audio_embeddings (
            video_id   varchar(32) NOT NULL,
            version    varchar(16) NOT NULL,
            embedding  vector(256) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (video_id, version)
        )
        """
    )


def downgrade() -> None:
    # The extension stays: prod's is the master user's.
    op.drop_table("audio_embeddings")
