---
name: list-projects
description: List the projects registered in titan-tyr. A project (#44) is a tag attached to parts and contracts so the UI and agents can filter the graph to one project at a time. Use when the user asks "what projects are there", "show projects", "which project should I tag this with", or before running /register-part / /register-contract / /update-part with the `project` field. Read-only; does not mutate state.
---

# list-projects

You are surfacing the projects currently registered in titan-tyr.
This is a small read-only skill — its main job is to give the
caller (a human or another skill) the list of valid project slugs
so they can pick one when registering or updating parts and
contracts.

## Server location

Standard env vars:

| Variable          | Required | Purpose                                  |
| ----------------- | -------- | ---------------------------------------- |
| `TITAN_TYR_URL`   | yes      | Base URL. No trailing slash.             |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.     |

If `TITAN_TYR_URL` is unset, run `/check-titan-tyr-env` first and
surface its verdict.

## Workflow

```sh
curl -fsS -H "Authorization: Bearer ${TITAN_TYR_TOKEN:-sysmlv2}" \
  "$TITAN_TYR_URL/projects"
```

Response shape:

```json
{
  "results": [
    {
      "name": "watchervault",
      "description": "WatcherVault platform — titan-tyr, titan-mimiron, archaedas, postgres",
      "created_at": "2026-05-04T03:00:00Z",
      "created_by_actor": "chris.cox@westfall.io",
      "part_count": 8,
      "contract_count": 14
    },
    ...
  ],
  "next": null
}
```

Surface a compact table by default (name, description, counts);
include the timestamps and `created_by_actor` on request.

If the list is empty, tell the user no projects are registered yet
and that they can either run `/register-project` or leave parts
and contracts unprojected (the legacy default — they continue to
work as before).

## Single-project lookup

For a quick check on one project:

```sh
curl -fsS -H "Authorization: Bearer ${TITAN_TYR_TOKEN:-sysmlv2}" \
  "$TITAN_TYR_URL/projects/<slug>"
```

404 if the slug is unknown.

## Notes

- Projects are global metadata, not part of the structural graph.
  Membership is recorded as a `project_id` foreign key on parts and
  contracts, not as a contract.
- A part or contract carries at most one project tag; junction-table
  multi-membership is deferred per the design call in #44.
- Project tagging is optional. The UI default of "show all" includes
  unprojected rows.
