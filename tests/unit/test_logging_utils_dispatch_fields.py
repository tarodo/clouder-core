from collector.logging_utils import ALLOWED_LOG_FIELDS


def test_dispatch_count_fields_are_allowed():
    for field in (
        "claimed",
        "skipped",
        "candidate_labels",
        "candidate_artists",
        "source_hint",
    ):
        assert field in ALLOWED_LOG_FIELDS
