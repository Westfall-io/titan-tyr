---
name: register-part
description: Register a part with the titan-tyr API. A part is one of titan-tyr's typed nodes — currently subtype `software` (a codebase / deployable boundary) or `container` (a running instance of an image). Use when the user wants to add a new node to WatcherVault's graph — e.g. "register this repo with titan-tyr", "register the prod payments container", "create a part for X". Branches on subtype: fetches the matching template (`/templates/software` or `/templates/container`), helps the user fill it in, then POSTs to `/parts`.
---

# register-part

You are helping the user register a part with titan-tyr. **Parts** are
the typed nodes in titan-tyr's graph; contracts (edges) connect them.
Per #23, parts come in subtypes — currently `software` and `container`.
This skill walks through the **node creation** path: `POST /parts`.

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

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → bearer token is wrong. Tell the user; do not proceed.
- Connection refused / DNS failure → the URL is wrong or the server isn't running. Tell the user.

### 2. Pick the subtype

Branch on what the user is registering:

| Subtype     | When to use                                                                             |
| ----------- | --------------------------------------------------------------------------------------- |
| `software`  | A codebase, deployable, or library. The "what does this thing do" node.                 |
| `container` | A running instance of an image at a specific address — the live form of some software.  |

If the user said something ambiguous ("register this service"), ask:
"Software node (the codebase) or container (a running deployment of it)?"

The subtype determines the template you fetch in step 4.

### 3. Gather the inputs

The `POST /parts` body has these fields. Confirm each with the user
before the request — don't invent values:

| Field               | Source                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------ |
| `name`              | Unique identifier across **all** parts (one namespace, software + container share it). Ask the user; suggest the repo name (for software) or `<image-name>-<env>` (for containers). |
| `subtype`           | From step 2: `"software"` or `"container"`.                                                |
| `repo_uri`          | Git URL. For software: read `git config --get remote.origin.url`; confirm. For container: the repo that defines the image / compose / deploy spec. |
| `issue_tracker_uri` | Optional. Where to file tickets if not the repo's default. Must be `https://`. |
| `aliases`           | Optional list of colloquial labels other agents may use to refer to this part (`payments`, `billing`, `front end`, `前端`, `payments-prod`). Used by `GET /parts?match=<query>` for fuzzy lookup. Per-entry: 1–128 chars, no control chars/newlines, Unicode allowed; case-preserved on storage; case-insensitive dedupe within payload. Cross-part collisions allowed. |
| `markdown`          | The filled-in part-template body for this subtype (see step 5).                            |
| `version`           | Optional; defaults to `"1.0.0"`. Plain `MAJOR.MINOR.PATCH` (no RC suffix on parts).         |

### 4. Fetch the template

Pull the template matching the chosen subtype:

```sh
# subtype=software
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" "$TITAN_TYR_URL/templates/software"

# subtype=container
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" "$TITAN_TYR_URL/templates/container"
```

The template body is `text/markdown`. To get the **active template
version** (needed for the stamp substitution in step 5), call:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/<subtype>/proposals" \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['active_version'])"
```

### 5. Fill the template

The template is **self-describing** — its instructional blockquotes
(`>` blocks) and any `### …` reference subsections are guidance for
the human / agent doing the fill, not content to save. Read them,
follow them, then strip them from the body you POST.

Generic fill rules — these apply regardless of which subtype's template
you're filling:

1. **`<...>` placeholders are content slots.** Replace each with real
   content and drop the angle brackets.

2. **Reserved meta-placeholders.** Filled by the skill, not the user:
   - `<template-version>` — substitute with the active template version
     you fetched in step 4. The stamp is usually
     `<!-- template: <subtype>@<template-version> -->` at the top of the
     body. Keep the comment line; replace the placeholder.

3. **Instructional blockquotes are filler-only.** Any `>` block whose
   content is guidance to the filler gets stripped. Templates from
   `software@2.4.0` / `contract@1.2.0` / all `container@*` onward
   prefix every such blockquote with `**DELETE WHEN FILLING IN.**` —
   when you see that marker, drop the whole block.

4. **Pure-reference H3 subsections are filler-only.** If an H3 only
   exists to explain how to fill its parent section, drop it. If it
   invites you to add real content, keep it iff you have real content.

5. **Don't invent structure.** No new H2 sections beyond what the
   template defined. Surplus content goes in the Notes / Feedback
   section the template provides.

