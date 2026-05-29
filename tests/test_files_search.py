import sys
from pathlib import Path

import pytest

# ---- /files/search -----------------------------------------------------

async def test_search_short_query_returns_placeholder(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "match.txt").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "m"}
    )

    assert response.status_code == 200
    body = response.text
    assert "type at least 2 characters" in body
    # Placeholder must NOT include any matching results.
    assert "match.txt" not in body


async def test_search_finds_basename_match_recursive(
    client, fake_server, server_dir: Path
) -> None:
    (server_dir / "match.txt").write_text("x", encoding="utf-8")
    nested = server_dir / "sub" / "deep"
    nested.mkdir(parents=True)
    (nested / "alsoMATCH.log").write_text("y", encoding="utf-8")
    (server_dir / "skip.cfg").write_text("z", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "match"}
    )

    assert response.status_code == 200
    body = response.text
    assert "match.txt" in body
    # Case-insensitive substring matches the nested file too.
    assert "alsoMATCH.log" in body
    assert "sub/deep/alsoMATCH.log" in body
    assert "skip.cfg" not in body


async def test_search_no_results(client, fake_server, server_dir: Path) -> None:
    (server_dir / "foo.txt").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "zzznotthere"}
    )

    assert response.status_code == 200
    assert "no matches" in response.text


async def test_search_caps_at_limit_and_marks_truncated(
    client, fake_server, server_dir: Path, monkeypatch
) -> None:
    """Generate more than the cap so the truncated badge shows."""
    monkeypatch.setattr("mcontrol.routes.files.search._SEARCH_LIMIT", 5)
    for i in range(20):
        (server_dir / f"matchX-{i}.txt").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "matchX"}
    )

    assert response.status_code == 200
    body = response.text
    # Truncation marker present and result count is at the cap.
    assert "capped" in body or "truncated" in body
    # `data-select-path="matchX-` appears once per rendered hit.
    assert body.count('data-select-path="matchX-') == 5
    # Late files weren't rendered. the cap stopped the walk early.
    assert "matchX-19" not in body


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
async def test_search_does_not_descend_into_symlinked_dir(
    client, fake_server, server_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "matchABC.txt").write_text("x", encoding="utf-8")
    (server_dir / "linkdir").symlink_to(outside)

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "matchABC"}
    )

    assert response.status_code == 200
    # The file inside the symlinked dir must NOT be reached.
    assert "matchABC.txt" not in response.text


async def test_search_skips_world_region_by_default(
    client, fake_server, server_dir: Path
) -> None:
    """Chunk-region files under `world/region/` are pruned from the default walk."""
    region = server_dir / "world" / "region"
    region.mkdir(parents=True)
    (region / "r.0.0.mca").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "mca"}
    )

    assert response.status_code == 200
    body = response.text
    assert "r.0.0.mca" not in body
    # Caption surfaces the skip so the operator knows results are filtered.
    assert "skipped" in body


async def test_search_include_chunks_disables_skip(
    client, fake_server, server_dir: Path
) -> None:
    """`include_chunks=1` walks into the noisy world subdirs again."""
    region = server_dir / "world" / "region"
    region.mkdir(parents=True)
    (region / "r.0.0.mca").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search",
        params={"q": "mca", "include_chunks": "1"},
    )

    assert response.status_code == 200
    body = response.text
    assert "r.0.0.mca" in body


async def test_search_top_level_region_is_not_skipped(
    client, fake_server, server_dir: Path
) -> None:
    """A `region/` directory NOT under `world/` or `DIM*/` is searched normally."""
    region = server_dir / "region"
    region.mkdir()
    (region / "r.0.0.mca").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "mca"}
    )

    assert response.status_code == 200
    body = response.text
    assert "r.0.0.mca" in body
    # No skip happened, so no caption.
    assert "skipped" not in body


async def test_search_skips_dim_region_by_default(
    client, fake_server, server_dir: Path
) -> None:
    """`DIM*` parents (e.g. `DIM-1/region/`) also trigger the skip."""
    region = server_dir / "DIM-1" / "region"
    region.mkdir(parents=True)
    (region / "r.0.0.mca").write_text("x", encoding="utf-8")

    response = await client.get(
        "/servers/atm10/files/search", params={"q": "mca"}
    )

    assert response.status_code == 200
    assert "r.0.0.mca" not in response.text


