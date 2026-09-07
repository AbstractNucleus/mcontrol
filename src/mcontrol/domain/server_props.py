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

# path → (mtime_ns, parsed). Keyed by path so a rewrite evicts the old
# mtime instead of accumulating unbounded (path, mtime) entries.
_props_cache: dict[str, tuple[int, dict[str, str]]] = {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def read_properties(path: Path) -> dict[str, str]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return {}
    cache_key = str(path)
    cached = _props_cache.get(cache_key)
    if cached is not None and cached[0] == st.st_mtime_ns:
        return cached[1]
    out: dict[str, str] = {}
    for raw_line in _read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    _props_cache[cache_key] = (st.st_mtime_ns, out)
    return out
