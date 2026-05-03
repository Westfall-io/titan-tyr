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
- Versions are semver strings. Parts and stable contract versions are
  `MAJOR.MINOR.PATCH`. Contract proposals may additionally carry an
  `-rcN` suffix.
- Errors are returned as `{"detail": "..."}` per FastAPI convention.

### CORS

The API serves CORS-permissive responses to browser clients from an
allow-listed set of origins. The default allow-list (when no env vars
are set) is:

- `https://digitalforge.app` (apex)
- `https://*.digitalforge.app` (any subdomain)
- `http://localhost` and `https://localhost` on any port (local dev)

For an allowed `Origin`, every endpoint reflects the origin in
`Access-Control-Allow-Origin`. `Access-Control-Allow-Methods` covers
`GET`, `POST`, and `PUT`; `Access-Control-Allow-Headers` covers
`Authorization` and `Content-Type`. Preflight `OPTIONS` requests are
handled — they don't `405`.

For a non-allow-listed `Origin`, the API still serves the response
(CORS is a browser-side enforcement), but no
`Access-Control-Allow-Origin` is sent, so browsers block the response.

The bearer token travels in the `Authorization` header, not as a
cookie, so `Access-Control-Allow-Credentials` is not set.

#### Configuring the allow-list per deployment

Two env vars, read once at startup. Precedence is top-to-bottom:

| Env var                 | When set                                                                                                                            |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `CORS_ALLOW_ANY_ORIGIN` | `=true` → fully open (`Access-Control-Allow-Origin: *` for any `Origin`). Opt-in only; never the default. Use sparingly.            |
| `CORS_ALLOWED_ORIGINS`  | Comma-separated list of literal origins (`scheme://host[:port]`) that **replaces** the source-hardcoded default verbatim.           |
| _(neither set)_         | Falls back to the default allow-list above.                                                                                         |

Example:

```
CORS_ALLOWED_ORIGINS=https://watchervault.example.com,https://other-tenant.example.com,http://localhost:8765
```

Per-entry rules: scheme must be `http` or `https`; host required;
optional port; no path, query, fragment, or trailing slash. Whitespace
around commas is trimmed; empty entries are skipped. Plain `*` is
**rejected** — use `CORS_ALLOW_ANY_ORIGIN=true` if that's what you
mean. Wildcard subdomains (e.g. `https://*.example.com`) are out of
scope for this env var; those need source-side regex configuration.

Invalid entries fail the API at startup with a clear error, so
misconfiguration is loud, not silent.

### Listing pagination

`GET /parts`, `GET /contracts` (list mode),
`GET /parts/{name}/contracts`, `GET /parts/{name}/history`, and
`GET /contracts/{contract_id}/history` are paginated.

- **Cursor-based.** Pass `?after=<cursor>` to continue from where the
  previous page ended. The cursor is an opaque base64-url-safe string;
  do not decode it.
- **Limit.** Default `50`, max `100`. `?limit=<n>` to override.
  Out-of-range → `422`.
- **Sort.** Most-recently-updated first. For parts, "updated" is the
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
{ "status": "ok", "version": "0.9.0", "db": "reachable" }
```

`503` response when the DB query fails:
```json
{ "status": "degraded", "version": "0.9.0", "db": "unreachable" }
```

`version` is the running titan-tyr package version (resolved from
the installed package metadata, not hardcoded). Use the 503 to fail
the pod / restart the container.

A separate split into `/livez` (process is up) and `/readyz` (can
serve traffic) is the more correct K8s pattern; deferred until
there's an actual orchestrator that benefits from the distinction.

---

## Templates

The three templates (`software`, `container`, `contract`) live in
Postgres as versioned markdown. They are mutated through the same
propose/accept flow as contracts — see Proposals below for the full
RC behaviour, the shape carries over here unchanged.

`software` and `container` are the two part subtypes; the matching
template is fetched at registration time depending on which subtype
the caller is creating.

### `GET /templates/{kind}` — latest active template

```sh
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/software
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/container
```

`kind` ∈ `{software, container, contract}`. Response is `text/markdown`
of the latest stable active version. RC-suffixed versions are never
returned here.

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

## Parts

Parts are the typed nodes in titan-tyr's graph. Every part carries a
`subtype` discriminator that selects which template was used to fill
its body:

| Subtype     | What it represents                                                                |
| ----------- | --------------------------------------------------------------------------------- |
| `software`  | A codebase / deployable boundary (a repo, a service, a library).                  |
| `container` | A running instance of an image — typically one row per `(software, environment)`. |

The `subtype` field is required at registration time and is
**immutable** afterward. Subtype-specific markdown structure lives in
the matching template (`/templates/software` or `/templates/container`),
not in the API surface.

### Part name format

`name` on `POST /parts` and the `owner_part` / `counterparty_part`
fields on `POST /contracts` are validated against a slug pattern:

```
^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$
```

- Lowercase letters, digits, hyphens.
- 1–64 characters.
- Cannot start or end with a hyphen.
- No spaces, dots, slashes, underscores, or other punctuation.
- Examples that pass: `payments-service`, `payments-prod`, `titan-tyr`, `a1`.
- Examples that fail (`422 Unprocessable Entity`): `My Service`,
  `weird.name`, `-leading`, `trailing-`, `name@example`, `café`.

The constraint exists because names appear in URL paths
(`GET /parts/{name}`) and inside contract markdown as
`owner_part` / `counterparty_part` references — anything that would
need URL-encoding or be awkward to grep is rejected at the door.

**One namespace across subtypes.** `name` is unique across software
AND container parts. A common convention is `<service>` for the
software part and `<service>-<env>` for the container
(`payments`, `payments-prod`).

### `GET /parts` — list registered parts (paginated)

```sh
curl -H 'Authorization: Bearer sysmlv2' \
  'http://localhost:8000/parts?limit=2'
