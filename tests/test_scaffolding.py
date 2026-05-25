import os

import jinja2
import pytest

from mcontrol.domain import scaffolding

_VARS = {
    "memory_budget_gb": 8,
    "port": 25565,
    "server_jar": "paper-1.21.4.jar",
    "jvm_extra_args": "-XX:+UseG1GC",
}


def test_render_compose_substitutes_name_memory_and_port():
    rendered = scaffolding.render_compose("atm10", _VARS)
    assert "  atm10:" in rendered
    assert "container_name: atm10" in rendered
    assert "image: eclipse-temurin:21-jre" in rendered
    assert "mem_limit: 8g" in rendered
    assert '- "25565:25565"' in rendered
    # Bind mount + entrypoint stay verbatim.
    assert "./server:/data" in rendered
    assert 'command: ["./start_server.sh"]' in rendered


def test_render_start_script_derives_xmx_from_memory_budget():
    rendered = scaffolding.render_start_script(_VARS)
    # 8 GB budget − 2 GB headroom = -Xmx6g.
    assert "-Xmx6g" in rendered
    assert "-jar paper-1.21.4.jar" in rendered
    assert "-XX:+UseG1GC" in rendered
    assert rendered.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in rendered


def test_render_start_script_treats_jvm_extra_args_as_optional():
    minimal = {"memory_budget_gb": 8, "port": 25565, "server_jar": "paper.jar"}
    rendered = scaffolding.render_start_script(minimal)
    assert "-Xmx6g" in rendered
    assert "-jar paper.jar" in rendered
    # No extra args present in vars → none injected.
    assert "-XX" not in rendered


def test_render_compose_raises_on_missing_required_variable():
    incomplete = {"memory_budget_gb": 8, "server_jar": "x.jar"}  # no port
    with pytest.raises(KeyError):
        scaffolding.render_compose("atm10", incomplete)


def test_render_start_script_raises_on_missing_server_jar():
    incomplete = {"memory_budget_gb": 8}
    with pytest.raises(KeyError):
        scaffolding.render_start_script(incomplete)


def test_render_compose_raises_on_undefined_template_var(monkeypatch):
    """StrictUndefined is in force. a typo in the template would raise
    rather than silently inject an empty string. Verified by rendering
    against an explicitly stripped context."""
    template = scaffolding._env.from_string("{{ ghost }}")
    with pytest.raises(jinja2.UndefinedError):
        template.render()


def test_scaffold_writes_both_files_under_base_name(tmp_path):
    scaffolding.scaffold("atm10", _VARS, tmp_path)

    compose = tmp_path / "atm10" / "docker-compose.yml"
    start = tmp_path / "atm10" / "server" / "start_server.sh"
    eula = tmp_path / "atm10" / "server" / "eula.txt"
    assert compose.exists()
    assert start.exists()
    assert eula.exists()
    assert "container_name: atm10" in compose.read_text()
    assert "-Xmx6g" in start.read_text()
    assert eula.read_text() == "eula=true\n"


def test_scaffold_creates_intermediate_directories(tmp_path):
    """Calling scaffold against a base where <base>/<name>/server doesn't
    yet exist must create both levels. no pre-mkdir required."""
    scaffolding.scaffold("brand-new", _VARS, tmp_path)
    assert (tmp_path / "brand-new" / "server").is_dir()


@pytest.mark.skipif(os.name == "nt", reason="chmod exec bit is a no-op on Windows")
def test_scaffold_marks_start_script_executable(tmp_path):
    scaffolding.scaffold("atm10", _VARS, tmp_path)
    start = tmp_path / "atm10" / "server" / "start_server.sh"
    mode = start.stat().st_mode & 0o777
    assert mode & 0o100, f"start_server.sh should be executable; mode={oct(mode)}"


def test_scaffold_uses_file_writer_atomic_write_text(monkeypatch, tmp_path):
    """Both files go through file_writer.atomic_write_text so PR 4's
    regenerate flow inherits the same atomicity guarantee."""
    seen: list[tuple[str, str]] = []
    real = scaffolding.atomic_write_text

    def tracker(path, content):
        seen.append((str(path), content))
        return real(path, content)

    monkeypatch.setattr(scaffolding, "atomic_write_text", tracker)

    scaffolding.scaffold("atm10", _VARS, tmp_path)

    paths = [p for p, _ in seen]
    assert any(p.endswith("docker-compose.yml") for p in paths)
    assert any(p.endswith("start_server.sh") for p in paths)
    assert any(p.endswith("eula.txt") for p in paths)
    assert len(seen) == 3
