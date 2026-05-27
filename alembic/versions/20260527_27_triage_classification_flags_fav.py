"""triage classification flags and FAV bucket

Revision ID: 20260527_27
Revises: 20260527_26
Create Date: 2026-05-27 00:00:02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260527_27"
down_revision = "20260527_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "triage_blocks",
        sa.Column(
            "include_disliked_artists",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "triage_blocks",
        sa.Column(
            "compilations_to_not",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
    )
    op.add_column(
        "triage_blocks",
        sa.Column(
            "include_favorites",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.drop_constraint(
        "ck_triage_buckets_type", "triage_buckets", type_="check"
    )
    op.create_check_constraint(
        "ck_triage_buckets_type",
        "triage_buckets",
        "bucket_type IN ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING','FAV')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_triage_buckets_type", "triage_buckets", type_="check"
    )
    op.create_check_constraint(
        "ck_triage_buckets_type",
        "triage_buckets",
        "bucket_type IN ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING')",
    )
    op.drop_column("triage_blocks", "include_favorites")
    op.drop_column("triage_blocks", "compilations_to_not")
    op.drop_column("triage_blocks", "include_disliked_artists")
