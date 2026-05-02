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

### 3. Fetch the template

Pull the current software template from the API:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" "$TITAN_TYR_URL/templates/software"
```

### 4. Build the markdown body from the template

The template you just fetched mixes **fillable content** (what the user
wants to record) with **filler-only guidance** (instructions you should
not save). Apply these fill rules — in this order — to convert the raw
template into the markdown body that will be POSTed.

#### Per-section guidance

- **Owner / Repository** header — use what the user already gave you.
- **Purpose** — ask for a 2–4 sentence description if not provided.
- **Ports** table — each row is a **logical operation** (one row covers
  all HTTP methods/routes that implement the same operation), not one
  row per HTTP method. Direction is from this software's perspective.
- **Notes** — anything that doesn't fit the above. Don't invent new H2
  sections; surplus content goes here.

If the user wants to skip Ports for this first registration (common),
leave a single placeholder row noting "TBD" and ask them to come back
later with `PUT /software/{name}`.

#### Fill rules

1. **`<...>` placeholders are content slots.** Replace each with real
   content; drop the angle brackets too. `<software-name>` →
   `payments-service`; `<in | out>` → `in`.

2. **Instructional blockquotes are filler-only.** Any block of lines
   starting with `>` near the top of the template is guidance for you;
   strip it from the saved markdown.

3. **Instructional H3 subsections are filler-only — except** when you
   have real content for them:
   - `### Direction conventions` — pure reference. **Always drop.**
   - `### What is *not* a Port` — drop if the software has nothing
     specific to call out; **keep with real exclusions** if it does
     (e.g. for an API: "Postgres connection — datastore" and
     "Bearer-password middleware — cross-cutting").

4. **Multi-counterparty rows.** The template's Ports row shows
   `<counterparty-name>[, <counterparty-name>...]`. Pick one
   convention and apply it consistently within this software's body —
   either comma-separate counterparties in one cell, or duplicate the
   Port row once per counterparty. Don't mix.

5. **Resolve placeholder counterparties to real software names.** If a
   counterparty isn't yet registered with titan-tyr (you can check via
   `GET /software/{name}`), flag it for the user — they may want to
   register it first, or accept a placeholder like
   `<any-authenticated-caller>` for now.

#### Worked example

Template fragment as returned by the API:

```markdown
# <software-name>

**Owner:** <team or person>
**Repository:** <repo-uri>

> A Software node is a unit of software ownership — one codebase, one
> deployable boundary, one owning team. ...

## Purpose

Two to four sentences. What does this software do and why does it
exist? Written for a reader with no prior context.
```

After applying the rules:

```markdown
# payments-service

**Owner:** payments-team
**Repository:** https://github.com/example/payments-service

## Purpose

Handles all card and ACH payment capture for the storefront. Owns
PCI-relevant data; everyone else integrates via the REST API.
```

### 5. Preview before submitting

Show the user the **full filled markdown body** you intend to POST.
Ask "ready to register?" Do not POST until the user confirms. If they
want changes, iterate — re-show after each edit.

### 6. Submit

```sh
curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "Content-Type: application/json" \
     --data @/tmp/body.json \
     "$TITAN_TYR_URL/software"
```

**Build the JSON body via a tool, not via shell heredocs or `-d "..."`.**
The markdown will contain backticks, pipes, asterisks, double quotes,
and unicode characters; `--data @file.json` written by Python or `jq`
sidesteps every shell-escaping landmine. Example:

```sh
python3 -c "
import json, pathlib
print(json.dumps({
    'name': 'payments-service',
    'repo_uri': 'https://github.com/example/payments-service',
    'markdown': pathlib.Path('/tmp/body.md').read_text(),
    'version': '1.0.0',
}))
" > /tmp/body.json
```

### 7. Report the result

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