The skill stops here on template specifics. What counts as a Port,
how to phrase Purpose, how to fill in the container's Connections
table — all of that lives **in the template body itself**, not in
this skill. If you find yourself wanting to add template-specific
guidance here, that's a signal to `/propose-template-change` instead.

### 6. Subtype-specific reminders (light)

- **`software`** — there is no `runs` Connection on a software body;
  the binding to its runtime container is captured on the container
  side via a contract.
- **`container`** — the body has `Ports` and `Connections` tables. The
  `runs` row in Connections refers by name to the software part this
  container hosts. **Ensure that software part is already registered**
  (step 8 below — pre-flight check). If not, register it first via this
  same skill (subtype=software) before continuing.

### 7. Preview before submitting

Show the user the **full filled markdown body**, the chosen `name`,
`subtype`, and other JSON fields. Ask "ready to register?" Do not POST
until the user confirms. Iterate on the body if they want changes.

### 8. Pre-flight: name uniqueness

`name` is unique across **all** parts (one namespace). Before POSTing:

```sh
curl -fsS -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/<name>"
```

- `200` → name is taken; stop and route the user to `/update-part` if
  they wanted to amend, or pick a different name if it's a different
  part.
- `404` → free to use.

For `subtype=container`, additionally pre-flight that the software
part referenced in the body's `runs` Connection actually exists.

### 9. Submit

**Scratch files must live inside the project.** Use `.scratch/` at the
repo root (gitignored — create it if it doesn't exist) and clean up
after.

**Build the JSON body via a tool, not via shell heredocs or `-d "..."`.**
The markdown will contain backticks, pipes, asterisks, double quotes,
and unicode characters; `--data @file.json` written by Python sidesteps
every shell-escaping landmine.

```sh
mkdir -p .scratch
python3 -c "
import json, pathlib
print(json.dumps({
    'name': 'payments-service',
    'subtype': 'software',                      # or 'container'
    'repo_uri': 'https://github.com/example/payments-service',
    # 'aliases': ['payments', 'billing'],       # uncomment if the user gave any
    'markdown': pathlib.Path('.scratch/body.md').read_text(),
    'version': '1.0.0',
}))
" > .scratch/body.json

curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "Content-Type: application/json" \
     --data @.scratch/body.json \
     "$TITAN_TYR_URL/parts"
```

### 10. Report the result

On `201`, summarise:

> Registered `<name>` (subtype: `<subtype>`) at version `1.0.0`.
> Part ID: `<uuid>`.
> Read it back: `curl -H 'Authorization: Bearer $TITAN_TYR_TOKEN' $TITAN_TYR_URL/parts/<name>`

For containers: ask if the user wants to register the `runs` contract
linking this container to the software part it hosts (one
`POST /contracts` with the container as owner, the software as
counterparty). Do NOT do this automatically — surface the option.

For software: ask if the user wants to register interface contracts
between this software and any other already-registered parts. Do NOT
do this automatically.

## Error handling

| Status | Meaning                                            | What to do                                                                  |
| ------ | -------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                   | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `409`  | A part with that `name` already exists (any subtype) | Show what's there (`GET /parts/{name}`); ask whether to update via `/update-part`. |
| `422`  | Malformed `version`, missing `subtype`, unknown subtype, or invalid `repo_uri` / `issue_tracker_uri` / alias | Read the `detail` field; fix the input and retry. |
| `500+` | Server problem                                     | Print the response body verbatim. Do not retry.                             |

## Notes

- **One namespace.** `name` is unique across software AND container
  parts. A common pattern is `<service>` for the software part and
  `<service>-<env>` for the container (`payments`, `payments-prod`).
- **Subtype is structural.** It can't be changed after registration
  (no PUT path mutates it). If you really need a different subtype,
  register a new part.
- **Do not** put a `Version` field inside the markdown body — the API
  tracks it on the version row separately. The template's header note
  explains why.
- **Do not** invent an `owner` field in the JSON body. There is no
  per-caller identity in this API yet. Put owner info in the markdown
  body if it matters to humans.
- The very first version of a part is created atomically with the
  part node; you can't register a part without an initial markdown body.
- **Container ↔ Software `runs` relationship.** Today this is encoded
  as a regular contract (Container as owner, Software as counterparty).
  Typed connections — `runs` as a first-class edge type — are deferred
  to a follow-up ticket per #23.
