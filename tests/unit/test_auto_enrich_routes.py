import json
from unittest.mock import MagicMock, patch

from collector.label_enrichment import auto_routes


def _put_event(body: dict) -> dict:
    return {
        "body": json.dumps(body),
        "requestContext": {"authorizer": {"lambda": {"user_id": "user-1"}}},
    }


def test_get_returns_defaults_when_no_config():
    repo = MagicMock()
    repo.get_config.return_value = None
    with patch.object(auto_routes, "_build_repository", return_value=repo):
        status, body = auto_routes.handle_get_auto_config({})
    assert status == 200
    assert body["config"]["enabled"] is False
    assert body["config"]["merge_vendor"] == "deepseek"
    assert set(body["options"]["vendors"]) <= {"gemini", "openai", "tavily_deepseek"}
    assert body["options"]["default_models"]["openai"] == "gpt-5.4-mini"


def test_get_returns_saved_config():
    repo = MagicMock()
    repo.get_config.return_value = {
        "kind": "labels", "enabled": True, "vendors": ["gemini"],
        "models": {"gemini": "g"}, "prompt_slug": "s", "prompt_version": "v",
        "merge_vendor": "deepseek", "merge_model": "m",
    }
    with patch.object(auto_routes, "_build_repository", return_value=repo):
        status, body = auto_routes.handle_get_auto_config({})
    assert status == 200
    assert body["config"]["enabled"] is True
    assert body["config"]["vendors"] == ["gemini"]


def test_put_validation_error_when_enabled_without_vendors():
    with patch.object(auto_routes, "_build_repository", return_value=MagicMock()):
        try:
            auto_routes.handle_put_auto_config(_put_event({"enabled": True, "vendors": []}))
            assert False, "expected ValidationError"
        except Exception as exc:
            assert "vendors required" in str(exc)


def test_put_persists_and_returns_204():
    repo = MagicMock()
    with patch.object(auto_routes, "_build_repository", return_value=repo):
        status, body = auto_routes.handle_put_auto_config(_put_event({
            "enabled": True, "vendors": ["gemini"], "models": {"gemini": "g"},
            "prompt_slug": "s", "prompt_version": "v",
            "merge_vendor": "deepseek", "merge_model": "m",
        }))
    assert status == 204
    repo.upsert_config.assert_called_once()
    kwargs = repo.upsert_config.call_args.kwargs
    assert kwargs["kind"] == "labels"
    assert kwargs["enabled"] is True
    assert kwargs["user_id"] == "user-1"
