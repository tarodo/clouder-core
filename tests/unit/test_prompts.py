"""Tests for prompt registry."""

from __future__ import annotations

import pytest

from collector.search.prompts import PromptConfig, get_latest, get_prompt, register
from collector.search.schemas import LabelSearchResult


def test_get_prompt_returns_registered_prompt() -> None:
    config = get_prompt("label_info", "v1")

    assert config.slug == "label_info"
    assert config.version == "v1"
    assert config.result_schema is LabelSearchResult
    assert config.model == "sonar"
    assert "{label_name}" in config.user_prompt_template
    assert "{style}" in config.user_prompt_template


def test_get_prompt_raises_for_unknown() -> None:
    with pytest.raises(KeyError, match="nonexistent/v99"):
        get_prompt("nonexistent", "v99")


def test_get_latest_returns_highest_version() -> None:
    config = get_latest("label_info")

    assert config.slug == "label_info"
    assert config.version == "v1"


def test_get_latest_raises_for_unknown_slug() -> None:
    with pytest.raises(KeyError, match="no_such_slug"):
        get_latest("no_such_slug")
