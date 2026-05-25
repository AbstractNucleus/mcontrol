import json
from pathlib import Path

import pytest

from mcontrol.domain import membership

_NOTCH_UUID = "069a79f4-44e9-4726-a5be-fca90e38aaf5"
_HEROBRINE_UUID = "ec561538-f3fd-461d-aff5-086b22154bce"


def _server_dir(tmp_path: Path, name: str = "atm10") -> Path:
    """Create the standard ``<base>/<name>/server/`` layout used by the
    real fleet, return the per-server directory (one level above
    ``server/``). same shape membership.py expects."""
    server_dir = tmp_path / name
    (server_dir / "server").mkdir(parents=True)
    return server_dir


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def test_whitelist_path_is_server_subdir(tmp_path):
    server_dir = _server_dir(tmp_path)
    assert membership.whitelist_path(server_dir) == server_dir / "server" / "whitelist.json"


def test_ops_path_is_server_subdir(tmp_path):
    server_dir = _server_dir(tmp_path)
    assert membership.ops_path(server_dir) == server_dir / "server" / "ops.json"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def test_read_whitelist_returns_empty_and_zero_when_file_missing(tmp_path):
    server_dir = _server_dir(tmp_path)
    entries, mtime_ns = membership.read_whitelist(server_dir)
    assert entries == []
    assert mtime_ns == 0


