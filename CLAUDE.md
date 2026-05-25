# mcontrol

Web panel for managing a single-host fleet of Minecraft servers running in Docker. See [README.md](README.md) for the project overview and [CONTRIBUTING.md](CONTRIBUTING.md) for the dev loop.

## Stack at a glance

FastAPI + Jinja2 + HTMX backend, Supabase (Postgres + service-role) for the servers/players/tombstones tables, `aiodocker` against `/var/run/docker.sock`, CodeMirror (vendored) for the in-app file editor. Python 3.12, [uv](https://docs.astral.sh/uv/) for deps.

## Project conventions

- **Surgical changes only.** Touch what the task requires; don't clean up adjacent code, comments, or formatting.
- **Route modules are thin.** HTTP wiring lives in `src/mcontrol/routes/`; business logic in `src/mcontrol/services/` and `src/mcontrol/domain/`; storage adapters in `src/mcontrol/infra/`.
- **No inline styles.** Components consume `--token-name` variables from `src/mcontrol/static/tokens.css`. New colors go in the semantic layer of `tokens.css`, never as raw hex in templates.
- **Tests mock collaborators.** Real Supabase and Docker socket are not available in CI. Use `monkeypatch` to stub `db.*` and the Docker client. See `tests/conftest.py` and `tests/test_home.py` for the pattern.
- **Comments are sparse.** Default to no comments. Add one only when the *why* is non-obvious: a hidden constraint, a workaround, a surprising invariant.

## Dev loop

```bash
uv run pytest -v        # must pass
uv run ruff check .     # must be clean
```
