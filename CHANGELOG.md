# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- File browser: read-only tree view and file viewer on server detail page
- File browser: CodeMirror editor with atomic save and mtime stale-write check
- File browser: multi-file upload with drag-drop and confirm-overwrite modal
- File browser: single-file download
- File browser: rename and move with destination-path picker modal
- File browser: delete and new-folder with type-name confirm for recursive delete
- File browser: search with Ctrl/Cmd+P shortcut, clear button, world-dir skip
- File browser: multi-select with WAI-ARIA keyboard navigation and tree selection modifiers
- File browser: bulk delete and move
- File browser: per-entry action popover menu (⋯) with destination refresh after move
- File browser: upload progress indicator and cancel
- File browser: syntax highlighting for JSON, YAML, TOML, XML
- File browser: reworked view-pane header (file size, mtime, info card, breadcrumb)
- File browser: Ctrl/Cmd+S keyboard shortcut for editor save
- File browser: cursor and scroll position preserved across saves
- Players page: DB-backed player roster with Mojang UUID lookup on add
- Players page: per-server whitelist and ops membership management
- Players page: Import button to ingest existing `whitelist.json` / `ops.json` into roster
- Players page: cascade-remove modal (roster-only vs. remove-from-all-servers)
- Server detail: Resources card showing CPU %, memory, and disk usage
- Server detail: Variables card and Health banner
- Server detail: Regenerate scripts with diff preview and mtime-stale-check before clobber
- Server detail: state-aware lifecycle buttons (Start / Stop / Restart) with accent on next action
- Server detail: legacy-server migration card (itzg → scaffold shape, one-way)
- Home page: real server list from discovery with empty state
- Home page: memory column showing per-server container memory usage
- New-server form and scaffolding endpoint (no-Dockerfile model; bind-mount only)
- Delete-server flow with tombstone rename and discovery dot-prefix filter
- Trash page: tombstone list, per-row Delete-now, and bulk Empty-trash (7-day default)
- Topnav: Servers / Players / Trash links with live tombstone count badge
- `POST /rescan`: operator-triggered fleet discovery without restarting the panel
- `GET /healthz`: deep per-subsystem probe (Supabase + Docker + bind-mount), 503 on degraded
- RCON console via SSE, password read from `server.properties`
- Live log stream via SSE
- Claude-flavoured theme with tri-state dark / light / system toggle persisted to `localStorage`
- GitHub Action for automated issue implementation via Claude Code

### Changed

- RCON password management moved to `server.properties` (operator-managed); panel no longer generates or stores it
- Scaffold model is now Dockerfile-free: `docker-compose.yml` references the upstream image directly; `start_server.sh` lives inside the bind-mounted `server/` directory
- Panel host-bind parameterised in `docker-compose.yml` via `HOST_BIND_IP` (defaults to `127.0.0.1` for local dev)
- TLS termination moved to the upstream reverse proxy; in-repo Caddy service removed
- Docker image references pinned to specific patch-level tags (no floating `:latest`)
- aiodocker client is now lifespan-scoped (constructed once at startup, closed at shutdown) and injected into routes via `Depends(get_docker)`; per-call construction removed from ~10 sites

### Removed

- Per-server `Dockerfile` and `entrypoint.sh` (superseded by no-Dockerfile scaffold model)
- `rcon_password` and `image_base` column references (columns are dormant; SQL drop is a separate `supabase-server` migration)
- `.env`-driven RCON password writing (`env_writer.py`, `passwords.py`)

### Fixed

- Discovery preserves operator-edited `container_name` and `dir` overrides on rescan
- Bulk delete and move now preserves file tree expansion state
- Saved indicator fades out after ~3 s instead of persisting indefinitely
- Save button disabled while a save POST is in flight
- Native `confirm()` replaced with HTMX modal on save-conflict Reload
- Backend error detail surfaced in file-browser action responses
- `/healthz` probe uses `docker.version()` (the `system.ping` method does not exist in aiodocker)
