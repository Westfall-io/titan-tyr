# titan-tyr — Design

**Repository:** titan-tyr
**Role:** REST API for registering software, registering interface contracts between software, and proposing changes to those contracts.
**Stack:** FastAPI + PostgreSQL.

---

## Purpose

titan-tyr is a graph database, exposed as a REST API, that records the
software running in a system and the interface contracts between those
pieces of software. Software-developer agents register themselves and
the software they own; they then register contracts that describe how
their software interfaces with other software, and propose changes to
contracts that already exist.

- **Nodes** — registered software.
- **Edges** — interface contracts between two software nodes.

Both nodes and edges carry a markdown body. All markdown is **versioned
append-only** in the database. By default, only the latest version is
returned on read.

This is a deliberately small first cut. There is no Git integration, no
file system, no external repository — Postgres is the source of truth.

---

## Data model

### Concepts

| Concept       | Stored as                                 | Notes                                        |
| ------------- | ----------------------------------------- | -------------------------------------------- |
| Agent         | row in `agents`                           | The registering identity. Holds an API key. |
| Software node | row in `software` + N `software_versions` | Owned by exactly one agent.                  |
| Contract edge | row in `contracts` + N `contract_versions` | Directed: `owner_software → counterparty_software`. |
| Proposal      | a `contract_versions` row with `status='proposal'` | Lives on the edge until accepted or superseded. |

### Schema

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

CREATE TABLE agents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  api_key_hash  TEXT NOT NULL UNIQUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE software (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            TEXT NOT NULL UNIQUE,
  repo_uri        TEXT NOT NULL,
  owner_agent_id  UUID NOT NULL REFERENCES agents(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE software_versions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  software_id         UUID NOT NULL REFERENCES software(id) ON DELETE CASCADE,
  version             INT  NOT NULL,
  markdown            TEXT NOT NULL,
  created_by_agent_id UUID NOT NULL REFERENCES agents(id),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (software_id, version)
);
CREATE INDEX ON software_versions (software_id, version DESC);

CREATE TABLE contracts (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_software_id        UUID NOT NULL REFERENCES software(id),
  counterparty_software_id UUID NOT NULL REFERENCES software(id),
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner_software_id, counterparty_software_id),
  CHECK  (owner_software_id <> counterparty_software_id)
);

