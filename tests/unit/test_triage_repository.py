"""Unit tests for TriageRepository (mocked Data API)."""

from __future__ import annotations

from collector.curation.triage_repository import (
    TriageRepository,
    TriageBlockRow,
    TriageBucketRow,
    BucketTrackRowOut,
)


def test_module_exposes_repository_class() -> None:
    assert hasattr(TriageRepository, "create_block")
    assert hasattr(TriageRepository, "get_block")
    assert hasattr(TriageRepository, "list_blocks_by_style")
    assert hasattr(TriageRepository, "list_blocks_all")
    assert hasattr(TriageRepository, "list_bucket_tracks")
    assert hasattr(TriageRepository, "move_tracks")
    assert hasattr(TriageRepository, "transfer_tracks")
    assert hasattr(TriageRepository, "finalize_block")
    assert hasattr(TriageRepository, "soft_delete_block")
    assert hasattr(
        TriageRepository, "snapshot_category_into_active_blocks"
    )
    assert hasattr(
        TriageRepository, "mark_staging_inactive_for_category"
    )


def test_dataclasses_have_expected_fields() -> None:
    row = TriageBlockRow(
        id="b-1",
        user_id="u-1",
        style_id="s-1",
        style_name="House",
        name="Tech House W17",
        date_from="2026-04-20",
        date_to="2026-04-26",
        status="IN_PROGRESS",
        created_at="2026-04-28T00:00:00+00:00",
        updated_at="2026-04-28T00:00:00+00:00",
        finalized_at=None,
        buckets=(),
    )
    assert row.id == "b-1"
    assert row.buckets == ()
