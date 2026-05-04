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

The eight templates (`software`, `container`, `image`, `pod`,
`compose`, `interaction`, `binding`, `connection`) live in Postgres
as versioned markdown. They are mutated through the same
propose/accept flow as contracts — see Proposals below for the full
RC behaviour, the shape carries over here unchanged.

Every template kind matches a subtype:
`software`/`container`/`image`/`pod`/`compose` are the five part
subtypes; `interaction`/`binding`/`connection` are the three
contract subtypes. The matching template is fetched at registration
time depending on which subtype the caller is creating.

> **Breaking change in v0.10.0**: template kind `contract` was renamed
> to `interaction` to match the new contract subtype names. Callers
> hitting `/templates/contract` will get `404` — switch to
> `/templates/interaction`. The body content is unchanged (the same
> `templates` row, just with a renamed `kind`).

> **New in v0.11.0**: template kind `connection` added (#32) — the
> body for the new `connection` contract subtype. See the Contracts
> section for the per-label From/To Part type rules.

> **New in v0.12.0**: template kind `image` added (#35) — the body
> for the new `image` Part subtype (built artifact between source
> and container). Unblocks the `builds-from` and `instantiates`
> (container arm) connection labels end-to-end.

> **New in v0.13.0**: template kind `pod` added (#36) — the body
> for the new `pod` Part subtype (K8s scheduled unit). Also
> unblocks the pod arms of `instantiates` and `runs`, and relaxes
> the `binding` source rule to admit either container or pod.

> **New in v0.14.0**: template kind `compose` added (#37) — the
> body for the new `compose` Part subtype (Docker Compose stack).
> Unblocks `connection_type=member-of` (container → compose)
> end-to-end. With this every `connection_type` arm has both Part
> subtypes implemented.

### `GET /templates/{kind}` — latest active template

```sh
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/software
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/container
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/image
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/pod
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/compose
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/interaction
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/binding
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/connection
```

`kind` ∈ `{software, container, image, pod, compose, interaction, binding, connection}`.
Response is `text/markdown` of the latest stable active version.
RC-suffixed versions are never returned here.

`404` if `kind` is unknown.

### `POST /templates/{kind}/proposals` — propose a change

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -H 'X-Actor: alice' \
     -d '{ "version": "1.1.0-rc1", "markdown": "..." }' \
     http://localhost:8000/templates/software/proposals
```

Same rules as contract proposals: required `version` matching
`^\d+\.\d+\.\d+(-rc\d+)?$`, strictly greater than the latest existing
version on this template.

`X-Actor` (optional) is recorded as `proposer_actor`. See
[Two-party attribution](#two-party-attribution-x-actor-handshake) under
Proposals — the same rule applies to the template flow.

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
    {
      "version": "1.1.0-rc1",
      "markdown": "...",
      "created_at": "...",
      "proposer_actor": "alice",
      "acceptor_actor": null,
      "single_operator_override": false
    }
  ]
}
```

The `proposer_actor`, `acceptor_actor`, and
`single_operator_override` fields are present in v0.16.0+ (#38);
pre-v0.16.0 responses omitted them.

### `POST /templates/{kind}/proposals/{version}/accept` — promote

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     -H 'X-Actor: bob' \
     http://localhost:8000/templates/software/proposals/1.1.0-rc2/accept
```

Stable proposal → flipped in place. RC proposal → new stable active
row created at the stripped version; the RC row stays as proposal for
posterity.

`X-Actor` is checked against the proposal row's `proposer_actor`
(provider v0.16.0+, #38); rejected with `422` if equal unless
`?single_operator=true` is set. Templates affect every consumer; the
two-party gate matters more here than for any single contract.

`200` response:
```json
{
  "kind": "software",
  "promoted_from_version": "1.1.0-rc2",
  "active_version": "1.1.0",
  "accepted_at": "2026-04-29T15:00:00Z",
  "proposer_actor": "alice",
  "acceptor_actor": "bob",
  "single_operator_override": false
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
| `image`     | A built artifact (tagged Docker image, Helm chart version, packaged binary). Sits between source repo and running instance. |
| `container` | A running instance of an image — typically one row per `(software, environment)`. Docker / Compose runtime. |
| `pod`       | The K8s sibling of `container` — a scheduled unit of one or more co-located containers sharing a network namespace and storage. |
| `compose`   | A Docker Compose stack — a collection of services declared in a `compose.yaml`. Metadata about the file; the `member-of` Connection ties container parts into this stack. |

The `subtype` field is required at registration time and is
**immutable** afterward. Subtype-specific markdown structure lives in
the matching template (`/templates/software`, `/templates/image`,
`/templates/container`, `/templates/pod`, or `/templates/compose`),
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

**One namespace across subtypes.** `name` is unique across software,
image, container, pod, AND compose parts. A common convention is
`<service>` for the software part, `<service>-image` for the
canonical image built from it, `<service>-<env>` for the container,
`<service>-pod` for the K8s pod, and `<repo>-stack` for the Compose
stack (`payments`, `payments-image`, `payments-prod`, `payments-pod`,
`watchervault-stack`).

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

#### `?subtype=<software|image|container|pod|compose>` — filter by subtype

```sh
curl -H 'Authorization: Bearer sysmlv2' \
  'http://localhost:8000/parts?subtype=container'
```

Restricts results to parts of the named subtype. Combines with
`?match=`, `?after=`, and `?limit=`. `422` if the value is anything
other than `software`, `image`, `container`, `pod`, or `compose`.

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
     -H 'X-Actor: alice' \
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

`X-Actor` (optional, provider v0.16.0+, #39) is recorded as the
part's `created_by_actor`. There is no propose/accept dance on
initial creation — this is a one-shot active write — so the
`X-Actor` is the only attribution the row will ever carry until it
gets its first body bump or subtype shift. Subsequent changes carry
their own proposer/acceptor actors. Pre-v0.16.0 rows have
`created_by_actor: null`.

`subtype` is **required** and must be one of `software`, `image`,
`container`, `pod`, `compose`. It is set at registration time and
cannot be changed afterward.

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

`201` response (provider v0.20.0+, #47): the full persisted row,
same shape as `GET /parts/{name}`:
```json
{
  "id": "12c3a4b5-...",
  "name": "payments-service",
  "subtype": "software",
  "repo_uri": "https://github.com/example/payments-service",
  "issue_tracker_uri": null,
  "aliases": [],
  "version": "1.0.0",
  "markdown": "# payments-service\n...",
  "updated_at": "2026-04-29T14:30:00Z",
  "created_by_actor": "alice@example.com",
  "project": null
}
```

> **Pre-v0.20.0** the response was the bare
> `{ "id", "name", "subtype", "version" }`. The widening is purely
> additive (existing fields preserved); consumers reading only `name`
> or `version` continue to work without change.

Errors:
- `409 Conflict` — name already taken (across all subtypes — names are
  one namespace).
- `422 Unprocessable Entity` — `name` not a valid slug (see above),
  `subtype` missing or not one of `software` / `image` / `container`
  / `pod` / `compose`, malformed
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

> **`X-Actor` and `created_by_actor`** (provider v0.21.0+, #54).
> If the part's `created_by_actor` is currently `null`, an
> `X-Actor: <identity>` header on this PUT will **claim** the row —
> first-write-wins. Once `created_by_actor` is set, subsequent PUTs
> ignore X-Actor on this field (no identity-spoofing of attributed
> rows).

`200` response (provider v0.20.0+, #47): the full persisted row,
same shape as `GET /parts/{name}` and `POST /parts`. Eliminates the
verify-with-GET round-trip — `update-part` callers can render the
echoed `markdown`, `updated_at`, and project / metadata fields
straight from the PUT response.

```json
{
  "id": "12c3a4b5-...",
  "name": "payments-service",
  "subtype": "software",
  "repo_uri": "https://github.com/example/payments-service-renamed",
  "issue_tracker_uri": "https://linear.app/example/team/PAY",
  "aliases": ["payments", "billing"],
  "version": "2.1.0",
  "markdown": "...",
  "updated_at": "2026-04-29T14:30:00Z",
  "created_by_actor": "alice@example.com",
  "project": null
}
```

> **Pre-v0.20.0** the response was the bare
> `{ "name", "version" }`. The widening is purely additive; consumers
> reading only those two fields continue to work without change.

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
      "subtype": "interaction",
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

### `GET /parts/{name}/history` — accepted timeline (paginated)

Lists every accepted change to this part, most-recent first. Two
event kinds are merged into one stream:

- `body_bump` — one entry per row in `part_versions` (every PUT
  appends a row).
- `subtype_shift` — one entry per accepted row in
  `part_subtype_proposals` (see [Subtype shifts](#subtype-shifts)).

**Markdown is not included** — fetch the current head body via
`GET /parts/{name}`; per-version body retrieval is out of scope today.

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     'http://localhost:8000/parts/payments-service/history?limit=10'
```

`200` response:
```json
{
  "results": [
    { "kind": "subtype_shift", "version": "1.2.0", "updated_at": "2026-05-02T11:00:00Z" },
    { "kind": "body_bump",     "version": "1.2.0", "updated_at": "2026-04-15T09:14:00Z" },
    { "kind": "body_bump",     "version": "1.1.1", "updated_at": "2026-03-22T17:02:11Z" },
    { "kind": "body_bump",     "version": "1.0.0", "updated_at": "2026-02-01T08:30:00Z" }
  ],
  "next": null
}
```

For `subtype_shift` entries, `version` is the latest body version at
shift time (the shift does not bump the version) and `updated_at` is
the proposal's `accepted_at`. For `body_bump` entries, `updated_at`
is the version row's `created_at`.

> **Backwards compat**: `kind` defaults to `"body_bump"` when omitted
> by older clients' parsers; pre-v0.15.0 history responses lacked the
> field entirely and are equivalent to "all `body_bump`".

Pagination follows the conventions described above.

Errors:
- `404 Not Found` — part not registered.

---

## Contracts

Contracts are directed edges between two parts. Every contract carries
a `subtype` discriminator that selects which template was used to fill
its body and which validation rules apply at registration:

| Subtype       | What it represents                                                                       | Source (owner_part)             | Target (counterparty_part)            |
| ------------- | ---------------------------------------------------------------------------------------- | ------------------------------- | ------------------------------------- |
| `interaction` | Protocol/schema-level agreement (HTTP API, queue topic, RPC). Env-agnostic. Runtime data flows. | any                             | any                                   |
| `binding`     | Deployment address binding from a runtime (container or pod) to a software part. Env-specific. Runtime.   | `container` or `pod`            | `software`                            |
| `connection`  | Structural binding declared in build/config/deploy artifacts. **No runtime data flow.**  | depends on `connection_type`    | depends on `connection_type`          |

The `subtype` field is required at registration time and is
**immutable** afterward (no PUT path mutates it; subsequent versions
go through propose/accept).

#### Connection sub-discriminator

`connection` contracts additionally carry a `connection_type` label
selecting one of six structural binding kinds. The label is required
when `subtype = "connection"` and rejected for any other subtype. Each
label has its own From/To Part subtype rule:

| `connection_type` | Owner part subtype  | Counterparty part subtype | What it records                                     |
| ----------------- | ------------------- | ------------------------- | --------------------------------------------------- |
| `builds-from`     | `software`          | `image`                   | Repository builds into image (Dockerfile + CI)      |
| `instantiates`    | `image`             | `container` or `pod`      | Image is run as a container or pod                  |
| `runs`            | `container` or `pod`| `software`                | Runtime hosts a specific software process            |
| `member-of`       | `container`         | `compose`                 | Container is a service entry in a compose stack     |
| `depends-on`      | `container`         | `container`               | Startup ordering within a compose stack              |
| `submodule`       | `software`          | `software`                | One repository includes another via `.gitmodules`   |

All six labels work end-to-end after #37. The router still has a
deferred-subtype guard for any future rule that references a
not-yet-implemented Part subtype, but no current rule trips it.
Tracking issues:
- `image` Part subtype → shipped in #35.
- `pod` Part subtype → shipped in #36.
- `compose` Part subtype → shipped in #37.

The unique constraint is on `(owner_part_id, counterparty_part_id)` —
subtype is **not** part of the key, so `A → B` can hold one contract
total, not one per subtype.

### `POST /contracts` — register a new contract

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -H 'X-Actor: alice' \
     -d '{
       "owner_part": "payments-service",
       "counterparty_part": "orders-service",
       "subtype": "interaction",
       "markdown": "...",
       "version": "1.0.0"
     }' \
     http://localhost:8000/contracts
```

`X-Actor` (optional, provider v0.16.0+, #39) is recorded as the
contract's `created_by_actor`. Same posture as `POST /parts` — a
one-shot active create with no propose/accept handshake; this is
the only attribution the row gets until it acquires its first
content proposal or subtype shift. Pre-v0.16.0 rows have
`created_by_actor: null`.

`subtype` is **required** and must be one of `interaction`, `binding`,
`connection`.

For `binding` specifically, the API additionally enforces:
- `owner_part.subtype == "container"`
- `counterparty_part.subtype == "software"`

For `connection` specifically:
- `connection_type` is **required** (one of the six labels above)
- The per-label From/To rule applies (see table above)
- Labels referencing un-implemented Part subtypes reject at
  registration with a "not yet implemented" error

`interaction` has no source/target subtype constraints — any (part,
part) pair is valid (preserves today's behaviour).

`version` is optional and defaults to `"1.0.0"`. Must be plain
`MAJOR.MINOR.PATCH`.

`201` response:
```json
{
  "contract_id": "ab12cd34-...",
  "owner": "payments-service",
  "counterparty": "orders-service",
  "subtype": "interaction",
  "version": "1.0.0",
  "status": "active"
}
```

Errors:
- `404 Not Found` — either part is unknown.
- `409 Conflict` — a contract from `owner_part` to
  `counterparty_part` already exists in any subtype. To change it, use
  `POST /contracts/{contract_id}/proposals`.
- `422 Unprocessable Entity` — `owner_part == counterparty_part`,
  `subtype` missing or not one of `interaction`/`binding`/`connection`,
  `connection_type` missing/wrong (required iff `subtype=connection`,
  rejected otherwise), malformed `version`, either part reference is
  not a valid slug (see Part name format above), `binding`
  source/target subtype mismatch (e.g. a `binding` contract with a
  software owner), `connection` source/target subtype mismatch per the
  per-label rule, or a `connection_type` whose required Part subtype
  is not yet implemented.

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
      "subtype": "interaction",
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
      "subtype": "interaction",
      "version": "1.2.0",
      "updated_at": "2026-04-15T09:14:00Z"
    }
  ],
  "next": null
}
```

#### `?subtype=<interaction|binding|connection>` — filter by subtype

```sh
curl -H 'Authorization: Bearer sysmlv2' \
  'http://localhost:8000/contracts?subtype=binding'
```

Restricts results to contracts of the named subtype. Combines with
both modes (search and list). `422` if the value is anything other
than `interaction`, `binding`, or `connection`.

#### `?connection_type=<label>` — filter by connection sub-label

```sh
curl -H 'Authorization: Bearer sysmlv2' \
  'http://localhost:8000/contracts?subtype=connection&connection_type=depends-on'
```

Only meaningful with `subtype=connection`. Combining
`?connection_type=` with `?subtype=interaction` or `?subtype=binding`
→ `422`. Unknown label values → `422` listing the six allowed labels.

> **New in v0.11.0**: `connection` subtype + `connection_type`
> sub-discriminator (#32). Existing rows are unaffected; their
> `connection_type` is `null`. Listings, search, and detail responses
> include `connection_type` for every contract; it is `null` for
> `interaction` and `binding`.

> **New in v0.12.0**: `image` Part subtype (#35). Unblocks
> `connection_type=builds-from` (software → image) and
> `connection_type=instantiates` to a container (image → container)
> end-to-end.

> **New in v0.13.0**: `pod` Part subtype (#36). Unblocks the pod
> arms of `connection_type=instantiates` (image → pod) and
> `connection_type=runs` (pod → software), and relaxes the
> `binding` source rule from container-only to either container
> or pod.

> **New in v0.14.0**: `compose` Part subtype (#37). Unblocks
> `connection_type=member-of` (container → compose) end-to-end.
> With this every `connection_type` arm has both Part subtypes
> implemented.

**Half-filter** (`?owner=…` alone or `?counterparty=…` alone) → `422`.
Search requires both filters; list requires neither.

### `GET /contracts/{contract_id}` — latest active contract by id

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     http://localhost:8000/contracts/ab12cd34-1234-1234-1234-1234567890ab
```

Returns the latest `status='active'` version. Response includes the
contract's immutable `subtype`:

```json
{
  "contract_id": "ab12cd34-...",
  "owner": "payments-service",
  "counterparty": "orders-service",
  "subtype": "interaction",
  "version": "1.2.0",
  "markdown": "# payments-service ↔ orders-service\n...",
  "updated_at": "2026-04-15T09:14:00Z"
}
```

`404` if the contract does not exist or has no active version yet.

### `PUT /contracts/{contract_id}` — soft metadata PATCH (provider v0.21.0+, #52, #53)

Updates **only soft metadata** on an existing contract — today, the
optional `project` tag. Body / version / subtype / connection_type /
endpoints all flow through their dedicated propose-accept endpoints
(`/proposals`, `/subtype-proposals`, `/endpoint-proposals`); this
PUT does not touch any of them. No version bump.

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -X PUT \
     -d '{"project": "watchervault"}' \
     http://localhost:8000/contracts/ab12cd34-1234-1234-1234-1234567890ab
```

PATCH semantics on `project` (mirrors `PUT /parts/{name}`):

| Field     | Omitted from body         | `"project": "<slug>"`                         | `"project": null`                |
| --------- | ------------------------- | --------------------------------------------- | -------------------------------- |
| `project` | Existing tag unchanged.   | Reassigns to that project (422 if unknown).   | Clears tag (move to unprojected). |

An empty body (`{}`) is valid — it makes no field change but still
runs the `created_by_actor` backfill below if `X-Actor` is sent.

> **`X-Actor` and `created_by_actor`** (provider v0.21.0+, #54).
> If the contract's `created_by_actor` is currently `null`, an
> `X-Actor: <identity>` header on this PUT will **claim** the row —
> first-write-wins. Once `created_by_actor` is set, subsequent PUTs
> ignore X-Actor on this field (no identity-spoofing of attributed
> rows). Per-version actor (proposer / acceptor of body changes,
> shift acceptances) lives on the proposal/accept rows and now
> surfaces on `GET /contracts/{contract_id}/history` (see below).

`200` response: the full persisted row, same shape as
`GET /contracts/{contract_id}`.

Errors:
- `404 Not Found` — contract id does not exist.
- `422 Unprocessable Entity` — `project` slug malformed or
  references an unknown project.

### `GET /contracts/{contract_id}/history` — accepted timeline (paginated)

Lists every accepted change to this contract, most-recent first. Two
event kinds are merged into one stream:

- `body_bump` — one entry per `status='active'` row in
  `contract_versions`. Superseded RC proposals are **not** included
  (consult `GET /contracts/{contract_id}/proposals` for the proposal
  pipeline).
- `subtype_shift` — one entry per accepted row in
  `contract_subtype_proposals` (see [Subtype shifts](#subtype-shifts)).

**Markdown is not included.**

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     'http://localhost:8000/contracts/ab12cd34-1234-1234-1234-1234567890ab/history?limit=10'
```

`200` response (provider v0.21.0+, #54): each entry now carries
optional per-version actor fields. `proposer_actor` and
`acceptor_actor` come from the underlying row's recorded X-Actor at
propose / accept time; `single_operator_override` is `true` when
the accept was made under `?single_operator=true`. All three are
optional — pre-#38 rows surface them as `null` / `false`.

```json
{
  "results": [
    {
      "kind": "endpoint_shift",
      "version": "1.2.0",
      "updated_at": "2026-05-04T10:00:00Z",
      "proposer_actor": "alice",
      "acceptor_actor": "bob",
      "single_operator_override": false
    },
    {
      "kind": "body_bump",
      "version": "1.2.0",
      "updated_at": "2026-04-15T09:14:00Z",
      "proposer_actor": "alice",
      "acceptor_actor": "bob",
      "single_operator_override": false
    },
    {
      "kind": "body_bump",
      "version": "1.0.0",
      "updated_at": "2026-02-01T08:30:00Z",
      "proposer_actor": null,
      "acceptor_actor": null,
      "single_operator_override": false
    }
  ],
  "next": null
}
```

For `body_bump` entries, `updated_at` is the row's `accepted_at` when
it was promoted from a proposal, otherwise its `created_at` (e.g. the
initial `1.0.0` written by `POST /contracts`). For `subtype_shift` /
`endpoint_shift` entries, `version` is the latest body version at
shift time (the shift does not bump the version) and `updated_at` is
the proposal's `accepted_at`.

> **Backwards compat**: pre-v0.15.0 history responses lacked the
> `kind` field (default to `body_bump`). Pre-v0.21.0 responses
> lacked `proposer_actor` / `acceptor_actor` /
> `single_operator_override` (consumers should default the actors
> to `null` and the override to `false`).
>
> **Parts caveat**: `GET /parts/{name}/history` always surfaces the
> three actor fields as `null` / `false`. `PartVersion` does not
> currently store per-version actor; adding the fields would
> require a schema migration. Tracked as a follow-up on #54.

Pagination follows the conventions above.

Errors:
- `404 Not Found` — contract id does not exist.

---

## Proposals

Proposals are the only place the API exposes RC-suffixed versions —
all other endpoints return only stable `MAJOR.MINOR.PATCH`.

### Two-party attribution (X-Actor handshake)

> **New in v0.16.0** (#38). All four propose / accept endpoints below
> (and the parallel template endpoints) accept an `X-Actor: <identity>`
> header. The proposer's actor is recorded on the version row;
> the acceptor's actor is checked against it on accept and rejected
> with `422` if they match — unless `?single_operator=true` is set on
> the accept call. The mechanics are identical to the
> [Subtype shifts](#subtype-shifts) two-party rule that shipped in
> v0.15.0; this section extends it to content + template proposals.

| Proposer  | Acceptor  | `?single_operator` | Result                                                  |
| --------- | --------- | ------------------ | ------------------------------------------------------- |
| set       | different | not set            | `200` accept, `single_operator_override=false`          |
| set       | same      | not set            | `422` — same actor cannot both propose and accept       |
| set       | same      | `=true`            | `200` accept, `single_operator_override=true`           |
| anonymous | any       | n/a                | `200` accept — rule unenforceable, accept proceeds      |
| any       | anonymous | n/a                | `200` accept — rule unenforceable, accept proceeds      |

The proposer / acceptor / override-flag values are stored on the
version row and surfaced on the **proposal listing** and the
**accept response**. They are intentionally **not** surfaced on the
`/history` endpoints; actor identity on history is reserved until
real per-caller auth lands.

### `POST /contracts/{contract_id}/proposals` — propose a new contract body

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -H 'X-Actor: alice' \
     -d '{ "version": "1.3.0-rc1", "markdown": "..." }' \
     http://localhost:8000/contracts/ab12cd34-.../proposals
```

`version` is required, must match `MAJOR.MINOR.PATCH` or
`MAJOR.MINOR.PATCH-rcN`, and must be strictly greater than any
existing version on this contract — including any prior proposals,
under semver ordering (a stable version beats any RC at the same triple,
RC numbers compare numerically).

`X-Actor` (optional) is recorded on the new version row as
`proposer_actor`. See "Two-party attribution" above.

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
    {
      "version": "1.3.0-rc1",
      "markdown": "...",
      "created_at": "...",
      "proposer_actor": "alice",
      "acceptor_actor": null,
      "single_operator_override": false
    },
    {
      "version": "1.3.0-rc2",
      "markdown": "...",
      "created_at": "...",
      "proposer_actor": "bob",
      "acceptor_actor": null,
      "single_operator_override": false
    },
    {
      "version": "2.0.0",
      "markdown": "...",
      "created_at": "...",
      "proposer_actor": null,
      "acceptor_actor": null,
      "single_operator_override": false
    }
  ]
}
```

The `proposer_actor`, `acceptor_actor`, and
`single_operator_override` fields are present in v0.16.0+
(#38); pre-v0.16.0 responses omitted them. Treat missing fields as
all `null` / `false`.

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
     -H 'X-Actor: bob' \
     http://localhost:8000/contracts/ab12cd34-.../proposals/1.3.0-rc2/accept
```

`X-Actor` is checked against the proposal row's `proposer_actor`;
see "Two-party attribution" above. Use
`?single_operator=true` to override for solo setups. The acceptor
actor is recorded on the resulting active row (and on the original
RC row when an RC is being promoted).

`200` response:
```json
{
  "contract_id": "ab12cd34-...",
  "promoted_from_version": "1.3.0-rc2",
  "active_version": "1.3.0",
  "accepted_at": "2026-04-29T15:00:00Z",
  "proposer_actor": "alice",
  "acceptor_actor": "bob",
  "single_operator_override": false
}
```

Errors:
- `404 Not Found` — contract or proposal does not exist.
- `409 Conflict` — the version is not in `proposal` status (e.g.
  already accepted), or you are accepting an RC whose stable target
  already exists.
- `422 Unprocessable Entity` — malformed version in the path, or
  `proposer_actor == X-Actor` without `?single_operator=true`
  (provider v0.16.0+).

---

## Subtype shifts

> **New in v0.15.0** (#33). Six endpoints — three on parts, three on
> contracts — let an operator correct a row's structural subtype
> (and, for connection contracts, the `connection_type` label)
> *without* mutating the body or bumping the version. This is the
> deliberate counterpart to content proposals (above): content
> changes go through `/proposals`; structural mis-classification
> goes through `/subtype-proposals`.

The flow is **propose → accept**, mirroring content proposals, but
the two flows are stored in separate tables and listed via separate
endpoints. Acceptance only flips the row's `subtype`
(and stamps `subtype_shifted_from` / `subtype_shifted_at`); the
body bytes and the latest version are untouched.

### Two-party rule (X-Actor handshake)

Both `POST .../subtype-proposals` and `POST
.../subtype-proposals/{id}/accept` accept an `X-Actor: <identity>`
header. The proposer's actor is recorded on the proposal row; the
acceptor's actor is checked against it.

| Proposer  | Acceptor  | `?single_operator` | Result                                                  |
| --------- | --------- | ------------------ | ------------------------------------------------------- |
| set       | different | not set            | `200` accept                                            |
| set       | same      | not set            | `422` — same actor cannot both propose and accept       |
| set       | same      | `=true`            | `200` accept (override for solo setups)                 |
| anonymous | any       | n/a                | `200` accept — rule unenforceable, accept proceeds      |
| any       | anonymous | n/a                | `200` accept — rule unenforceable, accept proceeds      |

The header is the only signal until real auth lands. Skill layers
should warn loudly when either side is anonymous.

### Soft-warn vs hard-block

- **Part shifts soft-warn.** The propose response includes
  `impact.related_rows_potentially_affected` — a list of contracts
  that would become structurally invalid under the new part subtype
  — but acceptance does **not** block. Each affected contract needs
  its own subsequent shift; the impact preview is informational.
- **Contract shifts hard-block.** The propose endpoint validates the
  new subtype's source/target rule against the current endpoint
  parts and returns `422` if it would fail. Fix the endpoint parts
  (via their own subtype shifts) before retrying.

### Body-realign signal

The propose response also includes
`impact.body_realign_required: bool`. `true` means the body's
first-line stamp (`<!-- template: <kind>@<version> -->`) names a
template kind that no longer matches the new subtype. Acceptance
does not touch the body — file a follow-up content proposal that
re-stamps to `<new-subtype>@<active-template-version>`.

### `POST /parts/{name}/subtype-proposals` — propose a part shift

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -H 'X-Actor: alice' \
     -d '{ "new_subtype": "container", "rationale": "registered as software but actually represents the prod deployment instance" }' \
     http://localhost:8000/parts/payments-service/subtype-proposals
```

`new_subtype` ∈ `{software, container, image, pod, compose}`.
`rationale` is required (1–2000 chars).

`201` response:
```json
{
  "proposal_id": "9b1f...",
  "current_subtype": "software",
  "new_subtype": "container",
  "impact": {
    "body_realign_required": true,
    "source_target_validation": "n/a",
    "related_rows_potentially_affected": [
      {
        "contract_id": "ab12...",
        "owner": "payments-service",
        "counterparty": "orders-service",
        "subtype": "interaction",
        "reason": "(informational) interaction allows any/any; no rule broken"
      }
    ]
  },
  "status": "proposal"
}
```

`source_target_validation` is `"n/a"` for parts (the rule is per
contract, not per part).

Errors:
- `404 Not Found` — part not registered.
- `409 Conflict` — `new_subtype == current` (no-op).
- `422 Unprocessable Entity` — unknown `new_subtype`, missing
  rationale, or rationale length out of bounds.

### `GET /parts/{name}/subtype-proposals` — list shift proposals

Returns every part-shift proposal regardless of status (open and
historical). Filter client-side by `status == "proposal"` for the
acceptable subset.

`200` response:
```json
{
  "name": "payments-service",
  "current_subtype": "software",
  "proposals": [
    {
      "proposal_id": "9b1f...",
      "new_subtype": "container",
      "rationale": "...",
      "proposer_actor": "alice",
      "status": "proposal",
      "impact": { "body_realign_required": true, "source_target_validation": "n/a", "related_rows_potentially_affected": [] },
      "created_at": "2026-05-02T10:30:00Z",
      "accepted_at": null,
      "acceptor_actor": null
    }
  ]
}
```

Errors:
- `404 Not Found` — part not registered.

### `POST /parts/{name}/subtype-proposals/{proposal_id}/accept` — promote a part shift

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     -H 'X-Actor: bob' \
     'http://localhost:8000/parts/payments-service/subtype-proposals/9b1f.../accept?single_operator=false'
```

`?single_operator=true` overrides the two-party rule for solo
setups (see table above).

`200` response:
```json
{
  "name": "payments-service",
  "previous_subtype": "software",
  "new_subtype": "container",
  "subtype_shifted_at": "2026-05-02T11:00:00Z",
  "acceptor_actor": "bob"
}
```

After this, `GET /parts/payments-service` returns
`subtype: "container"` with the body, version, and version history
unchanged. The shift event surfaces in
`GET /parts/payments-service/history` as a `subtype_shift` entry.

Errors:
- `404 Not Found` — part name or `proposal_id` does not exist.
- `409 Conflict` — proposal already accepted, or no-op (the part
  has shifted independently to the same subtype since propose time).
- `422 Unprocessable Entity` — `proposer_actor == acceptor_actor`
  without `?single_operator=true`.

### `POST /contracts/{contract_id}/subtype-proposals` — propose a contract shift

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -H 'X-Actor: alice' \
     -d '{ "new_subtype": "binding", "new_connection_type": null, "rationale": "owner is actually a container, this is environment-specific" }' \
     http://localhost:8000/contracts/ab12.../subtype-proposals
```

`new_subtype` ∈ `{interaction, binding, connection}`.
`new_connection_type` is **required iff** `new_subtype == "connection"`
and ∈ `{builds-from, instantiates, runs, member-of, depends-on, submodule}`;
must be `null` for the other two subtypes.

A label-only shift (subtype stays `connection`, label changes) is
**not** a no-op and is allowed; the new label's per-label
source/target rule is re-validated.

`201` response:
```json
{
  "proposal_id": "7d3e...",
  "current_subtype": "interaction",
  "current_connection_type": null,
  "new_subtype": "binding",
  "new_connection_type": null,
  "impact": {
    "body_realign_required": true,
    "source_target_validation": "pass",
    "related_rows_potentially_affected": []
  },
  "status": "proposal"
}
```

Errors:
- `404 Not Found` — contract not found.
- `409 Conflict` — no-op (subtype + connection_type both match
  current).
- `422 Unprocessable Entity` — `new_connection_type` missing iff
  `new_subtype == "connection"` (or set otherwise), the new
  subtype's source/target rule fails against the current endpoint
  parts (**hard-block**), or rationale missing / out of bounds.

### `GET /contracts/{contract_id}/subtype-proposals` — list shift proposals

Same shape as the parts listing. Open and historical proposals are
both returned; filter by `status == "proposal"` for acceptable.

### `POST /contracts/{contract_id}/subtype-proposals/{proposal_id}/accept` — promote a contract shift

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     -H 'X-Actor: bob' \
     'http://localhost:8000/contracts/ab12.../subtype-proposals/7d3e.../accept'
```

`200` response:
```json
{
  "contract_id": "ab12...",
  "previous_subtype": "interaction",
  "previous_connection_type": null,
  "new_subtype": "binding",
  "new_connection_type": null,
  "subtype_shifted_at": "2026-05-02T11:00:00Z",
  "acceptor_actor": "bob"
}
```

The accept endpoint **re-validates** the source/target rule against
the current endpoint parts (which may have shifted independently
since propose time). A proposal that was valid at propose time and
no longer is hard-blocks here too, with `422`.

Errors:
- `404 Not Found` — contract or `proposal_id` does not exist.
- `409 Conflict` — proposal already accepted, or no-op (the
  contract has shifted independently to the same shape).
- `422 Unprocessable Entity` — `proposer_actor == acceptor_actor`
  without `?single_operator=true`, or source/target rule now fails
  against current endpoint subtypes (re-propose if still wanted).

---

## Name shifts (parts)

> Renames a registered part in place. Same propose/accept handshake
> as subtype shifts; the body, version, contract endpoints, and
> proposal trail are all preserved. Contracts hold endpoints by id
> (not name), so the rename surfaces in contract responses
> automatically on the next GET via the join — there is no
> server-side cascade. Old slug 404s after acceptance; consumer
> cutover is the caller's concern.

### `POST /parts/{name}/name-proposals` — propose a part rename

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     -H 'X-Actor: alice' \
     -H 'Content-Type: application/json' \
     -d '{"new_name": "payments-service", "rationale": "drop legacy suffix"}' \
     http://localhost:8000/parts/payments-svc/name-proposals
```

Request body:
```json
{
  "new_name":  "payments-service",
  "rationale": "drop legacy svc suffix; team naming standard"
}
```

`new_name` follows the part-slug rules (lowercase, digits, hyphens;
1-64 chars; no leading/trailing hyphen; same regex as
`POST /parts`). `rationale` is required, 1-2000 chars.

`201` response:
```json
{
  "proposal_id":   "9b1f...",
  "part_name":     "payments-svc",
  "current_name":  "payments-svc",
  "new_name":      "payments-service",
  "rationale":     "drop legacy svc suffix; team naming standard",
  "proposer_actor":"alice"
}
```

Errors:
- `404 Not Found` — part does not exist.
- `409 Conflict` — `new_name == current_name` (no-op), or another
  part already owns the proposed slug.
- `422 Unprocessable Entity` — `new_name` slug invalid, missing
  `rationale`, or `rationale` length out of bounds.

### `GET /parts/{name}/name-proposals` — list rename proposals

Returns every proposal (open and historical) for the named part.
Filter by `status == "proposal"` for acceptable rows; accepted rows
are read-only history.

```json
{
  "part_name":    "payments-service",
  "current_name": "payments-service",
  "proposals": [
    {
      "proposal_id":             "9b1f...",
      "current_name_at_propose": "payments-svc",
      "new_name":                "payments-service",
      "rationale":               "drop legacy svc suffix",
      "proposer_actor":          "alice",
      "status":                  "accepted",
      "created_at":              "2026-05-04T10:00:00Z",
      "accepted_at":             "2026-05-04T10:30:00Z",
      "accepted_by":             "bob",
      "single_operator_override": false
    }
  ]
}
```

### `POST /parts/{name}/name-proposals/{proposal_id}/accept` — promote a rename

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     -H 'X-Actor: bob' \
     'http://localhost:8000/parts/payments-svc/name-proposals/9b1f.../accept'
```

`?single_operator=true` overrides the proposer-doesn't-accept rule
for solo setups. The override is recorded on the proposal row.

`200` response:
```json
{
  "proposal_id":           "9b1f...",
  "part_id":               "ab12...",
  "shifted_from_name":     "payments-svc",
  "shifted_to_name":       "payments-service",
  "accepted_at":           "2026-05-04T10:30:00Z",
  "accepted_by":           "bob",
  "single_operator_override": false
}
```

After acceptance, `GET /parts/payments-svc` returns `404` and
`GET /parts/payments-service` serves the (otherwise unchanged)
part. Existing contracts touching the part surface the new name
on their next GET.

Errors:
- `404 Not Found` — part or `proposal_id` does not exist (the part
  may have already shifted to a different slug).
- `409 Conflict` — proposal already accepted, no-op (concurrent
  shift landed first), or the proposed slug is now taken by another
  part (re-propose with a different `new_name`).
- `422 Unprocessable Entity` — `proposer_actor == acceptor_actor`
  without `?single_operator=true`.

---

## Endpoint shifts (contracts)

> Re-points one or both of a contract's `(owner_part_id,
> counterparty_part_id)` while preserving the contract id, version,
> body, subtype/connection_type, and proposal trail. Same
> propose/accept handshake as subtype shifts. Hard-blocks on
> source/target rule violation and on uniqueness collision (per
> #42's widened uniqueness key).

### `POST /contracts/{contract_id}/endpoint-proposals` — propose an endpoint shift

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     -H 'X-Actor: alice' \
     -H 'Content-Type: application/json' \
     -d '{"new_owner": "payments-service-v2", "rationale": "cutover to v2 prod"}' \
     http://localhost:8000/contracts/ab12.../endpoint-proposals
```

Request body — at least one of `new_owner` / `new_counterparty`
must be set, and the resulting `(owner, counterparty)` pair must
differ from the current pair:

```json
{
  "new_owner":        "payments-service-v2",
  "new_counterparty": null,
  "rationale":        "cutover the binding owner to the v2 deployment"
}
```

`201` response:
```json
{
  "proposal_id":         "7d3e...",
  "contract_id":         "ab12...",
  "current_owner":       "payments-service",
  "current_counterparty":"orders-service",
  "new_owner":           "payments-service-v2",
  "new_counterparty":    null,
  "rationale":           "cutover the binding owner to the v2 deployment",
  "proposer_actor":      "alice"
}
```

Errors:
- `404 Not Found` — contract or one of the named endpoint parts
  does not exist.
- `409 Conflict` — resulting `(owner, counterparty, subtype,
  connection_type)` tuple would collide with an existing contract
  (the widened uniqueness key from #42).
- `422 Unprocessable Entity` — neither side set, no-op (resolves
  to current pair), self-loop (owner == counterparty after shift),
  source/target rule violation, or invalid slug.

### `GET /contracts/{contract_id}/endpoint-proposals` — list endpoint shifts

Same shape as the subtype-proposals listing. `current_owner` /
`current_counterparty` reflect the contract's *current* endpoints
at read time (post any accepted shifts).

```json
{
  "contract_id":         "ab12...",
  "current_owner":       "payments-service-v2",
  "current_counterparty":"orders-service",
  "proposals": [
    {
      "proposal_id":                    "7d3e...",
      "current_owner_at_propose":       "payments-service",
      "current_counterparty_at_propose":"orders-service",
      "new_owner":                      "payments-service-v2",
      "new_counterparty":               null,
      "rationale":                      "cutover the binding owner to v2",
      "proposer_actor":                 "alice",
      "status":                         "accepted",
      "created_at":                     "2026-05-04T10:00:00Z",
      "accepted_at":                    "2026-05-04T10:30:00Z",
      "accepted_by":                    "bob",
      "single_operator_override":       false
    }
  ]
}
```

### `POST /contracts/{contract_id}/endpoint-proposals/{proposal_id}/accept` — promote an endpoint shift

```sh
curl -X POST -H 'Authorization: Bearer sysmlv2' \
     -H 'X-Actor: bob' \
     'http://localhost:8000/contracts/ab12.../endpoint-proposals/7d3e.../accept'
```

`?single_operator=true` overrides the proposer-doesn't-accept rule.

`200` response:
```json
{
  "proposal_id":              "7d3e...",
  "contract_id":              "ab12...",
  "shifted_from_owner":       "payments-service",
  "shifted_to_owner":         "payments-service-v2",
  "shifted_from_counterparty":"orders-service",
  "shifted_to_counterparty":  "orders-service",
  "accepted_at":              "2026-05-04T10:30:00Z",
  "accepted_by":              "bob",
  "single_operator_override": false
}
```

`shifted_from_*` / `shifted_to_*` are reported for both sides even
on a one-sided shift; the unchanged side reports the same value on
both. The on-row bookkeeping cols
(`endpoint_shifted_from_owner` / `endpoint_shifted_from_counterparty`)
record `NULL` for the unchanged side, to mark the audit trail
precisely.

The accept endpoint **re-validates** source/target and uniqueness
against the current state (endpoint subtypes may have shifted, the
contract subtype/connection_type may have shifted, or another
contract at the proposed shape may have been created since
propose time). A proposal that was valid at propose time and no
longer is fails here with `422` or `409`.

Errors:
- `404 Not Found` — contract or `proposal_id` does not exist.
- `409 Conflict` — proposal already accepted, no-op (concurrent
  shift landed first), endpoint part deleted since propose, or a
  colliding contract now exists at the proposed endpoint pair.
- `422 Unprocessable Entity` — `proposer_actor == acceptor_actor`
  without `?single_operator=true`, source/target rule no longer
  satisfied, or self-loop after shift.

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