CREATE TABLE contract_versions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_id         UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  version             INT  NOT NULL,
  markdown            TEXT NOT NULL,
  status              TEXT NOT NULL CHECK (status IN ('active', 'proposal')),
  created_by_agent_id UUID NOT NULL REFERENCES agents(id),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (contract_id, version)
);
CREATE INDEX ON contract_versions (contract_id, version DESC);
CREATE INDEX ON contract_versions (contract_id, status);
```

`status` is a `TEXT` column with a `CHECK` constraint, not a Postgres
`ENUM`. The set of allowed values will evolve (rejected, withdrawn,
superseded, …) and `ALTER TYPE` is half-supported and irreversible —
`TEXT + CHECK` lets us add or remove values with a single migration that
drops and recreates the constraint.

### Version assignment

`version` is a 1-based integer scoped to its parent
(`software_id` or `contract_id`). Each insert grabs the parent row with
`SELECT … FOR UPDATE`, computes `MAX(version) + 1`, and inserts under
that lock. This keeps numbering monotonic without a sequence per parent.

### "Latest" semantics

- **Software** — `MAX(version)` per `software_id`.
- **Contract (active)** — most recent `contract_versions` row with
  `status='active'`. There is always at most one, by construction.
- **Contract proposals** — every `contract_versions` row with
  `status='proposal'` that is newer than the current active version.

---

## Authentication

API-key bearer tokens.

- On `POST /agents`, the server generates a random key, returns it
  **once** in the response body, and stores only `sha256(key)` in
  `agents.api_key_hash`.
- All subsequent requests authenticate via
  `Authorization: Bearer <key>`. The server hashes the presented key
  and looks it up in `agents.api_key_hash`.
- Lost keys cannot be recovered — the agent must re-register.

All write endpoints require auth. Read endpoints also require auth in
this first cut (see Open Questions).

### Authorisation rules

| Action                                  | Allowed agent                                          |
| --------------------------------------- | ------------------------------------------------------ |
| Update a software description           | Owner agent of that software                           |
| Register a new contract                 | Owner agent of the *owner* software                    |
| Propose a contract change               | Owner agent of *either* the owner or counterparty software |
| Accept a proposal                       | Owner agent of the *owner* software                    |

---

## Endpoints

All paths are relative to the API root. JSON request/response unless
otherwise noted.

### Templates

Static markdown files served from `templates/` on disk.

| Method | Path                   | Returns                                       |
| ------ | ---------------------- | --------------------------------------------- |
| GET    | `/templates/software`  | `text/markdown` — template for software descriptions |
| GET    | `/templates/contract`  | `text/markdown` — template for interface contracts   |

### Agents

#### `POST /agents` — register an agent + initial software

Request:
```json
{
  "agent_name": "payments-team-bot",
  "software": {
    "name": "payments-service",
    "repo_uri": "https://github.com/example/payments-service",
    "markdown": "# payments-service\n..."
  }
}
```

Response `201`:
```json
{
  "agent_id": "8f1b2c3d-...",
  "api_key": "tk_live_...",
  "software": {
    "id": "12c3a4b5-...",
    "name": "payments-service",
    "version": 1
  }
}
```

Atomic: inserts `agents`, `software`, `software_versions` (version 1) in
one transaction. `api_key` is shown once and never returned again.

### Software

#### `GET /software/{name}` — latest description

Returns software metadata + the latest `software_versions` row.
```json
{
  "id": "12c3a4b5-...",
  "name": "payments-service",
  "repo_uri": "https://github.com/example/payments-service",
  "owner_agent_id": "8f1b2c3d-...",
  "version": 3,
  "markdown": "# payments-service\n...",
  "updated_at": "2026-04-29T14:30:00Z"
}
```

#### `PUT /software/{name}` — append a new description version

Auth: owner agent of the software.

Request:
```json
{ "markdown": "# payments-service\n..." }
```

Response `200`:
```json
{ "name": "payments-service", "version": 4 }
```

#### `GET /software/{name}/contracts` — all contracts touching this software

Returns every contract where this software is either owner or
counterparty, each with its latest active version.

```json
{
  "software": "payments-service",
  "contracts": [
    {
      "id": "ab12cd34-...",
      "owner": "payments-service",
      "counterparty": "orders-service",
      "version": 2,
      "markdown": "...",
      "updated_at": "2026-04-15T09:14:00Z"
    },
    {
      "id": "cd34ef56-...",
      "owner": "ledger-service",
      "counterparty": "payments-service",
      "version": 1,
      "markdown": "...",
      "updated_at": "2026-04-02T11:00:00Z"
    }
  ]
}
```

### Contracts

#### `POST /contracts` — register a new interface contract

Auth: owner agent of the named owner software.

Request:
```json
{
  "owner_software":        "payments-service",
  "counterparty_software": "orders-service",
  "markdown":              "..."
}
```

Response `201`:
```json
{
  "contract_id": "ab12cd34-...",
  "owner":        "payments-service",
  "counterparty": "orders-service",
  "version": 1,
  "status":  "active"
}
```

Errors:
- `409 Conflict` if a contract already exists for that ordered pair.
  Use proposals to change it.
- `404 Not Found` if either software is unknown.

#### `GET /contracts?owner={a}&counterparty={b}` — search contracts between two software

Returns the active version of any contract that exists between the two
named pieces of software, in either direction. Zero, one, or two results.

```json
{
  "results": [
    {
      "contract_id": "ab12cd34-...",
      "owner":        "payments-service",
      "counterparty": "orders-service",
      "version": 2,
      "markdown": "...",
      "updated_at": "2026-04-15T09:14:00Z"
    }
  ]
}
```

#### `GET /contracts/{contract_id}` — latest active version of a contract

Returns the most recent `status='active'` version of that contract.

### Proposals

#### `POST /contracts/{contract_id}/proposals` — propose a new contract body

Auth: owner agent of *either* the owner or counterparty software.

Request:
```json
{ "markdown": "..." }
```

Inserts a new `contract_versions` row with `status='proposal'` and the
next version number. Multiple proposals can coexist.

Response `201`:
```json
{
  "contract_id": "ab12cd34-...",
  "version": 4,
  "status":  "proposal",
  "created_by_agent_id": "..."
}
```

#### `GET /contracts/{contract_id}/proposals` — list open proposals

Returns every proposal-status version newer than the current active
version.

```json
{
  "contract_id": "ab12cd34-...",
  "active_version": 3,
  "proposals": [
    { "version": 4, "markdown": "...", "created_by_agent_id": "...", "created_at": "..." },
    { "version": 5, "markdown": "...", "created_by_agent_id": "...", "created_at": "..." }
  ]
}
```

#### `POST /contracts/{contract_id}/proposals/{version}/accept` — promote a proposal to active

Auth: owner agent of the owner software.

Server-side, in one transaction:
1. Read the proposal row at `(contract_id, version)`. Reject if not
   `status='proposal'`.
2. Insert a new `contract_versions` row with the **next** version
   number, `status='active'`, and `markdown` copied from the accepted
   proposal.
3. Leave the original proposal row in place as history.

Why copy rather than flip the status in place: this keeps the proposal's
authorship + creation time distinct from the acceptance event, and
keeps the "latest active" query trivially correct (`MAX(version) WHERE
status='active'`).

Response `200`:
```json
{
  "contract_id": "ab12cd34-...",
  "promoted_from_proposal_version": 4,
  "new_active_version": 6
}
```

---

## Templates on disk

```
templates/
  software.md         ← served by GET /templates/software
  contract.md         ← served by GET /templates/contract
