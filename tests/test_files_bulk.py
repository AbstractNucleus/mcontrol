from pathlib import Path

# ---- /files/bulk_delete -----------------------------------------------

async def test_bulk_delete_removes_multiple_files(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("x", encoding="utf-8")
    (server_dir / "b.txt").write_text("y", encoding="utf-8")
    (server_dir / "stay.txt").write_text("z", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["a.txt", "b.txt"], "confirm": "DELETE"},
    )

    assert response.status_code == 204
    assert not (server_dir / "a.txt").exists()
    assert not (server_dir / "b.txt").exists()
    assert (server_dir / "stay.txt").exists()


async def test_bulk_delete_recursive_dir(
    client, fake_server, server_dir: Path
) -> None:
    d = server_dir / "doomed"
    (d / "nested").mkdir(parents=True)
    (d / "nested" / "leaf.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["doomed"], "confirm": "DELETE"},
    )

    assert response.status_code == 204
    assert not d.exists()


async def test_bulk_delete_400_without_DELETE_confirm(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["a.txt"]},
    )

    assert response.status_code == 400
    assert (server_dir / "a.txt").exists()


async def test_bulk_delete_400_with_wrong_confirm(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["a.txt"], "confirm": "delete"},
    )

    assert response.status_code == 400
    assert (server_dir / "a.txt").exists()


async def test_bulk_delete_400_refuses_root_in_paths(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "marker.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["", "marker.txt"], "confirm": "DELETE"},
    )

    assert response.status_code == 400
    # Nothing deleted.
    assert (server_dir / "marker.txt").exists()


async def test_bulk_delete_404_on_any_missing_aborts_batch(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["a.txt", "no-such.txt"], "confirm": "DELETE"},
    )

    assert response.status_code == 404
    # Refuse-on-any-bad-input: a.txt must NOT have been deleted.
    assert (server_dir / "a.txt").exists()


# ---- /files/bulk_move -------------------------------------------------

async def test_bulk_move_relocates_multiple_files(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("a", encoding="utf-8")
    (server_dir / "b.txt").write_text("b", encoding="utf-8")
    (server_dir / "dst").mkdir()

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a.txt", "b.txt"], "dest_dir": "dst"},
    )

    assert response.status_code == 204
    assert not (server_dir / "a.txt").exists()
    assert not (server_dir / "b.txt").exists()
    assert (server_dir / "dst" / "a.txt").read_text(encoding="utf-8") == "a"
    assert (server_dir / "dst" / "b.txt").read_text(encoding="utf-8") == "b"


async def test_bulk_move_409_on_any_collision_aborts_batch(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("a", encoding="utf-8")
    (server_dir / "b.txt").write_text("b", encoding="utf-8")
    (server_dir / "dst").mkdir()
    (server_dir / "dst" / "b.txt").write_text("victim", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a.txt", "b.txt"], "dest_dir": "dst"},
    )

    assert response.status_code == 409
    # Refuse-on-any-collision: nothing moved.
    assert (server_dir / "a.txt").exists()
    assert (server_dir / "b.txt").exists()
    assert (server_dir / "dst" / "b.txt").read_text(encoding="utf-8") == "victim"


async def test_bulk_move_400_refuses_no_op_for_any_source(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("a", encoding="utf-8")
    (server_dir / "sub").mkdir()
    (server_dir / "sub" / "b.txt").write_text("b", encoding="utf-8")

    # `a.txt`'s parent IS the destination root → no-op for it.
    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a.txt", "sub/b.txt"], "dest_dir": ""},
    )

    assert response.status_code == 400
    # Neither source moved.
    assert (server_dir / "a.txt").exists()
    assert (server_dir / "sub" / "b.txt").exists()


async def test_bulk_move_400_refuses_root_source(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "dst").mkdir()
    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": [""], "dest_dir": "dst"},
    )
    assert response.status_code == 400


async def test_bulk_move_400_refuses_into_descendant(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "parent" / "child").mkdir(parents=True)

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["parent"], "dest_dir": "parent/child"},
    )
    assert response.status_code == 400
    assert (server_dir / "parent" / "child").is_dir()


async def test_bulk_move_404_when_destination_missing(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("a", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a.txt"], "dest_dir": "no-such"},
    )
    assert response.status_code == 404
