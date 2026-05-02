# API reference

This document is the practical, example-driven reference for every
endpoint titan-tyr exposes. For the underlying design (data model,
schema, versioning rules), see [`DESIGN.md`](../DESIGN.md).

The OpenAPI schema is also served live at `/openapi.json` and rendered
at `/docs` and `/redoc` when the API is running.

---

## Conventions

- All paths are JSON request / JSON response **except** the two
  `/templates/*` endpoints, which return `text/markdown`.
- Every endpoint requires `Authorization: Bearer sysmlv2` **except**
  `GET /health`, which is unauthenticated so orchestrators can probe
  it. Missing or wrong tokens on protected endpoints get `401`.
- Versions are semver strings. Software and stable contract versions
  are `MAJOR.MINOR.PATCH`. Contract proposals may additionally carry an
  `-rcN` suffix.
- Errors are returned as `{"detail": "..."}` per FastAPI convention.

### Listing pagination

`GET /software`, `GET /contracts` (list mode), and
`GET /software/{name}/contracts` are paginated.

- **Cursor-based.** Pass `?after=<cursor>` to continue from where the
  previous page ended. The cursor is an opaque base64-url-safe string;
  do not decode it.
- **Limit.** Default `50`, max `100`. `?limit=<n>` to override.
  Out-of-range → `422`.
- **Sort.** Most-recently-updated first. For software, "updated" is the
  latest version's `created_at`; for contracts, the latest active
  version's `accepted_at` (falling back to `created_at`).
- **Response shape.** `{"results": [...], "next": "<cursor>" | null}`.
  `next` is `null` on the last page.
- **Listings omit `markdown`.** Follow up with the per-row GET endpoint
  for the body.

---

## Health

### `GET /health` — liveness + readiness probe

```sh
curl http://localhost:8000/health
```

No `Authorization` header required — orchestrators don't carry one.

`200` response when the API can reach Postgres:
```json
{ "status": "ok", "version": "0.7.0", "db": "reachable" }
```

`503` response when the DB query fails:
```json
{ "status": "degraded", "version": "0.7.0", "db": "unreachable" }
```

`version` is the running titan-tyr package version (resolved from
the installed package metadata, not hardcoded). Use the 503 to fail
the pod / restart the container.

A separate split into `/livez` (process is up) and `/readyz` (can
serve traffic) is the more correct K8s pattern; deferred until
there's an actual orchestrator that benefits from the distinction.

---

## Templates

The two templates (`software`, `contract`) live in Postgres as
versioned markdown. They are mutated through the same propose/accept
flow as contracts — see Proposals below for the full RC behaviour, the
shape carries over here unchanged.

### `GET /templates/{kind}` — latest active template

```sh
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/software
```

`kind` ∈ `{software, contract}`. Response is `text/markdown` of the
latest stable active version. RC-suffixed versions are never returned
here.

`404` if `kind` is unknown.

### `POST /templates/{kind}/proposals` — propose a change

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -d '{ "version": "1.1.0-rc1", "markdown": "..." }' \
     http://localhost:8000/templates/software/proposals
```

Same rules as contract proposals: required `version` matching
`^\d+\.\d+\.\d+(-rc\d+)?$`, strictly greater than the latest existing
version on this template.

`201` response:
```json
{ "kind": "software", "version": "1.1.0-rc1", "status": "proposal" }
```

### `GET /templates/{kind}/proposals` — list open proposals

```sh
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/software/proposals
```

```json
{
  "kind": "software",
  "active_version": "1.0.0",
  "proposals": [
    { "version": "1.1.0-rc1", "markdown": "...", "created_at": "..." },
    { "version": "1.1.0",     "markdown": "...", "created_at": "..." }
  ]
}
```

### `POST /templates/{kind}/proposals/{version}/accept` — promote

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     http://localhost:8000/templates/software/proposals/1.1.0-rc2/accept
```

Stable proposal → flipped in place. RC proposal → new stable active
row created at the stripped version; the RC row stays as proposal for
posterity.

`200` response:
```json
{
  "kind": "software",
  "promoted_from_version": "1.1.0-rc2",
  "active_version": "1.1.0",
  "accepted_at": "2026-04-29T15:00:00Z"
}
```

---

## Software

### Software name format

`name` on `POST /software` and the `owner_software` / `counterparty_software`
fields on `POST /contracts` are validated against a slug pattern:

```
^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$
```

