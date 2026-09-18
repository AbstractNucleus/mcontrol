# mcontrol / Dash — codebase and UI/UX review

Date: 2026-09-17. Reviewed at commit `78003d9` (main, clean working tree).

Follow-up: 2026-09-18, same commit. Added §9 and corrected source/coverage claims below. The follow-up used source inspection, temporary-directory reproductions, and focused tests; it did not repeat the original live-browser walkthrough or full-suite run.

Method: read every file under `src/mcontrol/routes`, `services`, `domain`, `infra`, all templates, all hand-written CSS and JS; ran the full test suite and lint; drove the live app (desktop and mobile viewports) through the mock backend — fleet view, console, file editor, players, new-server wizard, settings, and the delete-server confirmation flow. Every finding below marked "confirmed" was verified directly against source or in the running app, not just asserted by a sub-review pass.

## Overall impression

This is an unusually disciplined codebase for a solo project. Tests pass cleanly (933 passed, 27 skipped, 0 failed), `ruff check` is clean, there are no `TODO`/`FIXME` markers anywhere, and the file-safety and archive-extraction code is genuinely defense-in-depth (symlink rejection, decompression-bomb guards, atomic writes with rollback). The UI is calmer and better-guarded than most personal tools: destructive actions require typing the server name to confirm, buttons disable themselves with an explanatory title when an action isn't safe ("Stop the server before deleting"), and the empty/error states are actionable rather than dead ends.

The weak spots are consistency, not sloppiness: a shell-safety rule that was built once (for legacy migration) and never carried over to its sibling create/edit forms; a CSS split across nine `app.*.css` files that has accumulated dead and conflicting rules from incomplete refactors; and a "domain" layer that in practice does real database/Docker/filesystem I/O despite the layer names. None of this is alarming for a single-user tool behind your own access control, but it's worth tightening before the surface area grows.

---

## 1. Security

### 1.1 `jvm_extra_args` / `server_jar` reach the launch script unvalidated on create and edit (confirmed) — Medium-High

`domain/scaffolding/templates/start_server.sh.j2:3` interpolates both fields into the container's entrypoint:

```
exec java -Xmx{{ xmx_gb }}g {{ jvm_extra_args }} -jar "{{ server_jar }}" nogui
```

`jvm_extra_args` is **unquoted** — `;`, `` ` ``, `$()`, `|`, `&` all execute. `server_jar` is double-quoted, so a stray `"` still breaks out. [domain/server_variables_form.py](src/mcontrol/domain/server_variables_form.py:55)'s `validate()` — the validator shared by [routes/new_server.py](src/mcontrol/routes/new_server.py) (create) and [routes/variables.py](src/mcontrol/routes/variables.py) (edit) — checks memory, port, and emptiness, but never checks either field for shell metacharacters.

The fix already exists, just not here: [domain/migration.py:27-28](src/mcontrol/domain/migration.py:27) defines `_SAFE_JAR_RE` and `_UNSAFE_JVM_CHARS_RE`, enforced by `_validate_requested_launch` — but that's called only from the legacy-migration flow (`migration.py:635`), not from create or edit. No test drives either form with shell metacharacters, which is exactly the test that would have caught the gap.

**Why this is Medium-High rather than Critical**: there's no auth boundary to cross — the README states this is a single-user tool with "no built-in authentication or roles," meant to sit behind the operator's own access control. Anyone who can reach these forms already has a legitimate path to the same shell via the Files editor (they can already hand-edit `docker-compose.yml`/`start_server.sh` directly). So this isn't a privilege escalation so much as an easy-to-hit foot-gun: a copy-pasted JVM flag with a stray `;` or backtick silently does something unintended instead of failing validation. Still worth fixing for consistency with the migration path's own established pattern, and because "it's already exploitable another way" is a weak reason not to close an obvious hole.

