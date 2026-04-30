# titan-tyr

> WatcherVault REST API — a Git-backed contract file server with environment-aware indexing.

titan-tyr is the data layer for **WatcherVault**. It serves architecture
contract documents (markdown) stored in [`titan-norganon`][norganon] and
exposes them via a REST API. It injects Git version metadata (semantic
version, blob SHA, last-modified date) into every response so consumers
always know exactly which revision they are looking at.

It is consumed by:

- **[titan-mimiron][mimiron]** — the WatcherVault web UI
- **[titan-algalon][algalon]** — the WatcherVault MCP server

There is no database. titan-norganon is the source of truth.

---

## How it works

```
┌──────────────┐         ┌────────────┐        ┌──────────────────┐
│ titan-mimiron│ ──────▶ │            │ ─────▶ │ GitHub API       │
│ titan-algalon│         │ titan-tyr  │        │ titan-norganon   │
└──────────────┘ ◀────── │            │ ◀───── │ (contracts repo) │
                         └────────────┘        └──────────────────┘
                            REST/JSON              GitHub REST
```

- titan-tyr reads contracts from titan-norganon via the **GitHub REST API**
- An in-memory index is built on startup and refreshed every 60 s by
  polling the main branch HEAD SHA
- Per-file responses are cached using GitHub's `ETag` /
  `If-None-Match` mechanism so repeated reads do not consume rate limit
- Writes (`POST /api/files/:path`) always go to a new branch — never
  directly to `main`

The current GitHub-API backend is intended to be swappable for a
local-clone backend later. All Git interactions are isolated behind a
`RepositoryBackend` abstraction so that switch is a single-file change.

---

## API surface

| Method | Path                          | Purpose                                                   |
| ------ | ----------------------------- | --------------------------------------------------------- |
| GET    | `/api/environments`           | List available environment models (`local`, `staging`, …) |
| GET    | `/api/index?env={env}`        | Full merged model for an environment                      |
| GET    | `/api/files/:path`            | Raw markdown for a contract, with version metadata        |
| GET    | `/api/history/:path`          | Commit history for a contract file                        |
| GET    | `/api/search?q=&env=`         | Substring search across element names + contract content  |
| POST   | `/api/files/:path`            | Create / update a contract on a new branch                |
| GET    | `/api/health`                 | Liveness + GitHub rate limit headroom                     |

See [DESIGN.md](./DESIGN.md) for the full request/response shapes.

---

## Configuration

Set via environment variables:

| Variable       | Required | Description                                                                |
| -------------- | -------- | -------------------------------------------------------------------------- |
| `GITHUB_TOKEN` | yes      | PAT or GitHub App installation token with `contents:read` + `contents:write` on titan-norganon |

`GITHUB_TOKEN` must never be hardcoded or logged.

---

## Architecture repository layout

titan-tyr expects titan-norganon to follow this structure:

```
icd-docs/
  common/                  ← type definitions (read-only)
  instances/
    common/                ← environment-agnostic elements
    local/                 ← local development model
    staging/               ← staging model
    production/            ← production model
```

For a given environment, titan-tyr merges `instances/common/` with
`instances/{env}/` to produce the complete model.

---

## Project status

Pre-implementation — see the **Open Questions** section of
[DESIGN.md](./DESIGN.md) for items to resolve before the first cut.

---

## Repository docs

- [DESIGN.md](./DESIGN.md) — full developer brief: endpoints, GitHub API
  usage, versioning rules, abstraction requirements
- [AGENTS.md](./AGENTS.md) — operating rules for AI coding agents
  working in this repo

[norganon]: https://github.com/Westfall-io/titan-norganon
[mimiron]:  https://github.com/Westfall-io/titan-mimiron
[algalon]:  https://github.com/Westfall-io/titan-algalon
