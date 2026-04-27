from unittest.mock import MagicMock

import pytest

from mcontrol import db


@pytest.fixture(autouse=True)
def _reset_client_singleton(monkeypatch):
    """Each test starts with a fresh _client_singleton."""
    monkeypatch.setattr(db, "_client_singleton", None)


def _fake_supabase_client():
    """Build a fake supabase client whose .schema().table() chain we can introspect."""
    client = MagicMock(name="supabase_client")
    table = client.schema.return_value.table.return_value
    return client, table


def test_client_constructed_with_settings(env, monkeypatch):
    captured = {}

    def fake_create_client(url, key):
        captured["url"] = url
        captured["key"] = key
        return MagicMock()

    monkeypatch.setattr(db, "create_client", fake_create_client)

    db._client()

    assert captured == {"url": "https://api.noelkleen.com", "key": "test-key"}


def test_client_is_cached(env, monkeypatch):
    calls = {"n": 0}

    def fake_create_client(url, key):
        calls["n"] += 1
        return MagicMock()

    monkeypatch.setattr(db, "create_client", fake_create_client)

    a = db._client()
    b = db._client()

    assert a is b
    assert calls["n"] == 1


def test_table_targets_app_mcontrol_servers(env, monkeypatch):
    client, _ = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)

    db._table()

    client.schema.assert_called_once_with("app_mcontrol")
    client.schema.return_value.table.assert_called_once_with("servers")


def test_list_servers_orders_by_name(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)
    table.select.return_value.order.return_value.execute.return_value.data = [
        {"name": "atm10"},
        {"name": "monifactory"},
    ]

    rows = db.list_servers()

    table.select.assert_called_once_with("*")
    table.select.return_value.order.assert_called_once_with("name")
    assert rows == [{"name": "atm10"}, {"name": "monifactory"}]


def test_get_server_returns_first_row(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"name": "atm10", "state": "running"},
    ]

    row = db.get_server("atm10")

    table.select.return_value.eq.assert_called_once_with("name", "atm10")
    assert row == {"name": "atm10", "state": "running"}


def test_get_server_returns_none_when_missing(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    assert db.get_server("nope") is None


def test_upsert_server_uses_name_as_conflict_key(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)

    db.upsert_server(name="atm10", dir="/srv/atm10", state="running")

    args, kwargs = table.upsert.call_args
    payload = args[0]
    assert payload == {"name": "atm10", "dir": "/srv/atm10", "state": "running"}
    assert kwargs == {"on_conflict": "name"}
    table.upsert.return_value.execute.assert_called_once_with()
