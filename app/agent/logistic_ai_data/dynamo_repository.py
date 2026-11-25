"""DynamoDB tabanlı DataRepository (`logistic-ai-kb`). Tablo oluşturmaz; yalnızca Query yapar."""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from .dynamo_keys import DEFAULT_KB_TABLE, KB_TABLE_ENV, kb_pk
from .key_normalizer import normalize_key
from .repository import KEY_COLUMNS, QUESTION3, KeylessTableError, require_table


def _plain(value: Any) -> Any:
    """boto3 Decimal değerlerini int/float'a çevirir."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _stop_order(row: dict) -> int:
    try:
        return int(float(str(row.get("stop_sequence")).strip()))
    except (TypeError, ValueError):
        return 10**9  # geçersiz sıra en sona


class DynamoDataRepository:
    """`client_or_table`: boto3 `Table` kaynağı (test için Stubber'lı olabilir).

    Verilmezse tablo adı `table_name` ya da LOGISTIC_AI_KB_TABLE (varsayılan 'logistic-ai-kb')
    ile tembel olarak oluşturulur.
    """

    def __init__(self, table_name: str | None = None, client_or_table: Any = None) -> None:
        self.table_name = table_name or os.environ.get(KB_TABLE_ENV, DEFAULT_KB_TABLE)
        self._table = client_or_table

    def _get_table(self) -> Any:
        if self._table is None:
            import boto3  # tembel içe aktarma: soğuk başlangıcı etkilemesin

            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    def _query_pk(self, pk: str) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        table = self._get_table()
        params: dict[str, Any] = {"KeyConditionExpression": Key("PK").eq(pk)}
        rows: list[dict] = []
        while True:
            resp = table.query(**params)
            for item in resp.get("Items", []):
                data = item.get("data")
                if isinstance(data, dict):
                    rows.append(_plain(data))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            params["ExclusiveStartKey"] = last
        return rows

    def get_by_key(self, table: str, key: object) -> list[dict]:
        require_table(table)
        if table not in KEY_COLUMNS:
            raise KeylessTableError(table)
        if not normalize_key(key):
            return []
        rows = self._query_pk(kb_pk(table, key))
        if table == QUESTION3:
            rows.sort(key=_stop_order)
        return rows

    def get_all(self, table: str) -> list[dict]:
        require_table(table)
        if table in KEY_COLUMNS:
            raise KeylessTableError(table)
        return self._query_pk(kb_pk(table, None))
