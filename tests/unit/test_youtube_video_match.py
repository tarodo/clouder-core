from collector.providers.youtube.video_match import video_matches


def test_positive_clean_title():
    assert video_matches("Lychee", "Back In Time", "Lychee - Back in Time")


def test_positive_second_artist_format():
    assert video_matches("Tremor", "Disposition", "Tremor - Disposition")


def test_noise_in_title_still_matches():
    assert video_matches(
        "Lychee", "Back In Time",
        "Lychee - Back in Time (Official Video) [Fokuz Recordings]",
    )


def test_stopword_missing_in_title_still_matches():
    # query word "in" is a stopword; the title omits it -> still a match
    assert video_matches("Lychee", "Back In Time", "Lychee - Back Time")


def test_negative_different_track_same_artist():
    assert not video_matches(
        "Dysfunctional Family", "Overwhelmingly Positive",
        "Dysfunctional Family Christmas (Music Video)",
    )


def test_negative_unrelated():
    assert not video_matches("TENEM", "Sonar", "Liquid Drum and Bass Mix 747")


def test_version_original_rejects_remix():
    assert not video_matches("Lychee", "Back In Time", "Lychee - Back in Time (Someone Remix)")


def test_version_remix_track_matches_remix_video():
    assert video_matches(
        "Lychee", "Back In Time (Klute Remix)", "Lychee - Back in Time (Klute Remix)",
    )


def test_version_original_rejects_extended_mix():
    assert not video_matches("Lychee", "Back In Time", "Lychee - Back in Time (Extended Mix)")


def test_version_original_mix_candidate_matches_original():
    assert video_matches("Lychee", "Back In Time", "Lychee - Back in Time (Original Mix)")


def test_empty_query_returns_false():
    assert not video_matches("", "", "anything at all")
