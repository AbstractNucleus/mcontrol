# Slice 11 — Empty trash: tombstone purge

> Lean plan: contract + PR order. Ships the deferred "Empty trash" affordance
> that decision 026 explicitly named. The code is the source of truth — this
> doc is the napkin sketch.

## Goal

Operator opens `/trash` and sees every `.deleted-<name>-<unix-ts>/` directory
under `SERVER_BASE_PATH` with its parsed original-name, age, and bytes on
disk. Two purge controls: **Empty trash** (purges everything older than 7
days) and per-row **Delete now** (purges that single tombstone immediately).
Both confirm with a type-name modal matching the destructive-op friction
pattern from slice-5 recursive-delete and slice-6 delete-server. Decision 026
trade-off ("tombstoned directories accumulate on disk indefinitely until the
operator manually purges … a future 'Empty trash' affordance can sweep
tombstones older than N days when the cost stops being theoretical") closes
out here.

## Scope contract

| | |
|---|---|
| Surface | New page `GET /trash`. Inline list — one row per tombstone. No card on the home page; reachable via the new top-nav link. |
| Numbers shown | Original server name (parsed from dir name), age (now − parsed unix-ts; rendered as "5d 3h" / "2h 14m" / "47s"), bytes on disk (formatted via `resources.format_bytes`). |
| Threshold | `7` days hard-coded in `tombstones.py` as `_DEFAULT_PURGE_AGE_DAYS = 7`. Not exposed in the UI this slice — a configurable threshold is a follow-up if it ever matters. |
| Tombstone source | `<base>/.deleted-<slug>-<unix-ts>/` directories produced by slice-6's `routes/delete_server.py`. The dir is renamed (not removed) by Delete; this slice is the missing purge half. |
| Tombstone parse | Regex `^\.deleted-(?P<name>[a-z][a-z0-9-]{2,31})-(?P<ts>\d+)$`. Slug shape mirrors `routes/new_server.py:_NAME_RE` so a tombstone produced by `delete_server.py` always parses. Greedy backtrack handles slug-with-hyphens correctly: the trailing `-\d+$` anchor pins the unix-ts to the rightmost `-<digits>` run. Malformed entries are silently skipped — `<base>` may contain any operator-introduced `.foo` dir (per decision 026, dot-prefixed dirs are out-of-band to mcontrol), and the trash list is "tombstones I produced," not "every dot-dir." |
| Bytes source | `resources.read_disk_usage(path)` — already exists, already `follow_symlinks=False`, already path-safe. Reuse rather than rewrite; the os.scandir walk inside it is the same primitive a fresh implementation here would write. Walks once per render; at single-host scale + tombstone count typically ≤ a few, the cost is sub-second and matches the cadence of the slice-9 disk read on a server detail page. |
| Sort order | Oldest first. The Empty-trash button purges from oldest forward; rendering oldest-first means the row at the top is the first to be swept. |
| Path-safety | See dedicated section below. |
| Refresh model | Plain GET. No HTMX poll — tombstone list changes only on operator action (delete a server, click Delete now, click Empty trash), so a page refresh after each action is sufficient. POST handlers return `HX-Redirect: /trash` to re-render. |
| Empty-trash confirm | Type literal `EMPTY` (uppercase) into a confirm input. Slice-6 used "type the server name"; for a multi-target action there's no single name to type, and `EMPTY` is short, deliberate, and distinct enough to interrupt muscle memory. The button label surfaces the count and total bytes that will be swept ("Empty trash — 3 tombstones, 4.7 GiB") so the operator sees the blast radius before confirming. |
| Per-row Delete-now confirm | Type the parsed original server name (the `<name>` capture from the regex). Mirrors slice-6's delete-server flow exactly so muscle memory carries over; an operator who's deleted a server before knows what input the field expects. |
| Discovery interaction | None. Discovery's dot-prefix filter (decision 026) keeps tombstones invisible to scans; `/trash` bypasses discovery and reads `<base>` directly with `os.scandir`. The two read sides (discovery, trash) never overlap — discovery sees `name` not starting with `.`, trash sees `name` matching the tombstone regex. |
| Health-banner | Untouched. Tombstones are not a scaffold-integrity issue; they're operator-managed disk state. The Empty-trash entry point is the top-nav link, not a banner. |
| Top-nav | The "Players" nav link from slice 7 lives only in `templates/home.html` today. Per the operator's instruction (and to avoid conflicting with PR #39 which edits home.html), this slice introduces a new partial `templates/_topnav.html` that carries Servers / Players / Trash links. It is included from `templates/trash.html` and `templates/_players_main.html` so both pages can navigate to each other and to `/`. `templates/home.html` is intentionally left alone; a follow-up can replace its inline `home-header__actions` with `_topnav.html` once PR #39 is in. |

## Page shape

`/trash` — empty state:

```
mcontrol [Servers · Players · Trash]
─────────────────────────────────────────────
Trash
No tombstones. Deleted servers land here automatically.
```

`/trash` — populated:

```
mcontrol [Servers · Players · Trash]
─────────────────────────────────────────────
Trash

[ Empty trash — 2 tombstones older than 7 days, 4.7 GiB ]

  atm10        14 d ago   2.1 GiB    [Delete now]
  monifactory  10 d ago   2.6 GiB    [Delete now]
  testbed       3 h ago   12 MiB     [Delete now]
```

The Empty-trash button is disabled when no tombstones meet the 7-day cutoff
(label becomes "Empty trash — nothing older than 7 days"). The button being
present-but-disabled is more discoverable than hiding it: the operator
learns the threshold by reading the label.

Modals:
- **Empty trash** — type `EMPTY` to confirm. Lists by name + age + bytes
  every tombstone that will be purged. Cancel / Confirm.
- **Delete now (per row)** — type the parsed server name to confirm. Slice-6
  copy ("Files are not removed — recover by renaming the tombstone back
  from a shell.") is **not** carried over: this is the purge button, the
  files are removed, and that's the whole point.

## Routes

```
GET  /trash                          → list page (renders trash.html)
POST /trash/empty                    → purges every tombstone older than 7 days,
                                       redirects to /trash
POST /trash/{dir_name}/delete        → purges that single tombstone,
                                       redirects to /trash
```

`{dir_name}` is the literal directory name including the `.deleted-` prefix
(URL-encoded). FastAPI passes it as a string to the handler, which validates
against the tombstone regex before any filesystem operation — see
path-safety below.

## Modules

```
src/mcontrol/
  tombstones.py                      # NEW — pure functions:
                                     #   list_tombstones(base) -> list[Tombstone]
                                     #   purge_one(path) -> None
                                     #   purge_older_than(base, days) -> list[Tombstone]
                                     # Tombstone is a small dataclass:
                                     #   dir_name, original_name, deleted_at_unix,
                                     #   age_seconds, bytes
  routes/
    trash.py                         # NEW — three endpoints above. Uses
                                     #   tombstones.* + resources.format_bytes.
  templates/
    trash.html                       # NEW — extends base.html
    _topnav.html                     # NEW — Servers · Players · Trash links
    _trash_list.html                 # NEW (optional partial) — the list itself,
                                     #   so the modal-confirm flow can swap a
                                     #   single row if we ever want HTMX inline
                                     #   delete (deferred this slice; redirect
                                     #   pattern is sufficient).
    _trash_empty_confirm.html        # NEW — modal partial for Empty trash.
    _trash_delete_confirm.html       # NEW — modal partial for per-row delete.
  main.py                            # EDIT — register trash router.

tests/
  test_tombstones.py                 # NEW — tmp_path tests for parsing,
                                     #   listing, age, bytes, purge_one,
                                     #   purge_older_than, malformed-entry
                                     #   skip, empty-base case.
  test_trash.py                      # NEW — route tests: GET /trash renders,
                                     #   POST /trash/empty purges only ≥ 7d,
                                     #   POST /trash/{name}/delete validates
                                     #   the regex, path-traversal payloads
                                     #   are rejected, redirects target /trash.

src/mcontrol/templates/_players_main.html   # EDIT — include _topnav.html
                                            #   above the existing eyebrow.
```

## PR sequence

| # | Ships | Notes |
|---|---|---|
| 0 | Single PR — module + routes + page + nav + tests + plan + decision 030 | One vertical: `tombstones.py` (pure, tmp_path-tested), `routes/trash.py` wired into `main.py`, the four templates, tests, plan doc, decision 030. `uv run pytest -v` and `uv run ruff check .` both green. |

Single PR because the module surface is small and the tombstone format is
already an established artefact — there's no separate "land the parse, then
land the UI" step that adds value.

## Path-safety contract

The two write endpoints (`POST /trash/empty`, `POST /trash/{dir_name}/delete`)
are the only sites that call `shutil.rmtree(...)` on this slice's read tree.
Both go through a single helper, `tombstones.purge_one(base, dir_name)`,
which enforces:

1. **Name-regex gate.** `dir_name` must `re.fullmatch` the tombstone regex
   `^\.deleted-[a-z][a-z0-9-]{2,31}-\d+$`. Anything else raises a
   `ValueError` before any path operation. URL-decoded payloads like
   `..` / `../foo` / `foo/bar` / `foo%00bar` fail the regex (hyphen + dot +
   slash + null are all outside `[a-z0-9-]`) and never reach the filesystem.
2. **Containment check.** `target = (Path(base).resolve() / dir_name)`.
   Verify `target.parent == Path(base).resolve()` and
   `target.is_dir(follow_symlinks=False)`. The first check rejects the
   theoretical "dir_name passed regex but `Path` resolution still landed
   us elsewhere" case; the second rejects symlinks an operator might have
   dropped into `<base>` with a tombstone-shaped name.
3. **No globs, no operator-controlled segments beyond `dir_name`.** The
   base path comes from `Settings.server_base_path`, not the request.

`list_tombstones(base)` reads `<base>` with `os.scandir(base)`, applies the
regex to `entry.name`, and includes only entries where `entry.is_dir()` and
`not entry.is_symlink()`. The same regex / containment story keeps the read
side honest: even if an operator drops `.deleted-foo-bar-1234567890` as a
symlink to `/etc`, the read path skips it (and the write path would refuse
to follow it).

`purge_older_than(base, days)` lists tombstones, filters by `age_seconds >=
days * 86400`, and calls `purge_one(base, t.dir_name)` for each. The list
walk and the per-purge regex check both run; a tombstone that's listed but
whose name fails the regex on the second check is impossible by
construction (listing already filtered by the same regex), but the explicit
re-check is the contract. Best-effort: a failure on one tombstone (rmtree
raises mid-walk because of an open file handle, etc.) is recorded and the
loop continues.

## Decisions register impact

This slice **adds decision 030**: "Empty-trash affordance: tombstone purge
with 7-day default." Closes out decision 026's deferred trade-off note.

No prior decision is superseded. Decision 026 remains the source of truth
for the tombstone-on-delete contract; this slice is the closing-bracket on
its "future affordance" line, not a re-litigation.

Decisions referenced by the implementation:

- **026** — tombstone shape, dot-prefix discovery filter, `<base>` layout.
  This slice's read + write paths are scoped exactly to what 026 produces.
- **020** — pinned image refs. Irrelevant to this slice's code (no new
  image), but the regex pin (`^[a-z][a-z0-9-]{2,31}$`) inherited from
  slice 6 is the discipline equivalent: the tombstone parser is pinned to
  the producer's slug shape. If `_NAME_RE` ever changes, this slice's
  regex changes with it in lockstep.
- **016** — FastAPI + Jinja + HTMX. New page is server-rendered HTML;
  modals are HTMX swaps; POST handlers return `HX-Redirect`.
- **006** — Direct `/var/run/docker.sock` mount. Untouched by this slice;
  trash never talks to Docker.

## Deferred / out-of-scope

- **Configurable threshold UI.** The `7` lives in code only. If the felt
  need is "I want different defaults per environment," that's a future
  decision (ENV var or settings field) — not this slice. The build-and-
  deploy cost of bumping `_DEFAULT_PURGE_AGE_DAYS = 7` to a different
  number is one line + a test bump.
- **Restore button.** The slice-6 delete copy says "recover by renaming
  the tombstone back from a shell." That recovery path stays. Adding a
  panel-side Restore button would import a new flow (DB row re-creation,
  potential dir-name collision, container_name override repointing) that
  isn't justified for the rare-mistaken-delete case.
- **Automatic purge on a schedule.** No cron, no startup-time sweep. The
  decision-026 trade-off is explicit: tombstones are deliberately
  recoverable by default; auto-purge would silently destroy that
  reversibility. The Empty-trash button is the operator's deliberate moment.
- **Multi-host.** Decision 005.
- **Tombstone count on the home page or top-nav badge.** "(3)" next to
  the Trash link would be nice; punted to a follow-up. Single-operator
  scale, the Trash link itself is the affordance.
- **Per-tombstone "rename back" UI.** Same reasoning as Restore. Shell
  is the right tool for a rare reversal.
- **Bulk select / multi-row delete.** Empty-trash is the bulk affordance
  (sweeps all ≥ 7d), Delete-now is the single-row affordance. A free-form
  multi-select adds modal complexity for the felt-need-of-zero case.
- **Replacing the `home.html` inline `home-header__actions` block with
  `_topnav.html`.** Off-limits this slice — PR #39 edits home.html. The
  swap is a one-line follow-up after #39 lands.
- **Tombstone retention policy in CLAUDE.md / README.** The plan doc and
  decision 030 are the durable record; the README doesn't need to learn
  about tombstones until the operator-facing setup story does.

## Resolved during grilling

1. **Bytes source — `resources.read_disk_usage` vs fresh `os.scandir`:**
   reuse. The function is exactly the right primitive (recursive byte
   sum, `follow_symlinks=False`), it's already tested in `test_resources`,
   and forking a near-identical walk in `tombstones.py` would be the
   "200 lines that could be 50" anti-pattern. The cost (one extra import
   from `mcontrol.resources`) is paid once.
2. **Sort order — newest first vs oldest first:** oldest first. The
   Empty-trash button sweeps the head of the list; rendering oldest-first
   means "what you see at the top is what's about to go" matches the
   button semantics. Newest-first ("what did I just delete") is a
   different mental model but doesn't carry the threshold story.
3. **Threshold default — 7 days vs 14 vs 30:** 7. Decision 026's trade-off
   says "older than N days when the cost stops being theoretical"; 7 is
   short enough that an operator who deletes by mistake notices within
   the recovery window (a typical week's working pattern), long enough
   that an Empty-trash run after a planned cleanup actually frees the
   bytes. 30 would let a multi-GB modpack tombstone sit for too long;
   1 would feel adversarial.
4. **Confirm input — type the count, type `EMPTY`, type `delete`:**
   `EMPTY`. Typing the count works for one specific moment but doesn't
   force the operator to read the count (they can copy-paste from the
   button label); `EMPTY` is short, deliberate, and not something fingers
   have ever been trained to type by accident in this app. Per-row uses
   the parsed name, matching slice 6.
5. **Threshold gate inside `purge_older_than` vs route-level filter:**
   inside the module. The route is "operator clicked Empty trash";
   moving the threshold into the route would split the policy across two
   files. `tombstones.purge_older_than(base, days=_DEFAULT_PURGE_AGE_DAYS)`
   makes the policy locatable.
6. **Top-nav placement — extend home.html vs new partial:** new partial.
   PR #39 is editing home.html; touching it here would mean a merge
   conflict and a back-and-forth. `_topnav.html` is one extra file, used
   by `/trash` and `/players` immediately. The home page can adopt it in
   a follow-up after #39 lands; the asymmetry (home keeps its inline
   nav block until then) is acceptable for a single-operator panel.
7. **`Tombstone` shape — dataclass vs dict:** dataclass. Three fields
   (`dir_name`, `original_name`, `deleted_at_unix`, `age_seconds`,
   `bytes`) are stable enough to be worth typing; the dataclass also
   reads cleanly in tests (`assert t.original_name == "atm10"` vs
   dict-key access). No methods, no `__post_init__`, no inheritance —
   it's just a tagged tuple with named fields.
8. **`os.scandir` follow-symlinks behaviour at the read site:** don't
   follow. `entry.is_dir(follow_symlinks=False)` and `is_symlink()` skip
   ensure a symlink with a tombstone-shaped name (operator could create
   one for any reason) is invisible to `/trash`. Belt-and-suspenders
   alongside the regex check.
9. **Failure mode for a malformed-name dot-dir under `<base>`** (e.g.
   `.git`, `.lost+found`, `.deleted-foo` without the trailing
   `-<unix-ts>`): silently skipped on the read side. The trash list is
   "tombstones I produced," not "every operator dot-dir." Surfacing
   would mean the page mixes mcontrol-managed and operator-managed
   filesystem state — exactly the line decision 026's filter draws.
10. **HTMX inline-delete vs full-page redirect:** redirect. The
    `_trash_list.html` partial is sketched for a future inline swap, but
    plain redirect is the simplest pattern that's correct: one DOM tree,
    one source of truth (the GET handler), no partial-state assertions
    in tests. The cost is a flicker on each delete; for a page that gets
    visited a few times a year, it's free.
11. **`Settings.server_base_path` resolution timing:** at request time,
    inside the route. Mirrors `delete_server.py`; no caching across
    requests since the path is a config value, not a runtime-mutable
    state. `resolve()` is cheap.
12. **Empty `<base>` directory:** returns an empty list. The page
    renders the no-tombstones empty state. Same path-safety
    contract — `os.scandir` on an empty dir is a no-op.
