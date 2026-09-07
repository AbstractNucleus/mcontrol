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


async def test_bulk_delete_with_dir_and_descendant_selected(
    client, fake_server, server_dir: Path
) -> None:
    """F-10: a folder plus one of its children is a legal tree selection.
    Deleting the folder first used to make the child's unlink raise
    FileNotFoundError -> 500 with the folder already gone."""
    mods = server_dir / "mods"
    mods.mkdir()
    (mods / "x.jar").write_bytes(b"\x00jar")
    (server_dir / "keep.txt").write_text("k", encoding="utf-8")

    # Descendant listed first: order must not matter.
    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["mods/x.jar", "mods"], "confirm": "DELETE"},
    )

    assert response.status_code == 204
    assert not mods.exists()
    assert (server_dir / "keep.txt").exists()


async def test_bulk_delete_tolerates_entry_vanishing_mid_batch(
    client, fake_server, server_dir: Path, monkeypatch
) -> None:
    """F-10 defence layer: even without the nested-path pruning, an entry
    that disappeared after validation is skipped rather than 500ing."""
    from mcontrol.routes.files import mutate

    monkeypatch.setattr(mutate, "_prune_nested", lambda _dir, paths: paths)
    mods = server_dir / "mods"
    mods.mkdir()
    (mods / "x.jar").write_bytes(b"\x00jar")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["mods", "mods/x.jar"], "confirm": "DELETE"},
    )

    assert response.status_code == 204
    assert not mods.exists()


async def test_bulk_delete_ignores_duplicate_paths(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "a.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["a.txt", "a.txt"], "confirm": "DELETE"},
    )

    assert response.status_code == 204
    assert not (server_dir / "a.txt").exists()


async def test_bulk_delete_sibling_prefix_is_not_nested(
    client, fake_server, server_dir: Path
) -> None:
    """F-10: `a` must not be treated as an ancestor of sibling `ab`."""
    (server_dir / "a").mkdir()
    (server_dir / "ab").mkdir()
    (server_dir / "a" / "f.txt").write_text("a", encoding="utf-8")
    (server_dir / "ab" / "g.txt").write_text("ab", encoding="utf-8")

    response = await client.post(
        "/servers/atm10/files/bulk_delete",
        data={"paths": ["a", "ab"], "confirm": "DELETE"},
    )

    assert response.status_code == 204
    assert not (server_dir / "a").exists()
    assert not (server_dir / "ab").exists()


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


async def test_bulk_move_409_when_sources_share_basename(
    client, fake_server, server_dir: Path
) -> None:
    """F-1: two sources that would land on the same destination basename
    must 409 before any rename, listing the colliding names."""
    (server_dir / "a").mkdir()
    (server_dir / "b").mkdir()
    (server_dir / "a" / "config.json").write_text("from-a", encoding="utf-8")
    (server_dir / "b" / "config.json").write_text("from-b", encoding="utf-8")
    (server_dir / "dest").mkdir()

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a/config.json", "b/config.json"], "dest_dir": "dest"},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "config.json" in detail
    assert (server_dir / "a" / "config.json").read_text(encoding="utf-8") == "from-a"
    assert (server_dir / "b" / "config.json").read_text(encoding="utf-8") == "from-b"
    assert not (server_dir / "dest" / "config.json").exists()


async def test_bulk_move_distinct_basenames_are_moved(
    client, fake_server, server_dir: Path
) -> None:
    """F-1: distinct destination basenames still move."""
    (server_dir / "a").mkdir()
    (server_dir / "b").mkdir()
    (server_dir / "a" / "one.json").write_text("1", encoding="utf-8")
    (server_dir / "b" / "two.json").write_text("2", encoding="utf-8")
    (server_dir / "dest").mkdir()

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a/one.json", "b/two.json"], "dest_dir": "dest"},
    )

    assert response.status_code == 204
    assert not (server_dir / "a" / "one.json").exists()
    assert not (server_dir / "b" / "two.json").exists()
    assert (server_dir / "dest" / "one.json").read_text(encoding="utf-8") == "1"
    assert (server_dir / "dest" / "two.json").read_text(encoding="utf-8") == "2"


async def test_bulk_move_single_source_is_not_a_duplicate(
    client, fake_server, server_dir: Path
) -> None:
    """F-1: a single source must not trip the shared-basename 409."""
    (server_dir / "a").mkdir()
    (server_dir / "a" / "config.json").write_text("only", encoding="utf-8")
    (server_dir / "dest").mkdir()

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["a/config.json"], "dest_dir": "dest"},
    )

    assert response.status_code == 204
    assert not (server_dir / "a" / "config.json").exists()
    assert (server_dir / "dest" / "config.json").read_text(encoding="utf-8") == "only"


async def test_bulk_move_with_dir_and_descendant_selected(
    client, fake_server, server_dir: Path
) -> None:
    """F-10: a folder plus a child moves the folder once (child rides along)."""
    mods = server_dir / "mods"
    mods.mkdir()
    (mods / "x.jar").write_bytes(b"\x00jar")
    (server_dir / "dest").mkdir()

    response = await client.post(
        "/servers/atm10/files/bulk_move",
        data={"sources": ["mods/x.jar", "mods"], "dest_dir": "dest"},
    )

    assert response.status_code == 204
    assert not mods.exists()
    assert (server_dir / "dest" / "mods").is_dir()
    assert (server_dir / "dest" / "mods" / "x.jar").read_bytes() == b"\x00jar"
    assert not (server_dir / "dest" / "x.jar").exists()


def test_prune_nested_drops_descendants(tmp_path: Path) -> None:
    from mcontrol.routes.files.mutate import _prune_nested

    kept = _prune_nested(str(tmp_path), ["mods/x.jar", "mods"])
    assert kept == ["mods"]


def test_prune_nested_keeps_prefix_siblings(tmp_path: Path) -> None:
    from mcontrol.routes.files.mutate import _prune_nested

    kept = _prune_nested(str(tmp_path), ["a", "ab"])
    assert kept == ["a", "ab"]
