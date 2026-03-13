"""Perplexity API client for AI search."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from pydantic import BaseModel

from .prompts import PromptConfig


def search_label(
    label_name: str,
    style: str,
    config: PromptConfig,
    api_key: str,
) -> BaseModel:
    """Search for label info via Perplexity API and return structured result."""
    user_prompt = config.user_prompt_template.format(
        label_name=label_name,
        style=style,
    )

    response = _call_perplexity(
        api_key=api_key,
        model=config.model,
        system_prompt=config.system_prompt,
        user_prompt=user_prompt,
        result_schema=config.result_schema,
    )

    return config.result_schema.model_validate_json(response)


def _call_perplexity(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    result_schema: type[BaseModel],
) -> str:
    """Call Perplexity chat completions API and return raw content string."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "schema": result_schema.model_json_schema(),
            },
        },
        "temperature": 0.1,
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url="https://api.perplexity.ai/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=30.0) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Empty choices in Perplexity response")

    content = choices[0].get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Empty content in Perplexity response")

    return content
