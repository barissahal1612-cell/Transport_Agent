"""Safety checks of scripts/local/create_local_tables.py (no network)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local"))
import create_local_tables as c  # noqa: E402


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:5001", "http://localhost:5000", "https://localhost",
])
def test_accepts_loopback(url):
    assert c.local_endpoint_or_none({c.ENDPOINT_ENV: url}) == url


@pytest.mark.parametrize("url", [
    None, "", "https://dynamodb.us-east-1.amazonaws.com", "http://127.0.0.1.evil.com:5001",
    "http://10.0.0.1:5000", "http://user@127.0.0.1:5001", "not a url",
])
def test_rejects_everything_else(url):
    env = {} if url is None else {c.ENDPOINT_ENV: url}
    assert c.local_endpoint_or_none(env) is None


def test_main_refuses_without_local_endpoint(monkeypatch, capsys):
    monkeypatch.delenv(c.ENDPOINT_ENV, raising=False)
    assert c.main() == 2
    assert "REFUSED" in capsys.readouterr().err


def test_table_specs_match_schema():
    specs = {s["TableName"]: s for s in c.table_specs({})}
    assert specs["logistic-ai-kb"]["GlobalSecondaryIndexes"][0]["IndexName"] == "sheet-index"
    assert specs["logistic-ai-users"]["GlobalSecondaryIndexes"][0]["IndexName"] == "userid-index"
    assert "GlobalSecondaryIndexes" not in specs["logistic-ai-permissions"]
