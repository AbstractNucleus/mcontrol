# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`docs/CONTEXT.md`** — domain glossary (canonical term definitions; cross-links to decisions).
- **`docs/decisions.md`** — single-file architectural decisions register. Entries are numbered (`001`, `002`, …) with a status table at the top. Read entries that touch the area you're about to work in. This repo uses a single-file register rather than the conventional `docs/adr/<NNN>-<slug>.md` per-file layout — same role, different shape.

## File structure

Single-context repo:

```
/
├── README.md
├── docs/
│   └── decisions.md          ← architectural decisions (single-file ADR register)
└── src/mcontrol/
```

When skills reference `docs/adr/`, read `docs/decisions.md` instead. Decision IDs in this repo are `NNN` (e.g. `decision 021`), not `ADR-NNNN`.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as established in `docs/decisions.md` and the slice plans under `docs/plans/` (e.g. *server*, *binding*, *RCON*, *slice*, *bind mount*, *tailnet*, *terminator*). Don't drift to synonyms the existing docs explicitly avoid.

If the concept you need isn't established yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`, or for a new decision entry).

## Flag decision conflicts

If your output contradicts an existing decision in `docs/decisions.md`, surface it explicitly rather than silently overriding:

> _Contradicts decision 019 (TLS termination at aserver-nginx) — but worth reopening because…_

Per the register's own rules (`docs/decisions.md:14-16`), a superseding decision gets a new `NNN`; the old entry's status flips to `Superseded by NNN` rather than being edited in place.
