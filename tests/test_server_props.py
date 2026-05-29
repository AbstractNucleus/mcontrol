from pathlib import Path

from mcontrol.domain import server_props


def test_read_properties_returns_empty_when_file_missing(tmp_path):
    assert server_props.read_properties(tmp_path / "missing.properties") == {}


def test_read_properties_parses_simple_kvp(tmp_path):
    path = tmp_path / "server.properties"
    path.write_text("port=25565\nmotd=hello\n")

    assert server_props.read_properties(path) == {"port": "25565", "motd": "hello"}


def test_read_properties_skips_blank_lines_and_comments(tmp_path):
    path = tmp_path / "server.properties"
    path.write_text(
        "\n"
        "# a comment\n"
        "enable-rcon=true\n"
        "\n"
        "rcon.password=secret\n"
        "# trailing comment\n"
    )

    assert server_props.read_properties(path) == {
        "enable-rcon": "true",
        "rcon.password": "secret",
    }


def test_read_properties_strips_whitespace_around_key_and_value(tmp_path):
    path = tmp_path / "server.properties"
    path.write_text("  motd  =  hello world  \n")

    assert server_props.read_properties(path) == {"motd": "hello world"}


def test_read_properties_last_write_wins_on_duplicate_keys(tmp_path):
    path = tmp_path / "server.properties"
    path.write_text("port=25565\nport=25577\n")

    assert server_props.read_properties(path) == {"port": "25577"}


def test_read_properties_skips_lines_without_equals(tmp_path):
    path = tmp_path / "server.properties"
    path.write_text("not a key value\nport=25565\n")

    assert server_props.read_properties(path) == {"port": "25565"}


def test_read_properties_handles_value_containing_equals(tmp_path):
    path = tmp_path / "server.properties"
    path.write_text("rcon.password=a=b=c\n")

    assert server_props.read_properties(path) == {"rcon.password": "a=b=c"}


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_read_properties_serves_cached_result_without_rereading(tmp_path, monkeypatch):
    path = tmp_path / "server.properties"
    path.write_text("port=25565\n")

    server_props.read_properties(path)  # populate cache

    read_count = [0]
    _orig = Path.read_text

    def counting_read_text(self, *a, **kw):
        read_count[0] += 1
        return _orig(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    result = server_props.read_properties(path)

    assert result == {"port": "25565"}
    assert read_count[0] == 0  # served from cache


def test_read_properties_cache_miss_on_mtime_change(tmp_path):
    path = tmp_path / "server.properties"
    path.write_text("port=25565\n")

    server_props.read_properties(path)  # populate cache

    path.write_text("port=25577\n")

    assert server_props.read_properties(path) == {"port": "25577"}
