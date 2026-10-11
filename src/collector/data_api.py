"""Thin wrapper over AWS RDS Data API."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from .data_api_retry import retry_data_api, retry_data_api_pre_execution

# BatchExecuteStatement rejects a request body over 4 MiB (HTTP 413) — a whole
# large run's relations once did. Leave room for the ARNs and JSON framing.
_BATCH_REQUEST_BYTES = 3_000_000


class DataAPIClient:
    def __init__(
        self,
        client: Any,
        resource_arn: str,
        secret_arn: str,
        database: str,
    ) -> None:
        self._client = client
        self._resource_arn = resource_arn
        self._secret_arn = secret_arn
        self._database = database

    @retry_data_api()
    def execute(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        transaction_id: str | None = None,
    ) -> list[dict[str, Any]]:
        request: dict[str, Any] = {
            "resourceArn": self._resource_arn,
            "secretArn": self._secret_arn,
            "database": self._database,
            "sql": sql,
            "includeResultMetadata": True,
        }
        if params:
            request["parameters"] = [_to_parameter(name, value) for name, value in params.items()]
        if transaction_id:
            request["transactionId"] = transaction_id

        response = self._client.execute_statement(**request)
        return _to_rows(response)

    def batch_execute(
        self,
        sql: str,
        parameter_sets: Iterable[Mapping[str, Any]],
        transaction_id: str | None = None,
    ) -> None:
        """Send parameter sets in requests that stay under the Data API's body
        limit (4 MiB, HTTP 413 above it), all in the caller's transaction."""
        converted = [
            [_to_parameter(name, value) for name, value in params.items()]
            for params in parameter_sets
        ]
        for chunk in _size_chunks(converted, _BATCH_REQUEST_BYTES - len(sql)):
            self._batch_execute_chunk(sql, chunk, transaction_id)

    @retry_data_api()
    def _batch_execute_chunk(
        self,
        sql: str,
        parameter_sets: list[list[dict[str, Any]]],
        transaction_id: str | None,
    ) -> None:
        request: dict[str, Any] = {
            "resourceArn": self._resource_arn,
            "secretArn": self._secret_arn,
            "database": self._database,
            "sql": sql,
            "parameterSets": parameter_sets,
        }
        if transaction_id:
            request["transactionId"] = transaction_id
        self._client.batch_execute_statement(**request)

    @retry_data_api()
    def begin_transaction(self) -> str:
        response = self._client.begin_transaction(
            resourceArn=self._resource_arn,
            secretArn=self._secret_arn,
            database=self._database,
        )
        return str(response["transactionId"])

    @retry_data_api_pre_execution()
    def commit_transaction(self, transaction_id: str) -> None:
        self._client.commit_transaction(
            resourceArn=self._resource_arn,
            secretArn=self._secret_arn,
            transactionId=transaction_id,
        )

    @retry_data_api_pre_execution()
    def rollback_transaction(self, transaction_id: str) -> None:
        self._client.rollback_transaction(
            resourceArn=self._resource_arn,
            secretArn=self._secret_arn,
            transactionId=transaction_id,
        )

    @contextmanager
    def transaction(self) -> Iterator[str]:
        transaction_id = self.begin_transaction()
        try:
            yield transaction_id
            self.commit_transaction(transaction_id)
        except Exception:
            self.rollback_transaction(transaction_id)
            raise


def create_default_data_api_client(
    resource_arn: str, secret_arn: str, database: str
) -> DataAPIClient:
    import boto3

    return DataAPIClient(
        client=boto3.client("rds-data"),
        resource_arn=resource_arn,
        secret_arn=secret_arn,
        database=database,
    )


def _to_parameter(name: str, value: Any) -> dict[str, Any]:
    parameter: dict[str, Any] = {
        "name": name,
        "value": _to_field(value),
    }

    if isinstance(value, datetime):
        parameter["typeHint"] = "TIMESTAMP"
    elif isinstance(value, date):
        parameter["typeHint"] = "DATE"
    elif isinstance(value, (dict, list)):
        parameter["typeHint"] = "JSON"
    elif isinstance(value, Decimal):
        parameter["typeHint"] = "DECIMAL"

    return parameter


def _to_field(value: Any) -> dict[str, Any]:
    if value is None:
        return {"isNull": True}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"longValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, Decimal):
        return {"stringValue": str(value)}
    if isinstance(value, datetime):
        # RDS Data API TIMESTAMP parser expects SQL-like datetime without timezone suffix.
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return {"stringValue": value.strftime("%Y-%m-%d %H:%M:%S.%f")}
    if isinstance(value, date):
        return {"stringValue": value.isoformat()}
    if isinstance(value, (dict, list)):
        return {"stringValue": json.dumps(value, ensure_ascii=False, separators=(",", ":"))}
    return {"stringValue": str(value)}


def _to_rows(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = response.get("records")
    if not isinstance(records, list):
        return []

    metadata = response.get("columnMetadata")
    if not isinstance(metadata, list):
        return []

    columns = [item.get("name", f"col_{idx}") for idx, item in enumerate(metadata)]
    rows: list[dict[str, Any]] = []

    for record in records:
        if not isinstance(record, list):
            continue
        row: dict[str, Any] = {}
        for index, field in enumerate(record):
            if index >= len(columns):
                continue
            row[columns[index]] = _from_field(field)
        rows.append(row)
    return rows


def _from_field(field: Any) -> Any:
    if not isinstance(field, Mapping):
        return None
    if field.get("isNull"):
        return None

    for key in ("stringValue", "longValue", "doubleValue", "booleanValue"):
        if key in field:
            return field[key]

    if "arrayValue" in field:
        array_value = field["arrayValue"]
        if isinstance(array_value, Mapping):
            values = array_value.get("arrayValues")
            if isinstance(values, list):
                return [_from_field(value) for value in values]
        return None

    if "blobValue" in field:
        return field["blobValue"]

    return None


def _size_chunks(
    items: list[list[dict[str, Any]]], budget: int
) -> Iterator[list[list[dict[str, Any]]]]:
    """Consecutive groups whose JSON size stays within `budget`; an item larger
    than the budget goes alone (the service decides)."""
    chunk: list[list[dict[str, Any]]] = []
    size = 2  # the enclosing brackets
    for item in items:
        item_size = len(json.dumps(item, separators=(",", ":"), default=str)) + 1
        if chunk and size + item_size > budget:
            yield chunk
            chunk, size = [], 2
        chunk.append(item)
        size += item_size
    if chunk:
        yield chunk
