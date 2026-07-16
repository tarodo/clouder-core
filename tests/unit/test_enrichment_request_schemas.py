from collector.artist_enrichment.schemas import ArtistInfo, ArtistInfoRequest
from collector.label_enrichment.schemas import LabelInfo, LabelInfoRequest

AI_FIELDS = {"ai_content", "ai_signals", "ai_reasoning"}


def test_request_models_are_storage_minus_ai():
    assert set(LabelInfoRequest.model_fields) == set(LabelInfo.model_fields) - AI_FIELDS
    assert set(ArtistInfoRequest.model_fields) == set(ArtistInfo.model_fields) - AI_FIELDS


def test_request_payload_validates_into_storage_via_defaults():
    req = LabelInfoRequest(label_name="X", summary="s", confidence=0.5)
    info = LabelInfo.model_validate(req.model_dump())
    assert info.ai_reasoning == "" and info.ai_content.value == "unknown" and info.ai_signals == []

    areq = ArtistInfoRequest(artist_name="Y", summary="s", confidence=0.5)
    ainfo = ArtistInfo.model_validate(areq.model_dump())
    assert ainfo.ai_reasoning == "" and ainfo.ai_signals == []


def test_request_field_types_match_storage():
    for req_model, store_model in ((LabelInfoRequest, LabelInfo), (ArtistInfoRequest, ArtistInfo)):
        for name, f in req_model.model_fields.items():
            assert f.annotation == store_model.model_fields[name].annotation, name
