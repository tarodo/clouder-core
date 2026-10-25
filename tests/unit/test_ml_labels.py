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


def test_training_rows_oldest_first() -> None:
    """By each video's newest label: the keep head's row cap keeps the newest rows."""
    day = [datetime(2026, 10, d, tzinfo=UTC) for d in range(1, 6)]
    labels = [
        Label("t1", "v1", True, "c1", day[4]),
        Label("t2", "v2", False, None, day[1]),
        Label("t3", "v1", True, "c1", day[0]),
        Label("t4", "v3", False, None, day[2]),
    ]
    ids, keep, cats = training_rows(labels)
    assert ids == ["v2", "v3", "v1"]  # v1's newest label is the last
    assert keep.tolist() == [False, False, True]
    assert cats == [None, None, "c1"]
