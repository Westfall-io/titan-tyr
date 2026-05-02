# titan-tyr

> A graph-shaped REST API for software and the interface contracts
> between them. Versioned markdown nodes and edges, all in Postgres.

titan-tyr is a small FastAPI service that records:

- **Software** — your services, libraries, repos. Each is a node.
- **Interface contracts** — directed edges between two software nodes
  describing how one talks to the other.

Both nodes and edges carry a versioned markdown body. The latest
version is what reads return. Contracts additionally support
**proposals** (and RC iterations of them) so a change can be drafted,
revised, and accepted as the new active version without losing history.

```
            ┌──────────────────────────────────────────────────┐
            │                  titan-tyr API                   │
            │                                                  │
software ──▶│ POST /software        GET  /software/{name}      │
contract ──▶│ POST /contracts       GET  /contracts/{id}       │
proposal ──▶│ POST /…/proposals     POST /…/{ver}/accept       │
            │                                                  │
            └─────────────────────────┬────────────────────────┘
                                      │
                                  PostgreSQL
                       (software, contracts, *_versions)
```

## Features

- **FastAPI + async SQLAlchemy + asyncpg.** Auto-generated OpenAPI at
  `/docs` and `/redoc`.
- **Caller-supplied semver** (`MAJOR.MINOR.PATCH`) on every write,
  validated for format and strict-greater-than-latest. The server
  refuses to interpret what a bump *means* — only the caller knows.
- **RC pre-release support** (`1.3.0-rc1`, `1.3.0-rc2`, …) on contract
  proposals, with full history preserved on acceptance.
- **First-class migrations.** Alembic with autogenerate, a `MetaData`
  naming convention so diffs stay reproducible, and a CI policy of
  running `alembic check` against the model.
- **Test suite (95% coverage).** Pytest + httpx + a throwaway Postgres
  via testcontainers; an env-var override is supported for shared dev
  instances.

## Quickstart

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"

# Postgres for local dev
docker run --rm -d --name titan-tyr-pg -p 5432:5432 \
  -e POSTGRES_USER=titan -e POSTGRES_PASSWORD=titan -e POSTGRES_DB=titan_tyr \
  postgres:16-alpine

DATABASE_URL='postgresql+asyncpg://titan:titan@localhost:5432/titan_tyr' \
  alembic upgrade head

DATABASE_URL='postgresql+asyncpg://titan:titan@localhost:5432/titan_tyr' \
  uvicorn src.main:app --reload --port 8000
```

```sh
# Smoke test
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/software
```

## Authentication

> **Placeholder.** A single shared bearer token (`sysmlv2`) gates every
> endpoint. Real per-caller auth is a deferred capability — see the
> Authentication section in `DESIGN.md`.

```
Authorization: Bearer sysmlv2
```

## Configuration

| Env var        | Required | Description                                                          |
| -------------- | -------- | -------------------------------------------------------------------- |
| `DATABASE_URL` | yes      | Async DSN, e.g. `postgresql+asyncpg://user:pw@host:5432/titan_tyr`   |

## Run the tests

```sh
pytest
```

Spins up a Postgres in Docker via `testcontainers`, recreates the
schema per test, asserts on every endpoint behaviour and on the semver
module directly. To use an existing Postgres instead, set
`TEST_DATABASE_URL`.

## Project layout

```
src/                FastAPI app, ORM models, schemas, routers, semver
templates/          Static markdown served by /templates/*
alembic/            Migrations (initial schema in versions/0001_initial.py)
tests/              Pytest + testcontainers
docs/               getting-started, api reference (also see DESIGN.md)
```

## Documentation

- [`docs/getting-started.md`](./docs/getting-started.md) — running it
  locally, running the tests, layout overview.
- [`docs/api.md`](./docs/api.md) — endpoint reference with `curl`
  examples.
- [`DESIGN.md`](./DESIGN.md) — full design rationale: data model,
  schema, versioning rules, migration policy, open questions.
- [`AGENTS.md`](./AGENTS.md) — operating rules for AI coding agents
  working in this repo.
