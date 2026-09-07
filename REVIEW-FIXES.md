# mcontrol review fixes

A wrap-up of the console, start, files, and UI work. Nothing here has been deployed to the live panel yet.

## What was broken

- **Console.** Typing a command often killed the RCON connection. A second tab was refused. Errors were silent. Opening a stopped server spammed the panel log.
- **New servers could not be started from the panel.** Start said “no such container” instead of creating one. When a container did exist, Start could sit on “starting” forever because the panel probed the wrong host (`127.0.0.1` inside Docker).
- **A few other things people hit.** Memory of 2 GB produced `-Xmx0g` (the server never boots). The Variables card was missing from the server page. After delete or emptying Trash, Home/Trash showed no confirmation. Missing containers were labelled “daemon unreachable”. Bad folder names (`bad?`) returned 500. After rename, Save could write the old path. The Home “running” count included dead rows like `atm10-030826`.

## What we changed

**Console**
- Commands stay connected. Two tabs share one connection and both see output.
- Failures show as `[error]` lines. A stopped server retries quietly instead of crashing the stream.

**Starting servers**
- Start runs `docker compose up` when the container is missing. Recreate / Apply compose is on the detail page.
- The panel probes the Docker gateway (or `PROBE_HOST`) so Start can become “running”.
- Minimum memory is 3 GB. New servers pick Java 17 / 21 / 25 (default 21) and get RCON turned on.

**Files**
- Rename/move updates the editor path so Save writes the new file.
- Invalid names (including `bad?`) return 400, not 500.
- New files inherit the folder owner where the OS allows it.

**New-server form**
- Java version picker, 3 GB minimum, reserved name `new` blocked, port checks see live Docker and other compose files.

**Look and feel**
- Start/Stop/Restart refresh the pill, buttons, sidebar dot, and Home running count.
- Files editor is usable at laptop widths. Sidebar and Home behave on a phone.
- Delete and Trash purge show a short toast on the page you land on.
- 404 pages still list servers in the sidebar. Missing `/static/*` files stay plain text.
- Memory bar width uses a CSS variable (same look).

## What we tested

- Unit tests: **821 passed, 21 skipped** (Windows POSIX-only skips). `ruff` clean.
- Live on the **dev** panel at `http://100.124.22.82:8004` (not production `:8003`):
  - Health check OK. Home listed `mctest1` / `mctest2`. Running count was **2** (`loading` + `mctest1`); `atm10-030826` did not inflate it.
  - `mctest1`: Variables + Regenerate present. Console `list` → 204; two streams both got “0 of 20 players”. Stop → `exited`. Start → `running` (not stuck). Restart → `running`.
  - `mctest2`: memory 3 GB + regenerate (fixes `-Xmx0g`). Start created the container with no SSH. No jar, so it sat on “starting” / restart-looped — expected. Stop then delete worked.
  - Files: rename scratch → Save wrote the new path; `mkdir bad?` → 400.
  - Delete `mctest2` → toast “Deleted mctest2 (moved to Trash).” Trash Delete now → “Purged mctest2.”
  - Missing container caption: “container not found”.
  - `loading`: GET only. Left running.
- Probe host in the running panel: `172.17.0.1` (Docker gateway).

## What we cleaned up

- Stopped and deleted `mctest1` / `mctest2` (and their Trash entries).
- Removed leftover `mctest1_default` / `mctest2_default` networks.
- Unplugged production `mcontrol-app-1` from `mctest1_default` and the stale `atm10-030826_default`. Left it on `loading_default` and `mcontrol_default`.
- Removed the scratch `mcontrol-dev` container and image, `/home/abstract/scratch/mcontrol-dev`, `/tmp/mcontrol-dev.tgz`, `/tmp/rcon_probe.py`.
- Did not touch `.localdev` on this machine.

## What we did not change

- **Production panel** (`mcontrol-app-1` on `:8003`) is still the old image until you deploy.
- **`loading`** was not stopped, edited, or whitelist-changed.
- No git commit. No production `docker compose` in `/home/abstract/deploy/mcontrol`.