**Fix**: reuse `_SAFE_JAR_RE`/`_UNSAFE_JVM_CHARS_RE` (or move them to a shared location) inside `server_variables_form.validate()` so create and edit get the same protection migration already has.

### 1.2 Inconsistent locking across the Files routes — Medium

[routes/files/archive.py](src/mcontrol/routes/files/archive.py:23) uses `get_locked_server_or_404` (the fleet mutation lock), matching `migrate.py`, `regenerate.py`, `variables.py`, `bindings.py`, `delete_server.py`, and `lifecycle.py`. But `routes/files/mutate.py`, `write.py`, `tree.py`, `search.py`, and `view.py` all use the unlocked `get_server_or_404`. Deleting/renaming/uploading a file through the Files panel is not serialized against a concurrent Migrate/Regenerate operation rewriting `docker-compose.yml` or `start_server.sh`, or against an in-flight archive extraction on the same tree. Variables edits update database JSONB only; Regenerate applies those values to disk. Prioritize locking mutations and their conflict checks; read-only tree/search/view routes need a separate consistency decision, rather than automatically holding the fleet-wide write lock.

### 1.3 Silent broad excepts hide real bugs as "Docker unreachable" — Low-Medium

[infra/resources.py:57,62,72](src/mcontrol/infra/resources.py:57) (`_read_container_stats`) and [infra/docker_client.py:86](src/mcontrol/infra/docker_client.py:86) catch bare `Exception` and return a generic unreachable/empty result with **no logging at all** — `resources.py` doesn't even import `logger`. A parsing bug in aiodocker's stats payload is indistinguishable from a genuinely down daemon, with no trail to diagnose it. Same pattern, lower stakes, in [routes/migrate.py:189-191](src/mcontrol/routes/migrate.py:189).

### 1.4 What's already solid

- `infra/file_safety.py`, `services/file_archive.py`, `infra/file_writer.py`: symlink refusal at every path component, `..`/NUL rejection, special-file exclusion, declared-vs-actual size checks on zip/rar members (decompression-bomb guard), member/byte/time caps, staged-extraction-then-publish with rollback, `O_NOFOLLOW` on compress sources, Windows-reserved-name and ADS checks. No path-traversal or archive-extraction issues found.
- `infra/healthz.py:34-41` deliberately sanitizes exception text so `SUPABASE_SERVICE_ROLE_KEY` can't leak into a health-check response.
- All RAR/compose subprocess calls use argument lists (`shell=False`) — no shell-injection surface there.
- `.env` is correctly gitignored and untracked; no secrets found committed.
- No CSRF token exists, but there's also no session/auth cookie to forge — the trust boundary is "who can reach the host," matching the documented deployment model (reverse proxy in front).

---

## 2. Backend architecture

The module names suggest a separation between routes, services, domain rules, and infrastructure. The current `CONTRIBUTING.md` requires thin handlers and small behavior interfaces, but does **not** specify the strict `routes → services → domain → infra` dependency direction or a pure domain layer. Treat the following as design observations, not violations of a documented purity rule:

