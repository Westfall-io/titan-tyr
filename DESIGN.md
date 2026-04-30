# titan-tyr — Developer Brief
## WatcherVault REST API

**Repository:** titan-tyr
**Capability:** WatcherVault
**Role:** Backend — Git-backed contract file server with environment-aware indexing

---

## Purpose

titan-tyr is the data layer for WatcherVault. It serves architecture contract documents stored as markdown files in titan-norganon (the architecture repository), exposes them via a REST API consumed by titan-mimiron (the web UI) and indirectly by titan-algalon (the MCP server), and injects Git version metadata into every response.

There is no database. titan-norganon is the source of truth. titan-tyr reads from titan-norganon via the **GitHub REST API**. This is the current implementation approach — it will be replaced with a local Git clone in a future iteration when performance or rate limit constraints require it. The abstraction layer between titan-tyr's internal GitHub client and its outward API must be kept clean so this substitution can be made without changing any downstream behaviour.

---

## Architecture Repository Structure

titan-tyr reads from titan-norganon via the GitHub API. The repository follows this layout — titan-tyr must understand this structure to build the environment index correctly:

```
icd-docs/
  common/                          ← type definitions (read-only)
    parts/
    ports/
    interfaces/
    connections/

  instances/
    common/                        ← environment-agnostic elements
      parts/                       ← SoftwarePart, ImagePart instances
      interfaces/                  ← Interaction Interface contracts
      connections/

    local/                         ← local development model
      model.md
      parts/                       ← ContainerPart, ComposePart instances
      interfaces/                  ← Binding Interface contracts
      connections/

    staging/
      model.md
      parts/
      interfaces/
      connections/

    production/
      model.md
      parts/                       ← PodPart instances
      interfaces/
      connections/
```

When building the index for a given environment, titan-tyr merges
`instances/common/` with `instances/{env}/` to produce the complete model.

---

## GitHub API Access

titan-tyr communicates with titan-norganon exclusively via the GitHub REST API. All file reads, version metadata, and write operations go through this API.

### Authentication

titan-tyr requires a GitHub Personal Access Token (PAT) or GitHub App installation token with `contents:read` permission on titan-norganon, and `contents:write` for branch creation via `POST /api/files`.

Configure via environment variable: `GITHUB_TOKEN`. This must never be hardcoded or logged.

### Required GitHub API Calls

**Get file content and metadata:**
```
GET https://api.github.com/repos/{org}/titan-norganon/contents/{path}?ref=main
```
Returns the file content (base64 encoded), the blob SHA, and the `last_modified` header. Decode content with `base64.b64decode(response['content'])`.

**List directory contents:**
```
GET https://api.github.com/repos/{org}/titan-norganon/contents/{dir-path}?ref=main
```
Returns an array of file and directory entries with `name`, `path`, `type` (`file` or `dir`), and `sha`.

**Get commit history for a file:**
```
GET https://api.github.com/repos/{org}/titan-norganon/commits?path={file-path}&sha=main&per_page=20
```
Returns an array of commits. Each entry has `sha`, `commit.author.date`, `commit.author.name`, and `commit.message`.

**Create or update a file on a branch:**
```
PUT https://api.github.com/repos/{org}/titan-norganon/contents/{path}
```
Body requires `message` (commit message), `content` (base64 encoded), `branch` (branch name), and `sha` (current blob SHA if updating an existing file).

**Create a branch:**
```
POST https://api.github.com/repos/{org}/titan-norganon/git/refs
```
Body: `{ "ref": "refs/heads/{branch-name}", "sha": "{main-head-sha}" }`

Get main HEAD SHA first with:
```
GET https://api.github.com/repos/{org}/titan-norganon/git/ref/heads/main
```

### Rate Limits

The GitHub API allows 5000 requests per hour for authenticated requests. This is sufficient for current usage but must be managed carefully:

- **Cache aggressively** — the index is built once and held in memory. Individual file fetches are cached with the `ETag` / `If-None-Match` mechanism.
- **ETags** — store the `ETag` response header on every file fetch. On subsequent fetches, send `If-None-Match: {etag}`. GitHub returns `304 Not Modified` (free, not counted against content rate limit) if the file has not changed.
- **Respect `X-RateLimit-Remaining`** — check this header on every response. If it falls below 100, log a warning. If it reaches 0, return `503` to callers with a `Retry-After` header.
- **Avoid recursive directory walks at request time** — the index must be built on startup and on a polling interval, not on every incoming API request.