def test_read_whitelist_returns_entries_and_mtime(tmp_path):
    server_dir = _server_dir(tmp_path)
    path = membership.whitelist_path(server_dir)
    path.write_text(json.dumps([{"uuid": _NOTCH_UUID, "name": "Notch"}]))

    entries, mtime_ns = membership.read_whitelist(server_dir)

    assert entries == [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    assert mtime_ns == path.stat().st_mtime_ns
    assert mtime_ns > 0


def test_read_whitelist_treats_empty_file_as_empty_list(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.whitelist_path(server_dir).write_text("")

    entries, _ = membership.read_whitelist(server_dir)
    assert entries == []


def test_read_whitelist_raises_on_invalid_json(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.whitelist_path(server_dir).write_text("{not json")

    with pytest.raises(membership.MalformedFileError):
        membership.read_whitelist(server_dir)


def test_read_whitelist_raises_when_top_level_is_not_a_list(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.whitelist_path(server_dir).write_text(json.dumps({"uuid": _NOTCH_UUID}))

    with pytest.raises(membership.MalformedFileError):
        membership.read_whitelist(server_dir)


def test_read_whitelist_raises_when_list_contains_non_objects(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.whitelist_path(server_dir).write_text(json.dumps(["Notch"]))

    with pytest.raises(membership.MalformedFileError):
        membership.read_whitelist(server_dir)


def test_read_ops_returns_entries(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.ops_path(server_dir).write_text(
        json.dumps(
            [
                {
                    "uuid": _NOTCH_UUID,
                    "name": "Notch",
                    "level": 4,
                    "bypassesPlayerLimit": False,
                }
            ]
        )
    )

    entries, _ = membership.read_ops(server_dir)

    assert entries == [
        {
            "uuid": _NOTCH_UUID,
            "name": "Notch",
            "level": 4,
            "bypassesPlayerLimit": False,
        }
    ]


# ---------------------------------------------------------------------------
# Write. vanilla shape, mtime guard, atomicity
# ---------------------------------------------------------------------------


def test_write_whitelist_uses_vanilla_shape_when_file_missing(tmp_path):
    server_dir = _server_dir(tmp_path)
    new_mtime_ns = membership.write_whitelist(
        server_dir, [{"uuid": _NOTCH_UUID, "name": "Notch"}], expected_mtime_ns=0
    )

    raw = membership.whitelist_path(server_dir).read_text(encoding="utf-8")
    assert raw == (
        '[\n'
        '  {\n'
        f'    "uuid": "{_NOTCH_UUID}",\n'
        '    "name": "Notch"\n'
        '  }\n'
        ']\n'
    )
    assert new_mtime_ns == membership.whitelist_path(server_dir).stat().st_mtime_ns


def test_write_whitelist_round_trip_preserves_insertion_order(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.write_whitelist(
        server_dir,
        [
            {"uuid": _HEROBRINE_UUID, "name": "Herobrine"},
            {"uuid": _NOTCH_UUID, "name": "Notch"},
        ],
        expected_mtime_ns=0,
    )

    entries, _ = membership.read_whitelist(server_dir)
    assert [e["uuid"] for e in entries] == [_HEROBRINE_UUID, _NOTCH_UUID]


def test_write_whitelist_raises_stale_when_file_changed_between_read_and_write(tmp_path):
    server_dir = _server_dir(tmp_path)
    path = membership.whitelist_path(server_dir)
    path.write_text(json.dumps([{"uuid": _NOTCH_UUID, "name": "Notch"}]))
    _, mtime_ns = membership.read_whitelist(server_dir)

    # Simulate a concurrent edit (slice 5 file editor) bumping the mtime.
    path.write_text(json.dumps([{"uuid": _HEROBRINE_UUID, "name": "Herobrine"}]))

    with pytest.raises(membership.StaleWriteError):
        membership.write_whitelist(
            server_dir,
            [{"uuid": _NOTCH_UUID, "name": "Notch"}],
            expected_mtime_ns=mtime_ns,
        )


def test_write_whitelist_with_zero_mtime_refuses_to_overwrite_existing_file(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.whitelist_path(server_dir).write_text("[]")

    with pytest.raises(membership.StaleWriteError):
        membership.write_whitelist(
            server_dir,
            [{"uuid": _NOTCH_UUID, "name": "Notch"}],
            expected_mtime_ns=0,
        )


# ---------------------------------------------------------------------------
# add/remove helpers
# ---------------------------------------------------------------------------


def test_add_whitelist_entry_appends_and_returns_true(tmp_path):
    server_dir = _server_dir(tmp_path)

    wrote = membership.add_whitelist_entry(server_dir, uuid=_NOTCH_UUID, name="Notch")

    assert wrote is True
    entries, _ = membership.read_whitelist(server_dir)
    assert entries == [{"uuid": _NOTCH_UUID, "name": "Notch"}]


def test_add_whitelist_entry_is_noop_when_uuid_already_present(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.add_whitelist_entry(server_dir, uuid=_NOTCH_UUID, name="Notch")
    before = membership.whitelist_path(server_dir).read_text()

    wrote = membership.add_whitelist_entry(server_dir, uuid=_NOTCH_UUID, name="Notch")

    assert wrote is False
    assert membership.whitelist_path(server_dir).read_text() == before


def test_remove_whitelist_entry_drops_only_matching_uuid(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.add_whitelist_entry(server_dir, uuid=_NOTCH_UUID, name="Notch")
    membership.add_whitelist_entry(server_dir, uuid=_HEROBRINE_UUID, name="Herobrine")

    wrote = membership.remove_whitelist_entry(server_dir, uuid=_NOTCH_UUID)

    assert wrote is True
    entries, _ = membership.read_whitelist(server_dir)
    assert entries == [{"uuid": _HEROBRINE_UUID, "name": "Herobrine"}]


def test_remove_whitelist_entry_is_noop_when_missing(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.add_whitelist_entry(server_dir, uuid=_NOTCH_UUID, name="Notch")
    before = membership.whitelist_path(server_dir).read_text()

    wrote = membership.remove_whitelist_entry(server_dir, uuid=_HEROBRINE_UUID)

    assert wrote is False
    assert membership.whitelist_path(server_dir).read_text() == before


def test_add_op_entry_writes_vanilla_default_level_and_bypasses(tmp_path):
    server_dir = _server_dir(tmp_path)

    membership.add_op_entry(server_dir, uuid=_NOTCH_UUID, name="Notch")

    entries, _ = membership.read_ops(server_dir)
    assert entries == [
        {
            "uuid": _NOTCH_UUID,
            "name": "Notch",
            "level": 4,
            "bypassesPlayerLimit": False,
        }
    ]


def test_add_op_entry_preserves_existing_non_default_levels_on_round_trip(tmp_path):
    server_dir = _server_dir(tmp_path)
    # Operator has hand-set Notch to level 2, bypassesPlayerLimit=true.
    membership.ops_path(server_dir).write_text(
        json.dumps(
            [
                {
                    "uuid": _NOTCH_UUID,
                    "name": "Notch",
                    "level": 2,
                    "bypassesPlayerLimit": True,
                }
            ]
        )
    )

    membership.add_op_entry(server_dir, uuid=_HEROBRINE_UUID, name="Herobrine")

    entries, _ = membership.read_ops(server_dir)
    assert entries[0] == {
        "uuid": _NOTCH_UUID,
        "name": "Notch",
        "level": 2,
        "bypassesPlayerLimit": True,
    }
    assert entries[1] == {
        "uuid": _HEROBRINE_UUID,
        "name": "Herobrine",
        "level": 4,
        "bypassesPlayerLimit": False,
    }


def test_remove_op_entry_drops_only_matching_uuid(tmp_path):
    server_dir = _server_dir(tmp_path)
    membership.add_op_entry(server_dir, uuid=_NOTCH_UUID, name="Notch")
    membership.add_op_entry(server_dir, uuid=_HEROBRINE_UUID, name="Herobrine")

    wrote = membership.remove_op_entry(server_dir, uuid=_NOTCH_UUID)

    assert wrote is True
    entries, _ = membership.read_ops(server_dir)
    assert [e["uuid"] for e in entries] == [_HEROBRINE_UUID]


# ---------------------------------------------------------------------------
# Cross-server scan
# ---------------------------------------------------------------------------


def test_scan_memberships_visits_every_server_and_emits_kind_records(tmp_path):
    atm = _server_dir(tmp_path, "atm10")
    moni = _server_dir(tmp_path, "monifactory")
    membership.add_whitelist_entry(atm, uuid=_NOTCH_UUID, name="Notch")
    membership.add_op_entry(atm, uuid=_NOTCH_UUID, name="Notch")
    membership.add_whitelist_entry(moni, uuid=_HEROBRINE_UUID, name="Herobrine")

    records = membership.scan_memberships(
        [
            {"name": "atm10", "dir": str(atm)},
            {"name": "monifactory", "dir": str(moni)},
        ]
    )

    assert records == [
        {"server_name": "atm10", "kind": "whitelist", "uuid": _NOTCH_UUID, "name": "Notch"},
        {"server_name": "atm10", "kind": "ops", "uuid": _NOTCH_UUID, "name": "Notch"},
        {
            "server_name": "monifactory",
            "kind": "whitelist",
            "uuid": _HEROBRINE_UUID,
            "name": "Herobrine",
        },
    ]


def test_scan_memberships_skips_missing_files_silently(tmp_path):
    server_dir = _server_dir(tmp_path)

    records = membership.scan_memberships([{"name": "atm10", "dir": str(server_dir)}])

    assert records == []


def test_scan_memberships_skips_malformed_files_silently(tmp_path):
    atm = _server_dir(tmp_path, "atm10")
    membership.whitelist_path(atm).write_text("{not json")
    membership.add_op_entry(atm, uuid=_NOTCH_UUID, name="Notch")

    records = membership.scan_memberships([{"name": "atm10", "dir": str(atm)}])

    # Whitelist failed to parse → only the ops record is emitted.
    assert records == [
        {"server_name": "atm10", "kind": "ops", "uuid": _NOTCH_UUID, "name": "Notch"},
    ]


# ---------------------------------------------------------------------------
# _read cache (whitelist.json / ops.json)
# ---------------------------------------------------------------------------


def test_read_whitelist_serves_cached_result_without_rereading(tmp_path, monkeypatch):
    from pathlib import Path as _Path

    server_dir = _server_dir(tmp_path)
    path = membership.whitelist_path(server_dir)
    path.write_text(json.dumps([{"uuid": _NOTCH_UUID, "name": "Notch"}]))

    membership.read_whitelist(server_dir)  # populate cache

    read_count = [0]
    _orig = _Path.read_text

    def counting_read_text(self, *a, **kw):
        read_count[0] += 1
        return _orig(self, *a, **kw)

    monkeypatch.setattr(_Path, "read_text", counting_read_text)

    entries, _ = membership.read_whitelist(server_dir)

    assert entries == [{"uuid": _NOTCH_UUID, "name": "Notch"}]
    assert read_count[0] == 0  # served from cache


def test_read_whitelist_cache_miss_on_mtime_change(tmp_path):
    server_dir = _server_dir(tmp_path)
    path = membership.whitelist_path(server_dir)
    path.write_text(json.dumps([{"uuid": _NOTCH_UUID, "name": "Notch"}]))

    membership.read_whitelist(server_dir)  # populate cache

    path.write_text(json.dumps([{"uuid": _HEROBRINE_UUID, "name": "Herobrine"}]))

    entries, _ = membership.read_whitelist(server_dir)
    assert entries == [{"uuid": _HEROBRINE_UUID, "name": "Herobrine"}]


def test_scan_memberships_skips_entries_missing_uuid_or_name(tmp_path):
    atm = _server_dir(tmp_path, "atm10")
    membership.whitelist_path(atm).write_text(
        json.dumps(
            [
                {"uuid": _NOTCH_UUID, "name": "Notch"},
                {"uuid": _HEROBRINE_UUID},  # missing name
                {"name": "Anonymous"},  # missing uuid
            ]
        )
    )

    records = membership.scan_memberships([{"name": "atm10", "dir": str(atm)}])

    assert records == [
        {"server_name": "atm10", "kind": "whitelist", "uuid": _NOTCH_UUID, "name": "Notch"},
    ]
