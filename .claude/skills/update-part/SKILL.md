---
name: update-part
description: Append a new version to a part already registered with titan-tyr. Use when the user wants to update a registered part's body — e.g. "update my software registration", "bump titan-tyr's version", "my part is out of date with the template", "register a new version of X". Detects template-version drift, helps the user revise the body, and PUTs to /parts/{name}. Distinct from /register-part, which creates new parts.
---

# update-part

You are appending a new version to a part that already exists
in titan-tyr. The endpoint is `PUT /parts/{name}`. Each call adds
one row to that part's `*_versions` history; reads always return
the latest.

There are two reasons to update:

- **Content drift** — the software actually changed (new ports, new
  purpose, owner moved teams).
- **Template drift** — the template moved forward (e.g. `software@1.0.0`
  → `software@2.1.0`) and the body is now structurally stale even if
  nothing about the software itself changed.

This skill handles both, in either combination.

## Server location

Same env vars as the other titan-tyr skills:

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |

If `TITAN_TYR_URL` is unset, **stop and tell the user**:

> `TITAN_TYR_URL` is not set. Set it to the titan-tyr base URL before running this skill, e.g.
> `export TITAN_TYR_URL=http://localhost:8000`.

Don't guess. Don't default to localhost silently.

## Workflow

### 1. Confirm reachability and identify the software

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → wrong token. Stop.
- Connection refused → wrong URL or server down. Stop.

Ask the user which software to update (the `name` they registered it
under). If they don't remember, they can list candidates via the
relevant `GET` endpoints — but pick a single name before continuing.

### 2. Fetch current state

Two reads, in parallel:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{name}"
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software"
```

Note the current software `version` and `markdown` from the first
response, and the active template body from the second. Pull the
active template version off `GET /templates/software/proposals`'s
`active_version` field (the markdown endpoint returns the body, not
metadata).

`404` on `/parts/{name}` → the software is not registered. Stop
and point at `/register-part`.

### 3. Detect template-version drift

Look for the **template-version stamp** at the top of the body:

```html
<!-- template: software@X.Y.Z -->
```

Three cases:

- **Stamp matches active template version.** No template drift. The
  body is structurally compliant; this is content-only.
- **Stamp present but older.** Template drift exists. Diff the old
  template body (stamp version) against the current active template
  body so the user sees what changed structurally. Then plan a
  migration (see step 4).
- **No stamp.** The body pre-dates the stamp feature (introduced in
  `software@2.1.0`). Treat as "unknown but probably drifted." Diff
  the current body's structure against the active template; surface
  any sections, columns, or placeholders that don't line up.

Fetching an older template version is not currently exposed by the
API — it stores the history but doesn't serve it. If the user needs
the old template body for the diff, they can paste it; otherwise
work from the current body's existing shape.

### 4. Decide what's changing

Ask the user to confirm scope:

- **Content only.** Edit the existing body in place. Keep all
  structure the body already has.
- **Template migration only.** The software is unchanged but the body
  needs to be reshaped onto the current template. Carry user-supplied
  content forward; drop sections the new template no longer has;
  initialise sections the new template added.
- **Both.** Do the migration first (gives you a clean scaffold), then
  apply content changes on top.

Apply the same generic fill rules as `/register-part`:

1. `<...>` placeholders are content slots; replace and drop brackets.
2. Reserved meta-placeholders are filled by the skill:
   - `<template-version>` → the active template version you just
     fetched.
3. Instructional blockquotes are filler-only; strip them. Templates
   from `software@2.4.0` / `contract@1.2.0` onward prefix every such
   blockquote with `**DELETE WHEN FILLING IN.**` to make this
   unambiguous — when you see that marker, drop the whole block.
4. Pure-reference H3 subsections are filler-only; drop unless you
   have real content for them.
5. Don't invent H2 structure.

**Always re-stamp on structural migration.** If you're moving the
body's shape onto a newer template version (anything beyond pure
content edits), update the stamp
`<!-- template: software@X.Y.Z -->` to the active template version
*even though it's already a literal value*. The
substitute-`<template-version>` rule from `/register-part` only
fires on registration, when the stamp is still a placeholder. On
update the stamp is already a literal version string baked in at the
last write — no `<...>` to substitute. If you don't re-type it, the
stamp will silently lie about which template the body matches, and
the next `/update-part` run will mis-detect drift in step 3.

Conversely, on a **content-only** edit (no structural reshape), keep
the stamp as-is. The body still matches the template version stamped
on it; that's the whole point of the stamp.

The skill does not carry template-specific knowledge beyond this. If
the user needs guidance on what a section *means*, that guidance lives
in the template body's instructional blockquotes — read them, follow
them, strip them on POST.

### 5. Optional: update row-level metadata (repo_uri, issue_tracker_uri, aliases)

`PUT /parts/{name}` accepts three optional row-level metadata fields
with **PATCH semantics**. They share the same omit/value/null shape;
the only differences are around what null means per field.

| Field               | Omitted                   | `"...": "value"`                | `"...": null`               |
| ------------------- | ------------------------- | ------------------------------- | --------------------------- |
| `repo_uri`          | Existing value unchanged. | Replaces stored value.          | **422** — cannot clear.     |
| `issue_tracker_uri` | Existing value unchanged. | Replaces stored value (https-only). | Clears stored value.    |
| `aliases`           | Existing list unchanged.  | Replaces stored list (full set).| Clears list to `[]`.        |

Ask the user only if they have a reason to change any of these (repo
renamed/moved, adopted Jira/Linear, new colloquial nickname, etc.).
Otherwise omit. Validation:
`repo_uri` accepts any non-empty string (HTTPS, SSH form, etc.);
`issue_tracker_uri` is strictly `https://` with a host;
`aliases` entries must be 1–128 chars after trim, no control chars or
newlines, Unicode allowed, case preserved. Setting an empty list
(`[]`) is equivalent to `null` — both clear. Aliases are a full
replacement, not a merge — to *add* one, fetch the existing list
first and resubmit with the addition appended.