### Keeping the Index Current

Without a local clone and webhook, titan-tyr uses a **polling approach**:

- On startup, build the full index by walking the titan-norganon directory tree via the GitHub API
- Poll the main branch HEAD SHA every 60 seconds:
  ```
  GET https://api.github.com/repos/{org}/titan-norganon/git/ref/heads/main
  ```
- If the HEAD SHA has changed since the last poll, rebuild the index
- The index rebuild fetches only the directory listings (cheap); individual file content is fetched on demand and cached by ETag

This replaces the webhook and `git pull` approach used in the local-clone model.

---

## Versioning

Every contract response carries three version signals. titan-tyr populates two of them at serve time — the semantic version is already in the document body.

**Semantic version** — parse from document body after fetching file content:
```python
import re
match = re.search(r'\*\*Version:\*\*\s*([\d\.]+)', content)
version = match.group(1) if match else "unknown"
```

**Git SHA** — the blob SHA returned by the GitHub Contents API response field `sha`. This is the blob hash of the file, equivalent to `git rev-parse HEAD:{path}`.

**Last modified** — the date of the most recent commit touching this file. Retrieved from the commits API:
```
GET /repos/{org}/titan-norganon/commits?path={path}&sha=main&per_page=1
```
Use `commits[0].commit.author.date`.

titan-tyr injects these into the document before returning it by replacing the placeholder text `[populated by backend]` in the `**Git SHA:**` and `**Last modified:**` lines. It also returns them as response headers.

---

## API Endpoints

### `GET /api/environments`

Lists available environment models. titan-tyr determines available environments by listing the directories under `icd-docs/instances/` via the GitHub API and filtering out `common/`. Each environment's `model.md` is fetched to extract version and metadata.

```json
{
  "environments": [
    {
      "id": "local",
      "path": "instances/local/model.md",
      "version": "1.0.0",
      "sha": "a1b2c3d4...",
      "lastModified": "2025-04-20T10:00:00Z"
    }
  ]
}
```

### `GET /api/index?env={environment}`

Returns the complete merged model for the specified environment.
Merges `instances/common/` with `instances/{env}/`.
Default env: `local`.

```json
{
  "environment": "local",
  "generatedAt": "2025-04-29T14:30:00Z",
  "elements": [
    {
      "id": "payments-service",
      "type": "SoftwarePart",
      "name": "payments-service",
      "path": "instances/common/parts/payments-service.md",
      "version": "3.1.0",
      "sha": "a1b2c3d4...",
      "lastModified": "2025-04-01T09:14:00Z",
      "owner": "payments-team",
      "layer": "common",
      "connections": [
        {
          "to": "iface-orders-payments",
          "edgeType": "interaction-interface",
          "direction": "in",
          "label": "REST POST",
          "version": "1.2.0"
        }
      ]
    }
  ]
}
```

**`layer`** — `"common"` if from `instances/common/`, `"env"` if from the environment folder. Used by titan-mimiron to determine which graph view an element belongs to.

**`edgeType`** — one of: `interaction-interface`, `binding-interface`, `connection`.

Agree the full response shape with titan-mimiron before implementing — this is the primary interface between the two repos.

### `GET /api/files/:path`

Returns the raw markdown content of the file at `{path}` relative to `icd-docs/`, with Git fields injected.

titan-tyr fetches the file from the GitHub Contents API, decodes the base64 content, parses the semantic version from the body, retrieves the last-modified date from the commits API, and injects all three version values into the document before returning it.

Cache the response using the GitHub-returned `ETag`. On subsequent calls for the same path, send `If-None-Match` and serve from cache on `304`.

Response headers:
```
Content-Type: text/plain
X-Contract-Version: 3.1.0
X-Git-SHA: a1b2c3d4e5f6...
X-Git-Last-Modified: 2025-04-29T14:23:00Z
```

Returns `404` with JSON body if the GitHub API returns 404:
```json
{ "error": "File not found", "path": "instances/common/parts/payments-service.md" }
```

### `GET /api/history/:path`

Returns the commit history for a specific file. Sourced from the GitHub commits API:

```
GET /repos/{org}/titan-norganon/commits?path=icd-docs/{path}&sha=main&per_page=20
```