# ---- /files/search cache (issue #49) ----------------------------------

async def test_search_cache_reflects_mutation(
    client, fake_server, server_dir: Path
) -> None:
    """A mutating handler must invalidate the cache so the next search
    sees the new file. Without invalidation the cached index would still
    report the pre-mutation tree."""
    (server_dir / "alpha.txt").write_text("x", encoding="utf-8")

    first = await client.get(
        "/servers/atm10/files/search", params={"q": "beta"}
    )
    assert first.status_code == 200
    assert "beta.txt" not in first.text

    # Mutate via the upload endpoint (one of the invalidating handlers).
    upload = await client.post(
        "/servers/atm10/files/upload",
        data={"path": ""},
        files=[("files", ("beta.txt", b"y"))],
    )
    assert upload.status_code == 200

    second = await client.get(
        "/servers/atm10/files/search", params={"q": "beta"}
    )
    assert second.status_code == 200
    assert "beta.txt" in second.text


async def test_search_cache_ttl_expires(
    client, fake_server, server_dir: Path, monkeypatch
) -> None:
    """An out-of-band edit doesn't invalidate the cache, but the TTL
    safety net rebuilds the index after `_INDEX_TTL_SECONDS`."""
    from mcontrol.services import file_search

    (server_dir / "old.txt").write_text("x", encoding="utf-8")

    clock = [1000.0]
    monkeypatch.setattr(file_search, "_now", lambda: clock[0])

    first = await client.get(
        "/servers/atm10/files/search", params={"q": "newfile"}
    )
    assert "newfile.txt" not in first.text

    # Direct filesystem mutation. bypasses every invalidating handler.
    (server_dir / "newfile.txt").write_text("y", encoding="utf-8")

    # Still within TTL → cached, stale result.
    stale = await client.get(
        "/servers/atm10/files/search", params={"q": "newfile"}
    )
    assert "newfile.txt" not in stale.text

    # Advance past the TTL → cache is treated as expired and rebuilt.
    clock[0] += file_search._INDEX_TTL_SECONDS + 1

    fresh = await client.get(
        "/servers/atm10/files/search", params={"q": "newfile"}
    )
    assert "newfile.txt" in fresh.text


async def test_search_cache_two_servers_isolated(
    client, monkeypatch, tmp_path: Path
) -> None:
    """Indexes are keyed by server name. a mutation on one server
    must not pollute or invalidate the other server's cache."""
    a_dir = tmp_path / "a"
    a_dir.mkdir()
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    (a_dir / "alpha.txt").write_text("x", encoding="utf-8")
    (b_dir / "beta.txt").write_text("y", encoding="utf-8")

    rows = {
        "srvA": {"name": "srvA", "dir": str(a_dir)},
        "srvB": {"name": "srvB", "dir": str(b_dir)},
    }
    from mcontrol.infra import db
    from mcontrol.services import file_search
    monkeypatch.setattr(db, "get_server", rows.get)
    file_search._search_index.clear()

    # Warm both caches.
    ra = await client.get("/servers/srvA/files/search", params={"q": "alpha"})
    assert "alpha.txt" in ra.text
    rb = await client.get("/servers/srvB/files/search", params={"q": "beta"})
    assert "beta.txt" in rb.text

    # Mutate srvA via mkdir. must invalidate srvA only.
    mk = await client.post(
        "/servers/srvA/files/mkdir", data={"path": "", "dirname": "fresh"}
    )
    assert mk.status_code == 200

    assert "srvA" not in file_search._search_index
    assert "srvB" in file_search._search_index


async def test_search_cache_skip_rules_apply_at_build(
    client, fake_server, server_dir: Path
) -> None:
    """Skip-set rules must be enforced at index-build time, not at
    query time. chunk-region files are absent from the default index
    and present in the `include_chunks=1` index."""
    region = server_dir / "world" / "region"
    region.mkdir(parents=True)
    (region / "r.0.0.mca").write_text("x", encoding="utf-8")

    default = await client.get(
        "/servers/atm10/files/search", params={"q": "mca"}
    )
    assert default.status_code == 200
    assert "r.0.0.mca" not in default.text

    with_chunks = await client.get(
        "/servers/atm10/files/search",
        params={"q": "mca", "include_chunks": "1"},
    )
    assert with_chunks.status_code == 200
    assert "r.0.0.mca" in with_chunks.text
