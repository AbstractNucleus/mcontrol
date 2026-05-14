"""Tests for routes/variables.py — the Variables card on the detail page."""

import pytest

from mcontrol.domain import scaffolding


@pytest.fixture
def fake_db(monkeypatch):
    state = {"rows": [], "writes": []}
    from mcontrol.infra import db

    def fake_list_servers():
        return list(state["rows"])

    def fake_get_server(name):
        for row in state["rows"]:
            if row["name"] == name:
                return row
        return None

    def fake_update_variables(*, name, variables):
        state["writes"].append(("update_variables", {"name": name, "variables": variables}))
        for row in state["rows"]:
            if row["name"] == name:
                row["variables"] = variables

    monkeypatch.setattr(db, "list_servers", fake_list_servers)
    monkeypatch.setattr(db, "get_server", fake_get_server)
    monkeypatch.setattr(db, "update_variables", fake_update_variables)

    return state


def _row(tmp_path, **overrides) -> dict:
    row = {
        "name": "newshire",
        "container_name": None,
        "dir": str(tmp_path / "newshire"),
        "state": "created",
        "scaffolded_at": "2026-05-06T12:00:00+00:00",
        "variables": {
            "memory_budget_gb": 8,
            "port": 25575,
            "server_jar": "paper.jar",
        },
    }
    row.update(overrides)
    return row


# ---- GET ------------------------------------------------------------


async def test_get_card_renders_current_variables(client, fake_db, tmp_path):
    row = _row(tmp_path)
    scaffolding.scaffold(row["name"], row["variables"], tmp_path)
    fake_db["rows"].append(row)

    response = await client.get("/servers/newshire/variables")

    assert response.status_code == 200
    body = response.text
    assert "Variables" in body
    assert "8" in body  # memory budget
    assert "25575" in body
    assert "paper.jar" in body
    assert 'hx-get="/servers/newshire/variables?edit=1"' in body


async def test_get_form_renders_editable_inputs(client, fake_db, tmp_path):
    row = _row(tmp_path)
    fake_db["rows"].append(row)

    response = await client.get("/servers/newshire/variables?edit=1")

    assert response.status_code == 200
    body = response.text
    assert 'name="memory_budget_gb"' in body
    assert 'name="port"' in body
    assert 'name="server_jar"' in body
    assert 'name="jvm_extra_args"' in body
    assert 'value="8"' in body
    assert 'value="25575"' in body


async def test_get_returns_404_for_unknown_server(client, fake_db):
    response = await client.get("/servers/unknown/variables")
    assert response.status_code == 404


# ---- POST happy path ------------------------------------------------


async def test_post_writes_variables_and_returns_card(client, fake_db, tmp_path):
    row = _row(tmp_path)
    scaffolding.scaffold(row["name"], row["variables"], tmp_path)
    fake_db["rows"].append(row)

    response = await client.post(
        "/servers/newshire/variables",
        data={
            "memory_budget_gb": "12",
            "port": "25577",
            "server_jar": "paper-1.21.4.jar",
            "jvm_extra_args": "-XX:+UseG1GC",
        },
    )

    assert response.status_code == 200
    op, kwargs = fake_db["writes"][0]
    assert op == "update_variables"
    assert kwargs["variables"] == {
        "memory_budget_gb": 12,
        "port": 25577,
        "server_jar": "paper-1.21.4.jar",
        "jvm_extra_args": "-XX:+UseG1GC",
    }
    # Card re-renders with the new values.
    body = response.text
    assert "12" in body
    assert "25577" in body
    assert "paper-1.21.4.jar" in body


async def test_post_drops_jvm_extra_args_when_blank(client, fake_db, tmp_path):
    row = _row(tmp_path, variables={
        "memory_budget_gb": 8,
        "port": 25575,
        "server_jar": "paper.jar",
        "jvm_extra_args": "-XX:+UseG1GC",
    })
    scaffolding.scaffold(row["name"], row["variables"], tmp_path)
    fake_db["rows"].append(row)

    response = await client.post(
        "/servers/newshire/variables",
        data={
            "memory_budget_gb": "8",
            "port": "25575",
            "server_jar": "paper.jar",
            "jvm_extra_args": "",
        },
    )

    assert response.status_code == 200
    kwargs = fake_db["writes"][0][1]
    assert "jvm_extra_args" not in kwargs["variables"]