```json
{
  "path": "instances/common/interfaces/iface-orders-payments.md",
  "history": [
    {
      "sha": "a1b2c3d4...",
      "date": "2025-04-01T09:14:00Z",
      "author": "orders-team-bot",
      "message": "Propose metadata.channel field (Open Proposals)"
    }
  ]
}

### `GET /api/search?q={query}&env={environment}`

Substring match across element names and contract content in the given environment.

```json
{
  "query": "payment",
  "environment": "local",
  "results": [
    {
      "id": "payments-service",
      "type": "SoftwarePart",
      "path": "instances/common/parts/payments-service.md",
      "matchContext": "...handles payment capture and refunds..."
    }
  ]
}
```

### `POST /api/files/:path`

Creates or updates a contract file on a new branch in titan-norganon. Never writes to main directly.

Procedure:
1. Fetch the current main HEAD SHA via `GET /repos/{org}/titan-norganon/git/ref/heads/main`
2. Create a new branch: `POST /repos/{org}/titan-norganon/git/refs` with `ref: refs/heads/agent/{name}-{date}` and the HEAD SHA
3. If updating an existing file, fetch the current blob SHA for the file first (required by GitHub API)
4. Write the file: `PUT /repos/{org}/titan-norganon/contents/icd-docs/{path}` with the branch name, base64-encoded content, and blob SHA if updating

Validate the path is within `icd-docs/` before writing (prevent path traversal).

```json
{
  "path": "instances/local/interfaces/binding-payments.md",
  "written": true,
  "branch": "agent/update-binding-payments-20250429",
  "sha": "c3d4e5f6..."
}
```

### `GET /api/health`

```json
{ "status": "ok", "githubRateLimitRemaining": 4823, "indexLastBuilt": "2025-04-29T14:28:00Z" }
```

The `githubRateLimitRemaining` value surfaces the most recent `X-RateLimit-Remaining` header received from the GitHub API. This allows operators to monitor rate limit consumption without inspecting logs.

---

## Parsing Contract Metadata

Parse the document header block (before the first `##` heading):

```python
import re

def parse_metadata(content: str) -> dict:
    meta = {}
    header = content.split('\n## ')[0]

    name_match = re.search(r'^# (.+)$', header, re.MULTILINE)
    if name_match:
        meta['name'] = name_match.group(1).strip()

    for match in re.finditer(r'\*\*(\w[\w\s]+):\*\*\s*(.+)', header):
        key = match.group(1).strip().lower().replace(' ', '_')
        meta[key] = match.group(2).strip()

    return meta
```

Parse connections from the `## Ports` and `## Connections` table sections.

---

## Technology

**Python + FastAPI** recommended:
- FastAPI for REST endpoints
- `httpx` or `PyGithub` for GitHub API calls — `PyGithub` provides a typed client and handles token refresh; `httpx` is lower-level but more explicit
- In-memory dict for index cache and ETag cache — no database required
- `asyncio` background task for the 60-second HEAD SHA poll

### Abstraction Requirement

All GitHub API interactions must be isolated behind a `RepositoryBackend` interface or equivalent abstraction layer. The rest of titan-tyr must not call the GitHub API directly — it calls the backend interface. This makes the future switch to a local Git clone a single-file change rather than a codebase-wide refactor.

```python
class RepositoryBackend(Protocol):
    async def get_file(self, path: str) -> FileResult: ...
    async def list_directory(self, path: str) -> list[DirEntry]: ...
    async def get_history(self, path: str, limit: int) -> list[Commit]: ...
    async def write_file(self, path: str, content: str, message: str) -> WriteResult: ...

class GitHubBackend:
    """Current implementation — reads from GitHub API."""
    ...

class LocalGitBackend:
    """Future implementation — reads from local clone."""
    ...
```

---

## CLAUDE.md Requirement

titan-tyr must include a `CLAUDE.md` and `.mcp.json` wiring it to titan-algalon. Agents working on the API must consult the WatcherVault architecture contracts in titan-norganon before changing any endpoint that titan-mimiron or titan-algalon depends on.

---

## Open Questions

1. Agree `/api/index` response shape with titan-mimiron developer before implementing
2. Authentication — does titan-tyr itself require auth from callers, or is it behind a network boundary?
3. Whether titan-algalon calls titan-tyr's REST API or reads titan-norganon directly
4. GitHub token management — PAT or GitHub App? PATs are simpler but expire; GitHub Apps rotate automatically. Choose before starting.
5. Rate limit headroom — if multiple agents and the UI are calling titan-tyr simultaneously, model the expected request volume against the 5000/hour limit before launch
