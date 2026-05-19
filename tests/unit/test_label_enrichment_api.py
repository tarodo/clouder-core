import json
from unittest.mock import MagicMock, patch

import pytest

from collector.handler import lambda_handler


def _admin_event(route_key: str, body: dict | None = None, path_params: dict | None = None) -> dict:
    return {
        "routeKey": route_key,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": path_params or {},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": True, "user_id": "user-1"}},
        },
    }


def _non_admin_event(route_key: str, body: dict | None = None) -> dict:
    return {
        "routeKey": route_key,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": {},
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "user-2"}},
        },
    }


_VALID_BODY = {
    "labels": [
        {"label_name": "Drumcode", "style": "techno"},
        {"label_name": "Anjunadeep", "style": "deep house"},
    ],
    "vendors": ["gemini", "openai", "tavily_deepseek"],
    "models": {
        "gemini": "gemini-3-flash-preview",
        "openai": "gpt-5.4-mini",
        "tavily_deepseek": "deepseek-v4-flash",
    },
    "prompt_slug": "label_v3_app_fields",
    "prompt_version": "v1",
    "merge_vendor": "deepseek",
    "merge_model": "deepseek-v4-flash",
}


@pytest.fixture
def patched_deps(monkeypatch):
    repo = MagicMock()
    repo.upsert_label_by_name.side_effect = lambda name: f"lbl-{name.lower().replace(' ', '-')}"
    repo.create_run.return_value = "run-1"
    sqs_client = MagicMock()
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_repository",
        lambda: repo,
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes._build_sqs_client",
        lambda: sqs_client,
    )
    monkeypatch.setenv("LABEL_ENRICHMENT_QUEUE_URL", "https://sqs.example/q")
    yield repo, sqs_client


def test_post_enrich_returns_202_and_enqueues_one_message_per_label(patched_deps):
    repo, sqs = patched_deps
    resp = lambda_handler(_admin_event("POST /admin/labels/enrich", _VALID_BODY), None)
    assert resp["statusCode"] == 202
    body = json.loads(resp["body"])
    assert body["run_id"] == "run-1"
    assert body["queued_labels"] == 2
    assert sqs.send_message.call_count == 2
    repo.create_run.assert_called_once()
    spec = repo.create_run.call_args[0][0]
    assert spec.requested_labels == 2
    assert spec.created_by_user_id == "user-1"


def test_post_enrich_rejects_non_admin(patched_deps):
    resp = lambda_handler(_non_admin_event("POST /admin/labels/enrich", _VALID_BODY), None)
    assert resp["statusCode"] == 403


def test_post_enrich_rejects_invalid_body(patched_deps):
    bad = {**_VALID_BODY, "labels": []}
    resp = lambda_handler(_admin_event("POST /admin/labels/enrich", bad), None)
    assert resp["statusCode"] == 400


