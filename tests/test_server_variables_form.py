"""Tests for `mcontrol.domain.server_variables_form`: the shared validator
and the loader-from-jar inference helper (issue #123).

The shared validator is exercised end-to-end in `test_new_server.py` and
`test_migrate_routes.py`; this file pins the unit-level rules for the
new `loader` enum and the inference helper that mirrors the
supabase-server backfill.
"""

import pytest

from mcontrol.domain.server_variables_form import (
    LOADERS,
    MEMORY_MIN_GB,
    build_variables,
    check_port_collision,
    infer_loader_from_jar,
    validate,
)

# ---- LOADERS contract -----------------------------------------------


def test_loaders_tuple_matches_supabase_enum():
    """The five values are the supabase-server#8 enum, no more no less."""
    assert set(LOADERS) == {"vanilla", "forge", "fabric", "paper", "quilt"}


# ---- validate(loader=...) -------------------------------------------


def _base_form(**overrides) -> dict:
    body = {
        "memory_budget_gb": 8,
        "port": 25575,
        "server_jar": "paper-1.21.4.jar",
    }
    body.update(overrides)
    return body


def test_validate_accepts_each_loader_enum_value():
    for loader in LOADERS:
        errors = validate(_base_form(loader=loader))
        assert "loader" not in errors, f"{loader} should be accepted"


def test_validate_rejects_unknown_loader_value():
    errors = validate(_base_form(loader="neoforge"))
    assert "loader" in errors
    assert "Must be one of" in errors["loader"]


def test_validate_skips_loader_check_when_field_absent():
    """migrate.py and variables.py don't currently submit a loader; the
    validator must stay backward-compatible for those callers."""
    errors = validate(_base_form())
    assert "loader" not in errors


# ---- infer_loader_from_jar -----------------------------------------


@pytest.mark.parametrize(
    "jar,expected",
    [
        # Direct hits, mirroring the supabase-server backfill order.
        ("forge-1.20.1-47.2.0.jar", "forge"),
        ("fabric-server-launch.jar", "fabric"),
        ("paper-1.21.4.jar", "paper"),
        ("quilt-server-launch.jar", "quilt"),
        # Vanilla fallback when nothing matches.
        ("server.jar", "vanilla"),
        ("minecraft_server.1.21.4.jar", "vanilla"),
        ("", "vanilla"),
        # Case-insensitive match. DB does ILIKE; we lower() the needle.
        ("FORGE-1.20.1.jar", "forge"),
        ("Paper-1.21.4.JAR", "paper"),
    ],
)
def test_infer_loader_from_jar_known_patterns(jar, expected):
    assert infer_loader_from_jar(jar) == expected


def test_infer_loader_from_jar_precedence_forge_before_fabric():
    """Order is forge → fabric → paper → quilt → vanilla, first match
    wins. A pathological filename containing both substrings resolves to
    `forge` because it comes earlier in the order."""
    assert infer_loader_from_jar("forge-fabric-shim.jar") == "forge"


def test_infer_loader_from_jar_precedence_paper_before_quilt():
    assert infer_loader_from_jar("paper-quilt-bridge.jar") == "paper"


def test_validate_rejects_budget_that_leaves_zero_heap():
    errors = validate(_base_form(memory_budget_gb=MEMORY_MIN_GB - 1))
    assert "memory_budget_gb" in errors
    assert str(MEMORY_MIN_GB) in errors["memory_budget_gb"]


def test_validate_accepts_minimum_budget():
    errors = validate(_base_form(memory_budget_gb=MEMORY_MIN_GB))
    assert "memory_budget_gb" not in errors


def test_validate_rejects_unknown_java_version():
    errors = validate(_base_form(java_version=16))
    assert "java_version" in errors


def test_validate_accepts_each_java_version():
    from mcontrol.domain.scaffolding import JAVA_VERSIONS

    for version in JAVA_VERSIONS:
        errors = validate(_base_form(java_version=version))
        assert "java_version" not in errors, version


def test_validate_skips_java_version_when_field_absent():
    errors = validate(_base_form())
    assert "java_version" not in errors


def test_build_variables_defaults_java_version_to_21():
    built = build_variables(_base_form())
    assert built["java_version"] == 21


def test_build_variables_stores_explicit_java_version():
    built = build_variables(_base_form(java_version=17))
    assert built["java_version"] == 17


async def test_check_port_collision_reads_legacy_compose_port(tmp_path, monkeypatch):
    server_dir = tmp_path / "loading"
    server_dir.mkdir()
    (server_dir / "docker-compose.yml").write_text(
        "services:\n"
        "  loading:\n"
        "    ports:\n"
        '      - "25567:25565"\n',
        encoding="utf-8",
    )
    rows = [
        {
            "name": "loading",
            "dir": str(server_dir),
            "variables": {},
        }
    ]
    from mcontrol.infra import db

    monkeypatch.setattr(db, "list_servers", lambda: rows)

    err = await check_port_collision(None, 25567)
    assert err is not None
    assert "loading" in err
    assert "docker-compose.yml" in err


async def test_check_port_collision_prefers_variables_port_over_compose(
    tmp_path, monkeypatch
):
    server_dir = tmp_path / "atm10"
    server_dir.mkdir()
    (server_dir / "docker-compose.yml").write_text(
        'ports:\n  - "25567:25565"\n', encoding="utf-8"
    )
    from mcontrol.infra import db

    monkeypatch.setattr(
        db,
        "list_servers",
        lambda: [
            {
                "name": "atm10",
                "dir": str(server_dir),
                "variables": {"port": 25590},
            }
        ],
    )

    assert await check_port_collision(None, 25567) is None
    err = await check_port_collision(None, 25590)
    assert err is not None
    assert "atm10" in err
    assert "docker-compose.yml" not in err