- Lowercase letters, digits, hyphens.
- 1–64 characters.
- Cannot start or end with a hyphen.
- No spaces, dots, slashes, underscores, or other punctuation.
- Examples that pass: `payments-service`, `titan-tyr`, `a1`, `x`.
- Examples that fail (`422 Unprocessable Entity`): `My Service`,
  `weird.name`, `-leading`, `trailing-`, `name@example`, `café`.

The constraint exists because names appear in URL paths
(`GET /software/{name}`) and inside contract markdown as
`owner_software` / `counterparty_software` references — anything that
would need URL-encoding or be awkward to grep is rejected at the door.

### `GET /software` — list registered software (paginated)

```sh
curl -H 'Authorization: Bearer sysmlv2' \
  'http://localhost:8000/software?limit=2'
```

`200` response:
```json
{
  "results": [
    {
      "id": "12c3a4b5-...",
      "name": "payments-service",
      "repo_uri": "https://github.com/example/payments-service",
      "issue_tracker_uri": null,
      "aliases": ["payments", "billing"],
      "version": "2.1.0",
      "updated_at": "2026-04-29T14:30:00Z"
    },
    {
      "id": "98765432-...",
      "name": "orders-service",
      "repo_uri": "https://github.com/example/orders-service",
      "issue_tracker_uri": "https://example.atlassian.net/browse/ORD",
      "aliases": [],
      "version": "1.4.2",
      "updated_at": "2026-04-28T09:00:00Z"
    }
  ],
  "next": "eyJ0IjoiMjAyNi0wNC0yOFQwOTowMDowMFoiLCJpIjoiOTg3NjU0MzItLi4uIn0"
}
```

To fetch the next page, call again with `?after=<next>`.

#### `?match=<query>` — substring lookup over name + aliases

```sh
curl -H 'Authorization: Bearer sysmlv2' \
  'http://localhost:8000/software?match=front'
```

Restricts results to software whose `name` or any entry of `aliases`
contains `<query>` as a case-insensitive substring. The query may be
1–128 characters; ILIKE wildcards (`%`, `_`) in user input are escaped
and matched literally. Combines with `?after=` and `?limit=` as usual.

This is the primary lookup path for agents that know a colloquial
label ("front end", "billing") rather than the canonical slug.
Substring is intentionally generous — collisions are allowed across
software, so callers should be prepared to disambiguate when more than
one result comes back.

### `POST /software` — register a new software node

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -d '{
       "name": "payments-service",
       "repo_uri": "https://github.com/example/payments-service",
       "issue_tracker_uri": "https://example.atlassian.net/browse/PAY",
       "aliases": ["payments", "billing"],
       "markdown": "# payments-service\n...",
       "version": "1.0.0"
     }' \
     http://localhost:8000/software
```

`version` is optional and defaults to `"1.0.0"`. It must be plain
`MAJOR.MINOR.PATCH` — software does not support `-rcN` suffixes.

`issue_tracker_uri` is **optional**. When set it is the canonical
"where to file a ticket against this software" URL — useful for teams
on Jira, Linear, or any tracker that isn't `<repo_uri>/issues`. When
absent, consumers should fall back to inferring GitHub Issues from
`repo_uri`. Validation: must be a well-formed `https://` URL with a
host (no `http://`, no `mailto:`, no bare paths).

`aliases` is **optional** and defaults to `[]`. Each entry is a
human-friendly label that should resolve to this software via
`?match=` lookups (e.g. `"front end"`, `"billing"`, `"前端"`). Per-entry
rules: 1–128 characters after trim, no control characters or
newlines, Unicode allowed, case is preserved on storage.
Within a single payload, entries are deduplicated case-insensitively
(first occurrence wins). **Cross-software collisions are allowed by
design** — `?match=` surfaces all candidates and the caller
disambiguates.

`201` response:
```json
{ "id": "12c3a4b5-...", "name": "payments-service", "version": "1.0.0" }
```

Errors:
- `409 Conflict` — name already taken.
- `422 Unprocessable Entity` — `name` not a valid slug (see above),
  malformed `version` (or `-rcN` suffix), `issue_tracker_uri` not a
  valid `https://` URL, or any `aliases` entry is empty / over 128
  chars / contains control characters.

