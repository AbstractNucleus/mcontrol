from pathlib import Path

from mcontrol import env_writer


def test_write_rcon_password_creates_env_when_absent(tmp_path):
    env_path = tmp_path / ".env"

    env_writer.write_rcon_password(env_path, "hunter2")

    assert env_path.read_text() == "RCON_PASSWORD=hunter2\n"


def test_write_rcon_password_overwrites_existing_line(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=value\nRCON_PASSWORD=oldpwd\nKEEP_ME=yes\n")

    env_writer.write_rcon_password(env_path, "newpwd")

    text = env_path.read_text()
    assert "OTHER=value" in text
    assert "KEEP_ME=yes" in text
    assert "RCON_PASSWORD=newpwd" in text
    assert "RCON_PASSWORD=oldpwd" not in text


def test_write_rcon_password_appends_when_var_absent(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=value\n")

    env_writer.write_rcon_password(env_path, "hunter2")

    text = env_path.read_text()
    assert text.endswith("RCON_PASSWORD=hunter2\n")
    assert "OTHER=value" in text


def test_write_rcon_password_creates_parent_directories(tmp_path):
    env_path = tmp_path / "deep" / "nested" / "dir" / ".env"

    env_writer.write_rcon_password(env_path, "hunter2")

    assert env_path.exists()


def test_write_rcon_password_uses_atomic_replace(tmp_path, monkeypatch):
    """Ensures the writer goes through a temp-file + os.replace dance,
    so a partial write can never leave a half-written .env."""
    env_path = tmp_path / ".env"
    env_path.write_text("RCON_PASSWORD=oldpwd\n")

    seen_paths: list[Path] = []
    real_replace = Path.replace

    def tracking_replace(self, target):
        seen_paths.append(self)
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", tracking_replace)

    env_writer.write_rcon_password(env_path, "newpwd")

    assert any(p != env_path for p in seen_paths), "writer should replace from a temp path"
    assert env_path.read_text() == "RCON_PASSWORD=newpwd\n"


def test_read_rcon_password_returns_none_when_file_absent(tmp_path):
    assert env_writer.read_rcon_password(tmp_path / "nope") is None


def test_read_rcon_password_returns_value_when_present(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=value\nRCON_PASSWORD=hunter2\nKEEP=yes\n")

    assert env_writer.read_rcon_password(env_path) == "hunter2"


def test_read_rcon_password_returns_none_when_var_absent(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=value\n")

    assert env_writer.read_rcon_password(env_path) is None
