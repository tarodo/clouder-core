from __future__ import annotations

from datetime import UTC, datetime

from collector.ml.labels import Label, training_rows

T = datetime(2026, 10, 1, tzinfo=UTC)


def test_training_rows_drop_conflicting_video() -> None:
    labels = [
        Label("t1", "v1", True, "c1", T),
        Label("t2", "v1", True, "c1", T),  # same video, same decision: one row
        Label("t3", "v2", True, "c1", T),
        Label("t4", "v2", False, None, T),  # keep vs discard: dropped
        Label("t5", "v3", True, "c1", T),
        Label("t6", "v3", True, "c2", T),  # two categories: dropped
        Label("t7", "v4", False, None, T),
    ]
    ids, keep, cats = training_rows(labels)
    assert ids == ["v1", "v4"]
    assert keep.dtype == bool
    assert keep.tolist() == [True, False]
    assert cats == ["c1", None]