### `GET /software/{name}` — latest description

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     http://localhost:8000/software/payments-service
```

`200` response:
```json
{
  "id": "12c3a4b5-...",
  "name": "payments-service",
  "repo_uri": "https://github.com/example/payments-service",
  "issue_tracker_uri": "https://example.atlassian.net/browse/PAY",
  "aliases": ["payments", "billing"],
  "version": "2.1.0",
  "markdown": "# payments-service\n...",
  "updated_at": "2026-04-29T14:30:00Z"
}
```

`issue_tracker_uri` is `null` when the software was registered without
one (consumers fall back to GitHub Issues inference from `repo_uri`).
`aliases` is `[]` when none were registered.

`404` if the named software does not exist.

### `PUT /software/{name}` — append a new version

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -X PUT \
     -d '{
       "version": "2.1.0",
       "markdown": "...",
       "repo_uri": "https://github.com/example/payments-service-renamed",
       "issue_tracker_uri": "https://linear.app/example/team/PAY",
       "aliases": ["payments", "billing"]
     }' \
     http://localhost:8000/software/payments-service
```

`version` is required, must be plain `MAJOR.MINOR.PATCH`, and must be
strictly greater than the latest existing version for this software.

`repo_uri`, `issue_tracker_uri`, and `aliases` are optional with
**PATCH semantics**. They share the same omit/value/null shape; the
only differences are around what null means per field.

| Field               | Omitted from body         | `"...": "value"`                    | `"...": null`                  |
| ------------------- | ------------------------- | ----------------------------------- | ------------------------------ |
| `repo_uri`          | Existing value unchanged. | Replaces stored value.              | **422** — cannot clear.        |
| `issue_tracker_uri` | Existing value unchanged. | Replaces stored value (https-only). | Clears stored value to `null`. |
| `aliases`           | Existing list unchanged.  | Replaces stored list (full set).    | Clears list to `[]`.           |

`repo_uri` accepts any non-empty string (HTTPS URLs, SSH form like
`git@github.com:owner/repo.git`, etc.) — the API does not enforce a
URL grammar on it. `issue_tracker_uri` is strictly validated as
`https://` with a host. `aliases` follows the same per-entry rules
as on register (1–128 chars, no control characters, case-preserved,
case-insensitive per-payload dedupe). Setting an empty list (`[]`) is
equivalent to setting `null` — both clear.

`200` response:
```json
{ "name": "payments-service", "version": "2.1.0" }
```

Errors:
- `404 Not Found` — software not registered.
- `409 Conflict` — `version` is not strictly greater than the latest.
- `422 Unprocessable Entity` — malformed `version`, `repo_uri` set to
  null or empty string, `issue_tracker_uri` not a valid `https://` URL,
  or any `aliases` entry violates the per-entry rules.

### `GET /software/{name}/contracts` — contracts touching this software (paginated)

Returns each contract where this software appears as either owner or
counterparty, with that contract's latest active version. Paginated.
**Markdown is not included** — follow up with `GET /contracts/{id}` for
the body.

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     'http://localhost:8000/software/payments-service/contracts?limit=10'
```

`200` response:
```json
{
  "software": "payments-service",
  "results": [
    {
      "contract_id": "ab12cd34-...",
      "owner": "payments-service",
      "counterparty": "orders-service",
      "version": "1.2.0",
      "updated_at": "2026-04-15T09:14:00Z"
    }
  ],
  "next": null
}
```

Pagination follows the conventions described above.

> **Breaking change in v0.6.0**: this endpoint previously returned a
> `contracts` key with full markdown bodies. It now returns `results`
> (no markdown) and a `next` cursor for pagination.

---

## Contracts

### `POST /contracts` — register a new interface contract

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -d '{
       "owner_software": "payments-service",
       "counterparty_software": "orders-service",
       "markdown": "...",
       "version": "1.0.0"
     }' \
     http://localhost:8000/contracts
```

`version` is optional and defaults to `"1.0.0"`. Must be plain
`MAJOR.MINOR.PATCH`.

`201` response:
```json
{
  "contract_id": "ab12cd34-...",
  "owner": "payments-service",
  "counterparty": "orders-service",
  "version": "1.0.0",
  "status": "active"
}
```

Errors:
- `404 Not Found` — either software is unknown.
- `409 Conflict` — a contract from `owner_software` to
  `counterparty_software` already exists. To change it, use
  `POST /contracts/{contract_id}/proposals`.
- `422 Unprocessable Entity` — `owner_software == counterparty_software`,
  malformed `version`, or either software reference is not a valid
  slug (see Software name format above).

### `GET /contracts` — list or search contracts

Two modes, dispatched by query parameters:

