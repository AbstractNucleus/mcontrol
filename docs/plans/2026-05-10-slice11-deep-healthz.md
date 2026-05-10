# Slice 11 — Deep `/healthz` probe

> Lean plan: contract + PR. The code is the source of truth — this doc is the napkin sketch.

## Goal

Turn `/healthz` from a one-line liveness ping into a real readiness probe that exercises every subsystem the panel needs to function: Supabase reachability, Docker socket reachability, and the bind-mount base path being a writable directory. Returns JSON with per-subsystem status; HTTP **200** when all checks pass, **503** when any one fails — so the upstream nginx terminator (decision 019) can react. One URL is also the operator's diagnostic for "is mcontrol healthy?" after a deploy or socket disruption.

## Scope contract

| | |
|---|---|
| Endpoint | `GET /healthz`. Single endpoint, unchanged URL. JSON-only response — same shape on both 200 and 503 so nginx and `curl` see the same envelope. |
| Response shape | `{ "status": "ok" \| "degraded", "checks": { "db": { "status": "ok"\|"fail", "detail": "..." }, "docker": { ... }, "base_path": { ... } }, "elapsed_ms": <int> }`. |
| Status mapping | All three checks `"ok"` → top-level `"ok"` + HTTP 200. Any check `"fail"` → top-level `"degraded"` + HTTP 503. |
| db check | A lightweight `SELECT` against `app_mcontrol.servers` via the existing supabase-py client (`select("name", count="exact", head=True).limit(1)`) — confirms PostgREST is up and the schema is reachable. 250 ms timeout. Errors render as `"fail"` with a sanitised single-line `detail`; never the full traceback, never the connection URL or service-role key. |
| docker check | `aiodocker.Docker(...).system.ping()` against the configured `docker_host`. 250 ms timeout. Errors render as `"fail"` with a sanitised `detail`. |
| base_path check | `Path(SERVER_BASE_PATH).is_dir()` plus a write probe (touch + unlink a `.healthz-<pid>-<unix-ms>` file under base) — catches the failure mode where the bind-mount is mounted read-only or the path is a stale symlink. 250 ms timeout. Errors render as `"fail"` with a sanitised `detail`. |
| Concurrency | All three probes via `asyncio.gather(..., return_exceptions=True)` so total latency is one slow probe, not three. An exception escaping a probe degrades that subsystem to `"fail"` rather than 500-ing the endpoint. |
| Auth | None. Decision 003 — tailnet-only access is the gate; nginx needs to probe without creds. |
| Caching | None. Every hit re-runs the probes; staleness defeats the purpose. |
| `elapsed_ms` | Integer milliseconds of wall-clock time spent in `gather`. Operator-facing diagnostic for "the endpoint feels slow" — surfaces tail-latency without a separate metric. |
| Sanitised detail | Per probe: the exception class name plus its `str()`, truncated to 200 chars. No traceback frames, no Settings values inlined. The Settings object holds the SUPABASE_SERVICE_ROLE_KEY, so `repr(e)` could leak it on an unlucky exception — `f"{type(e).__name__}: {e}"[:200]` is the canonical form. |

## Routes

```
GET  /healthz   →  200 (ok) or 503 (degraded), always JSON in the contracted shape.
```

No new endpoints; the existing one gains real teeth.

## Modules

```
src/mcontrol/
  healthz.py            # build_report() -> (status_code, payload).
                        # Pure async, gathers the three probes, computes
                        # the envelope. No FastAPI imports.
  main.py               # /healthz route is a one-liner that calls
                        # healthz.build_report and returns a JSONResponse.
  db.py                 # gains a tiny ping() helper so healthz doesn't
                        # reach into private query construction.
```

`healthz.py` is its own file (not folded into `main.py`) for the same reason every other slice extracts logic out of `main.py`: testable in isolation, no FastAPI/test-client ceremony for the unit tests. Distinct from `src/mcontrol/health.py` (per-server scaffold-integrity for the detail-page banner) — the two modules answer different questions and a future contributor reading the import list shouldn't have to guess.

## PR sequence

| # | Ships | Notes |
|---|---|---|
| 0 | `healthz.py` + route rewire + db.ping helper + tests + README + decision 030 | Single PR. The probe is small (~80 lines), the contract is single-endpoint, and there's no useful intermediate state to land separately. |

## Test contract

`tests/test_healthz.py` rewritten to cover:

- **all-ok** — every probe returns ok; status code 200, top-level `"ok"`, all three subsystems `"ok"`, `elapsed_ms` is an int ≥ 0.
- **db-fail** — db probe raises; status code 503, top-level `"degraded"`, db `"fail"` with sanitised detail, other two `"ok"`.
- **docker-fail** — same shape with docker probe raising.
- **base-path-fail (missing)** — base path doesn't exist; base_path `"fail"`.
- **base-path-fail (read-only)** — base path exists but write probe fails; base_path `"fail"`. Skipped on Windows where chmod-readonly doesn't reliably block writes.
- **every-fail** — all three raise; 503, all three `"fail"`, top-level `"degraded"`.
- **timeout** — a probe exceeds 250 ms; that subsystem renders `"fail"` with a timeout detail and the endpoint still returns inside a bounded time.
- **detail sanitisation** — a probe raises an exception whose `repr()` would include the SUPABASE_SERVICE_ROLE_KEY; `detail` does not contain the key.

Probes are mocked via `monkeypatch.setattr` against `healthz._probe_db` / `_probe_docker` / `_probe_base_path` so tests don't need a live Supabase or Docker daemon.

## Decisions register impact

This slice introduces:

