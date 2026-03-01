from __future__ import annotations

import pytest
from pydantic import ValidationError

from collector.settings import get_api_settings, reset_settings_cache


def test_api_settings_require_raw_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAW_BUCKET_NAME", raising=False)
    reset_settings_cache()

    with pytest.raises(ValidationError):
        get_api_settings()

    reset_settings_cache()
