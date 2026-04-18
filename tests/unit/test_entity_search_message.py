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


def test_coerce_label_search_message_payload() -> None:
    from collector.schemas import coerce_search_message

    coerced = coerce_search_message(
        {
            "label_id": "label-123",
            "label_name": "Test",
            "styles": "Techno",
            "prompt_slug": "label_info",
            "prompt_version": "v1",
        }
    )

    assert coerced.entity_type == "label"
    assert coerced.entity_id == "label-123"
    assert coerced.prompt_slug == "label_info"
    assert coerced.prompt_version == "v1"
    assert coerced.context == {"label_name": "Test", "styles": "Techno"}


def test_coerce_passes_through_entity_search_message() -> None:
    from collector.schemas import coerce_search_message

    payload = {
        "entity_type": "label",
        "entity_id": "x",
        "prompt_slug": "label_info",
        "prompt_version": "v1",
        "context": {"label_name": "Test", "styles": "Techno"},
    }
    coerced = coerce_search_message(payload)

    assert coerced.entity_type == "label"
    assert coerced.context == {"label_name": "Test", "styles": "Techno"}


def test_coerce_raises_on_unknown_shape() -> None:
    import pytest as _pytest
    from pydantic import ValidationError

    from collector.schemas import coerce_search_message

    with _pytest.raises(ValidationError):
        coerce_search_message({"unknown": "payload"})
