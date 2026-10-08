"""The S3 / lake half of user deletion: covers, tombstone, Iceberg deletes."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from collector.user_deletion import delete_covers, purge_lake

UID = "3f2b8c1e-0000-4000-8000-000000000001"


class FakeS3:
    def __init__(self, versions: list[dict]) -> None:
        self.versions = versions
        self.deleted: list[dict] = []
        self.put: dict | None = None

    def get_paginator(self, name: str):
        assert name == "list_object_versions"
        return self

    def paginate(self, *, Bucket: str, Prefix: str):
        rows = [v for v in self.versions if v["Key"].startswith(Prefix)]
        yield {"Versions": [v for v in rows if not v.get("marker")],
               "DeleteMarkers": [v for v in rows if v.get("marker")]}

    def delete_objects(self, *, Bucket: str, Delete: dict) -> dict:
        self.deleted += Delete["Objects"]
        return {}

    def put_object(self, **kwargs) -> dict:
        self.put = kwargs
        return {}


class FakeAthena:
    def __init__(self, state: str = "SUCCEEDED") -> None:
        self.state = state
        self.queries: list[dict] = []

    def start_query_execution(self, **kwargs) -> dict:
        self.queries.append(kwargs)
        return {"QueryExecutionId": str(len(self.queries))}

    def get_query_execution(self, *, QueryExecutionId: str) -> dict:
        return {"QueryExecution": {"Status": {"State": self.state}}}


def test_delete_covers_removes_every_version_and_marker_of_this_user_only() -> None:
    s3 = FakeS3([
        {"Key": f"covers/{UID}/p1/1.jpg", "VersionId": "v1"},
        {"Key": f"covers/{UID}/p1/1.jpg", "VersionId": "v2", "marker": True},
        {"Key": "covers/someone-else/p9/1.jpg", "VersionId": "v3"},
    ])

    assert delete_covers(s3, "raw", UID) == 2
    assert s3.deleted == [{"Key": f"covers/{UID}/p1/1.jpg", "VersionId": "v1"},
                          {"Key": f"covers/{UID}/p1/1.jpg", "VersionId": "v2"}]


def test_purge_lake_writes_the_tombstone_before_deleting_derived_rows() -> None:
    s3, athena = FakeS3([]), FakeAthena()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

    purge_lake(s3, athena, user_id=UID, lake_bucket="lake", workgroup="wg", now=now, sleep=lambda _: None)

    assert s3.put["Key"] == f"governance/deleted_users/{UID}.json"
    assert json.loads(s3.put["Body"]) == {"user_id": UID, "deleted_at": "2026-10-08T12:00:00+00:00"}
    assert [q["QueryString"] for q in athena.queries] == [
        "DELETE FROM clouder_silver.events WHERE user_id = ?",
        "DELETE FROM clouder_gold.fct_play WHERE user_id = ?",
    ]
    assert all(q["ExecutionParameters"] == [f"'{UID}'"] and q["WorkGroup"] == "wg" for q in athena.queries)


def test_purge_lake_fails_loudly_when_athena_fails() -> None:
    with pytest.raises(RuntimeError, match="FAILED"):
        purge_lake(FakeS3([]), FakeAthena("FAILED"), user_id=UID, lake_bucket="lake",
                   workgroup="wg", now=datetime.now(timezone.utc), sleep=lambda _: None)


def test_lake_steps_refuse_an_id_that_is_not_a_uuid() -> None:
    with pytest.raises(ValueError):
        delete_covers(FakeS3([]), "raw", "../")
