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


@pytest.mark.parametrize(
    "phase_method,expected_entity_type",
    [
        ("batch_upsert_source_entities", None),
    ],
)
def test_every_phase_passes_transaction_id(phase_method, expected_entity_type):
    repo = MagicMock()
    repo.transaction.return_value.__enter__.return_value = "tx-1"
    repo.find_identity.return_value = None

    Canonicalizer(repo).process_run(run_id="r", bundle=_full_bundle())

    method = getattr(repo, phase_method)
    # 5 entity phases call batch_upsert_source_entities (labels, styles,
    # artists, albums, tracks).
    assert method.call_count >= 5
    for call in method.call_args_list:
        assert call.kwargs.get("transaction_id") is not None, (
            f"{phase_method} called without transaction_id: {call}"
        )


def test_find_identity_runs_inside_transaction():
    """Resolver reads must see uncommitted writes from same txn."""
    repo = MagicMock()
    repo.transaction.return_value.__enter__.return_value = "tx-1"
    repo.find_identity.return_value = None

    Canonicalizer(repo).process_run(run_id="r", bundle=_full_bundle())

    txn_calls = [
        c
        for c in repo.find_identity.call_args_list
        if c.kwargs.get("transaction_id") == "tx-1"
    ]
    assert txn_calls, "find_identity must propagate transaction_id"


def test_transaction_rolled_back_on_failure():
    repo = MagicMock()
    txn_cm = MagicMock()
    repo.transaction.return_value = txn_cm
    txn_cm.__enter__.return_value = "tx-fail"

    repo.find_identity.return_value = None
    repo.create_label.side_effect = RuntimeError("boom")

    c = Canonicalizer(repo)
    try:
        c.process_run(run_id="r", bundle=_bundle_with_one_label())
    except RuntimeError:
        pass

    assert txn_cm.__exit__.called
    exit_args = txn_cm.__exit__.call_args[0]
    assert exit_args[0] is RuntimeError
