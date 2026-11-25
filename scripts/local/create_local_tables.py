"""Create the three Logistic AI DynamoDB tables on a LOCAL moto server.

Safety: refuses to run unless ``AWS_ENDPOINT_URL_DYNAMODB`` points to localhost/127.0.0.1,
so it can never create tables in a real AWS account.

Usage (from ``scripts/``):  uv run python local/create_local_tables.py
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

ENDPOINT_ENV = "AWS_ENDPOINT_URL_DYNAMODB"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


def local_endpoint_or_none(env: dict[str, str] | os._Environ[str]) -> str | None:
    """Return the endpoint URL if it is a loopback http(s) URL, else None."""
    url = (env.get(ENDPOINT_ENV) or "").strip()
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        parsed.port  # noqa: B018 - validates the port
    except ValueError:
        return None
    if parsed.scheme in ("http", "https") and host in LOCAL_HOSTS and not parsed.username:
        return url
    return None


def table_specs(env: dict[str, str] | os._Environ[str]) -> list[dict]:
    kb = env.get("LOGISTIC_AI_KB_TABLE", "logistic-ai-kb")
    users = env.get("LOGISTIC_AI_USERS_TABLE", "logistic-ai-users")
    perms = env.get("LOGISTIC_AI_PERMISSIONS_TABLE", "logistic-ai-permissions")
    s = lambda n: {"AttributeName": n, "AttributeType": "S"}  # noqa: E731
    return [
        {
            "TableName": kb,
            "AttributeDefinitions": [s("PK"), s("SK"), s("sheet")],
            "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            "GlobalSecondaryIndexes": [{
                "IndexName": "sheet-index",
                "KeySchema": [{"AttributeName": "sheet", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": users,
            "AttributeDefinitions": [s("USERNAME"), s("USERID")],
            "KeySchema": [{"AttributeName": "USERNAME", "KeyType": "HASH"}],
            "GlobalSecondaryIndexes": [{
                "IndexName": "userid-index",
                "KeySchema": [{"AttributeName": "USERID", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": perms,
            "AttributeDefinitions": [s("SUBJECT"), s("RESOURCE")],
            "KeySchema": [
                {"AttributeName": "SUBJECT", "KeyType": "HASH"},
                {"AttributeName": "RESOURCE", "KeyType": "RANGE"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
    ]


def main() -> int:
    endpoint = local_endpoint_or_none(os.environ)
    if endpoint is None:
        print(
            f"REFUSED: {ENDPOINT_ENV} must point to localhost or 127.0.0.1 "
            "(e.g. http://127.0.0.1:5001). No table was created.",
            file=sys.stderr,
        )
        return 2
    import boto3

    region = os.environ.get("LOGISTIC_AI_AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    client = boto3.client("dynamodb", region_name=region, endpoint_url=endpoint)
    existing = set(client.list_tables().get("TableNames", []))
    for spec in table_specs(os.environ):
        name = spec["TableName"]
        if name in existing:
            print(f"exists : {name}")
            continue
        client.create_table(**spec)
        print(f"created: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
