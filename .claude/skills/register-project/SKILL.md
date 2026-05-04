---
name: register-project
description: Register a new project in titan-tyr (#44). A project is a tag attached to parts and contracts so the UI and agents can filter the graph to one project at a time. Use when the user wants to "create a project", "register a project", "set up a new WatcherVault project area", or when they ask to tag parts/contracts with a project that doesn't exist yet. POSTs to `/projects`. Does NOT register parts or contracts — that's `/register-part` and `/register-contract` with the optional `project` field.
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
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.     |
| `TITAN_TYR_ACTOR` | no       | X-Actor header. Stored as `created_by_actor` on the new project row. If unset the paper trail goes blank — warn the user. |

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
  -H "Authorization: Bearer ${TITAN_TYR_TOKEN:-sysmlv2}" \
  -H "X-Actor: ${TITAN_TYR_ACTOR:-}" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "<slug>",
    "description": "<one-sentence summary, optional>"
  }' \
  "$TITAN_TYR_URL/projects"
```

201 → `{name, description, created_at, created_by_actor}`.

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
- Existing un-tagged parts and contracts can be moved into the project
  by re-running `/update-part` with `project: "<slug>"` in the payload.
- Run `/list-projects` to see counts.

## Notes

- No `DELETE /projects/{name}` exists yet — projects accumulate.
  Archive semantics are deferred per the #44 design.
- Updates: only `description` is mutable via `PUT /projects/{name}`.
  Name is the immutable handle.
