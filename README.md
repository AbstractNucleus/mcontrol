# Dash

A personal dashboard workspace. **mcontrol** is the first dashboard, for managing Minecraft servers on a single Docker host.

The sidebar selects dashboards. Inside mcontrol, Servers and Players have their own navigation. Each server has a configurable workspace for Console, Players, and Files, plus Settings and a server switcher.

The Python package, image, and deployment directory are still named `mcontrol`. The move to `dash.noelkleen.com` is planned separately.

## mcontrol features

- Start, stop, restart, create, discover, and delete Minecraft servers.
- Live CPU, memory, uptime, disk usage, and connection status.
- Console logs and RCON commands with search and filtering.
- File editing, upload, download, search, move, bulk actions, and ZIP/RAR extraction.
- Player roster, whitelist, and operator management.
- Shared panel layouts with resizing, rearranging, focus mode, and Save/Cancel.
- Server configuration, generated startup scripts, and legacy-server migration.

Each server is a directory containing `docker-compose.yml` and a bind-mounted `server/` folder. The dashboard works with those files directly. Supabase stores server metadata and the player roster; deleted servers stay on disk as `.deleted-<name>-<timestamp>/` directories.

This is a single-user workspace with no built-in authentication or roles. Put it behind your own access control.

## Local preview

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run uvicorn dev_mock:app --reload --port 8000
```

Open http://localhost:8000. The preview uses fake Docker and database adapters and seeds sample server files under `.localdev/minecraft/`. It does not manage real servers. Set `MCONTROL_MOCK_BASE` to use another preview directory.

For real services, copy `.env.example` to `.env`, configure Supabase and the Minecraft server directory, then run:

```sh
uv run uvicorn mcontrol.main:app --reload --port 8000
```

The production runtime also needs Docker access. See [deployment](deploy/README.md) for the container setup.

## Server files

For a modpack with a Linux start script, enter its `.sh` filename in **Custom start script**, then upload the extracted pack into the server's `server/` folder. The path is relative to that folder. Keep the generated `start_server.sh`; rename the pack's script if it uses that name. Windows `.bat` scripts cannot run in the Linux container.

The selected Java version and container memory limit still apply. Configure heap and JVM flags in the pack's own script, leaving memory for the rest of the container. The form's JVM extra arguments apply to JAR startup. Clear the custom script in Settings to return to JAR startup.

ZIP and RAR extraction keep the original archive and never overwrite existing files. Password-protected and multipart archives are unsupported. Operations are limited to 20 GiB, 100,000 entries, and ten minutes, and need temporary disk space. ZIP creation is built in; RAR creation requires a separately installed and licensed `rar` writer. The image includes only the UnRAR reader.

Deleting a server preserves its files in a `.deleted-<name>-<timestamp>/` directory. Restore it manually by renaming the directory back and rescanning, or remove that directory manually when the files are no longer needed.

## Development and deployment

- [CONTRIBUTING.md](CONTRIBUTING.md): project structure, checks, and adding dashboards.
- [deploy/README.md](deploy/README.md): image publishing, host configuration, verification, and rollback.
