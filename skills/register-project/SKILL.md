---
name: register-project
description: Register a new project tag in titan-tyr (groups parts/contracts so UI can filter to one project). POSTs to /projects.
---

# register-project

You are registering a new project tag with titan-tyr. A project
groups parts and contracts so consumers can filter the graph to
one project at a time. The graph itself is unchanged; project
membership is metadata that lives on the part / contract row.

## Server location

| Variable          | Required | Purpose                                  |
| ----------------- | -------- | ---------------------------------------- |
| `TITAN_TYR_URL`   | yes      | Base URL. No trailing slash.             |
| `TITAN_TYR_TOKEN` | no       | Bearer per-caller token (issue via `/issue-auth-token`). Required.     |
| `TITAN_TYR_ACTOR` | no       | X-Actor header. Stored as `owner_actor` on the new project row. If unset the paper trail goes blank — warn the user. |

If `TITAN_TYR_URL` is unset, run `/check-titan-tyr-env` first.

## Workflow

### 1. Pick a slug

The project name must be a slug: lowercase letters, digits, and
hyphens; 1–64 chars; cannot start or end with a hyphen. Same rule
as part names. Examples: `watchervault`, `payments`, `experimental-sandbox`.

The slug is the canonical handle and is **immutable** after
creation. Pick something short and stable. Aliases are not
supported on projects (#44 design call).

The slug namespace is **separate** from parts — a project named
`payments` does not collide with a part named `payments`.

### 2. POST it

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "X-Actor: ${TITAN_TYR_ACTOR:-}" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "<slug>",
    "description": "<one-sentence summary, optional>"
  }' \
  "$TITAN_TYR_URL/projects"
```

201 → `{name, description, created_at, owner_actor}`.

### 3. Errors

| Status | Meaning                                              | What to do                                       |
| ------ | ---------------------------------------------------- | ------------------------------------------------ |
| `409`  | A project with that slug already exists              | Stop. Suggest the user pick a different slug or run `/list-projects` to find the existing one. |
| `422`  | Slug fails validation (uppercase, dot, leading hyphen, etc) | Fix and retry. |
| `401`  | Bad bearer token                                     | Stop. Tell user to fix `TITAN_TYR_TOKEN`.        |

## After creation

- Tell the user the project is ready and that they can now register parts
  and contracts tagged with the slug via `/register-part` or
  `/register-contract` (both accept an optional `project` field).
- To **backfill** existing rows into the project, point the user at
  `/bulk-claim-rows`. The typical backfill is
  `--project <slug> --current-project __none__` — tag every untagged
  row in one pass with a dry-run table and confirmation gate. Per-row
  `/update-part` / `/update-contract` is the right tool for one-off
  edits, not for sweeping a freshly-registered project across the
  catalog.
- Run `/list-projects` to see counts.

## Notes

- No `DELETE /projects/{name}` exists yet — projects accumulate.
  Archive semantics are deferred per the #44 design.
- Updates: only `description` is mutable via `PUT /projects/{name}`.
  Name is the immutable handle.