def test_get_enrich_run_returns_row(patched_deps):
    repo, _ = patched_deps
    repo.get_run.return_value = {
        "id": "run-1", "status": "running", "cells_total": 6,
        "cells_ok": 3, "cells_error": 0,
    }
    repo.list_cells_for_run.return_value = []
    resp = lambda_handler(
        _admin_event(
            "GET /admin/labels/enrich-runs/{run_id}",
            path_params={"run_id": "run-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["id"] == "run-1"


def test_get_enrich_run_404(patched_deps):
    repo, _ = patched_deps
    repo.get_run.return_value = None
    resp = lambda_handler(
        _admin_event(
            "GET /admin/labels/enrich-runs/{run_id}",
            path_params={"run_id": "nope"},
        ),
        None,
    )
    assert resp["statusCode"] == 404


def test_get_label_info_returns_row(patched_deps):
    repo, _ = patched_deps
    repo.get_label_info.return_value = {
        "label_id": "lbl-1", "label_name": "Drumcode",
        "merged": {"label_name": "Drumcode"},
        "status": "active", "ai_content": "none_detected",
    }
    resp = lambda_handler(
        _admin_event(
            "GET /admin/labels/{label_id}",
            path_params={"label_id": "lbl-1"},
        ),
        None,
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["label_name"] == "Drumcode"


def test_get_label_info_404(patched_deps):
    repo, _ = patched_deps
    repo.get_label_info.return_value = None
    resp = lambda_handler(
        _admin_event(
            "GET /admin/labels/{label_id}",
            path_params={"label_id": "lbl-9"},
        ),
        None,
    )
    assert resp["statusCode"] == 404


def test_post_enrich_by_label_id(patched_deps):
    repo, sqs = patched_deps
    repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Drumcode"}
    repo.derive_style_for_label.return_value = "techno"
    body = {**_VALID_BODY, "labels": [{"label_id": "lbl-1"}]}
    resp = lambda_handler(_admin_event("POST /admin/labels/enrich", body), None)
    assert resp["statusCode"] == 202
    assert sqs.send_message.call_count == 1
    # Worker message should carry the resolved style
    msg = json.loads(sqs.send_message.call_args.kwargs["MessageBody"])
    assert msg["label_id"] == "lbl-1"
    assert msg["label_name"] == "Drumcode"
    assert msg["style"] == "techno"


def test_post_enrich_by_label_id_400_when_missing(patched_deps):
    repo, sqs = patched_deps
    repo.get_label_by_id.return_value = None
    body = {**_VALID_BODY, "labels": [{"label_id": "nonexistent"}]}
    resp = lambda_handler(_admin_event("POST /admin/labels/enrich", body), None)
    assert resp["statusCode"] == 400  # ValidationError → 400
    assert sqs.send_message.call_count == 0


def test_post_enrich_by_label_id_falls_back_to_music_when_no_tracks(patched_deps):
    repo, sqs = patched_deps
    repo.get_label_by_id.return_value = {"id": "lbl-1", "name": "Brand New"}
    repo.derive_style_for_label.return_value = None
    body = {**_VALID_BODY, "labels": [{"label_id": "lbl-1"}]}
    resp = lambda_handler(_admin_event("POST /admin/labels/enrich", body), None)
    assert resp["statusCode"] == 202
    msg = json.loads(sqs.send_message.call_args.kwargs["MessageBody"])
    assert msg["style"] == "music"


def test_post_enrich_rejects_unknown_prompt_slug(patched_deps):
    bad = {**_VALID_BODY, "prompt_slug": "nonsense"}
    resp = lambda_handler(_admin_event("POST /admin/labels/enrich", bad), None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "prompt_slug" in body.get("message", "") or "prompt_slug" in body.get("error_message", "") or "nonsense" in json.dumps(body)


def test_routes_build_repository_passes_kwargs_from_settings(monkeypatch):
    """Regression: _build_repository was called with no args and TypeError'd.

    Verify it now reads from get_data_api_settings() and threads
    resource_arn/secret_arn/database into create_default_data_api_client.
    """
    from types import SimpleNamespace
    from collector.label_enrichment import routes

    fake_settings = SimpleNamespace(
        is_configured=True,
        aurora_cluster_arn="arn:aws:rds:cluster",
        aurora_secret_arn="arn:aws:secretsmanager:abc",
        aurora_database="postgres",
    )
    monkeypatch.setattr(
        "collector.label_enrichment.routes.get_data_api_settings",
        lambda: fake_settings,
    )

    captured: dict = {}

    def fake_create_client(*, resource_arn, secret_arn, database):
        captured["resource_arn"] = resource_arn
        captured["secret_arn"] = secret_arn
        captured["database"] = database
        return MagicMock(name="data-api-client")

    monkeypatch.setattr(
        "collector.label_enrichment.routes.create_default_data_api_client",
        fake_create_client,
    )

    repo = routes._build_repository()
    assert repo is not None
    assert captured == {
        "resource_arn": "arn:aws:rds:cluster",
        "secret_arn": "arn:aws:secretsmanager:abc",
        "database": "postgres",
    }


def test_routes_build_repository_raises_when_not_configured(monkeypatch):
    from types import SimpleNamespace
    from collector.label_enrichment import routes

    monkeypatch.setattr(
        "collector.label_enrichment.routes.get_data_api_settings",
        lambda: SimpleNamespace(
            is_configured=False,
            aurora_cluster_arn=None,
            aurora_secret_arn=None,
            aurora_database="postgres",
        ),
    )
    with pytest.raises(RuntimeError, match="not configured"):
        routes._build_repository()