async def test_post_preserves_unknown_jsonb_keys(client, fake_db, tmp_path):
    """motd / rcon_enabled aren't surfaced in the UI but live in the
    same JSONB. Decision 013 + slice-6 plan — write-back must merge,
    not replace, so any pre-existing keys survive."""
    row = _row(tmp_path, variables={
        "memory_budget_gb": 8,
        "port": 25575,
        "server_jar": "paper.jar",
        "motd": "Welcome",
    })
    scaffold_vars = {k: row["variables"][k] for k in ("memory_budget_gb", "port", "server_jar")}
    scaffolding.scaffold(row["name"], scaffold_vars, tmp_path)
    fake_db["rows"].append(row)

    await client.post(
        "/servers/newshire/variables",
        data={
            "memory_budget_gb": "12",
            "port": "25575",
            "server_jar": "paper.jar",
            "jvm_extra_args": "",
        },
    )

    kwargs = fake_db["writes"][0][1]
    assert kwargs["variables"]["motd"] == "Welcome"


# ---- POST validation ----------------------------------------------


async def test_post_rejects_invalid_memory(client, fake_db, tmp_path):
    fake_db["rows"].append(_row(tmp_path))

    response = await client.post(
        "/servers/newshire/variables",
        data={"memory_budget_gb": "1", "port": "25575",
              "server_jar": "paper.jar", "jvm_extra_args": ""},
    )

    assert response.status_code == 422
    assert "Minimum" in response.text
    assert fake_db["writes"] == []


async def test_post_rejects_port_out_of_range(client, fake_db, tmp_path):
    fake_db["rows"].append(_row(tmp_path))

    response = await client.post(
        "/servers/newshire/variables",
        data={"memory_budget_gb": "8", "port": "80",
              "server_jar": "paper.jar", "jvm_extra_args": ""},
    )

    assert response.status_code == 422
    assert "between" in response.text
    assert fake_db["writes"] == []


async def test_post_rejects_blank_server_jar(client, fake_db, tmp_path):
    fake_db["rows"].append(_row(tmp_path))

    response = await client.post(
        "/servers/newshire/variables",
        data={"memory_budget_gb": "8", "port": "25575",
              "server_jar": "   ", "jvm_extra_args": ""},
    )

    assert response.status_code == 422
    assert "Required" in response.text
    assert fake_db["writes"] == []


async def test_post_rejects_port_collision_with_other_server(
    client, fake_db, tmp_path
):
    fake_db["rows"].append(_row(tmp_path))
    fake_db["rows"].append({
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "running", "scaffolded_at": None,
        "variables": {"port": 25600},
    })

    response = await client.post(
        "/servers/newshire/variables",
        data={"memory_budget_gb": "8", "port": "25600",
              "server_jar": "paper.jar", "jvm_extra_args": ""},
    )

    assert response.status_code == 422
    body = response.text
    assert "25600" in body
    assert "atm10" in body
    assert fake_db["writes"] == []


async def test_post_allows_keeping_own_port(client, fake_db, tmp_path):
    """The collision check excludes the row being edited — the operator
    can save without changing the port."""
    row = _row(tmp_path)
    scaffolding.scaffold(row["name"], row["variables"], tmp_path)
    fake_db["rows"].append(row)

    response = await client.post(
        "/servers/newshire/variables",
        data={"memory_budget_gb": "8", "port": "25575",
              "server_jar": "paper.jar", "jvm_extra_args": ""},
    )

    assert response.status_code == 200
    assert len(fake_db["writes"]) == 1


async def test_post_returns_404_for_unknown_server(client, fake_db):
    response = await client.post(
        "/servers/unknown/variables",
        data={"memory_budget_gb": "8", "port": "25575",
              "server_jar": "paper.jar", "jvm_extra_args": ""},
    )
    assert response.status_code == 404
