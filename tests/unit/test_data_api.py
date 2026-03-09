"""Tests for DataAPIClient and its parameter/field encoding."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from collector.data_api import (
    DataAPIClient,
    _from_field,
    _to_field,
    _to_parameter,
    _to_rows,
)


# ── _to_field tests ──────────────────────────────────────────────────


def test_to_field_none() -> None:
    assert _to_field(None) == {"isNull": True}


def test_to_field_bool() -> None:
    assert _to_field(True) == {"booleanValue": True}
    assert _to_field(False) == {"booleanValue": False}


def test_to_field_int() -> None:
    assert _to_field(42) == {"longValue": 42}
    assert _to_field(0) == {"longValue": 0}


def test_to_field_float() -> None:
    assert _to_field(3.14) == {"doubleValue": 3.14}


def test_to_field_decimal() -> None:
    assert _to_field(Decimal("0.850")) == {"stringValue": "0.850"}


def test_to_field_string() -> None:
    assert _to_field("hello") == {"stringValue": "hello"}


def test_datetime_is_serialized_for_rds_data_api_timestamp() -> None:
    value = datetime(2026, 3, 1, 16, 31, 43, 123456, tzinfo=timezone.utc)
    assert _to_field(value) == {"stringValue": "2026-03-01 16:31:43.123456"}


def test_to_field_date() -> None:
    assert _to_field(date(2026, 3, 1)) == {"stringValue": "2026-03-01"}


def test_to_field_dict() -> None:
    result = _to_field({"key": "value"})
    assert result == {"stringValue": '{"key":"value"}'}


def test_to_field_list() -> None:
    result = _to_field([1, 2])
    assert result == {"stringValue": "[1,2]"}


# ── _to_parameter tests ─────────────────────────────────────────────


def test_to_parameter_datetime_has_timestamp_hint() -> None:
    param = _to_parameter("ts", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert param["typeHint"] == "TIMESTAMP"
    assert param["name"] == "ts"


def test_to_parameter_date_has_date_hint() -> None:
    param = _to_parameter("d", date(2026, 1, 1))
    assert param["typeHint"] == "DATE"


def test_to_parameter_decimal_has_decimal_hint() -> None:
    param = _to_parameter("c", Decimal("1.00"))
    assert param["typeHint"] == "DECIMAL"


def test_to_parameter_dict_has_json_hint() -> None:
    param = _to_parameter("meta", {"key": "value"})
    assert param["typeHint"] == "JSON"


def test_to_parameter_string_no_hint() -> None:
    param = _to_parameter("name", "hello")
    assert "typeHint" not in param


# ── _from_field tests ────────────────────────────────────────────────


def test_from_field_null() -> None:
    assert _from_field({"isNull": True}) is None


def test_from_field_string() -> None:
    assert _from_field({"stringValue": "hello"}) == "hello"


def test_from_field_long() -> None:
    assert _from_field({"longValue": 42}) == 42


def test_from_field_double() -> None:
    assert _from_field({"doubleValue": 3.14}) == 3.14


def test_from_field_boolean() -> None:
    assert _from_field({"booleanValue": True}) is True


def test_from_field_blob() -> None:
    assert _from_field({"blobValue": b"data"}) == b"data"


def test_from_field_non_mapping_returns_none() -> None:
    assert _from_field("invalid") is None
    assert _from_field(42) is None


def test_from_field_empty_returns_none() -> None:
    assert _from_field({}) is None


# ── _to_rows tests ──────────────────────────────────────────────────


def test_to_rows_converts_response_to_dicts() -> None:
    response = {
        "columnMetadata": [{"name": "id"}, {"name": "name"}],
        "records": [
            [{"longValue": 1}, {"stringValue": "Alice"}],
            [{"longValue": 2}, {"stringValue": "Bob"}],
        ],
    }
    rows = _to_rows(response)
    assert len(rows) == 2
    assert rows[0] == {"id": 1, "name": "Alice"}
    assert rows[1] == {"id": 2, "name": "Bob"}


def test_to_rows_returns_empty_on_no_records() -> None:
    assert _to_rows({}) == []
    assert _to_rows({"records": None}) == []
    assert _to_rows({"records": []}) == []


def test_to_rows_handles_null_fields() -> None:
    response = {
        "columnMetadata": [{"name": "val"}],
        "records": [[{"isNull": True}]],
    }
    rows = _to_rows(response)
    assert rows == [{"val": None}]


def test_to_rows_skips_non_list_records() -> None:
    response = {
        "columnMetadata": [{"name": "id"}],
        "records": ["not_a_record", [{"longValue": 1}]],
    }
    rows = _to_rows(response)
    assert len(rows) == 1
    assert rows[0] == {"id": 1}


# ── DataAPIClient tests ─────────────────────────────────────────────


class FakeRdsDataClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.execute_response: dict[str, Any] = {}
        self.transaction_id = "tx-123"

    def execute_statement(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("execute_statement", kwargs))
        return self.execute_response

    def batch_execute_statement(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("batch_execute_statement", kwargs))
        return {}

    def begin_transaction(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("begin_transaction", kwargs))
        return {"transactionId": self.transaction_id}

    def commit_transaction(self, **kwargs: Any) -> None:
        self.calls.append(("commit_transaction", kwargs))

    def rollback_transaction(self, **kwargs: Any) -> None:
        self.calls.append(("rollback_transaction", kwargs))


def test_execute_sends_params_and_returns_rows() -> None:
    fake = FakeRdsDataClient()
    fake.execute_response = {
        "columnMetadata": [{"name": "cnt"}],
        "records": [[{"longValue": 5}]],
    }
    client = DataAPIClient(fake, "arn:resource", "arn:secret", "mydb")

    rows = client.execute("SELECT count(*) AS cnt", {"limit": 10})

    assert rows == [{"cnt": 5}]
    _, kwargs = fake.calls[0]
    assert kwargs["sql"] == "SELECT count(*) AS cnt"
    assert kwargs["database"] == "mydb"
    assert len(kwargs["parameters"]) == 1
    assert kwargs["parameters"][0]["name"] == "limit"


def test_execute_with_transaction_id() -> None:
    fake = FakeRdsDataClient()
    fake.execute_response = {"columnMetadata": [], "records": []}
    client = DataAPIClient(fake, "arn:r", "arn:s", "db")

    client.execute("INSERT INTO t VALUES (:v)", {"v": 1}, transaction_id="tx-1")

    _, kwargs = fake.calls[0]
    assert kwargs["transactionId"] == "tx-1"


def test_batch_execute_sends_parameter_sets() -> None:
    fake = FakeRdsDataClient()
    client = DataAPIClient(fake, "arn:r", "arn:s", "db")

    client.batch_execute(
        "INSERT INTO t (a) VALUES (:a)",
        [{"a": "x"}, {"a": "y"}],
    )

    _, kwargs = fake.calls[0]
    assert len(kwargs["parameterSets"]) == 2


def test_batch_execute_skips_empty_parameter_sets() -> None:
    fake = FakeRdsDataClient()
    client = DataAPIClient(fake, "arn:r", "arn:s", "db")

    client.batch_execute("INSERT INTO t (a) VALUES (:a)", [])

    assert len(fake.calls) == 0


def test_transaction_commits_on_success() -> None:
    fake = FakeRdsDataClient()
    client = DataAPIClient(fake, "arn:r", "arn:s", "db")

    with client.transaction() as tx_id:
        assert tx_id == "tx-123"

    call_types = [c[0] for c in fake.calls]
    assert "begin_transaction" in call_types
    assert "commit_transaction" in call_types
    assert "rollback_transaction" not in call_types


def test_transaction_rolls_back_on_exception() -> None:
    fake = FakeRdsDataClient()
    client = DataAPIClient(fake, "arn:r", "arn:s", "db")

    with pytest.raises(ValueError):
        with client.transaction():
            raise ValueError("boom")

    call_types = [c[0] for c in fake.calls]
    assert "begin_transaction" in call_types
    assert "rollback_transaction" in call_types
    assert "commit_transaction" not in call_types
