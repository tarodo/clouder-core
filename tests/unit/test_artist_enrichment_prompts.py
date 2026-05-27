from collector.artist_enrichment.prompts import PROMPTS, get_prompt, load_builtin_prompts
from collector.artist_enrichment.prompts.base import render_user
from collector.artist_enrichment.schemas import ArtistInfo


def test_builtin_artist_v1_registered():
    load_builtin_prompts()
    cfg = get_prompt("artist_v1")
    assert cfg.version == "v1"
    assert cfg.schema is ArtistInfo
    assert "{context_block}" in cfg.user_template


def test_render_user_with_context():
    load_builtin_prompts()
    cfg = PROMPTS["artist_v1"]
    out = render_user(cfg, artist_name="ANNA", style="techno",
                      sample_tracks=["Hidden Beauties"], known_labels=["Drumcode"])
    assert "ANNA" in out and "Hidden Beauties" in out and "Drumcode" in out
    assert "genre hint: techno" in out


def test_render_user_without_context():
    load_builtin_prompts()
    cfg = PROMPTS["artist_v1"]
    out = render_user(cfg, artist_name="ANNA", style="techno")
    assert "Disambiguation context" not in out
