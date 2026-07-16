from collector.artist_enrichment.prompts import load_builtin_prompts as load_artist
from collector.artist_enrichment.prompts import get_prompt as get_artist
from collector.artist_enrichment.schemas import ArtistInfoRequest
from collector.label_enrichment.prompts import load_builtin_prompts as load_label
from collector.label_enrichment.prompts import get_prompt as get_label
from collector.label_enrichment.schemas import LabelInfoRequest


def test_no_ai_prompts_registered_with_request_schemas():
    load_label(); load_artist()
    lbl = get_label("label_v4_no_ai")
    art = get_artist("artist_v2_no_ai")
    assert lbl.schema is LabelInfoRequest
    assert art.schema is ArtistInfoRequest


def test_no_ai_text_anywhere():
    load_label(); load_artist()
    for cfg in (get_label("label_v4_no_ai"), get_artist("artist_v2_no_ai")):
        for text in (cfg.system, cfg.user_template):
            low = text.lower()
            assert "ai-content" not in low and "ai_" not in low
            assert "assess" not in low


def test_defaults_point_to_no_ai():
    from collector.label_enrichment import prompts as lp
    from collector.artist_enrichment import prompts as ap
    assert lp._DEFAULT_PROMPT_SLUG == "label_v4_no_ai"
    assert ap._DEFAULT_PROMPT_SLUG == "artist_v2_no_ai"
