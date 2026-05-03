# titan-tyr — Design

**Repository:** titan-tyr
**Role:** REST API for registering parts, registering interface contracts between parts, and proposing changes to those contracts.
**Stack:** FastAPI + PostgreSQL.

---

## Purpose

titan-tyr is a graph database, exposed as a REST API, that records the
parts running in a system and the interface contracts between them.
Callers register parts (software repos, running containers), register
interface contracts that describe how one part interfaces with another,
and propose changes to contracts that already exist.

- **Nodes** — registered parts. Each part has a `subtype` discriminator
  (`software` for a codebase / deployable boundary, `container` for a
  running instance of an image).
- **Edges** — interface contracts between two parts.

Both nodes and edges carry a markdown body. All markdown is **versioned
append-only** in the database. By default, only the latest version is
returned on read.

This is a deliberately small first cut. There is no per-caller identity
and no Git integration — Postgres is the source of truth, and a single
shared password gates the API. A real authentication and authorisation
model will land in a future capability update.

---

## Data model

### Concepts

| Concept       | Stored as                                          | Notes                                               |
| ------------- | -------------------------------------------------- | --------------------------------------------------- |
| Part          | row in `parts` + N `part_versions`                 | Identified by unique name. Carries a `subtype` discriminator (`software` or `container`). |
| Contract edge | row in `contracts` + N `contract_versions`         | Directed: `owner_part → counterparty_part`.         |
| Template      | row in `templates` + N `template_versions`         | Three singletons keyed by `kind ∈ {software, container, contract}`. Served by `GET /templates/{kind}`. |
| Proposal      | a `contract_versions` or `template_versions` row with `status='proposal'` | Lives on its parent until accepted or superseded.   |

### Schema

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

CREATE TABLE parts (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL UNIQUE,
  subtype     TEXT NOT NULL CHECK (subtype IN ('software', 'container')),
  repo_uri    TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE part_versions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  part_id       UUID NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  version_major INT  NOT NULL CHECK (version_major >= 0),
  version_minor INT  NOT NULL CHECK (version_minor >= 0),
  version_patch INT  NOT NULL CHECK (version_patch >= 0),
  markdown      TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (part_id, version_major, version_minor, version_patch)
);
CREATE INDEX ON part_versions
  (part_id, version_major DESC, version_minor DESC, version_patch DESC);

CREATE TABLE contracts (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_part_id        UUID NOT NULL REFERENCES parts(id),
  counterparty_part_id UUID NOT NULL REFERENCES parts(id),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner_part_id, counterparty_part_id),
  CHECK  (owner_part_id <> counterparty_part_id)
);

CREATE TABLE contract_versions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_id   UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  version_major INT  NOT NULL CHECK (version_major >= 0),
  version_minor INT  NOT NULL CHECK (version_minor >= 0),
  version_patch INT  NOT NULL CHECK (version_patch >= 0),
  prerelease    TEXT          CHECK (prerelease ~ '^rc\d+$'),  -- NULL = stable; e.g. 'rc1', 'rc2'
  markdown      TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('active', 'proposal')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  accepted_at   TIMESTAMPTZ,                  -- set when a proposal is promoted to active
  promoted_from_prerelease TEXT,              -- on stable-active rows promoted from an RC, the RC suffix
  UNIQUE NULLS NOT DISTINCT
    (contract_id, version_major, version_minor, version_patch, prerelease),
  CHECK (status = 'active' OR prerelease IS NULL OR prerelease ~ '^rc\d+$'),
  CHECK (status = 'proposal' OR prerelease IS NULL)  -- active rows are always stable
);
CREATE INDEX ON contract_versions
  (contract_id, version_major DESC, version_minor DESC, version_patch DESC,
   prerelease DESC NULLS FIRST);
CREATE INDEX ON contract_versions (contract_id, status);