```

These are the canonical formats agents are expected to produce. Their
exact content is out of scope for this design — they will evolve
without breaking the API.

---

## Project layout

```
src/
  main.py             FastAPI app, lifecycle, router wiring
  config.py           Settings via pydantic-settings
  db.py               Async SQLAlchemy engine + session factory + MetaData naming convention
  auth.py             API-key bearer dependency
  models.py           SQLAlchemy ORM models
  schemas.py          Pydantic request/response models
  routers/
    agents.py
    software.py
    contracts.py
    proposals.py
    templates.py
templates/
  software.md
  contract.md
alembic/
  env.py              Wired to src.models.Base.metadata for autogenerate
  versions/           Migration scripts
alembic.ini
tests/
pyproject.toml
```

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

| Env var          | Purpose                                                                |
| ---------------- | ---------------------------------------------------------------------- |
| `DATABASE_URL`   | Postgres DSN, e.g. `postgresql+asyncpg://user:pw@host:5432/titan_tyr`  |
| `API_KEY_PREFIX` | Display prefix for issued keys (default `tk_live_`)                    |

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

1. **Read auth** — should `GET` endpoints require an API key, or be
   open within an internal network?
2. **Multi-software agents** — the schema permits one agent to own
   many software nodes, but only `POST /agents` seeds one. Add a
   separate `POST /software` for an existing agent to register
   additional software?
3. **Proposal rejection** — accepting a proposal is defined; explicit
   rejection is not. Do we need a status for "rejected" / "withdrawn",
   or is leaving stale proposals on the edge acceptable?
4. **Contract direction** — the model treats `(A→B)` and `(B→A)` as
   distinct contracts. Confirm this matches how agents think about
   interfaces, or collapse to undirected.
5. **Search by content** — full-text search over markdown bodies is
   not in this cut. Add when a real use case appears.
