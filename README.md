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
  and template proposals, with full history preserved on acceptance.
- **Templates are versioned and proposable too.** The `software` and
  `contract` markdown templates served by the API live in Postgres
  alongside everything else, mutated through the same propose/accept
  flow.
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
# Smoke test (no auth required — the /health endpoint is the orchestrator probe)
curl http://localhost:8000/health
# → {"status":"ok","version":"0.7.0","db":"reachable"}

# Sanity check on the auth path
curl -H 'Authorization: Bearer sysmlv2' http://localhost:8000/templates/software
```

## Run from Docker

```sh
docker build -t titan-tyr:0.7.0 .
```

The image runs as a non-root `app` user, exposes port 8000, and bundles
both `uvicorn` (default `CMD`) and `alembic` (override `CMD` to use it).
Per [`DESIGN.md`](./DESIGN.md#migrations), migrations run as a separate
step *before* the API container starts:

```sh
# 1. Apply migrations (one-shot)
docker run --rm \
  -e DATABASE_URL='postgresql+asyncpg://titan:titan@host.docker.internal:5432/titan_tyr' \
  titan-tyr:0.7.0 alembic upgrade head

# 2. Serve the API
docker run --rm -p 8000:8000 \
  -e DATABASE_URL='postgresql+asyncpg://titan:titan@host.docker.internal:5432/titan_tyr' \
  titan-tyr:0.7.0
```

(In Compose / Kubernetes, the migrate step is a `depends_on` job or an
init container; the API container only starts once it exits 0.)

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
alembic/            Migrations (0001 = schema, 0002 = templates + seed)
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

## Claude Code skills

Project-level skills under [`.claude/skills/`](./.claude/skills/) are
auto-available in Claude Code when run from this repo. Invoke with
`/<skill-name>`. They expect `TITAN_TYR_URL` (and optionally
`TITAN_TYR_TOKEN`) in the environment.

- `/register-software` — walk through registering a software node
  against a running titan-tyr.
- `/update-software` — append a new version to a registered software
  node. Detects template-version drift and helps migrate.
- `/learn-software` — look up everything titan-tyr knows about a
  registered software node (description, ticket-filing target,
  contracts). Read-only; returns structured JSON.
- `/find-software` — resolve a colloquial label or partial name
  ("front end", "billing") to a canonical software slug via
  `GET /software?match=`. Read-only.
- `/propose-template-change` — draft and POST a proposal to update the
  `software` or `contract` template. Does not auto-accept.
- `/accept-template-proposal` — promote an open template proposal to
  the new active version. Mutates what every caller sees.
