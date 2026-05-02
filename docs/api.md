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

---

## Health

### `GET /health` — liveness + readiness probe

```sh
curl http://localhost:8000/health
```

No `Authorization` header required — orchestrators don't carry one.

`200` response when the API can reach Postgres:
```json
{ "status": "ok", "version": "0.4.0", "db": "reachable" }
```

`503` response when the DB query fails:
```json
{ "status": "degraded", "version": "0.4.0", "db": "unreachable" }
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

### `POST /software` — register a new software node

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     -H 'Content-Type: application/json' \
     -d '{
       "name": "payments-service",
       "repo_uri": "https://github.com/example/payments-service",
       "issue_tracker_uri": "https://example.atlassian.net/browse/PAY",
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

`201` response:
```json
{ "id": "12c3a4b5-...", "name": "payments-service", "version": "1.0.0" }
```

Errors:
- `409 Conflict` — name already taken.
- `422 Unprocessable Entity` — malformed `version` (or `-rcN` suffix),
  or `issue_tracker_uri` not a valid `https://` URL.

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
  "version": "2.1.0",
  "markdown": "# payments-service\n...",
  "updated_at": "2026-04-29T14:30:00Z"
}
```

`issue_tracker_uri` is `null` when the software was registered without
one (consumers fall back to GitHub Issues inference from `repo_uri`).

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
       "issue_tracker_uri": "https://linear.app/example/team/PAY"
     }' \
     http://localhost:8000/software/payments-service
```

`version` is required, must be plain `MAJOR.MINOR.PATCH`, and must be
strictly greater than the latest existing version for this software.

`repo_uri` and `issue_tracker_uri` are optional with **PATCH semantics**.
The two fields share the same shape; the only difference is that
`repo_uri` is required at registration and may not be cleared.

| Field               | Omitted from body         | `"...": "value"`                | `"...": null`                 |
| ------------------- | ------------------------- | ------------------------------- | ----------------------------- |
| `repo_uri`          | Existing value unchanged. | Replaces stored value.          | **422** — cannot clear.       |
| `issue_tracker_uri` | Existing value unchanged. | Replaces stored value (https-only). | Clears stored value to `null`. |

`repo_uri` accepts any non-empty string (HTTPS URLs, SSH form like
`git@github.com:owner/repo.git`, etc.) — the API does not enforce a
URL grammar on it. `issue_tracker_uri` is strictly validated as
`https://` with a host.

`200` response:
```json
{ "name": "payments-service", "version": "2.1.0" }
```

Errors:
- `404 Not Found` — software not registered.
- `409 Conflict` — `version` is not strictly greater than the latest.
- `422 Unprocessable Entity` — malformed `version`, `repo_uri` set to
  null or empty string, or `issue_tracker_uri` not a valid `https://` URL.

### `GET /software/{name}/contracts` — every contract touching this software

Returns each contract where this software appears as either owner or
counterparty, with that contract's latest active version.

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     http://localhost:8000/software/payments-service/contracts
```

`200` response:
```json
{
  "software": "payments-service",
  "contracts": [
    {
      "id": "ab12cd34-...",
      "owner": "payments-service",
      "counterparty": "orders-service",
      "version": "1.2.0",
      "markdown": "...",
      "updated_at": "2026-04-15T09:14:00Z"
    }
  ]
}
```

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
  or malformed `version`.

### `GET /contracts?owner={a}&counterparty={b}` — search by software pair

Returns the active contract(s) between the two software nodes, in
either direction. Zero, one, or two results.

```sh
curl -H 'Authorization: Bearer sysmlv2' \
     'http://localhost:8000/contracts?owner=payments-service&counterparty=orders-service'
```

`200` response (e.g. when only `payments → orders` exists):
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
