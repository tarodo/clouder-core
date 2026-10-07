"""Verify all canonicalize phases run within a transaction."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from collector.canonicalize import Canonicalizer
from collector.normalize import NormalizedBundle, NormalizedRelation
from collector.models import (
    NormalizedAlbum,
    NormalizedArtist,
    NormalizedLabel,
    NormalizedStyle,
    NormalizedTrack,
)


def _bundle_with_one_label() -> NormalizedBundle:
    return NormalizedBundle(
        tracks=(),
        artists=(),
        labels=(
            NormalizedLabel(
                bp_label_id=1,
                name="L",
                normalized_name="l",
                payload={"id": 1},
            ),
        ),
        albums=(),
        styles=(),
        relations=(),
    )


def _full_bundle() -> NormalizedBundle:
    return NormalizedBundle(
        labels=(
            NormalizedLabel(
                bp_label_id=1, name="L", normalized_name="l", payload={"id": 1}
            ),
        ),
        styles=(
            NormalizedStyle(
                bp_genre_id=10, name="S", normalized_name="s", payload={"id": 10}
            ),
        ),
        artists=(
            NormalizedArtist(
                bp_artist_id=20, name="A", normalized_name="a", payload={"id": 20}
            ),
        ),
        albums=(
            NormalizedAlbum(
                bp_release_id=30,
                title="T",
                normalized_title="t",
                release_date=None,
                bp_label_id=1,
                payload={"id": 30},
            ),
        ),
        tracks=(
            NormalizedTrack(
                bp_track_id=40,
                title="Tr",
                normalized_title="tr",
                mix_name=None,
                isrc=None,
                bpm=None,
                length_ms=None,
                key_name=None,
                key_camelot=None,
                publish_date=None,
                bp_release_id=30,
                bp_genre_id=10,
                bp_artist_ids=(20,),
                payload={"id": 40},
            ),
        ),
        relations=(
            NormalizedRelation(
                from_entity_type="album",
                from_external_id="30",
                relation_type="released_by",
                to_entity_type="label",
                to_external_id="1",
            ),
        ),
    )


def _echo_repo() -> MagicMock:
    """MagicMock repo whose identity lookups return what was just claimed."""
    repo = MagicMock()
    repo.transaction.return_value.__enter__.return_value = "tx-1"
    claimed: dict[tuple[str, str], str] = {}

    def claim(commands, transaction_id=None):
        for cmd in commands:
            claimed.setdefault((cmd.entity_type, cmd.external_id), cmd.clouder_id)

    def find(source, entity_type, external_ids, transaction_id=None):
        return {
            ext: claimed[(entity_type, ext)]
            for ext in external_ids
            if (entity_type, ext) in claimed
        }

    repo.claim_identities.side_effect = claim
    repo.find_identities.side_effect = find
    repo.read_track_state.return_value = {}
    return repo


@pytest.mark.parametrize(
    "method",
    [
        "batch_upsert_source_entities",
        "claim_identities",
        "find_identities",
        "read_track_state",
        "batch_create_labels",
        "batch_create_styles",
        "batch_create_artists",
        "batch_create_albums",
        "batch_create_tracks",
        "batch_conservative_update_tracks",
        "batch_upsert_track_artists",
    ],
)
def test_every_phase_call_passes_transaction_id(method):
    repo = _echo_repo()

    Canonicalizer(repo).process_run(run_id="r", bundle=_full_bundle())

    calls = getattr(repo, method).call_args_list
    assert calls, f"{method} was never called"
    for call in calls:
        assert call.kwargs.get("transaction_id") == "tx-1", f"{method}: {call}"


def test_transaction_rolled_back_on_failure():
    repo = _echo_repo()
    txn_cm = MagicMock()
    repo.transaction.return_value = txn_cm
    txn_cm.__enter__.return_value = "tx-fail"
    repo.batch_create_labels.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        Canonicalizer(repo).process_run(run_id="r", bundle=_bundle_with_one_label())

    assert txn_cm.__exit__.called
    assert txn_cm.__exit__.call_args[0][0] is RuntimeError
