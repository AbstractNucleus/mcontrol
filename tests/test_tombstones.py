"""Unit tests for mcontrol.tombstones (slice 11)."""

import time
from pathlib import Path

import pytest

from mcontrol import tombstones

# ---------------------------------------------------------------------------
# Name parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        (".deleted-atm10-1700000000", ("atm10", 1700000000)),
        # slug-with-hyphens — backtrack pins the unix-ts to the rightmost run
        (".deleted-kobra-2022-1700000000", ("kobra-2022", 1700000000)),
        (".deleted-monifactory-1234567890", ("monifactory", 1234567890)),
    ],
)
def test_parse_extracts_name_and_unix_ts(name: str, expected: tuple[str, int]):
    assert tombstones._parse(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "atm10",                              # missing prefix
        ".deleted-atm10",                     # missing ts
        ".deleted--1700000000",               # empty slug
        ".deleted-AB-1700000000",             # uppercase in slug
        ".deleted-a-1700000000",              # slug too short (1 char)
        ".deleted-foo_bar-1700000000",        # underscore not allowed
        ".deleted-foo-bar",                   # ts not digits
        "..",                                 # path traversal payload
        "../etc",                             # path traversal
        ".git",                               # operator dot-dir
        ".lost+found",                        # operator dot-dir
    ],
)
def test_parse_rejects_malformed_names(name: str):
    assert tombstones._parse(name) is None


# ---------------------------------------------------------------------------
# list_tombstones
# ---------------------------------------------------------------------------


def _make_tombstone(base: Path, name: str, ts: int, contents: dict[str, bytes]) -> Path:
    """Create a `.deleted-<name>-<ts>/` dir under base with some files."""
    tomb = base / f".deleted-{name}-{ts}"
    tomb.mkdir()
    for fname, body in contents.items():
        path = tomb / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return tomb


def test_list_tombstones_returns_empty_when_base_missing(tmp_path: Path):
    assert tombstones.list_tombstones(tmp_path / "no-such") == []


def test_list_tombstones_returns_empty_when_base_has_no_tombstones(tmp_path: Path):
    (tmp_path / "atm10").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "lost+found").mkdir()
    assert tombstones.list_tombstones(tmp_path) == []


def test_list_tombstones_parses_and_sums_bytes(tmp_path: Path):
    now = int(time.time())
    _make_tombstone(tmp_path, "atm10", now - 10, {"world/level.dat": b"x" * 1024})

    result = tombstones.list_tombstones(tmp_path)

    assert len(result) == 1
    t = result[0]
    assert t.dir_name == f".deleted-atm10-{now - 10}"
    assert t.original_name == "atm10"
    assert t.deleted_at_unix == now - 10
    assert 0 <= t.age_seconds <= 30  # allow some test-runtime slack
    assert t.bytes == 1024


def test_list_tombstones_sorts_oldest_first(tmp_path: Path):
    now = int(time.time())
    _make_tombstone(tmp_path, "newest", now - 60, {"f": b""})
    _make_tombstone(tmp_path, "oldest", now - 3600, {"f": b""})
    _make_tombstone(tmp_path, "middle", now - 600, {"f": b""})

    result = tombstones.list_tombstones(tmp_path)

    assert [t.original_name for t in result] == ["oldest", "middle", "newest"]


def test_list_tombstones_skips_malformed_dot_dirs(tmp_path: Path):
    now = int(time.time())
    _make_tombstone(tmp_path, "atm10", now, {"f": b""})
    (tmp_path / ".deleted-foo").mkdir()              # missing ts
    (tmp_path / ".deleted-bar-not-digits").mkdir()   # ts not digits
    (tmp_path / ".git").mkdir()                       # unrelated dot-dir

    result = tombstones.list_tombstones(tmp_path)

    assert [t.original_name for t in result] == ["atm10"]


def test_list_tombstones_skips_files_with_tombstone_shaped_names(tmp_path: Path):
    """A regular file named like a tombstone must not be listed."""
    (tmp_path / ".deleted-atm10-1700000000").write_bytes(b"not a dir")

    result = tombstones.list_tombstones(tmp_path)

    assert result == []


# ---------------------------------------------------------------------------
# purge_one
# ---------------------------------------------------------------------------


def test_purge_one_removes_the_tombstone_directory(tmp_path: Path):
    now = int(time.time())
    tomb = _make_tombstone(tmp_path, "atm10", now, {"world/level.dat": b"x"})
    assert tomb.exists()

    tombstones.purge_one(tmp_path, tomb.name)

    assert not tomb.exists()
    assert tmp_path.exists()  # parent untouched


@pytest.mark.parametrize(
    "bad_name",
    [
        "..",
        "../etc",
        "atm10",                          # missing prefix
        ".deleted-atm10",                 # missing ts
        ".git",
        ".deleted-foo/../bar-1700000000", # embedded slash
        "",
    ],
)
def test_purge_one_rejects_non_tombstone_names(tmp_path: Path, bad_name: str):
    with pytest.raises(ValueError):
        tombstones.purge_one(tmp_path, bad_name)


def test_purge_one_refuses_symlink_with_tombstone_shaped_name(tmp_path: Path):
    """Even if the regex passes, a symlink target must not be followed."""
    target = tmp_path / "outside"
    target.mkdir()
    link_name = ".deleted-atm10-1700000000"
    try:
        (tmp_path / link_name).symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    with pytest.raises(ValueError):
        tombstones.purge_one(tmp_path, link_name)

    # Symlink not followed; target still exists.
    assert target.exists()


# ---------------------------------------------------------------------------
# purge_older_than
# ---------------------------------------------------------------------------


def test_purge_older_than_purges_only_old_enough_tombstones(tmp_path: Path):
    now = int(time.time())
    eight_days = 8 * 86400
    ten_minutes = 600

    _make_tombstone(tmp_path, "stale", now - eight_days, {"f": b""})
    _make_tombstone(tmp_path, "fresh", now - ten_minutes, {"f": b""})

    purged = tombstones.purge_older_than(tmp_path, days=7)

    assert [t.original_name for t in purged] == ["stale"]
    assert not (tmp_path / f".deleted-stale-{now - eight_days}").exists()
    assert (tmp_path / f".deleted-fresh-{now - ten_minutes}").exists()


def test_purge_older_than_default_threshold_is_seven_days(tmp_path: Path):
    """The 7-day default lives in code only; assert it's the value the
    function uses when called without a days argument."""
    now = int(time.time())
    six_days = 6 * 86400
    eight_days = 8 * 86400

    _make_tombstone(tmp_path, "fresh", now - six_days, {"f": b""})
    _make_tombstone(tmp_path, "stale", now - eight_days, {"f": b""})

    purged = tombstones.purge_older_than(tmp_path)

    assert [t.original_name for t in purged] == ["stale"]


def test_purge_older_than_empty_base_is_noop(tmp_path: Path):
    assert tombstones.purge_older_than(tmp_path, days=7) == []


def test_purge_older_than_skips_fresh_tombstones_entirely(tmp_path: Path):
    now = int(time.time())
    _make_tombstone(tmp_path, "fresh1", now - 60, {"f": b""})
    _make_tombstone(tmp_path, "fresh2", now - 600, {"f": b""})

    purged = tombstones.purge_older_than(tmp_path, days=7)

    assert purged == []
    # Both tombstones still exist
    assert len(tombstones.list_tombstones(tmp_path)) == 2