```

`200` response:
```json
{
  "results": [
    {
      "id": "12c3a4b5-...",
      "name": "payments-service",
      "subtype": "software",
      "repo_uri": "https://github.com/example/payments-service",
      "issue_tracker_uri": null,
      "aliases": ["payments", "billing"],
      "version": "2.1.0",
      "updated_at": "2026-04-29T14:30:00Z"
    },
    {
      "id": "98765432-...",
      "name": "payments-prod",
      "subtype": "container",
      "repo_uri": "https://github.com/example/payments-service",
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

#### `?subtype=<software|container>` — filter by subtype

```sh
curl -H 'Authorization: Bearer sysmlv2' \
  'http://localhost:8000/parts?subtype=container'
```

Restricts results to parts of the named subtype. Combines with
`?match=`, `?after=`, and `?limit=`. `422` if the value is anything
other than `software` or `container`.

#### `?match=<query>` — substring lookup over name + aliases

```sh
curl -H 'Authorization: Bearer sysmlv2' \
  'http://localhost:8000/parts?match=front'
```

Restricts results to parts whose `name` or any entry of `aliases`
contains `<query>` as a case-insensitive substring. The query may be
1–128 characters; ILIKE wildcards (`%`, `_`) in user input are escaped
and matched literally. Combines with `?after=`, `?limit=`, and
`?subtype=` as usual.

This is the primary lookup path for agents that know a colloquial
label ("front end", "billing") rather than the canonical slug.
Substring is intentionally generous — collisions are allowed across
parts, so callers should be prepared to disambiguate when more than
one result comes back.

### `POST /parts` — register a new part

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -d '{
       "name": "payments-service",
       "subtype": "software",
       "repo_uri": "https://github.com/example/payments-service",
       "issue_tracker_uri": "https://example.atlassian.net/browse/PAY",
       "aliases": ["payments", "billing"],
       "markdown": "# payments-service\n...",
       "version": "1.0.0"
     }' \
     http://localhost:8000/parts
```

`subtype` is **required** and must be one of `software`, `container`.
It is set at registration time and cannot be changed afterward.

`version` is optional and defaults to `"1.0.0"`. It must be plain
`MAJOR.MINOR.PATCH` — parts do not support `-rcN` suffixes.

`issue_tracker_uri` is **optional**. When set it is the canonical
"where to file a ticket against this part" URL — useful for teams
on Jira, Linear, or any tracker that isn't `<repo_uri>/issues`. When
absent, consumers should fall back to inferring GitHub Issues from
`repo_uri`. Validation: must be a well-formed `https://` URL with a
host (no `http://`, no `mailto:`, no bare paths).

`aliases` is **optional** and defaults to `[]`. Each entry is a
human-friendly label that should resolve to this part via
`?match=` lookups (e.g. `"front end"`, `"billing"`, `"前端"`). Per-entry
rules: 1–128 characters after trim, no control characters or
newlines, Unicode allowed, case is preserved on storage.
Within a single payload, entries are deduplicated case-insensitively
(first occurrence wins). **Cross-part collisions are allowed by
design** — `?match=` surfaces all candidates and the caller
disambiguates.

`201` response:
```json
{ "id": "12c3a4b5-...", "name": "payments-service", "subtype": "software", "version": "1.0.0" }
```

Errors:
- `409 Conflict` — name already taken (across all subtypes — names are
  one namespace).
- `422 Unprocessable Entity` — `name` not a valid slug (see above),
  `subtype` missing or not one of `software` / `container`, malformed
  `version` (or `-rcN` suffix), `issue_tracker_uri` not a valid
  `https://` URL, or any `aliases` entry is empty / over 128 chars /
  contains control characters.

### `GET /parts/{name}` — latest description

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     http://localhost:8000/parts/payments-service
```

`200` response:
```json
{
  "id": "12c3a4b5-...",
  "name": "payments-service",
  "subtype": "software",
  "repo_uri": "https://github.com/example/payments-service",
  "issue_tracker_uri": "https://example.atlassian.net/browse/PAY",
  "aliases": ["payments", "billing"],
  "version": "2.1.0",
  "markdown": "# payments-service\n...",
  "updated_at": "2026-04-29T14:30:00Z"
}
```

`issue_tracker_uri` is `null` when the part was registered without
one (consumers fall back to GitHub Issues inference from `repo_uri`).
`aliases` is `[]` when none were registered.

`404` if the named part does not exist.

### `PUT /parts/{name}` — append a new version

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
     http://localhost:8000/parts/payments-service
```

`version` is required, must be plain `MAJOR.MINOR.PATCH`, and must be
strictly greater than the latest existing version for this part.

`subtype` cannot be changed via PUT — it's structural; register a new
part if you need a different subtype.

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
- `404 Not Found` — part not registered.
- `409 Conflict` — `version` is not strictly greater than the latest.
- `422 Unprocessable Entity` — malformed `version`, `repo_uri` set to
  null or empty string, `issue_tracker_uri` not a valid `https://` URL,
  or any `aliases` entry violates the per-entry rules.

### `GET /parts/{name}/contracts` — contracts touching this part (paginated)

Returns each contract where this part appears as either owner or
counterparty, with that contract's latest active version. Paginated.
**Markdown is not included** — follow up with `GET /contracts/{id}` for
the body.

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     'http://localhost:8000/parts/payments-service/contracts?limit=10'
```

`200` response:
```json
{
  "part": "payments-service",
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

> **Breaking change in v0.9.0**: `software` was renamed to `part`
> throughout. The endpoint moved from `/software/{name}/contracts` to
> `/parts/{name}/contracts`, and the response key flipped from
> `software` to `part`.

### `GET /parts/{name}/history` — accepted version timeline (paginated)

Lists every version of this part, most-recent first. One entry per
row in `part_versions` (every PUT appends a row). **Markdown is
not included** — fetch full bodies via `GET /parts/{name}` for the
current head; per-version body retrieval is out of scope today.

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     'http://localhost:8000/parts/payments-service/history?limit=10'
```

`200` response:
```json
{
  "results": [
    { "version": "1.2.0", "updated_at": "2026-04-15T09:14:00Z" },
    { "version": "1.1.1", "updated_at": "2026-03-22T17:02:11Z" },
    { "version": "1.0.0", "updated_at": "2026-02-01T08:30:00Z" }
  ],
  "next": null
}
```

Pagination follows the conventions described above.

Errors:
- `404 Not Found` — part not registered.

---

## Contracts

### `POST /contracts` — register a new interface contract

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -d '{
       "owner_part": "payments-service",
       "counterparty_part": "orders-service",
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
- `404 Not Found` — either part is unknown.
- `409 Conflict` — a contract from `owner_part` to
  `counterparty_part` already exists. To change it, use
  `POST /contracts/{contract_id}/proposals`.
- `422 Unprocessable Entity` — `owner_part == counterparty_part`,
  malformed `version`, or either part reference is not a valid
  slug (see Part name format above).

### `GET /contracts` — list or search contracts

Two modes, dispatched by query parameters:

**Search mode** (`?owner=…&counterparty=…`) — both filters present.
Returns the active contract(s) between the two parts, in
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

`404` if either part does not exist.

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

### `GET /contracts/{contract_id}/history` — accepted version timeline (paginated)

Lists every accepted version of this contract, most-recent first. One
entry per `status='active'` row in `contract_versions` — superseded RC
proposals are **not** included (consult
`GET /contracts/{contract_id}/proposals` for the proposal pipeline).
**Markdown is not included.**

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     'http://localhost:8000/contracts/ab12cd34-1234-1234-1234-1234567890ab/history?limit=10'
```

`200` response:
```json
{
  "results": [
    { "version": "1.2.0", "updated_at": "2026-04-15T09:14:00Z" },
    { "version": "1.1.1", "updated_at": "2026-03-22T17:02:11Z" },
    { "version": "1.0.0", "updated_at": "2026-02-01T08:30:00Z" }
  ],
  "next": null
}
```

`updated_at` is the row's `accepted_at` when it was promoted from a
proposal, otherwise its `created_at` (e.g. the initial `1.0.0` written
by `POST /contracts`). Pagination follows the conventions above.

Errors:
- `404 Not Found` — contract id does not exist.

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
