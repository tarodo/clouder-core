import pytest

from collector.label_enrichment.prompts import (
    PROMPTS,
    load_builtin_prompts,
    get_prompt,
)
from collector.label_enrichment.prompts.base import render_user
from collector.label_enrichment.schemas import LabelInfo


def setup_function(_):
    PROMPTS.clear()
    load_builtin_prompts()


def test_builtin_prompts_register():
    assert {"label_v2_facts", "label_v3_app_fields"} <= set(PROMPTS)
    assert "label_v1_baseline" not in PROMPTS


def test_label_v3_directives_present():
    cfg = get_prompt("label_v3_app_fields")
    assert cfg.version == "v1"
    assert cfg.schema is LabelInfo
    for directive in ("instagram_url", "tagline", "status", "primary_styles"):
        assert directive in cfg.system


def test_render_user_without_release():
    cfg = get_prompt("label_v2_facts")
    out = render_user(cfg, label_name="Drumcode", style="techno", release_name=None)
    assert 'Research label "Drumcode" in style "techno".' in out
    assert "Recent release" not in out


def test_render_user_with_release():
    cfg = get_prompt("label_v2_facts")
    out = render_user(
        cfg,
        label_name="Wisdom Teeth",
        style="bass",
        release_name="K-LONE - Cape Cira",
    )
    assert "Recent release: K-LONE - Cape Cira" in out


def test_get_prompt_unknown_raises():
    with pytest.raises(KeyError):
        get_prompt("nope")
