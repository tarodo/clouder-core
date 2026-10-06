from __future__ import annotations

import pytest

from collector import analytics_handler as ah


def _event(route: str):
    return {
        "rawPath": route,
        "requestContext": {"requestId": "r", "routeKey": f"GET {route}"},
        "headers": {},
    }


def test_route_name_accepts_listening():
    assert ah._route_name(_event("/v1/analytics/listening")) == "listening"


@pytest.mark.parametrize("route", ["/v1/analytics/user-daily", "/v1/analytics/sessions", "/v1/analytics/evil"])
def test_route_name_rejects_removed_and_unknown(route):
    with pytest.raises(ah.AnalyticsError) as exc:
        ah._route_name(_event(route))
    assert exc.value.status_code == 404


class FakeAthena:
    def __init__(self, state="SUCCEEDED"):
        self.state = state
        self.started = {}

    def start_query_execution(self, **kw):
        self.started = kw
        return {"QueryExecutionId": "q1"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": self.state}}}

    def get_query_results(self, QueryExecutionId):
        return {"ResultSet": {"Rows": [
            {"Data": [{"VarCharValue": "period"}, {"VarCharValue": "tracks"}]},
            {"Data": [{"VarCharValue": "week"}, {"VarCharValue": "3"}]},
        ]}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ATHENA_DATABASE", "db")
    monkeypatch.setenv("ATHENA_OUTPUT_LOCATION", "s3://b/athena-results/")


def test_run_athena_binds_params_and_maps_rows():
    client = FakeAthena()
    rows = ah._run_athena(client, "SELECT ?", ["u1"])
    assert client.started["ExecutionParameters"] == ["u1"]
    assert client.started["ResultReuseConfiguration"]["ResultReuseByAgeConfiguration"]["MaxAgeInMinutes"] == 5
    assert rows == [{"period": "week", "tracks": "3"}]


def test_run_athena_failure_is_502():
    with pytest.raises(ah.AnalyticsError) as exc:
        ah._run_athena(FakeAthena(state="FAILED"), "SELECT 1", [])
    assert exc.value.status_code == 502
