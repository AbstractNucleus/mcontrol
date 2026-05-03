# Slice 5 — File browser, editor, uploads

> Lean plan: contract + PR order. Each PR ships an end-to-end working vertical slice; merge in order. The code is the source of truth — this doc is the napkin sketch.

## Goal

Replace SSH-based editing of per-server data directories. The operator opens a server in mcontrol, navigates the tree, edits configs in-browser, drops in jars/mods, and deletes / renames / moves / downloads as needed.

## Scope contract

| | |
|---|---|
| Browser root | Full `<dir>/`. Scaffold files (`docker-compose.yml`, `Dockerfile`, `entrypoint.sh`, `start_server.sh`, `.env`) listed and editable. Plaintext `.env`. |
| Operations | view, edit, upload, new folder, delete (recursive w/ confirm), rename, move, download |
| Layout | Split pane: tree left, editor / info-card right |
| Tree | Expandable hierarchy, lazy-load on expand, hidden files shown, symlinks rendered but not followed, special files (sock/fifo/dev) skipped |
| Editor | CodeMirror 6 via CDN, with custom modes for `.properties` / `.snbt` |
| Save | Explicit Save button, atomic write (`tempfile.mkstemp` + `os.replace`), mtime stale-write check (refuse with `[Reload] [Overwrite] [Cancel]`) |
| Binary / large text | Info card with Download / Rename / Move / Delete (no editor); binary detected via 8 KB null-byte sniff; text > 5 MB → info card |
| Uploads | Drag-drop + button fallback, multi-file, no size cap, refuse + confirm-overwrite modal on conflict |
| File ownership | Root everywhere — same as slice-4 `env_writer`, no `chown` step |
| Search | Recursive filename search (Cmd-P-style); no full-text grep |
| Selection | Click / Shift+click / Cmd+click + checkbox column; bulk **Delete** and **Move** only (no bulk rename / download) |

## PR sequence

Each PR is shippable and useful by itself. Merge before starting the next — the discipline is what makes this work.

| # | Ships | Notes |
|---|---|---|
| 1 | Tree nav + view-only | Server-rendered HTMX, click-to-expand, click-file-to-view. No editor yet, no JS state. Proves path-safety / lazy-load / `world/region/` performance in production before any write code lands. |
| 2 | CodeMirror + save | Editor on top of #1's browser. Atomic write + mtime stale-write check. The riskiest write path ships alone. |
| 3 | Uploads | Drag-drop + button, multi-file, conflict modal. Independent of #2; reviewable on its own. |
| 4 | Delete + new folder | Destructive ops; type-name confirmation for recursive delete. Easy to revert if the confirmation UX is wrong. |
| 5 | Rename + move | Single-item only. Move uses a destination-path picker modal (no in-tree drag-drop). |
| 6 | Download | Single file via `FileResponse`. Trivial; could slip into any earlier PR if convenient. |
| 7 | Search + multi-select + bulk Delete / Move | ~80 lines of vanilla JS for selection state. Most easily cuttable if a deadline tightens. |

## Path-safety contract (every endpoint that takes a path)

1. Resolve: `(Path(<dir>) / operator_path).resolve()`.
2. Sub-path check: resolved path must be inside `Path(<dir>).resolve()`. Reject with HTTP 400 otherwise.
3. Symlinks: `Path.is_symlink()` at every step of traversal; refuse to follow on read/edit/download.
4. Special files: `stat.S_ISBLK` / `S_ISCHR` / `S_ISFIFO` / `S_ISSOCK` skipped from listings and rejected at endpoints.

## Deferred / out-of-scope

- **Full-text grep across files.** Defer; possibly its own slice.
- **Bulk rename, bulk download.** No obvious semantics.
- **Drag-drop move across folders in the tree.** Replaced by single-item Move modal.
- **Auto-save in the editor.** Explicit Save only.
- **Multi-user concurrent-editing semantics beyond the mtime check.** Single-user posture per decision 011.
- **Hex view for binary files.** Out of scope.
- **Scaffold-regenerate "merge vs clobber" contract** (decision 012's regen flow). This slice ships full-edit on scaffold files; **slice 6 must define a regenerate-vs-operator-edits policy when it lands** — flag in the slice 6 grilling.

## Deployment notes

- **aserver-nginx**: the `mcontrol.noelkleen.com` vhost defaults `client_max_body_size` to **1 MB**. Bump it (recommend `client_max_body_size 0;` to honour the no-cap policy) before PR 3 lands, or every meaningful upload silently 413s.

## Decisions register impact

None. Slice 5 is implementation under existing decisions:
- **012** (scaffold + file/upload UI) — this is the slice 012 referred to.
- **016** (FastAPI + Jinja + HTMX) — CodeMirror loaded via CDN, no bundler.
- **008** (bind mounts) — `<dir>/` is the bind-mount root.
- **010** (RCON `.env`) — slice-4 pattern preserved (atomic write, root ownership).

The "root everywhere" file-ownership pattern is consistent with slice 4 and doesn't warrant a new ADR; if a future slice adds a non-root MC container, that becomes the trigger for a new decision entry.
