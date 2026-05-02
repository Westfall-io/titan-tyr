---
name: register-software
description: Register a piece of software with the titan-tyr API. Use when the user wants to add a new software node to WatcherVault's graph — e.g. "register this repo with titan-tyr", "add my service to the WatcherVault catalog", "create a software node for X". Fetches the current `software` template, helps the user fill it in, then POSTs to /software.
---

# register-software

You are helping the user register a piece of software with titan-tyr — the
WatcherVault REST API. titan-tyr stores software as nodes in a graph and
contracts as edges. This skill walks through the **node creation** path:
`POST /software`.

## Server location

Read these from the environment:

| Variable          | Required | Purpose                                                                                |
| ----------------- | -------- | -------------------------------------------------------------------------------------- |
| `TITAN_TYR_URL`   | yes      | Base URL of the API, e.g. `http://localhost:8000`. No trailing slash.                  |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2` (the placeholder password — see titan-tyr DESIGN.md). |

If `TITAN_TYR_URL` is unset, **stop and tell the user**:

> `TITAN_TYR_URL` is not set. Set it to the titan-tyr base URL before running this skill, e.g.
> `export TITAN_TYR_URL=http://localhost:8000`.

Do not try to guess the URL. Do not default to localhost silently.

If `TITAN_TYR_TOKEN` is unset, use `sysmlv2` and mention you are doing so once
in your reply, so the user can override if they're hitting an instance with a
different placeholder.

## Workflow

### 1. Confirm the API is reachable

Before doing anything else, hit a cheap endpoint to fail fast on bad config:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → bearer token is wrong. Tell the user; do not proceed.
- Connection refused / DNS failure → the URL is wrong or the server isn't running. Tell the user.

### 2. Gather the inputs

The `POST /software` body needs four fields. Confirm each with the user before
the request — don't invent values:

| Field      | Source                                                                                    |
| ---------- | ----------------------------------------------------------------------------------------- |
| `name`     | Unique identifier for this software in titan-tyr. Ask the user; suggest the repo name.    |
| `repo_uri` | Git URL. Read from `git config --get remote.origin.url` if available; confirm with user.  |
| `markdown` | The filled-in software template body (see step 3).                                        |
| `version`  | Optional; defaults to `"1.0.0"`. Ask only if the user has a reason to start at something else. |

### 3. Fetch and fill the template

Pull the current software template from the API:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" "$TITAN_TYR_URL/templates/software"
```

The template is markdown with `<placeholder>`-style fill-ins. Walk the user
through each section:

- **Owner / Repository** header — use what they've already given you.
- **Purpose** — ask for a 2–4 sentence description.
- **Ports** table — every external interface this software exposes or
  consumes. Each port is a **logical operation** (one row covers all
  HTTP methods/routes that implement the same operation), not one row
  per HTTP method. Direction is from this software's perspective. See
  the template for the in/out conventions.
- **Notes** — anything else.

If the user wants to skip the ports for now (common for a first registration),
that's fine — leave the placeholder row and they can update later via
`PUT /software/{name}`.

Resolve placeholder counterparties to real software names if they exist; flag
unknown counterparties so the user can decide whether to register them first.

### 4. Submit

```sh
curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "Content-Type: application/json" \
     -d "$BODY" \
     "$TITAN_TYR_URL/software"
```

Where `$BODY` is JSON like:

```json
{
  "name": "payments-service",
  "repo_uri": "https://github.com/example/payments-service",
  "markdown": "# payments-service\n...",
  "version": "1.0.0"
}
```

Build `$BODY` carefully — the `markdown` field needs proper JSON escaping for
newlines and quotes. Prefer writing the body to a temp file and using
`--data @file.json`, which sidesteps shell-escaping issues entirely.

### 5. Report the result

On `201`, summarise:

> Registered `<name>` at version `1.0.0`. Software ID: `<uuid>`.
> Read it back with: `curl -H 'Authorization: Bearer $TITAN_TYR_TOKEN' $TITAN_TYR_URL/software/<name>`

Ask whether the user wants to also register interface contracts for this
software (one `POST /contracts` per directed edge). Do NOT do that
automatically — contracts need a counterparty software node to exist first.

## Error handling

| Status | Meaning                                            | What to do                                                                  |
| ------ | -------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                   | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `409`  | A software with that `name` already exists         | Show what's there (`GET /software/{name}`); ask whether to update via `PUT`. |
| `422`  | Malformed `version` (e.g. RC suffix or `1.0`)      | Software versions are plain `MAJOR.MINOR.PATCH`. Suggest a fix.             |
| `500+` | Server problem                                     | Print the response body verbatim. Do not retry.                             |

## Notes

- **Do not** put a `Version` field inside the markdown body — the API tracks
  it on the version row separately. The template's header note explains why.
- **Do not** invent an `owner` field in the JSON body. There is no per-caller
  identity in this API yet (the bearer password is a placeholder; real auth
  is deferred). Put owner info in the markdown body if it matters to humans.
- The very first version of a piece of software is created atomically with
  the software node; you can't register a software without an initial
  markdown body.
