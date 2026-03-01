"""Thin wrapper over AWS RDS Data API."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any, Dict, Iterable, Iterator, Mapping


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

    def execute(
        self,
        sql: str,
        params: Mapping[str, Any] | None = None,
        transaction_id: str | None = None,
    ) -> list[dict[str, Any]]:
        request: Dict[str, Any] = {
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

    def batch_execute(self, sql: str, parameter_sets: Iterable[Mapping[str, Any]], transaction_id: str | None = None) -> None:
        request: Dict[str, Any] = {
            "resourceArn": self._resource_arn,
            "secretArn": self._secret_arn,
            "database": self._database,
            "sql": sql,
            "parameterSets": [
                [_to_parameter(name, value) for name, value in params.items()]
                for params in parameter_sets
            ],
        }
        if transaction_id:
            request["transactionId"] = transaction_id

        if request["parameterSets"]:
            self._client.batch_execute_statement(**request)

    def begin_transaction(self) -> str:
        response = self._client.begin_transaction(
            resourceArn=self._resource_arn,
            secretArn=self._secret_arn,
            database=self._database,
        )
        return response["transactionId"]

    def commit_transaction(self, transaction_id: str) -> None:
        self._client.commit_transaction(
            resourceArn=self._resource_arn,
            secretArn=self._secret_arn,
            transactionId=transaction_id,
        )

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


def create_default_data_api_client(resource_arn: str, secret_arn: str, database: str) -> DataAPIClient:
    import boto3

    return DataAPIClient(
        client=boto3.client("rds-data"),
        resource_arn=resource_arn,
        secret_arn=secret_arn,
        database=database,
    )


def _to_parameter(name: str, value: Any) -> dict[str, Any]:
    parameter: Dict[str, Any] = {
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
        return {"stringValue": value.isoformat()}
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
        row: Dict[str, Any] = {}
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
