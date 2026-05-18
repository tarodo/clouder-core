import pytest

from lab.prompts.base import PromptConfig, render_user
from lab.schemas import LabelInfo


def _make_prompt(slug: str = "demo", version: str = "v1") -> PromptConfig:
    return PromptConfig(
        slug=slug,
        version=version,
        description="demo prompt",
        system="you research labels",
        user_template='Research "{label_name}" in style "{style}".{release_block}',
        schema=LabelInfo,
    )


def test_render_user_without_release():
    cfg = _make_prompt()
    out = render_user(cfg, label_name="Drumcode", style="techno", release_name=None)
    assert out == 'Research "Drumcode" in style "techno".'


def test_render_user_with_release():
    cfg = _make_prompt()
    out = render_user(
        cfg,
        label_name="Wisdom Teeth",
        style="bass",
        release_name="K-LONE - Cape Cira",
    )
    assert out == (
        'Research "Wisdom Teeth" in style "bass".\n'
        'Recent release: K-LONE - Cape Cira'
    )


def test_registry_register_and_get():
    from lab.prompts import PROMPTS, register, get_prompt

    PROMPTS.clear()
    cfg = _make_prompt(slug="demo_a", version="v1")
    register(cfg)
    assert get_prompt("demo_a") is cfg


def test_registry_rejects_duplicate():
    from lab.prompts import PROMPTS, register

    PROMPTS.clear()
    register(_make_prompt(slug="demo_b", version="v1"))
    with pytest.raises(ValueError, match="already registered"):
        register(_make_prompt(slug="demo_b", version="v1"))


def test_builtin_prompts_register():
    from lab.prompts import PROMPTS, load_builtin_prompts

    load_builtin_prompts()
    assert {"label_v1_baseline", "label_v2_facts"} <= set(PROMPTS)
    assert "label_v3_ai_focus" not in PROMPTS
