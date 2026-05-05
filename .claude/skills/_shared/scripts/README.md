# Shared skill helpers

Cross-cutting helpers that more than one SKILL.md is expected to invoke.
Per-skill helpers (those wrapped by exactly one SKILL.md) live in their
owning skill's directory instead.

This directory is **not a skill** — it has no `SKILL.md`. The
`update-skills` sync script discovers it via path prefix and pulls
its contents into downstream consumers at the matching local path,
so source and destination layouts agree.

Every helper here reads the same env vars the SKILL.mds standardize:
`TITAN_TYR_URL` (required), `TITAN_TYR_TOKEN` (default `sysmlv2`),
`TITAN_TYR_ACTOR` (the X-Actor identity).

## The `tyr-*` toolkit (#63)

| Helper                      | What it does                                                                   |
| --------------------------- | ------------------------------------------------------------------------------ |
| `tyr-curl.sh`               | Header-injecting curl wrapper. `tyr-curl GET /parts` / `POST /parts --data @-`. Auto-adds Authorization, X-Actor, Content-Type; pretty-prints JSON by default; `--raw` opts out. |
| `tyr-payload.sh`            | JSON-payload assembler. Subcommands `register-part` / `update-part` / `register-contract` / `update-contract`; takes `--md FILE` plus the structured fields as flags; emits JSON to stdout (default) or `--out FILE`. |
| `tyr-slug-check.sh`         | Slug pre-flight. `tyr-slug-check foo` → exit 0 + `free`, or exit 1 + `taken: ... part \`foo\`, updated DATE by ACTOR, project=PROJ`. |
| `tyr-shift-and-accept.sh`   | Propose-then-accept loop for solo workflows. Subcommands `name-shift` / `part-subtype-shift` / `contract-subtype-shift` / `endpoint-shift` / `body-bump`. **Requires `--single-operator` to land the accept** — without it, stops after propose and prints the proposal_id (or version) for the second party to pick up. |

## Composing the toolkit

The four pieces fit together:

```sh
# Pre-flight + payload + curl, chained:
.claude/skills/_shared/scripts/tyr-slug-check.sh new-part-name && \
.claude/skills/_shared/scripts/tyr-payload.sh register-part \
    --md .scratch/new-part.md \
    --name new-part-name --subtype software --version 1.0.0 \
    --project watchervault --repo-uri https://example.com/repo \
  | .claude/skills/_shared/scripts/tyr-curl.sh POST /parts --data @-
```

Or, for a solo rename:

```sh
.claude/skills/_shared/scripts/tyr-shift-and-accept.sh name-shift \
    --part old-name \
    --new-name new-name \
    --rationale-file .scratch/rationale.md \
    --single-operator
```

## Safety properties

- `tyr-shift-and-accept.sh` will **not** silently fold accept into
  propose. The `--single-operator` flag must be passed explicitly,
  and the bypass shows up at the call site.
- `tyr-curl.sh` warns on stderr when a write method (POST/PUT/PATCH)
  fires without `TITAN_TYR_ACTOR` — the row's paper trail will land
  null otherwise.
- `tyr-payload.sh` does not call the API; it only builds JSON. Any
  validation error you see comes from the live POST that consumes
  its output (`-fsS` on `tyr-curl.sh` surfaces it).
