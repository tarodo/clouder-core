"""Pure-Python helpers for spec-D triage (no DB)."""

from __future__ import annotations

from datetime import date

import pytest

from collector.curation import (
    InactiveBucketError,
    InvalidStateError,
    StyleMismatchError,
    ValidationError,
)
from collector.curation.triage_service import (
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_DISCARD,
    BUCKET_TYPE_UNCLASSIFIED,
    BUCKET_TYPE_STAGING,
    TECHNICAL_BUCKET_TYPES,
    classify_bucket_type,
    validate_block_input,
    validate_target_for_transfer,
    validate_track_ids,
)


class TestValidateBlockInput:
    def test_happy_path(self) -> None:
        validate_block_input(
            "Tech House", date(2026, 4, 20), date(2026, 4, 26)
        )

    def test_empty_name(self) -> None:
        with pytest.raises(ValidationError):
            validate_block_input("", date(2026, 4, 20), date(2026, 4, 26))

    def test_whitespace_name(self) -> None:
        with pytest.raises(ValidationError):
            validate_block_input(
                "   ", date(2026, 4, 20), date(2026, 4, 26)
            )

    def test_long_name(self) -> None:
        with pytest.raises(ValidationError):
            validate_block_input(
                "x" * 129, date(2026, 4, 20), date(2026, 4, 26)
            )

    def test_inverted_window(self) -> None:
        with pytest.raises(ValidationError):
            validate_block_input(
                "X", date(2026, 4, 26), date(2026, 4, 20)
            )


class TestValidateTrackIds:
    def test_happy_path(self) -> None:
        validate_track_ids(
            ["00000000-0000-0000-0000-000000000001"]
        )

    def test_empty(self) -> None:
        with pytest.raises(ValidationError):
            validate_track_ids([])

    def test_cap(self) -> None:
        ids = [f"00000000-0000-0000-0000-{n:012d}" for n in range(1001)]
        with pytest.raises(ValidationError):
            validate_track_ids(ids)

    def test_bad_uuid_shape(self) -> None:
        with pytest.raises(ValidationError):
            validate_track_ids(["short"])


class TestValidateTargetForTransfer:
    def test_happy_path(self) -> None:
        validate_target_for_transfer(
            src_block={
                "user_id": "u1",
                "style_id": "s1",
                "status": "FINALIZED",
            },
            target_bucket={"inactive": False},
            target_block={
                "user_id": "u1",
                "style_id": "s1",
                "status": "IN_PROGRESS",
            },
        )

    def test_target_not_in_progress(self) -> None:
        with pytest.raises(InvalidStateError):
            validate_target_for_transfer(
                src_block={
                    "user_id": "u1",
                    "style_id": "s1",
                    "status": "IN_PROGRESS",
                },
                target_bucket={"inactive": False},
                target_block={
                    "user_id": "u1",
                    "style_id": "s1",
                    "status": "FINALIZED",
                },
            )

    def test_target_inactive(self) -> None:
        with pytest.raises(InactiveBucketError):
            validate_target_for_transfer(
                src_block={
                    "user_id": "u1",
                    "style_id": "s1",
                    "status": "IN_PROGRESS",
                },
                target_bucket={"inactive": True},
                target_block={
                    "user_id": "u1",
                    "style_id": "s1",
                    "status": "IN_PROGRESS",
                },
            )

    def test_style_mismatch(self) -> None:
        with pytest.raises(StyleMismatchError):
            validate_target_for_transfer(
                src_block={
                    "user_id": "u1",
                    "style_id": "s1",
                    "status": "IN_PROGRESS",
                },
                target_bucket={"inactive": False},
                target_block={
                    "user_id": "u1",
                    "style_id": "s2",
                    "status": "IN_PROGRESS",
                },
            )


class TestBucketConstants:
    def test_technical_set_excludes_staging(self) -> None:
        assert BUCKET_TYPE_STAGING not in TECHNICAL_BUCKET_TYPES
        assert BUCKET_TYPE_NEW in TECHNICAL_BUCKET_TYPES
        assert BUCKET_TYPE_OLD in TECHNICAL_BUCKET_TYPES
        assert BUCKET_TYPE_NOT in TECHNICAL_BUCKET_TYPES
        assert BUCKET_TYPE_DISCARD in TECHNICAL_BUCKET_TYPES
        assert BUCKET_TYPE_UNCLASSIFIED in TECHNICAL_BUCKET_TYPES


class TestClassifyBucketType:
    """Mirrors the SQL CASE in §6.1; used by repository tests as a fixture."""

    def test_null_release_date(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=None,
                release_type="single",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_UNCLASSIFIED
        )

    def test_release_before_window(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=date(2025, 1, 1),
                release_type="single",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_OLD
        )

    def test_compilation_in_window(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=date(2026, 4, 15),
                release_type="compilation",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_NOT
        )

    def test_old_beats_compilation(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=date(2025, 12, 1),
                release_type="compilation",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_OLD
        )

    def test_new_default(self) -> None:
        assert (
            classify_bucket_type(
                spotify_release_date=date(2026, 4, 15),
                release_type="single",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_NEW
        )

    def test_release_equal_to_date_from_is_new(self) -> None:
        # `<` not `<=`
        assert (
            classify_bucket_type(
                spotify_release_date=date(2026, 4, 1),
                release_type="single",
                date_from=date(2026, 4, 1),
            )
            == BUCKET_TYPE_NEW
        )
