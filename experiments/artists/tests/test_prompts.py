import pytest

from artlab.prompts.base import PromptConfig, render_user
from artlab.schemas import ArtistInfo


def _make_prompt(slug: str = "demo", version: str = "v1") -> PromptConfig:
    return PromptConfig(
        slug=slug,
        version=version,
        description="demo prompt",
        system="you research artists",
        user_template='Research "{artist_name}".{context_block}',
        schema=ArtistInfo,
    )


def test_render_user_without_context():
    cfg = _make_prompt()
    out = render_user(cfg, artist_name="ANNA", style="techno")
    assert out == 'Research "ANNA".'


def test_render_user_with_context():
    cfg = _make_prompt()
    out = render_user(
        cfg,
        artist_name="ANNA",
        style="techno",
        sample_tracks=["Hidden Beauties"],
        known_labels=["Drumcode"],
    )
    assert 'Research "ANNA".' in out
    assert "Hidden Beauties" in out
    assert "Drumcode" in out
    assert "genre hint: techno" in out


def test_registry_register_and_get():
    from artlab.prompts import PROMPTS, get_prompt, register

    PROMPTS.clear()
    cfg = _make_prompt(slug="demo_a")
    register(cfg)
    assert get_prompt("demo_a") is cfg


def test_registry_rejects_duplicate():
    from artlab.prompts import PROMPTS, register

    PROMPTS.clear()
    register(_make_prompt(slug="demo_b"))
    with pytest.raises(ValueError, match="already registered"):
        register(_make_prompt(slug="demo_b"))


def test_builtin_prompts_register():
    from artlab.prompts import PROMPTS, load_builtin_prompts

    load_builtin_prompts()
    assert "artist_v1" in PROMPTS


def test_artist_v1_contains_directives():
    from artlab.prompts import PROMPTS, load_builtin_prompts

    load_builtin_prompts()
    cfg = PROMPTS["artist_v1"]
    assert cfg.version == "v1"
    assert "disambiguation" in cfg.system.lower()
    assert "ai_reasoning" in cfg.system
    assert "spotify" in cfg.user_template.lower()
    assert "{context_block}" in cfg.user_template
    assert cfg.schema is ArtistInfo