### 6. Choose a new software version

The new version must be **strictly greater** than the current one and
plain `MAJOR.MINOR.PATCH` (no `-rcN` — software does not support
pre-releases; only contract and template proposals do).

Bump rationale is about the **software**, not the template. The
template moving from 1.0.0 to 2.1.0 doesn't itself force a MAJOR bump
on the software — pick based on what changed in *this software*:

| Change                                                | Bump  |
| ----------------------------------------------------- | ----- |
| New Port, removed Port, breaking interface change     | MAJOR |
| Refined Purpose, additional Notes, new optional info  | MINOR |
| Typo / clarification only                             | PATCH |

Pure template migration with no real content change is usually a
PATCH bump — the software didn't change, the documentation just got
re-shaped.

### 7. Preview before submitting

Show the user **the full new body** plus the version about to be
submitted. Also surface the **stamp value** explicitly alongside the
**active template version**, so any mismatch is visible at the
confirmation gate:

> Stamp: `software@<X.Y.Z>` (active template: `<X.Y.Z>`)

If those two don't match, call it out before asking to proceed —
either the user intended a content-only edit and the mismatch is
pre-existing drift left from a prior bad update (file an issue
against the prior body, then either keep the mismatch or correct it
now), or the user intended a structural migration and forgot to
re-stamp (loop back to step 4).

Ask "ready to update?" Do not PUT until the user confirms. Iterate if
they want changes.

### 8. Submit

Same scratch-file convention as the other skills — JSON via tool, not
shell heredocs. Include `issue_tracker_uri` in the dict only if the
user wants to change it (per step 5):

```sh
mkdir -p .scratch
python3 -c "
import json, pathlib
print(json.dumps({
    'version': 'X.Y.Z',
    'markdown': pathlib.Path('.scratch/update-body.md').read_text(),
    # 'repo_uri': 'https://...',                # uncomment to replace; null/empty 422
    # 'issue_tracker_uri': 'https://...',       # uncomment to set, or null to clear
    # 'aliases': ['payments', 'billing'],       # uncomment to replace; [] or null to clear
}))
" > .scratch/update-body.json

curl -fsS -X PUT \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "Content-Type: application/json" \
     --data @.scratch/update-body.json \
     "$TITAN_TYR_URL/parts/{name}"
```

### 9. Report

On `200`, summarise:

> Updated `<name>` to version `<new-version>`.
> Read it back: `curl -H 'Authorization: Bearer sysmlv2' $TITAN_TYR_URL/parts/<name>`

Note whether the update closed any template drift (stamp now matches
active template), or whether it only addressed content.

## Error handling

| Status | Meaning                                                             | What to do                                                                  |
| ------ | ------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                                    | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `404`  | Software not registered                                             | Stop. Point at `/register-part`.                                        |
| `409`  | New `version` not strictly greater than current                     | Bump beyond current; suggest the next sensible value.                       |
| `422`  | Malformed `version` (e.g. `1.0`, `1.0.0-rc1`)                       | Software versions are plain `MAJOR.MINOR.PATCH`, no RC suffix. Suggest a fix. |
| `5xx`  | Server problem                                                      | Print response body verbatim. Do not retry.                                 |

## Notes

- This skill mutates a single part's history. Acceptance-style
  confirmation gates (as in `/accept-template-proposal`) are not needed
  — `PUT /parts/{name}` only affects this one part's reads, not
  every caller's view of a template.
- If the user is updating purely to close template drift, mention that
  the propose/accept of the new template version was already the
  cross-cutting change; this update is just bringing one node into
  compliance. Other registered software may still be on older
  templates.
- `/register-part` and `/update-part` share the same generic
  fill rules. If those rules grow, update both in lockstep.