- **030 — Deep `/healthz`: per-subsystem probe with 503-on-degraded.** Pins the contract that `/healthz` is the readiness URL (not just a liveness URL), that 503 is the canonical degraded signal so upstream nginx (decision 019) can act, and that the response is always JSON in a single envelope shape regardless of status. Forecloses the "split into `/livez` + `/readyz`" exit ramp at this scale — single-host, single-operator, one URL is enough.

This slice acts on:

- **003** Tailnet-only access — no auth gate on `/healthz`; the network layer is the gate, and nginx needs to probe without creds.
- **006** Direct `/var/run/docker.sock` mount — the docker probe is the same socket-reachability check the rest of the panel relies on.
- **007** Shared Supabase, schema `app_mcontrol` — the db probe lives in `app_mcontrol.servers` and validates that PostgREST is up *and* the schema is reachable (a wrong service-role key yields a `"fail"`, not a misleading `"ok"`).
- **008** Bind mounts at `~abstract/servers/minecraft/<name>/` — the base_path probe catches the failure mode where the bind-mount itself is broken (host path missing, mounted read-only, etc.), which is the most likely operator-visible production failure given decision 019's reverse-proxy posture.
- **016** FastAPI — JSON via `JSONResponse(status_code=...)` for the explicit 503 case.
- **019** TLS termination at aserver-nginx — the endpoint is the upstream-health URL nginx's `proxy_next_upstream` / monitoring directive will hit. Wiring nginx to consume it is operator's hand on aserver, not in scope here.

## Deferred / out-of-scope

- **nginx config changes on aserver.** Outside this repo. Operator wires `proxy_next_upstream` / `health_check` to the new endpoint when ready.
- **Prometheus exposition format.** The endpoint is JSON-only. If/when metrics scraping is wanted, a separate `/metrics` route is the right surface, not overloading `/healthz`.
- **Per-server health rollup.** That's `src/mcontrol/health.py`'s job (slice 6+ scaffold-integrity banner). Distinct concern, distinct module.
- **Auth gate.** Tailnet (decision 003) is the gate. Adding HTTP auth here would block nginx's probe without buying anything the network layer doesn't already give.
- **Historical retention / SLO computation.** No log line, no time-series store. The endpoint is point-in-time; tracking uptime is monitoring's job, not the panel's.
- **Split into `/livez` + `/readyz`.** Single-host, single-operator, single URL. If the panel ever runs behind a Kubernetes-style probe pair, that's a future decision.
- **Probing all subsystems on every request.** This slice does exactly that. If the cost ever becomes felt, the fix is per-subsystem caching with a short TTL, gated by a query param; not in scope today.
- **Configurable per-probe timeouts.** 250 ms is hard-coded across all three. If one subsystem ever needs a longer cap, refactor then.

## Resolved during grilling

1. **Auth gate yes/no.** No. Decision 003 puts the network layer in front of every panel surface; an HTTP auth gate would block the nginx probe (defeating the point) for no security gain.
2. **Single endpoint vs `/livez` + `/readyz`.** Single. The k8s-style pair is overkill at single-host scale; one URL with a per-subsystem breakdown is enough for both the nginx probe and the operator's `curl` check.
3. **HTTP status code on degraded — 200-with-flag vs 503.** 503. Nginx and any future monitoring expect a real status code to decide upstream-up vs upstream-down; 200-with-`status: degraded` would force every consumer to parse the body to know if the panel is up.
4. **JSON shape — flat vs nested `checks`.** Nested. A flat shape would force the consumer to know the set of subsystem keys; the nested envelope makes "what subsystems exist" structurally discoverable.
5. **Probe timeout — 100 ms vs 250 ms vs 1 s.** 250 ms. 100 ms is too tight for a Supabase round-trip on a slow tailnet hop; 1 s is too generous and would let a single misbehaving subsystem make the whole endpoint slow. 250 ms is a single human-perceptible blink and concurrent probes mean the worst-case endpoint latency is ~250 ms, not 750 ms.
6. **Sequential vs `asyncio.gather` for the probes.** Gather. Three independent probes; serial would be ~750 ms worst-case for no reason. `return_exceptions=True` keeps a single probe's failure from bubbling up as a 500.
7. **db probe — full table read vs head-only count.** Head-only. `select("name", count="exact", head=True).limit(1)` validates the path (PostgREST up, JWT valid, schema reachable, table exists) without paying for a row body. The head request is the canonical "are you alive" probe in supabase-py.
8. **docker probe — `containers.list()` vs `system.ping()`.** Ping. Listing containers does the same socket round-trip plus an unrelated read; ping is the named "is the daemon up" call. Cheaper and more honest.
9. **base_path probe — `is_dir()` only vs add a write probe.** Add a write probe. The most likely operator-visible base-path failure under decision 019's deployment shape is "the host bind-mount is read-only" (e.g. host filesystem went read-only after disk-fill); `is_dir()` would still return True. Touch + unlink under base catches it without leaving an artifact.
10. **Sanitised `detail` content.** `f"{type(e).__name__}: {e}"[:200]`. The Settings object holds the SUPABASE_SERVICE_ROLE_KEY; `repr(e)` could leak it on an unlucky exception. The tests pin this contract by raising an exception whose `repr` would include the key.
11. **Caching.** None. A `/healthz` that lies about the past is worse than one that takes 250 ms to tell the truth.
12. **`elapsed_ms` — yes vs no.** Yes. Cheap to compute, immediately useful when the operator says "the endpoint feels slow" — surfaces tail-latency without setting up a separate metric.
13. **Module location — fold into `main.py` vs new `healthz.py`.** New `healthz.py`. `main.py` is the wiring shell; logic lives in modules so it's testable in isolation. Distinct from `health.py` (per-server scaffold integrity) — different question, different consumer, different module.
