from splitlab.schemas import (
    URL_FIELDS,
    ArtistFacts,
    ArtistNarrative,
    LabelFacts,
    LabelNarrative,
)

ALL_REQUEST_MODELS = [LabelNarrative, ArtistNarrative, LabelFacts, ArtistFacts]


def test_no_ai_fields_anywhere():
    for model in ALL_REQUEST_MODELS:
        for name in model.model_fields:
            assert not name.startswith("ai_"), f"{model.__name__}.{name}"


def test_no_url_fields_in_llm_schemas():
    for model in ALL_REQUEST_MODELS:
        for name in model.model_fields:
            assert name not in URL_FIELDS
            assert not name.endswith("_url") and name != "website"


def test_narrative_has_no_numbers():
    for name in ("founded_year", "catalog_size_estimate", "releases_last_12_months"):
        assert name not in LabelNarrative.model_fields
        assert name in LabelFacts.model_fields
    assert "active_since" in ArtistFacts.model_fields
    assert "active_since" not in ArtistNarrative.model_fields


def test_key_narrative_fields_present():
    for f in ("tagline", "summary", "primary_styles", "notable_artists",
              "country", "status", "confidence", "sources"):
        assert f in LabelNarrative.model_fields
    for f in ("tagline", "summary", "bio", "notable_releases",
              "notable_collaborators", "artist_type"):
        assert f in ArtistNarrative.model_fields


def test_url_fields_constant():
    assert set(URL_FIELDS) == {
        "website", "bandcamp_url", "residentadvisor_url", "discogs_url",
        "beatport_url", "soundcloud_url", "instagram_url", "twitter_url",
    }
