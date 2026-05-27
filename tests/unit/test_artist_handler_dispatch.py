"""Tests that collector handler dispatches all artist route_keys to the correct handlers."""
import json
from unittest.mock import patch

import pytest

from collector.handler import lambda_handler


def _admin_event(route_key: str, body: dict | None = None, path_params: dict | None = None) -> dict:
    return {
        "routeKey": route_key,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": path_params or {},
        "queryStringParameters": None,
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": True, "user_id": "user-1"}},
        },
    }


def _user_event(route_key: str, body: dict | None = None, path_params: dict | None = None) -> dict:
    return {
        "routeKey": route_key,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": path_params or {},
        "queryStringParameters": None,
        "requestContext": {
            "authorizer": {"lambda": {"is_admin": False, "user_id": "user-2"}},
        },
    }


def _stub(name: str):
    """Return a stub callable that returns a sentinel (200, {"h": name})."""
    def _fn(event):
        return (200, {"h": name})
    return _fn


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

def test_post_admin_artists_enrich_dispatched():
    with patch("collector.artist_enrichment.routes.handle_post_enrich", _stub("handle_post_enrich")):
        resp = lambda_handler(_admin_event("POST /admin/artists/enrich"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_post_enrich"


def test_get_admin_artists_enrich_options_dispatched():
    with patch("collector.artist_enrichment.routes.handle_get_options", _stub("handle_get_options")):
        resp = lambda_handler(_admin_event("GET /admin/artists/enrich/options"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_get_options"


def test_get_admin_artists_enrich_runs_dispatched():
    with patch("collector.artist_enrichment.routes.handle_get_runs_list", _stub("handle_get_runs_list")):
        resp = lambda_handler(_admin_event("GET /admin/artists/enrich-runs"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_get_runs_list"


def test_get_admin_artists_enrich_run_by_id_dispatched():
    with patch("collector.artist_enrichment.routes.handle_get_run", _stub("handle_get_run")):
        resp = lambda_handler(_admin_event("GET /admin/artists/enrich-runs/{run_id}", path_params={"run_id": "r1"}), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_get_run"


def test_get_admin_artists_backlog_dispatched():
    with patch("collector.artist_enrichment.routes.handle_get_backlog", _stub("handle_get_backlog")):
        resp = lambda_handler(_admin_event("GET /admin/artists/backlog"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_get_backlog"


def test_get_admin_artist_history_dispatched():
    """history route must be dispatched (not shadowed by bare {artist_id})."""
    with patch("collector.artist_enrichment.routes.handle_get_artist_history", _stub("handle_get_artist_history")):
        resp = lambda_handler(
            _admin_event("GET /admin/artists/{artist_id}/history", path_params={"artist_id": "a1"}),
            None,
        )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_get_artist_history"


def test_get_admin_artist_by_id_dispatched():
    with patch("collector.artist_enrichment.routes.handle_get_artist", _stub("handle_get_artist")):
        resp = lambda_handler(
            _admin_event("GET /admin/artists/{artist_id}", path_params={"artist_id": "a1"}),
            None,
        )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_get_artist"


def test_get_admin_auto_enrich_artists_dispatched():
    with patch("collector.artist_enrichment.auto_routes.handle_get_auto_config", _stub("handle_get_auto_config")):
        resp = lambda_handler(_admin_event("GET /admin/auto-enrich/artists"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_get_auto_config"


def test_put_admin_auto_enrich_artists_dispatched():
    with patch("collector.artist_enrichment.auto_routes.handle_put_auto_config", _stub("handle_put_auto_config")):
        resp = lambda_handler(_admin_event("PUT /admin/auto-enrich/artists"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_put_auto_config"


def test_admin_artist_routes_require_admin():
    """A non-admin request to an admin artist route gets a 403."""
    event = _admin_event("GET /admin/artists/backlog")
    event["requestContext"]["authorizer"]["lambda"]["is_admin"] = False
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 403


# ---------------------------------------------------------------------------
# Non-admin (user-facing) routes
# ---------------------------------------------------------------------------

def test_get_artists_list_dispatched():
    with patch("collector.artist_enrichment.routes.handle_get_artists_list", _stub("handle_get_artists_list")):
        resp = lambda_handler(_user_event("GET /artists"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_get_artists_list"


def test_get_artist_user_dispatched():
    with patch("collector.artist_enrichment.routes.handle_get_artist_user", _stub("handle_get_artist_user")):
        resp = lambda_handler(
            _user_event("GET /artists/{artist_id}", path_params={"artist_id": "a42"}),
            None,
        )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_get_artist_user"


def test_put_artist_preference_dispatched():
    with patch("collector.artist_enrichment.routes.handle_put_artist_preference", _stub("handle_put_artist_preference")):
        resp = lambda_handler(
            _user_event("PUT /artists/{artist_id}/preference", path_params={"artist_id": "a42"}),
            None,
        )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_put_artist_preference"


def test_get_my_artist_preferences_dispatched():
    with patch("collector.artist_enrichment.routes.handle_get_my_artist_preferences", _stub("handle_get_my_artist_preferences")):
        resp = lambda_handler(_user_event("GET /me/artist-preferences"), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["h"] == "handle_get_my_artist_preferences"
