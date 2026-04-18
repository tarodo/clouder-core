from __future__ import annotations

import pytest
from pydantic import ValidationError

from collector.schemas import EntitySearchMessage


def test_entity_search_message_accepts_full_payload() -> None:
    msg = EntitySearchMessage.model_validate(
        {
            "entity_type": "label",
            "entity_id": "label-123",
            "prompt_slug": "label_info",
            "prompt_version": "v1",
            "context": {"label_name": "Test", "styles": "Techno"},
        }
    )

    assert msg.entity_type == "label"
    assert msg.entity_id == "label-123"
    assert msg.prompt_slug == "label_info"
    assert msg.prompt_version == "v1"
    assert msg.context == {"label_name": "Test", "styles": "Techno"}


def test_entity_search_message_requires_entity_type() -> None:
    with pytest.raises(ValidationError):
        EntitySearchMessage.model_validate(
            {
                "entity_id": "x",
                "prompt_slug": "label_info",
                "prompt_version": "v1",
                "context": {},
            }
        )


def test_entity_search_message_trims_whitespace() -> None:
    msg = EntitySearchMessage.model_validate(
        {
            "entity_type": " label ",
            "entity_id": " x ",
            "prompt_slug": " p ",
            "prompt_version": " v1 ",
            "context": {},
        }
    )
    assert msg.entity_type == "label"
    assert msg.entity_id == "x"
    assert msg.prompt_slug == "p"
    assert msg.prompt_version == "v1"


def test_entity_search_message_defaults_empty_context() -> None:
    msg = EntitySearchMessage.model_validate(
        {
            "entity_type": "label",
            "entity_id": "x",
            "prompt_slug": "p",
            "prompt_version": "v1",
        }
    )
    assert msg.context == {}
