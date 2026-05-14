"""Tests for `mcontrol.server_variables_form` — the shared validator
and the loader-from-jar inference helper (issue #123).

The shared validator is exercised end-to-end in `test_new_server.py` and
`test_migrate_routes.py`; this file pins the unit-level rules for the
new `loader` enum and the inference helper that mirrors the
supabase-server backfill.
"""

import pytest

from mcontrol.server_variables_form import (
    LOADERS,
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
        # Case-insensitive match — DB does ILIKE; we lower() the needle.
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
