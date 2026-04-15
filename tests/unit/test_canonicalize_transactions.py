"""Verify all canonicalize phases run within a transaction."""
from __future__ import annotations

from unittest.mock import MagicMock

from collector.canonicalize import Canonicalizer
from collector.normalize import NormalizedBundle
from collector.models import NormalizedLabel


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


def test_labels_phase_uses_transaction():
    repo = MagicMock()
    repo.transaction.return_value.__enter__.return_value = "tx-1"
    repo.find_identity.return_value = None

    c = Canonicalizer(repo)
    c.process_run(run_id="r", bundle=_bundle_with_one_label())

    label_calls = [
        call for call in repo.batch_upsert_source_entities.call_args_list
        if call.kwargs.get("transaction_id") == "tx-1"
    ]
    assert label_calls, (
        "labels phase must pass transaction_id to batch_upsert_source_entities"
    )


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