CREATE TABLE templates (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind        TEXT NOT NULL UNIQUE CHECK (kind IN ('software', 'container', 'contract')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE template_versions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id   UUID NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
  version_major INT  NOT NULL CHECK (version_major >= 0),
  version_minor INT  NOT NULL CHECK (version_minor >= 0),
  version_patch INT  NOT NULL CHECK (version_patch >= 0),
  prerelease    TEXT          CHECK (prerelease ~ '^rc\d+$'),
  markdown      TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('active', 'proposal')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  accepted_at   TIMESTAMPTZ,
  promoted_from_prerelease TEXT,
  CHECK (status = 'proposal' OR prerelease IS NULL)
);
CREATE UNIQUE INDEX
  ON template_versions (template_id, version_major, version_minor, version_patch, prerelease)
  NULLS NOT DISTINCT;
CREATE INDEX ON template_versions
  (template_id, version_major DESC, version_minor DESC, version_patch DESC,
   prerelease DESC NULLS FIRST);
CREATE INDEX ON template_versions (template_id, status);
```

The three `templates` rows (`kind='software'`, `kind='container'`,
`kind='contract'`) are seeded by the templates migrations
(`software` + `contract` in `0002_templates`, `container` in
`0005_software_to_part_subtype` alongside the table rename). The
`template_versions` schema is structurally identical to
`contract_versions` — same proposal/RC machinery, same accept-time
invariants — because templates are mutated through the same
propose-then-accept flow.

`status` is a `TEXT` column with a `CHECK` constraint, not a Postgres
`ENUM`. The set of allowed values is small today (`active`, `proposal`)
but may grow (e.g. `superseded` if we start tagging rows whose newer
version has been accepted). `ALTER TYPE` for ENUMs is half-supported
and irreversible; `TEXT + CHECK` lets us add or remove values with a
single migration that drops and recreates the constraint. Note that
`rejected` / `withdrawn` are intentionally *not* in the planned set —
see Open Questions §1.

### Versioning scheme

Versions are **caller-supplied semver** of the form `MAJOR.MINOR.PATCH`,
stored as three integer columns. Convention follows
[semver.org](https://semver.org/):

- **MAJOR** — breaking change to the contract or part interface.
- **MINOR** — backwards-compatible addition.
- **PATCH** — backwards-compatible fix or clarification (typos,
  rewording, examples).

The server cannot infer the *meaning* of a change — only the caller
knows the intent — so the version is supplied by the caller on every
write. The server validates only the mechanics:

1. **Format** — must match `^\d+\.\d+\.\d+(-rc\d+)?$`. The `-rcN`
   suffix is allowed only on contract proposals (see Pre-release
   versions below); part versions and stable contract versions
   must be plain `MAJOR.MINOR.PATCH`.
2. **Strictly greater than the current latest** — including both
   `active` and `proposal` rows for that parent. Comparison is semver
   tuple ordering: `(major, minor, patch)` first, then a stable
   version is greater than any pre-release at the same triple
   (`1.3.0 > 1.3.0-rc2 > 1.3.0-rc1`).
3. **Initial version** — if omitted on `POST /parts` or
   `POST /contracts`, defaults to `1.0.0`. May be overridden (e.g. to
   `0.1.0` for a pre-stable release).

The write happens under `SELECT … FOR UPDATE` on the parent row to
serialise concurrent writers and ensure the "strictly greater" check
cannot race.

### Pre-release versions (RCs)

Contract **proposals** may carry a `-rcN` suffix
(e.g. `1.3.0-rc1`, `1.3.0-rc2`) to stage iterations of a target
version before promoting it to a stable active release. This is the
only place the suffix is allowed:

- **Part versions** — never carry a suffix.
- **Active contract versions** — never carry a suffix
  (enforced by `CHECK (status = 'proposal' OR prerelease IS NULL)`).
- **Contract proposals** — may carry `-rcN` or be a plain
  `MAJOR.MINOR.PATCH`.

When a proposal is accepted, the server creates a new stable active
row at the plain `MAJOR.MINOR.PATCH` (suffix stripped). The original
RC row is left in place as `status='proposal'` for posterity — RC
history is preserved indefinitely. See the accept endpoint below.

**Visibility rule.** RC-suffixed versions appear *only* in responses
from proposal-specific endpoints (`POST /contracts/{id}/proposals`,
`GET /contracts/{id}/proposals`, `POST /contracts/{id}/proposals/{version}/accept`).
All other endpoints — `GET /contracts/{id}`, `GET /contracts?…`,
`GET /parts/{name}/contracts` — return only stable versions and
never expose a `-rcN` suffix in any response field.

### "Latest" semantics

- **Part** — row with the highest `(version_major, version_minor,
  version_patch)` per `part_id`.
- **Contract (active)** — highest version among `contract_versions`
  rows with `status='active'`. There is always at most one, by
  construction. Active rows never carry a `prerelease`.
- **Contract proposals** — every `contract_versions` row with
  `status='proposal'` that is newer than the current active version.
  Includes both stable proposals and RC iterations.
- **Contract latest-of-anything** (used internally for the
  strictly-greater check on writes) — `MAX` over all rows for the
  contract under semver ordering, treating `prerelease IS NULL` as
  greater than any non-null at the same triple.

---

## Authentication

> **Placeholder.** The shared password `sysmlv2` gates every endpoint.
> A real auth model — per-caller identity, fine-grained authorisation,
> rotation, audit — will land in a future capability update. Treat the
> current scheme as throwaway.

The password is sent as `Authorization: Bearer sysmlv2`. Anything else
returns `401 Unauthorized`. There is no notion of "who" made a request,
so there are no per-caller authorisation rules: any authenticated
caller can perform any action.

---

## Endpoints

All paths are relative to the API root. JSON request/response unless
otherwise noted. Every endpoint requires the bearer password above.

### Templates

Templates are stored in Postgres as versioned markdown, exactly like
contracts — same propose/accept/RC machinery. There are three
templates, identified by `kind ∈ {software, container, contract}`.
The initial v1.0.0 of `software` and `contract` is seeded by
`0002_templates`; `container` is seeded by
`0005_software_to_part_subtype` alongside the table rename.

#### `GET /templates/{kind}` — latest active template

Returns the latest stable active version as `text/markdown`. RC
suffixes are never returned here — same visibility rule that contracts
follow.

`404` if `kind` is not one of `software`, `container`, `contract`.

#### `POST /templates/{kind}/proposals` — propose a change

Request:
```json
{ "version": "1.1.0-rc1", "markdown": "..." }
```

Same rules as contract proposals: `version` may carry a `-rcN` suffix,
must match `^\d+\.\d+\.\d+(-rc\d+)?$`, must be strictly greater than
the latest existing version on this template (semver tuple ordering;
stable beats RC at the same triple).

Response `201`:
```json
{ "kind": "software", "version": "1.1.0-rc1", "status": "proposal" }
```

#### `GET /templates/{kind}/proposals` — list open proposals

Returns every proposal-status version newer than the current active
version, including RCs.

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

#### `POST /templates/{kind}/proposals/{version}/accept` — promote to active

Same two acceptance paths as contracts:

- **Stable proposal** — flipped in place; the proposed version *is*
  the new active version.
- **RC proposal** — a new stable active row is created at
  `MAJOR.MINOR.PATCH` (suffix stripped); the original RC row stays as
  `status='proposal'` for posterity.

Response `200`:
```json
{
  "kind": "software",
  "promoted_from_version": "1.1.0-rc2",
  "active_version": "1.1.0",
  "accepted_at": "2026-04-29T15:00:00Z"
}
```

### Parts

#### `POST /parts` — register a new part

Request:
```json
{
  "name":     "payments-service",
  "subtype":  "software",
  "repo_uri": "https://github.com/example/payments-service",
  "markdown": "# payments-service\n...",
  "version":  "1.0.0"
}
```

`subtype` is required (`software` or `container`) and is immutable
after registration. `version` is optional and defaults to `"1.0.0"`.

Response `201`:
```json
{
  "id":      "12c3a4b5-...",
  "name":    "payments-service",
  "subtype": "software",
  "version": "1.0.0"
}
```

Atomic: inserts `parts` and `part_versions` in one transaction.
`409 Conflict` if `name` is already taken (across all subtypes — names
are one namespace).

#### `GET /parts/{name}` — latest description

Returns part metadata + the latest `part_versions` row. `subtype` is
included so callers know which template the body conforms to.
```json
{
  "id":         "12c3a4b5-...",
  "name":       "payments-service",
  "subtype":    "software",
  "repo_uri":   "https://github.com/example/payments-service",
  "version":    "2.1.0",
  "markdown":   "# payments-service\n...",
  "updated_at": "2026-04-29T14:30:00Z"
}
```

#### `PUT /parts/{name}` — append a new description version

Request:
```json
{
  "version":  "2.1.0",
  "markdown": "# payments-service\n..."
}
```

`version` is required and must be strictly greater than the latest
existing version for this part (semver tuple comparison). `subtype`
cannot be changed via PUT.

Errors:
- `409 Conflict` if `version` is not strictly greater than the latest.
- `422 Unprocessable Entity` if `version` is malformed.

Response `200`:
```json
{ "name": "payments-service", "version": "2.1.0" }
```

#### `GET /parts/{name}/contracts` — all contracts touching this part

Returns every contract where this part is either owner or
counterparty, each with its latest active version. Paginated.
**Markdown is not included** — follow up with `GET /contracts/{id}`
for the body.

```json
{
  "part": "payments-service",
  "results": [
    {
      "contract_id":  "ab12cd34-...",
      "owner":        "payments-service",
      "counterparty": "orders-service",
      "version":      "1.2.0",
      "updated_at":   "2026-04-15T09:14:00Z"
    },
    {
      "contract_id":  "cd34ef56-...",
      "owner":        "ledger-service",
      "counterparty": "payments-service",
      "version":      "1.0.0",
      "updated_at":   "2026-04-02T11:00:00Z"
    }
  ],
  "next": null
}
```

### Contracts

#### `POST /contracts` — register a new interface contract

Request:
```json
{
  "owner_part":        "payments-service",
  "counterparty_part": "orders-service",
  "markdown":          "...",
  "version":           "1.0.0"
}
```

`version` is optional and defaults to `"1.0.0"`.

Response `201`:
```json
{
  "contract_id":  "ab12cd34-...",
  "owner":        "payments-service",
  "counterparty": "orders-service",
  "version":      "1.0.0",
  "status":       "active"
}
```

Errors:
- `409 Conflict` if a contract already exists for that ordered pair.
  Use proposals to change it.
- `404 Not Found` if either part is unknown.

#### `GET /contracts?owner={a}&counterparty={b}` — search contracts between two parts

Returns the active version of any contract that exists between the two
named parts, in either direction. Zero, one, or two results.

```json
{
  "results": [
    {
      "contract_id":  "ab12cd34-...",
      "owner":        "payments-service",
      "counterparty": "orders-service",
      "version":      "1.2.0",
      "markdown":     "...",
      "updated_at":   "2026-04-15T09:14:00Z"
    }
  ]
}
```

#### `GET /contracts/{contract_id}` — latest active version of a contract

Returns the most recent `status='active'` version of that contract.

### Proposals

#### `POST /contracts/{contract_id}/proposals` — propose a new contract body

Request:
```json
{
  "version":  "1.3.0-rc1",
  "markdown": "..."
}
```

`version` is required, must match `^\d+\.\d+\.\d+(-rc\d+)?$`, and must
be strictly greater than the latest existing version on this contract
(across both active rows and prior proposals, applying semver
pre-release ordering). Multiple proposals can coexist — including a
sequence of RCs leading to a stable proposal — as long as each picks a
higher version than the last.

Errors:
- `409 Conflict` if `version` is not strictly greater than the latest.
- `422 Unprocessable Entity` if `version` is malformed.

Response `201`:
```json
{
  "contract_id": "ab12cd34-...",
  "version":     "1.3.0-rc1",
  "status":      "proposal"
}
```

#### `GET /contracts/{contract_id}/proposals` — list open proposals

Returns every proposal-status version newer than the current active
version, including any RC iterations.

```json
{
  "contract_id":    "ab12cd34-...",
  "active_version": "1.2.0",
  "proposals": [
    { "version": "1.3.0-rc1", "markdown": "...", "created_at": "..." },
    { "version": "1.3.0-rc2", "markdown": "...", "created_at": "..." },
    { "version": "2.0.0",     "markdown": "...", "created_at": "..." }
  ]
}
```

#### `POST /contracts/{contract_id}/proposals/{version}/accept` — promote a proposal to active

The path `{version}` is the full semver string of the proposal to
accept, e.g. `1.3.0` or `1.3.0-rc2`.

The acceptance behaviour depends on whether the proposal is stable or
an RC:

**Stable proposal (no `-rcN` suffix)** — the row is flipped in place:
`UPDATE … SET status='active', accepted_at=now()`. The caller's
proposed version *is* the new active version.

**RC proposal (`-rcN` suffix)** — a new stable active row is created
at `MAJOR.MINOR.PATCH` (suffix stripped). The new row's `markdown` is
copied from the accepted RC; `status='active'`; `accepted_at=now()`;
`promoted_from_prerelease` records the RC suffix that was promoted
(e.g. `'rc2'`). The original RC row is left in place as
`status='proposal'` for posterity. Any earlier RC rows for the same
target version (`1.3.0-rc1`, etc.) also remain in place — they will
no longer appear in the proposals listing because they are now
older than the active version.

Both paths run in a single transaction.

Response `200` (stable accept):
```json
{
  "contract_id":            "ab12cd34-...",
  "promoted_from_version":  "1.3.0",
  "active_version":         "1.3.0",
  "accepted_at":            "2026-04-29T15:00:00Z"
}
```

Response `200` (RC accept):
```json
{
  "contract_id":            "ab12cd34-...",
  "promoted_from_version":  "1.3.0-rc2",
  "active_version":         "1.3.0",
  "accepted_at":            "2026-04-29T15:00:00Z"
}
```

`promoted_from_version` is the only field in the entire API outside
the proposal-specific endpoints that may legitimately echo back an
RC string — and it appears here only because this endpoint *is* a
proposal endpoint.

---

## Project layout

```
src/
  main.py             FastAPI app, lifecycle, router wiring
  config.py           Settings via pydantic-settings
  db.py               Async SQLAlchemy engine + session factory + MetaData naming convention
  auth.py             Bearer-password dependency (placeholder)
  models.py           SQLAlchemy ORM models (parts, contracts, templates, *_versions)
  schemas.py          Pydantic request/response models
  versioning.py       Semver parse / compare / format
  routers/
    parts.py
    contracts.py
    proposals.py
    templates.py      Templates + template proposals
alembic/
  env.py              Wired to src.models.Base.metadata for autogenerate
  versions/
    0001_initial.py                       software + contracts + *_versions
    0002_templates.py                     templates + template_versions, seeded with v1.0.0 of software + contract
    0003_software_issue_tracker_uri.py    optional issue_tracker_uri on software
    0004_software_aliases.py              aliases TEXT[] on software
    0005_software_to_part_subtype.py      rename software→parts, add subtype, seed container template v1.0.0
alembic.ini
tests/
pyproject.toml
```

Template content is **not** maintained as files on disk — the v1.0.0
markdown is embedded in `0002_templates.py` and seeded once. After
that, every change goes through the proposal + accept flow described
under Endpoints → Templates.

---

## Tech stack

- **Python 3.12+**
- **FastAPI** — routing, validation, OpenAPI
- **SQLAlchemy 2.x (async)** + **asyncpg** — Postgres access
- **Alembic** — schema migrations
- **pydantic-settings** — environment-driven config
- **uv** — dependency + venv management

---

## Configuration

| Env var        | Purpose                                                               |
| -------------- | --------------------------------------------------------------------- |
| `DATABASE_URL` | Postgres DSN, e.g. `postgresql+asyncpg://user:pw@host:5432/titan_tyr` |

The bearer password is the literal string `sysmlv2`, hardcoded in
`src/auth.py` as a placeholder. It will be removed when real auth lands
— do not promote it to a config value, since that risks it lingering
past the auth rework.

---

## Migrations

Schema is expected to evolve frequently, so migrations are treated as a
first-class concern rather than an afterthought.

### Tooling

**Alembic** with autogenerate. ORM models in `src/models.py` are the
single source of truth; the SQL DDL shown earlier in this document is
illustrative only — the canonical schema is whatever Alembic has
applied.

### SQLAlchemy naming convention

`src/db.py` defines a `MetaData` with an explicit
`naming_convention` and all ORM models bind to it:

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix":  "ix_%(table_name)s_%(column_0_N_name)s",
    "uq":  "uq_%(table_name)s_%(column_0_N_name)s",
    "ck":  "ck_%(table_name)s_%(constraint_name)s",
    "fk":  "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk":  "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

Without this, autogenerate produces hash-suffixed constraint names that
differ between machines and Postgres versions, causing spurious diffs
on every run and making `downgrade()` fragile. Set this on the very
first migration — retrofitting later requires a rename migration for
every existing constraint.

### Migration runtime

Migrations run as a **separate step before the API starts**, never as
part of FastAPI startup:

- **Local dev** — `alembic upgrade head` via a `make migrate` target.
- **Containers** — a dedicated `migrate` command in the image
  (`alembic upgrade head`), invoked as a Kubernetes Job / init
  container / Compose dependency. The API container runs only after
  the migrate step exits 0.
- **Rollback** — `downgrade()` is implemented for every migration but
  not relied on for production recovery; production rollback is
  forward-only via a new migration. Downgrades exist for local dev
  iteration.

### CI gate

CI runs `alembic check` against the model metadata to fail any PR
where the ORM and migrations have diverged. This catches the common
mistake of editing `src/models.py` without generating a corresponding
migration.

CI also runs `alembic upgrade head && alembic downgrade base &&
alembic upgrade head` against an ephemeral Postgres to confirm
migrations are reversible end-to-end.

### Schema vs data migrations

Alembic handles both, but they have different review bars:

- **Schema-only** (add column, add index, drop unused table) — routine,
  reviewed for correctness only.
- **Data migrations** (backfill a new column, transform existing rows)
  — must use bulk SQL (`op.execute(...)`), never the ORM, because the
  ORM in a migration script reflects the *current* model, not the
  schema at the migration's point in history. Large backfills go in
  separate migration files from the DDL change so they can be batched
  or run out-of-band.

### Expand / contract for breaking changes

For column renames or type changes, use the three-deploy pattern rather
than a single destructive migration:

1. **Expand** — add the new column nullable; write to both old and new.
2. **Backfill + cut over** — populate the new column for existing rows;
   switch reads to the new column.
3. **Contract** — drop the old column.

This is overkill for additive changes; reserve it for renames, type
changes, and constraint tightening on populated tables.

---

## Open questions

1. ~~**Proposal rejection**~~ — **Resolved (2026-05-02): no withdrawal
   or rejection mechanism, by design.** A proposal is the initiation of
   a conversation between two components because the current definition
   is insufficient — it must be resolved, not abandoned. The recourse
   when a proposal is wrong is to make a higher-version proposal on top
   (the existing RC iteration flow already supports this within a
   target version; cross-target counter-proposals work the same way).
   Stale proposals stay in `*_versions` for posterity, mirroring the
   "RCs preserved on accept" pattern, and are filtered out of
   `GET .../proposals` once the active version moves past them.
2. **Contract direction** — the model treats `(A→B)` and `(B→A)` as
   distinct contracts. Confirm this matches how callers think about
   interfaces, or collapse to undirected.
3. **Search by content** — full-text search over markdown bodies is
   not in this cut. Add when a real use case appears.
4. **Real auth** — the placeholder password is throwaway. The real auth
   model (per-caller identity, authorisation rules, key rotation) is
   deferred to a future capability update and is its own design
   conversation.
5. **Pre-release grammar** — only `-rcN` is supported on contract
   proposals. Other semver pre-release labels (`-alpha.1`, `-beta.2`,
   etc.) and build metadata (`+build.42`) are not. Add if a real use
   case appears.