**Search mode** (`?owner=…&counterparty=…`) — both filters present.
Returns the active contract(s) between the two software nodes, in
either direction. Zero, one, or two results. Includes full `markdown`.

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     'http://localhost:8000/contracts?owner=payments-service&counterparty=orders-service'
```

```json
{
  "results": [
    {
      "contract_id": "ab12cd34-...",
      "owner": "payments-service",
      "counterparty": "orders-service",
      "version": "1.2.0",
      "markdown": "...",
      "updated_at": "2026-04-15T09:14:00Z"
    }
  ]
}
```

`404` if either software does not exist.

**List mode** (no `owner` and no `counterparty`) — paginated summary of
every contract with an active version. **No markdown** in list items.

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     'http://localhost:8000/contracts?limit=20'
```

```json
{
  "results": [
    {
      "contract_id": "ab12cd34-...",
      "owner": "payments-service",
      "counterparty": "orders-service",
      "version": "1.2.0",
      "updated_at": "2026-04-15T09:14:00Z"
    }
  ],
  "next": null
}
```

**Half-filter** (`?owner=…` alone or `?counterparty=…` alone) → `422`.
Search requires both filters; list requires neither.

### `GET /contracts/{contract_id}` — latest active contract by id

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     http://localhost:8000/contracts/ab12cd34-1234-1234-1234-1234567890ab
```

Returns the latest `status='active'` version.

`404` if the contract does not exist or has no active version yet.

---

## Proposals

Proposals are the only place the API exposes RC-suffixed versions —
all other endpoints return only stable `MAJOR.MINOR.PATCH`.

### `POST /contracts/{contract_id}/proposals` — propose a new contract body

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -d '{ "version": "1.3.0-rc1", "markdown": "..." }' \
     http://localhost:8000/contracts/ab12cd34-.../proposals
```

`version` is required, must match `MAJOR.MINOR.PATCH` or
`MAJOR.MINOR.PATCH-rcN`, and must be strictly greater than any
existing version on this contract — including any prior proposals,
under semver ordering (a stable version beats any RC at the same triple,
RC numbers compare numerically).

`201` response:
```json
{ "contract_id": "ab12cd34-...", "version": "1.3.0-rc1", "status": "proposal" }
```

Errors:
- `404 Not Found` — contract does not exist.
- `409 Conflict` — `version` is not strictly greater than the latest.
- `422 Unprocessable Entity` — malformed `version`.

### `GET /contracts/{contract_id}/proposals` — list open proposals

Returns every proposal-status version newer than the current active
version. Older proposals (now superseded by an accepted version) are
preserved in the database but excluded from this listing.

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     http://localhost:8000/contracts/ab12cd34-.../proposals
```

`200` response:
```json
{
  "contract_id": "ab12cd34-...",
  "active_version": "1.2.0",
  "proposals": [
    { "version": "1.3.0-rc1", "markdown": "...", "created_at": "..." },
    { "version": "1.3.0-rc2", "markdown": "...", "created_at": "..." },
    { "version": "2.0.0",     "markdown": "...", "created_at": "..." }
  ]
}
```

### `POST /contracts/{contract_id}/proposals/{version}/accept` — promote a proposal

The path `{version}` is the full semver string of the proposal,
e.g. `1.3.0` or `1.3.0-rc2`.

Two acceptance paths:

**Stable proposal** — the proposal row is flipped in place
(`status='proposal'` → `status='active'`, `accepted_at = now()`). The
proposed version *is* the new active version.

**RC proposal** — a new stable active row is created at
`MAJOR.MINOR.PATCH` (suffix stripped) with `markdown` copied from the
RC. The original RC row stays as `status='proposal'` for posterity.
Any earlier RCs of the same target version also remain in place.

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     http://localhost:8000/contracts/ab12cd34-.../proposals/1.3.0-rc2/accept
```

`200` response:
```json
{
  "contract_id": "ab12cd34-...",
  "promoted_from_version": "1.3.0-rc2",
  "active_version": "1.3.0",
  "accepted_at": "2026-04-29T15:00:00Z"
}
```

Errors:
- `404 Not Found` — contract or proposal does not exist.
- `409 Conflict` — the version is not in `proposal` status (e.g.
  already accepted), or you are accepting an RC whose stable target
  already exists.
- `422 Unprocessable Entity` — malformed version in the path.

---

## Status codes used

| Code | When                                                   |
| ---- | ------------------------------------------------------ |
| 200  | Successful read or in-place mutation.                  |
| 201  | Successful create.                                     |
| 401  | Missing or wrong bearer token.                         |
| 404  | Named resource does not exist.                         |
| 405  | Method not allowed on this path.                       |
| 409  | Caller-supplied state conflicts with what is stored.   |
| 422  | Request body / path failed validation.                 |
| 503  | `GET /health` only — DB is unreachable.                |
