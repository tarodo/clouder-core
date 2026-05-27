"""Test Pydantic schemas for spec-D triage requests/responses."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from collector.curation.schemas import (
    CreateTriageBlockIn,
    MoveTracksIn,
    TransferTracksIn,
)


class TestCreateTriageBlockIn:
    def test_happy_path(self) -> None:
        m = CreateTriageBlockIn(
            style_id="00000000-0000-0000-0000-000000000001",
            name="Tech House W17",
            date_from=date(2026, 4, 20),
            date_to=date(2026, 4, 26),
        )
        assert m.name == "Tech House W17"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateTriageBlockIn(
                style_id="00000000-0000-0000-0000-000000000001",
                name="",
                date_from=date(2026, 4, 20),
                date_to=date(2026, 4, 26),
            )

    def test_whitespace_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateTriageBlockIn(
                style_id="00000000-0000-0000-0000-000000000001",
                name="   ",
                date_from=date(2026, 4, 20),
                date_to=date(2026, 4, 26),
            )

    def test_long_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateTriageBlockIn(
                style_id="00000000-0000-0000-0000-000000000001",
                name="x" * 129,
                date_from=date(2026, 4, 20),
                date_to=date(2026, 4, 26),
            )

    def test_inverted_window_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateTriageBlockIn(
                style_id="00000000-0000-0000-0000-000000000001",
                name="X",
                date_from=date(2026, 4, 26),
                date_to=date(2026, 4, 20),
            )


class TestMoveTracksIn:
    def test_happy_path(self) -> None:
        m = MoveTracksIn(
            from_bucket_id="00000000-0000-0000-0000-000000000001",
            to_bucket_id="00000000-0000-0000-0000-000000000002",
            track_ids=[
                "00000000-0000-0000-0000-000000000003",
                "00000000-0000-0000-0000-000000000004",
            ],
        )
        assert len(m.track_ids) == 2

    def test_empty_track_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MoveTracksIn(
                from_bucket_id="00000000-0000-0000-0000-000000000001",
                to_bucket_id="00000000-0000-0000-0000-000000000002",
                track_ids=[],
            )

    def test_cap_1000(self) -> None:
        ids = [f"00000000-0000-0000-0000-{n:012d}" for n in range(1001)]
        with pytest.raises(ValidationError):
            MoveTracksIn(
                from_bucket_id="00000000-0000-0000-0000-000000000001",
                to_bucket_id="00000000-0000-0000-0000-000000000002",
                track_ids=ids,
            )


class TestTransferTracksIn:
    def test_cap_1000(self) -> None:
        ids = [f"00000000-0000-0000-0000-{n:012d}" for n in range(1001)]
        with pytest.raises(ValidationError):
            TransferTracksIn(
                target_bucket_id="00000000-0000-0000-0000-000000000001",
                track_ids=ids,
            )

    def test_happy_path(self) -> None:
        m = TransferTracksIn(
            target_bucket_id="00000000-0000-0000-0000-000000000001",
            track_ids=["00000000-0000-0000-0000-000000000002"],
        )
        assert len(m.track_ids) == 1


class TestCreateTriageBlockInPopulateOptions:
    def test_defaults_populate_options(self) -> None:
        m = CreateTriageBlockIn.model_validate(
            {
                "style_id": "00000000-0000-0000-0000-000000000001",
                "name": "House",
                "date_from": "2026-04-20",
                "date_to": "2026-04-26",
            }
        )
        assert m.old_offset_weeks == 0
        assert m.include_disliked_labels is True
        assert m.include_disliked_artists is True
        assert m.compilations_to_not is True
        assert m.include_favorites is True

    def test_accepts_classification_flags_off(self) -> None:
        m = CreateTriageBlockIn.model_validate(
            {
                "style_id": "00000000-0000-0000-0000-000000000001",
                "name": "House",
                "date_from": "2026-04-20",
                "date_to": "2026-04-26",
                "include_disliked_labels": False,
                "include_disliked_artists": False,
                "compilations_to_not": False,
                "include_favorites": False,
            }
        )
        assert m.include_disliked_labels is False
        assert m.include_disliked_artists is False
        assert m.compilations_to_not is False
        assert m.include_favorites is False

    def test_accepts_populate_options(self) -> None:
        m = CreateTriageBlockIn.model_validate(
            {
                "style_id": "00000000-0000-0000-0000-000000000001",
                "name": "House",
                "date_from": "2026-04-20",
                "date_to": "2026-04-26",
                "old_offset_weeks": 3,
                "include_disliked_labels": True,
            }
        )
        assert m.old_offset_weeks == 3
        assert m.include_disliked_labels is True

    def test_rejects_negative_offset(self) -> None:
        with pytest.raises(ValidationError):
            CreateTriageBlockIn.model_validate(
                {
                    "style_id": "00000000-0000-0000-0000-000000000001",
                    "name": "House",
                    "date_from": "2026-04-20",
                    "date_to": "2026-04-26",
                    "old_offset_weeks": -1,
                }
            )


class TestExtraFieldsRejected:
    def test_create_triage_block_in_rejects_unknown_field(self) -> None:
        from datetime import date
        with pytest.raises(ValidationError):
            CreateTriageBlockIn(
                style_id="00000000-0000-0000-0000-000000000001",
                name="X",
                date_from=date(2026, 4, 20),
                date_to=date(2026, 4, 26),
                unknown_field="bogus",
            )

    def test_move_tracks_in_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            MoveTracksIn(
                from_bucket_id="00000000-0000-0000-0000-000000000001",
                to_bucket_id="00000000-0000-0000-0000-000000000002",
                track_ids=["00000000-0000-0000-0000-000000000003"],
                unknown_field="bogus",
            )

    def test_transfer_tracks_in_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            TransferTracksIn(
                target_bucket_id="00000000-0000-0000-0000-000000000001",
                track_ids=["00000000-0000-0000-0000-000000000002"],
                unknown_field="bogus",
            )
