# scripts/

Top-level dev-tools and ops shortcuts. Not skill helpers — those live
co-located with their owning skills under `.claude/skills/`.

| Layout | Where | What lives there |
| --- | --- | --- |
| Per-skill helpers | `.claude/skills/<owner>/scripts/` | Helpers a single SKILL.md wraps (e.g. `bulk-claim-rows`, `update-skills`). Source path matches what downstream consumers see after `update-skills` syncs. |
| Cross-cutting helpers | `.claude/skills/_shared/scripts/` | The `tyr-*` family designed to be invoked from many skills (`tyr-curl`, `tyr-payload`, `tyr-shift-and-accept`, `tyr-slug-check`). |
| Dev tools (this dir) | `scripts/` | Devops conveniences not invoked from any SKILL.md. |

## Files in this directory

| Script                          | What it does                                                                |
| ------------------------------- | --------------------------------------------------------------------------- |
| `list-part-contracts.sh`        | Tabular summary of contracts touching a registered part.                    |
| `list-routes.sh`                | Boot the FastAPI app and dump its routes (sanity check after route renames). |
| `propose-contract.sh`           | One-shot wrapper for posting a contract content proposal.                   |
| `propose-template.sh`           | One-shot wrapper for posting a template content proposal.                   |
| `show-contract.sh`              | Pretty-print a contract by id with endpoints and version.                   |
| `show-issue.sh`                 | Pretty-print a GitHub issue (title, state, body, comments) via `gh`.        |
| `show-template.sh`              | Pretty-print a template's active body and metadata.                         |

All read the same env vars as the skill helpers: `TITAN_TYR_URL`
(required), `TITAN_TYR_TOKEN` (default `sysmlv2`), `TITAN_TYR_ACTOR`.

## The `tyr-*` toolkit

See `.claude/skills/_shared/scripts/README.md` for the full shared-helper
catalog and composition examples.
