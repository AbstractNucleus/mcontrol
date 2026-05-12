# Contributing

## Local dev setup

```bash
uv sync
cp .env.example .env   # fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SERVER_BASE_PATH
uv run uvicorn mcontrol.main:app --reload --port 8000
```

The app expects a reachable Supabase instance and Docker socket at runtime, but tests mock both out — you can run the full test suite without either.

## Dev loop

```bash
uv run pytest -v        # must pass
uv run ruff check .     # must be clean
```

Ruff fixes most style issues automatically:

```bash
uv run ruff check . --fix
```

## Adding a new route

1. Create `src/mcontrol/routes/<name>.py` with an `APIRouter`:

   ```python
   from fastapi import APIRouter, Request
   from fastapi.responses import HTMLResponse
   from mcontrol.templates import templates

   router = APIRouter()

   @router.get("/example")
   async def example(request: Request) -> HTMLResponse:
       return templates.TemplateResponse(request=request, name="example.html", context={})
   ```

2. Add the template at `src/mcontrol/templates/example.html`. Extend `base.html` and consume only semantic tokens from `tokens.css` (decision 032 — no inline colours or raw hex values).

3. Register the router in `src/mcontrol/main.py`:

   ```python
   from mcontrol.routes import example   # add to the existing imports
   # ...
   app.include_router(example.router)    # add in create_app()
   ```

4. Add tests (see below).

## Adding a new test

Tests live in `tests/test_<name>.py`. The shared `client` fixture in `conftest.py` gives an `httpx.AsyncClient` wired to the ASGI app. Tests are async by default (`asyncio_mode = "auto"` in `pyproject.toml`).

Stub collaborators with `monkeypatch` so tests never hit a real DB or Docker socket:

```python
async def test_example_renders(client, monkeypatch):
    from mcontrol import db

    monkeypatch.setattr(db, "list_servers", lambda: [{"name": "atm10", "state": "running"}])

    response = await client.get("/example")

    assert response.status_code == 200
    assert "atm10" in response.text
```

See `tests/test_home.py` or `tests/test_server_detail.py` for worked examples of the fixture pattern.

## Project conventions

- **Surgical changes only.** Touch what the issue requires; don't clean up adjacent code.
- **No inline styles.** Components consume `--token-name` variables; new colours go in the semantic layer of `src/mcontrol/static/tokens.css`.
- **Route modules are thin.** Business logic lives in domain modules (`db.py`, `discovery.py`, etc.); routes wire HTTP to those modules.
- **Architecture decisions** are recorded in `docs/decisions.md` — read relevant entries before touching the area they govern.
