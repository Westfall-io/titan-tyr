# scripts/

Shell helpers around the titan-tyr API. Two flavors live here:

- **Per-task ops scripts** — short utilities tied to one workflow
  (e.g. `bulk-claim-rows.sh`, `list-part-contracts.sh`,
  `show-issue.sh`).
- **Generic API helpers** — the `tyr-*` family added in #63 that
  every register/update/propose/accept skill can compose with.

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

### Composing the toolkit

The four pieces fit together:

```sh
# Pre-flight
scripts/tyr-slug-check.sh new-part-name && \
# Build the payload from a markdown body + flags
scripts/tyr-payload.sh register-part \
    --md .scratch/new-part.md \
    --name new-part-name --subtype software --version 1.0.0 \
    --project watchervault --repo-uri https://example.com/repo \
  | scripts/tyr-curl.sh POST /parts --data @-
```

Or, for a solo rename:

```sh
scripts/tyr-shift-and-accept.sh name-shift \
    --part old-name \
    --new-name new-name \
    --rationale-file .scratch/rationale.md \
    --single-operator
```

### Safety properties

- `tyr-shift-and-accept.sh` will **not** silently fold accept into
  propose. The `--single-operator` flag must be passed explicitly,
  and the bypass shows up at the call site.
- `tyr-curl.sh` warns on stderr when a write method (POST/PUT/PATCH)
  fires without `TITAN_TYR_ACTOR` — the row's paper trail will land
  null otherwise.
- `tyr-payload.sh` does not call the API; it only builds JSON. Any
  validation error you see comes from the live POST that consumes
  its output (`-fsS` on `tyr-curl.sh` surfaces it).

## Per-task scripts

| Script                          | What it does                                                                                                |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `bulk-claim-rows.sh`            | One-pass project-tag + actor-claim sweep across `/parts` and `/contracts` with a dry-run gate (#59).        |
| `list-part-contracts.sh`        | Tabular summary of contracts touching a registered part.                                                    |
| `list-routes.sh`                | Boot the FastAPI app and dump its routes (sanity check after route renames).                                |
| `propose-contract.sh`           | Convenience wrapper for posting a contract content proposal.                                                |
| `propose-template.sh`           | Convenience wrapper for posting a template content proposal.                                                |
| `show-contract.sh`              | Pretty-print a contract by id with endpoints and version.                                                   |
| `show-issue.sh`                 | Pretty-print a GitHub issue (title, state, body, comments) via `gh`.                                        |
| `show-template.sh`              | Pretty-print a template's active body and metadata.                                                         |
| `sync-titan-tyr-skills.sh`      | Pull the titan-tyr skill catalog into a downstream consumer's `.claude/skills/` dir (used by `/update-skills`). |