- **Layering inversion**: [infra/server_rcon.py:113](src/mcontrol/infra/server_rcon.py:113) (`_run_via_console`) imports `mcontrol.routes.console` and calls into it — infra reaching *up* into routes, coupling the adapter to the HTTP layer. It's a lazy import specifically to dodge a circular dependency (`routes/console.py` imports `infra/server_rcon` at module scope), which is itself a sign the RCON connection-sharing logic is split across the wrong layers.
- **"Domain" doing real I/O**: `domain/discovery.py` calls `db`/`db_async`/`docker_client` directly; `domain/server_variables_form.py` awaits `infra.db_async.list_servers()` and does a blocking `socket.create_connection` inside `check_port_bound` (the create route correctly offloads this with `asyncio.to_thread`); `domain/health.py` imports `infra.server_rcon` for a process-global password cache; `migration.py`, `membership.py`, and `scaffolding/__init__.py` all call `infra.file_writer.atomic_write_text`. This is a repeated pattern, not a one-off — worth a naming/placement pass if "domain = pure rules" is meant to hold going forward.
- **Routes that aren't thin**: `routes/migrate.py::run_migration` and `routes/delete_server.py::post` embed multi-step Docker-state reconciliation directly in the handler; `routes/new_server.py::new_submit` inlines the full validate/collision/port-probe orchestration; `routes/console.py` (490 lines, the largest route file) holds process-lifetime state — module-level dicts for connections, subscribers, and locks — that reads more like a service than an HTTP handler.
- **Duplicated guard boilerplate**: the identical `try: ensure_no_pending_migration(...) / except migration.MigrationError: raise HTTPException(409, ...)` block is copy-pasted in `bindings.py`, `regenerate.py`, `delete_server.py`, and `variables.py`. A shared FastAPI dependency would collapse this to one place.
- **Unbounded dict growth**: `infra/docker_client.py`'s `_network_attach_locks` and `routes/console.py`'s `_connection_locks`/`_submit_locks`/`_connecting` are keyed by server name and never evicted. Harmless at this app's small, bounded fleet size, but worth a note if the fleet ever grows unbounded or servers churn heavily.

