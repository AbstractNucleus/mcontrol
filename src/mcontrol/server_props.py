"""Tiny parser for Minecraft ``server.properties`` files.

``server.properties`` is operator-managed; mcontrol only ever *reads*
it. This helper centralises the parse so the slice 4 RCON handshake
(``enable-rcon``, ``rcon.password``) and the slice 7 central Players
page (``white-list`` indicator) share one parser instead of growing two.

The format is the canonical Minecraft / ``java.util.Properties`` shape:

  - Lines that are blank, start with ``#``, or have no ``=`` are skipped.
  - Each remaining line is split on the first ``=``; key + value are
    each ``.strip()``-ed.
  - Last-write-wins on duplicate keys.

Missing file → ``{}``. Read errors propagate.
"""

from pathlib import Path

_props_cache: dict[tuple[str, int], dict[str, str]] = {}


def read_properties(path: Path) -> dict[str, str]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return {}
    cache_key = (str(path), st.st_mtime_ns)
    if cache_key in _props_cache:
        return _props_cache[cache_key]
    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    _props_cache[cache_key] = out
    return out
