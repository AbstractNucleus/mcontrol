# ---- server_detail integration ----------------------------------------

async def test_server_detail_renders_files_pane(client, monkeypatch) -> None:
    from mcontrol.infra import db
    monkeypatch.setattr(db, "get_server", lambda n: {
        "name": "atm10",
        "container_name": None,
        "dir": "/srv/atm10",
        "state": "running",
        "variables": {},
        "created_at": "2026-04-29T10:00:00Z",
        "updated_at": "2026-04-29T10:00:00Z",
    })

    response = await client.get("/servers/atm10")

    assert response.status_code == 200
    body = response.text
    assert "files-pane" in body
    assert 'id="file-tree"' in body
    assert 'id="file-view"' in body
    assert 'hx-get="/servers/atm10/files/tree?path="' in body
    # PR-3: upload UI is wired into the pane.
    assert 'data-server-name="atm10"' in body
    assert 'id="file-action-status"' in body
    assert 'id="file-upload-input"' in body
    # Root drop target + root upload trigger both carry data-upload-path="".
    assert 'data-upload-target' in body
    assert 'data-upload-trigger' in body
    # PR-4: root mkdir trigger is wired into the eyebrow (now inside the
    # follow-up's <details> popover).
    assert 'data-action-mkdir' in body
    # PR-7: search input + bulk toolbar are present (toolbar starts hidden).
    assert 'id="file-search-input"' in body
    assert 'id="file-search-results"' in body
    assert 'id="file-bulk-toolbar"' in body
    assert 'data-bulk-action="delete"' in body
    assert 'data-bulk-action="move"' in body