None of this is urgent — these are design tradeoffs, not demonstrated breakage — but the routes/files/*.py split (six files sharing `_listing.py` and common validators) shows what the rest of the routes layer could look like if it got the same treatment.

---

## 3. Test coverage

`uv run pytest -q` → **933 passed, 27 skipped** (original reported result; skip reasons were not recorded, so this cannot be attributed solely to POSIX checks), **0 failed**. `uv run ruff check .` → clean. This is a strong baseline, and the browser suite (`tests/browser/`, ~1,700 lines across 8 files) genuinely exercises keyboard/focus/ARIA behavior, not just happy-path clicking.

**Coverage qualification:** browser modules are opt-in through `MCONTROL_BROWSER_TESTS=1` (for example, `tests/browser/test_redesign.py:14-16`). The default test command and `publish-image.yml` do not enable them. Keep the manual browser walkthrough separate from automated browser-suite evidence, and record `pytest -rs` skip reasons when reporting a full run.

Gaps found by cross-referencing modules against `tests/`:

- No test submits shell metacharacters through the create or variables-edit forms — the direct test that would have caught finding 1.1.
- `services/telemetry.py` (the "don't promote to running before the listener probe succeeds" rule) has no dedicated unit test, only indirect coverage via `test_workspace_status.py`.
- `infra/server_lock.py` has no same-named test file, but it **does** have direct cancellation and cross-process serialization coverage in `tests/test_migration_concurrency.py:140-202`. Do not infer missing behavior coverage from filenames; any further lock tests should target specific uncovered failure cases.
- `infra/db_async.py` and `infra/file_writer.py` have no same-named test files. DB-write cancellation is directly exercised in `tests/test_migration_concurrency.py:107-137`; file-writer behavior also receives coverage through its callers. `file_writer._adopt_ownership`'s symlink-vs-regular-file mode/owner inheritance is nontrivial and platform-dependent.
- `domain/status.py::label()` has no test at all — trivial, low risk, but zero coverage.

---

## 4. Frontend architecture and CSS

The CSS convention (`tokens.css` owns every raw color/font; component files consume `var(--*)` only) is enforced by `tests/test_no_hardcoded_styles.py` and mostly holds. But the split into nine `app.*.css` feature files has left real debris from incomplete refactors:

### 4.1 Dead/conflicting `.state-pill--exited` rule (confirmed) — Medium

[app.server.css:211-212](src/mcontrol/static/app.server.css:211) styles `.state-pill--exited` as danger/red. [app.fleet.css:28](src/mcontrol/static/app.fleet.css:28) redefines the same selector as neutral gray. `mcontrol_base.html`'s `dashboard_styles` block loads `app.fleet.css` after `app.server.css` on every page, so the gray rule always wins — I confirmed this live: every "Stopped" pill in the app (fleet table and server-detail header alike) renders gray, matching fleet.css, never server.css's red. The red rule is dead code, not a visible bug today, but it's misleading to read and suggests the two files disagree about what "exited" should look like.

### 4.2 Duplicated, conflicting `.new-server*` rules across two files (confirmed) — Medium

`.new-server`, `.new-server__form`, `.new-server__fields`, and its fieldset/legend/label rules are defined independently in both [app.misc.css:21-36](src/mcontrol/static/app.misc.css:21) (`max-width: 800px`) and [app.creation.css:4-16](src/mcontrol/static/app.creation.css:4) (`max-width: 900px`, later overridden again to `1440px` at line 140). `new_server.html` loads `app.creation.css` last via `{{ super() }}` + an extra `<link>`, so creation.css always wins — confirmed by reading the template's `dashboard_styles` block. The misc.css versions are pure dead weight on the one page that uses this class. `.new-server__wide` and `.new-server__hint` in misc.css have no template references at all anymore.

### 4.3 Other CSS debris

- [app.server.css:84-99](src/mcontrol/static/app.server.css:84) vs [app.fleet.css:7](src/mcontrol/static/app.fleet.css:7): `.server-list` grid-template-columns defined twice with different values; fleet.css wins, server.css's version is dead.
- [app.server.css:704-706](src/mcontrol/static/app.server.css:704) vs [app.workspace.css:17](src/mcontrol/static/app.workspace.css:17): `.panel__body` padding set in server.css, unconditionally zeroed by workspace.css, which loads later.
- [app.files.css:504](src/mcontrol/static/app.files.css:504): `.file-archive-dialog::backdrop { background: rgb(0 0 0 / 55%); }` is a hardcoded color that slips past `test_no_hardcoded_styles.py` because its regex only matches `#hex` — a real gap in the enforcement test, not just the CSS.
- Spacing is inconsistently tokenized: ~36+ `margin`/`padding`/`gap` declarations across the component files use raw px instead of `var(--space-*)`. The color/font tokens are rigorously enforced (and tested); spacing isn't held to the same standard.
- `app.shell.css` defines `.sidebar__footer` and `.sidebar__collapse` twice, non-adjacently, in the same file — the later block silently wins. Easy to misread when editing.

**Root cause, in one line**: each `app.*.css` split (fleet.css, creation.css) was added on top of the older files without deleting what it superseded. Worth a follow-up pass to delete the shadowed rules — they're currently harmless-but-confusing, and one of them (4.1) is a live semantic disagreement about what "exited" should look like.

### 4.4 Template duplication

The same runtime-settings field set (memory budget, port, server jar, Java version, JVM extra args, help text, error slots) is hand-duplicated across three templates — `new_server.html`, `_variables_form.html`, `_migrate_card.html` — with different id prefixes instead of a shared macro. Any field change means editing three places in lockstep. Sharing markup would reduce UI drift, but would not fix finding 1.1: shell validation belongs in shared backend rules, independently of template reuse.

### 4.5 JS patterns

- Most modules (`errors.js`, `flash.js`, `focus.js`, `modals.js`, `sidebar.js`, `lifecycle.js`, `dashboard.js`, `workspace.js`, `streams.js`, `file_archives.js`) are IIFEs binding delegated listeners on `document`/`document.body`, which is exactly right for surviving htmx swaps — I did not find the classic "stale listener on a swapped node" leak the review went looking for.
- `file_uploader.js`, `file_bulk.js`, and `file_tree_nav.js` are plain top-level scripts sharing one script-level scope by design (documented in a `server_detail.html` comment about load order). It's a deliberate tradeoff for a >1000-line decomposition, but it's an inconsistent module pattern next to everything else being an IIFE, and a latent naming-collision risk if another module is added later.
- `htmx-ext-sse.js` is loaded on every mcontrol page, but no template uses `hx-ext="sse"` anywhere — `streams.js` hand-rolls SSE via raw `EventSource` instead. The extension is dead weight on every page load.
- Three near-identical "extract an error message from a failed request" helpers exist (`file_uploader.js` has two — one fetch-based, one XHR-based for upload-progress reasons — plus `errors.js`'s own inline version). Minor duplication, low risk.
- `streams.js::append()` inserts SSE payloads via `template.innerHTML = html`, trusting the backend always pre-escapes console/RCON output. That's true today and the backend does escape it, but it's the one place server text reaches `innerHTML` directly with no client-side second line of defense. Everywhere else that builds HTML from user data (`file_uploader.js`, `file_bulk.js`, `file_archives.js`) runs it through `escapeHtml()` first, so this one spot is the odd one out.

One claim from an earlier pass of this review turned out to be wrong and is **not** included above: a suspected null-reference crash in `workspace.js` on pages without a `.files-pane`. I checked it directly in a browser console — `a?.b().c()`-style optional chaining short-circuits the *entire* trailing chain in JavaScript, not just the first step, so `files?.querySelector(...).addEventListener(...)` safely evaluates to `undefined` and never throws when `files` is null. No bug there.

---

## 5. Accessibility

Genuinely strong for a solo project: real focus-trapping and Escape-to-close in `modals.js`, a full WAI-ARIA treeview with roving tabindex in `file_tree_nav.js`, focus restoration across htmx swaps in `focus.js`, keyboard-operable panel resize (Arrow keys as an alternative to the pointer-drag divider — I exercised this directly via the "Move Files up/down" and height-slider controls on mobile), and `aria-live`/`aria-busy` wiring throughout. Escape-closes-drawer and 44px touch targets under the mobile breakpoints both held up in my own testing.

Gaps:

- [new_server.html](src/mcontrol/templates/new_server.html:46) uses `role="tooltip"` on click-triggered, multi-sentence, dismissable help popovers — a misuse of a role meant for brief, non-interactive, hover/focus content. The same file's "About setup preview" popover (line 206) correctly omits the role, so the pattern isn't even applied consistently within one file.
- `server_detail.html` never uses `<h3>`: panel titles ("Console"/"Players"/"Files") and nested settings subsections are all marked up as sibling `<h2>`s, so a screen-reader's heading-navigation outline doesn't reflect the actual page structure.
- `file_tree_nav.js`'s keyboard handler covers Arrow keys, Enter, Space, and the context-menu key, but not Home/End (jump to first/last row) — a standard treeview pattern it's otherwise very faithful to.
- `_health_banner.html` uses `role="alert"` on a banner that's part of the initial server-rendered page (not injected after load), so the assertive-announcement behavior mostly won't fire in practice — cosmetic, not broken.

---

## 6. Live UI/UX walkthrough

Tested via the mock backend (desktop and 375×812 mobile viewports): fleet list, server workspace (console/players/files panels), new-server wizard, players roster, settings, and the delete-server flow.

**What works well:**
- The fleet table collapses into readable stacked cards on mobile without losing any information — no horizontal scroll, no truncation.
- The mobile nav drawer has a proper `aria-label`, a `Close navigation` button, and closes on Escape — verified directly.
- The new-server form's live Setup-preview panel (rendered `docker-compose.yml`, with `Advanced` collapsed by default) is a genuinely good touch — it shows the operator exactly what will be created before they commit.
- Destructive-action UX is well thought out: "Delete server" is disabled with an explanatory title ("Stop the server before deleting") until the server is stopped, and the confirmation modal requires typing the exact server name, explains precisely what happens (renamed to a `.deleted-*` folder, not removed, how to recover), and is not just a generic "Are you sure?".
- Zero console errors across every page and interaction tested.
- 404s render the app's own chrome-shaped error page with a way back home, not a bare Starlette error.

**Minor observations:**
- When the mock server's console/RCON connection can't be established (expected — the dev mock fakes Docker without real container networking), the pane surfaces raw implementation wording: `[error] no docker network found for container`. This is very likely mock-environment-only phrasing rather than something a real deployment shows, but if a similar message can surface in production, it reads as an internal log line rather than operator-facing copy. Worth a quick check against the real Docker path.
- The "Customize layout" / "Delete server" menu items communicate their disabled reasons through the HTML `title` attribute only (hover tooltip). That's invisible to touch users and adds a step for keyboard users relying on it before acting — consider surfacing the reason as visible helper text near the button, similar to how the Settings page already does it for "Migrate to scaffolded shape" ("Stop the server first" shown inline, not just on hover).

---

## 7. Ops and deployment

- `Dockerfile`: pinned Docker CLI/Compose-plugin versions, cache-friendly layer ordering, a real `HEALTHCHECK` using stdlib `urllib` instead of pulling in `curl`. Runs as root (needed for `/var/run/docker.sock` access) — a reasonable, acknowledged tradeoff for this kind of tool rather than an oversight.
- CI (`publish-image.yml`): runs `ruff` and the default `pytest` suite (browser tests remain opt-in) — including a `sudo`-elevated ownership-preservation test — before it ever builds or pushes an image, tags with the rollback-friendly `sha-<short>` scheme, and documents the exact rollback command in the job summary. Deploys are pull-based and manual on the host (`docker compose pull && up -d --wait`), not auto-pushed — a deliberate, sensible safety choice for a personal-infra project.
- `deploy/README.md` and `CONTRIBUTING.md` are current, specific, and match what's actually in the repo (verified: every path and command they reference exists) — this is above-average documentation hygiene for a solo project.

## 8. Small things noticed in passing

- `tests/test_no_hardcoded_styles.py` docstrings and its `APP_CSS` path reference `src/mcontrol/static/app.css` as "an `@import` manifest over the `app.*.css` modules" — that file doesn't exist (confirmed: no `app.css` anywhere in `static/`, no template references it, and the dev server's request log shows each `app.*.css` file loaded individually via its own `<link>` tag, never a manifest). The test still passes because `Path.glob("app*.css")` only needs the parent directory to exist, but the comment and variable name describe a manifest file that was apparently removed at some point and never cleaned up from the test.

---

## 9. Follow-up: regeneration and upload correctness (2026-09-18)

**Implementation update (2026-09-18):** the three findings below are fixed in the working tree. Regeneration confirmations now include a fingerprint of the proposed output and target; stale previews return 409. Managed-file writes restore changed files after an exception and report incomplete recovery. Uploads reject duplicate destination names before any writes, including forced uploads. Regression coverage includes the actual browser confirmation flow. The original findings and reproductions below are retained as the record of the bugs. Exception rollback does not guarantee recovery after a process crash.

**Fix validation:** final default-suite run: **949 passed, 103 skipped** (opt-in browser and platform-dependent checks); focused regeneration/scaffolding run including the final regression additions: **40 passed, 2 skipped**; opt-in browser regeneration test: **1 passed**; `uv run ruff check .`: clean. The browser regression was first observed failing against the original implementation.

### 9.1 Regenerate can apply settings the preview never showed (confirmed) — Medium

[routes/regenerate.py:105-127](src/mcontrol/routes/regenerate.py:105) accepts only the two disk mtimes when confirming. It then renders the **current** database variables. Open a regeneration preview, change Variables in another tab, and confirm the old preview: the Variables update leaves both disk mtimes unchanged, so confirmation succeeds with the newer settings. A changed port, heap size, Java version, or startup script can therefore be written without appearing in the approved diff. The fleet lock serializes confirmation itself but cannot detect changes made between preview and confirmation.

**Verification:** in a temporary directory, captured both mtimes, changed the supplied server row's port from 25565 to 25566 without touching the files, and called `confirm()` with the original mtimes. Confirmation accepted and wrote `25566:25565`. Only the pending-migration guard and response renderer were stubbed; the comparison and file writes were real.

**Fix/test:** include a fingerprint of the rendered proposal or relevant server inputs in the preview, compare it under the confirmation lock, and return a refreshed diff with 409 on mismatch. Add a route test that changes Variables between GET preview and POST confirm.

### 9.2 Regeneration is atomic per file, not across the managed pair (confirmed) — Medium

[domain/scaffolding/__init__.py:198-201](src/mcontrol/domain/scaffolding/__init__.py:198) replaces `docker-compose.yml`, then `server/start_server.sh`, then changes the script's mode. [routes/regenerate.py:127](src/mcontrol/routes/regenerate.py:127) has no rollback around this sequence. If the second write fails, the new Compose file remains alongside the old startup script. For example, changing both memory budget and heap settings can leave the two files describing different configurations. Rendering both templates before writing protects against render errors, but does not protect against later filesystem failures.

**Verification:** injected an `OSError` only on the startup-script write in a temporary directory. The Compose file changed while the script retained its old contents.

**Fix/test:** preserve both originals and restore the first if a later step fails; surface any incomplete recovery clearly. Add failure-injection coverage for the second replacement and final chmod. If crash recovery is required, use a durable recovery marker rather than relying on exception rollback alone.

### 9.3 Duplicate filenames within one upload silently overwrite each other (confirmed) — Medium

[routes/files/write.py:161-202](src/mcontrol/routes/files/write.py:161) checks upload conflicts against existing disk entries, but does not check for duplicate filenames inside the submitted batch. Two new multipart files both named `same.txt` pass the preflight scan; the write loop saves the first and immediately replaces it with the second, even when `force=false`. The first upload's content is lost without a conflict prompt. This needs no concurrent request and is separate from §1.2's locking gap.

**Verification:** sent two parts named `same.txt`, containing `first` and `second`, through an isolated FastAPI app using the real upload router and a temporary directory. With `force=false`, the response was 200 and the stored content was `second`. Only the server dependency and HTML response renderer were replaced.

**Fix/test:** reject duplicate destination names before writing any files, and add a multipart route test asserting a 400/409 response and no files written. The existing distinct-file and pre-existing-conflict tests do not cover this case.

**Focused validation:** `uv run pytest tests/test_regenerate.py tests/test_server_variables_form.py -q` → **46 passed**. These existing tests pass despite the regeneration reproductions above; neither scenario currently has a regression test. No application code was changed in this follow-up.

---

## Suggested priority order

1. **Close the `jvm_extra_args`/`server_jar` validation gap** (§1.1) — reuse `migration.py`'s existing regexes in `server_variables_form.validate()`. Small, mechanical, closes a real gap in ~10 lines.
2. **Serialize Files mutations and their conflict checks** (§1.2). The three regeneration/upload fixes in §9 are now implemented; the broader Files locking gap remains separate work.
3. **Delete the shadowed CSS** (§4.1–4.3) — remove the dead `.state-pill`, `.new-server*`, `.server-list`, and `.panel__body` rules from `app.server.css`/`app.misc.css` now that `app.fleet.css`/`app.creation.css`/`app.workspace.css` supersede them. Low-risk cleanup, removes a real source of future confusion.
4. **Extend the hardcoded-style test** to also catch `rgb()`/`rgba()`/`hsl()` literals, not just `#hex` (§4.3) — one regex change, closes the enforcement gap that let `app.files.css:504` through.
5. **Add a shared runtime-settings macro** for the three duplicated form templates (§4.4) — reduces markup drift; shared backend validation is still required for §1.1.
6. Everything else in this document is lower urgency: architecture drift (§2), test-coverage gaps (§3), and accessibility polish (§5) are all worth doing but none are blocking anything today.
