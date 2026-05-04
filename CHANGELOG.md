# CHANGELOG


## v0.1.0 (2026-05-04)

### Other

- 👷 Add GitHub Actions CI: pytest + alembic check + round-trip + docker build (closes #4)
  ([`b5c51a2`](https://github.com/Westfall-io/titan-tyr/commit/b5c51a26ccf99ebecb3b201e7339e04dedc4416d))

Three parallel jobs on push to main and on PRs:

- pytest — runs the full suite. testcontainers spins up its own Postgres so the runner only needs
  Docker (ubuntu-latest does). - migrations — alembic upgrade head, alembic check (drift detection),
  then a downgrade base / upgrade head round-trip against a service- container Postgres 16. Catches
  the kind of constraint-name issue that #1 surfaced (silent truncation in create_all but rejection
  in Alembic). - docker build — confirms the image still builds. Catches Dockerfile breakage like
  the recently-removed COPY templates ./templates line.

Verified locally that alembic check passes against the current model state (no drift between
  src/models.py and 0001/0002/0003) and that the round-trip cleanly migrates forward, back to base,
  and forward again.

concurrency.cancel-in-progress kills older runs when a newer commit lands on the same ref.

- 📦 Add Dockerfile (multi-stage, non-root, 252MB) and document usage
  ([`9fe1d4a`](https://github.com/Westfall-io/titan-tyr/commit/9fe1d4a498c0c7bc425af3ac15cbe71568067adb))

Multi-stage build: builder installs the package into /opt/venv; runtime copies the venv into a
  python:3.11-slim image, runs as uid 1000 'app', exposes 8000.

Default CMD is uvicorn. Override with 'alembic upgrade head' to run the migration step before the
  API starts, per the runtime model in DESIGN.md.

README gets a 'Run from Docker' section showing the migrate-then-serve two-step.

- 🔥 Remove _model/00_index.md
  ([`3e3f66e`](https://github.com/Westfall-io/titan-tyr/commit/3e3f66e2d3f0cc465028c70e429f41ff74dac025))

### ♻️

- ♻️ Drop agent identity from DESIGN.md; gate on shared password placeholder
  ([`eb3e0eb`](https://github.com/Westfall-io/titan-tyr/commit/eb3e0ebdb8cb72a37b8f9998cf1679e2ddc4e5ee))

- Remove agents table, owner_agent_id from software, and created_by_agent_id from both versions
  tables. - Replace POST /agents with POST /software for node creation. - Drop per-action
  authorisation rules; any authenticated caller can perform any action. - Hardcode 'sysmlv2' as the
  bearer password in src/auth.py with an explicit note that it's a throwaway placeholder; real auth
  lands in a future capability update. - Drop multi-software-agents open question; add deferred-auth
  question.

- ♻️ register-software: decouple from template specifics
  ([`8f7b6cf`](https://github.com/Westfall-io/titan-tyr/commit/8f7b6cfccc037c6ac14cb6ac338927cf7c77756e))

The skill was carrying per-section guidance (Ports semantics, multi-counterparty rows, Direction
  conventions, what-is-not-a-Port exclusions) — meaning every template change required a companion
  skill change. Strip all template-specific knowledge and keep only generic fill rules: substitute
  <...> placeholders, strip instructional blockquotes, drop pure-reference subsections.

Per-section guidance now belongs in the template body itself, where it travels with versioning and
  propose/accept. Surfaced by the 2.0.0 template change that removed Counterparty from Ports — fill
  rule #4 is gone with no companion follow-up needed.

- ♻️ Switch versioning to caller-supplied semver (MAJOR.MINOR.PATCH)
  ([`a5d317f`](https://github.com/Westfall-io/titan-tyr/commit/a5d317fa6f2935c41df814a9a3894c65c236eb3e))

- Replace single INT version column with three INT columns (version_major, version_minor,
  version_patch) plus matching UNIQUE and DESC composite indexes for tuple ordering. - Document the
  semver convention (major=breaking, minor=additive, patch=fix) and require callers to supply the
  version on every write; server only validates format and strict-greater-than-latest. - Add
  accepted_at timestamp to contract_versions; flip proposal→active in place on accept rather than
  copying, so the caller's intended version is preserved. - Update every endpoint request/response
  example to use string semver. - Add open question on pre-release suffix support.

### ✨

- ✨ /learn-contract: read-side narrator skill for contracts by id (closes #41)
  ([`f2cae15`](https://github.com/Westfall-io/titan-tyr/commit/f2cae15645855311ba89e31a3435b1e5ea2ec2cb))

Mirrors /learn-part for contracts. Takes a contract_id, fans out to GET /contracts/{id},
  /contracts/{id}/proposals, and /contracts/{id}/subtype-proposals in parallel; returns one composed
  JSON response with body, endpoints, open content proposals, open subtype shifts, and the most
  recent shift attribution.

Read-only — no propose/accept buttons; action surfaces remain in the existing skills
  (/accept-contract-proposal auto-branches between content + shift). Cross-referenced from
  /find-part and /learn-part.

- ✨ /update-skills: pull titan-tyr skill catalog into a downstream consumer
  ([#61](https://github.com/Westfall-io/titan-tyr/pull/61),
  [`7948ef0`](https://github.com/Westfall-io/titan-tyr/commit/7948ef07012708d4dedacba46a1e9afc6c338528))

* ✨ /update-skills: pull titan-tyr skill catalog into a downstream consumer

For agents working in repos that consume the titan-tyr API. Run the skill to refresh the local
  .claude/skills/ tree from github.com/Westfall-io/ titan-tyr@main; helper scripts referenced by
  each SKILL.md are captured under .claude/skills/<name>/scripts/ (per-skill namespace, so the
  consumer's top-level scripts/ dir stays untouched) and the SKILL.md text is rewritten to point at
  the namespaced copies.

All fetches go through `gh api` (raw accept header), so private-repo auth comes from the consumer's
  existing gh login — no token juggling for raw.githubusercontent.com.

Refuses to run inside titan-tyr itself: the canonical source lives here, and a self-overwrite would
  clobber in-flight skill edits. Override with TITAN_TYR_REPO if you actually want to point at a
  fork or staging mirror.

Does not delete local skills missing from main — surfaces them so the user decides whether a
  retired-upstream skill should be removed or kept (consumers may have local-only custom skills
  under .claude/skills/).

* 🔧 sync-titan-tyr-skills.sh --check: read-only drift detector (closes #58 part A)

Drift mode for the same script. SHA-compares each upstream SKILL.md (after applying the namespace
  rewrite) and each referenced script against the local copy. Prints OK / DIFF / NEW / RETIRED per
  file:

OK <name>/SKILL.md local matches upstream DIFF <name>/SKILL.md local exists but differs NEW <name>
  upstream has it, local doesn't RETIRED <name> (local only) local has it, upstream doesn't

Exits 1 if any DIFF or NEW (a real sync would change something); RETIRED is informational because
  sync doesn't auto-delete.

Hash equivalence works because the namespace rewrite is deterministic: the python rewrite anchored
  with `(^|[^/])scripts/X.sh` produces the same bytes given the same upstream input + same dest
  path. `git hash-object --stdin` matches GitHub's blob SHA on identical bytes (verified against the
  contents API).

Resolves the half-of-#58 that's audience-aligned with this PR (every consumer agent benefits from a
  drift pre-flight before running a catalog skill). Parts B/C of #58 — `tyr-routes` / `tyr-schema`
  for OpenAPI probing — are devops/maintainer concerns and stay out of scope here; closing them on
  the issue separately.

* 🔧 release.yml: python-semantic-release on push-to-main with gitmoji parser

Auto-versioning workflow. Reads version from pyproject.toml:project.version, parses commit messages
  with the gitmoji-aware emoji parser, computes the next semver bump, commits the bump back to main,
  tags vX.Y.Z, and creates a GitHub Release.

Emoji → bump mapping (in [tool.semantic_release.commit_parser_options]): 💥 major ✨ 🎉 minor 🐛 🚑 ⚡ 🔧 📝
  ♻️ 🔒 ⬆️ 🩹 patch (anything else) no bump

Squash-merges are the path of least resistance: the PR title becomes the single commit message, so
  the title's prefix dictates the bump. Run the action via push-to-main; concurrency group ensures
  runs serialize.

Closes the manual-version-bump pattern in titan-tyr — pyproject.toml's version is now
  action-managed; PRs should not touch it.

- ✨ Add aliases to software + ?match= lookup + /find-software skill (closes #13)
  ([`57f8c68`](https://github.com/Westfall-io/titan-tyr/commit/57f8c6841ca43ceafdc425a22c6983233e002469))

Adds a TEXT[] aliases column to software with PATCH semantics on PUT and a server-side fuzzy lookup
  at GET /software?match=<query> that substring-matches case-insensitively over name + aliases. New
  /find-software skill wraps the lookup as the discovery front-end for the rest of the titan-tyr
  skill family. Per #13 adjudications: collisions across software are allowed by design.

- ✨ Add Claude Code skill: /accept-contract-proposal (closes #16)
  ([`0fd0a26`](https://github.com/Westfall-io/titan-tyr/commit/0fd0a2690e8dd470dc350e7d2d04e2bd5910ae71))

Mirrors /accept-template-proposal with contract-specific deltas: addressing by id / via software /
  from list (no UUID typing); unified diff between active and proposal body before confirmation;
  explicit 'owner accepts is governance, not API gate' callout. Companion update to
  /accept-template-proposal adds the same callout. Sibling /propose-contract-change tracked in #17.

- ✨ Add Claude Code skill: /accept-template-proposal
  ([`3a8d175`](https://github.com/Westfall-io/titan-tyr/commit/3a8d175520aeaa50c718b17bf9afd4825b4670e0))

Promotes an open template proposal (RC or stable) to the new active version. Lists open proposals,
  requires explicit confirmation on the exact version about to land, then POSTs to
  /templates/{kind}/proposals/{version}/accept.

Acceptance is the only step in the propose/accept flow that changes what every caller sees on the
  next GET /templates/{kind}, so the skill treats the final POST as load-bearing.

- ✨ Add Claude Code skill: /audit-skill (closes #31)
  ([`4bd6733`](https://github.com/Westfall-io/titan-tyr/commit/4bd6733ab4793a25f8a028c97e8545939972bb41))

Post-invocation review of how a skill run actually went. Reads the target skill's SKILL.md,
  reconstructs the run from conversation context, classifies gaps (bug / friction / missing-guidance
  / stale), walks the user through which to act on, and drafts inline edits or issue bodies for
  confirmed fixes. Strict no-auto-* boundary: no auto-apply, no auto-file, no replay, no fabrication
  when context is gone.

Closes the loop that grep-based rename sweeps don't reach — friction the user hit, branches the
  skill body didn't cover, instructions that were technically right but read as ambiguous in
  context.

- ✨ Add Claude Code skill: /learn-software (closes #12)
  ([`c903a0d`](https://github.com/Westfall-io/titan-tyr/commit/c903a0d954afdc1574a3c609a85db4f270a08414))

Read-only lookup skill that pulls everything titan-tyr knows about a registered software node —
  description, version, ticket-filing target, and contracts touching it — and returns it as
  structured JSON for the calling agent to parse.

Inputs: target (required), caller (optional). When caller is given, contracts are filtered to
  caller↔target. Otherwise every contract touching the target is returned.

Workflow: 1. GET /software/{target} → row metadata + latest version markdown. 2. GET
  /software/{target}/contracts → list all contracts (filter to caller-touching if caller provided),
  then GET each contract by ID to fetch its full markdown body (the listing endpoint omits it per
  #7). 3. Resolve ticket-filing target with the precedence from #10: issue_tracker_uri if set; else
  infer GitHub Issues from repo_uri (handles HTTPS and SSH forms); else surface as unknown. 4.
  Return a structured "found" response.

Unknown-target path: substring match (case-insensitive) against the GET /software listing for
  suggestions. Falls back to listing all names when there are no substring hits AND the registry is
  small (≤10). Colloquial mappings ("front end" → admin-ui) are not handled here — they need aliases
  (#13) and will land via /find-software once that schema work is in.

Smoke-tested against the deployed instance: - Found path on titan-tyr: returns the row, infers the
  GitHub Issues URL from the SSH-form repo_uri, contracts empty as expected. - Not-found path on a
  made-up name: returns the only registered name as a suggestion (small-registry fallback rule).

No backend changes; this is purely a skill on top of the existing read endpoints. Aliases follow-up
  tracked in #13; resolution-mode sibling /find-software follows once aliases land.

- ✨ Add Claude Code skill: /propose-contract-change (closes #17)
  ([`1878f3d`](https://github.com/Westfall-io/titan-tyr/commit/1878f3d876010c7a978a6a6a8198f05f0d135460))

Mirrors /propose-template-change with contract-specific deltas: addressing by id / via software /
  from list (no UUID typing); fetches the active contract body for in-place editing rather than
  starting from a template; previews the change as a unified diff; pairs with
  /accept-contract-proposal as the natural next step. Completes the contract propose+accept skill
  pair landed in #16.

- ✨ Add Claude Code skill: /propose-template-change
  ([`b170ccd`](https://github.com/Westfall-io/titan-tyr/commit/b170ccda3e2516b7ae66b2fc3f7a1585a95df4c7))

Drafts and POSTs a proposal to update the software or contract template. Same env-var configuration
  as /register-software (TITAN_TYR_URL, TITAN_TYR_TOKEN). Explicitly does not auto-accept —
  acceptance stays a deliberate separate step.

- ✨ Add Claude Code skill: /register-contract (closes #18)
  ([`9bb0f75`](https://github.com/Westfall-io/titan-tyr/commit/9bb0f75caae0e413353af4548a47983ce1116fd1))

Mirrors /register-software with contract-specific deltas: resolves owner+counterparty via ?match=
  autocomplete (rejects unregistered sides with a route to /register-software); checks for an
  existing contract in the same direction and routes to /propose-contract-change on collision; same
  generic template fill rules as the software side; reports the new contract_id and pairs with
  /propose-contract-change and /accept-contract-proposal. Completes the contract lifecycle skill
  trio (register #18, propose #17, accept #16).

- ✨ Add Claude Code skill: /register-software
  ([`da6aa47`](https://github.com/Westfall-io/titan-tyr/commit/da6aa47b68b8969f96a33bf0ae38a1753dbbc061))

Project-level skill at .claude/skills/register-software/SKILL.md that walks through registering a
  software node against a running titan-tyr instance: confirm the API is reachable, gather inputs,
  fetch and fill the current software template, POST /software, and report the result.

Server location is read from environment variables: - TITAN_TYR_URL (required, no default — fail
  fast if unset) - TITAN_TYR_TOKEN (defaults to 'sysmlv2', the placeholder bearer)

Env-var-only on purpose; .claude/skills/README.md documents the choice (per-shell scope, no
  file-vs-env precedence question, CI-friendly). README.md gets a 'Claude Code skills' section
  pointing at the directory.

- ✨ Add Claude Code skill: /update-software
  ([`fa4ff1c`](https://github.com/Westfall-io/titan-tyr/commit/fa4ff1c0a18332346c6de7c872aaffd7c0963b07))

Appends a new version to an already-registered software node via PUT /software/{name}. Detects
  template-version drift by reading the <!-- template: ... --> stamp from the existing body and
  comparing against the active template version, then helps the user migrate.

Also teaches /register-software the <template-version> meta-placeholder introduced in software
  template 2.1.0, so the stamp is auto-filled from the active template version on POST.

- ✨ Add CORS support with allow-list (closes #14)
  ([`c17366f`](https://github.com/Westfall-io/titan-tyr/commit/c17366fa98050de9cb15d94c5787dbd7848168ff))

FastAPI CORSMiddleware reflects Access-Control-Allow-Origin for digitalforge.app (+ subdomains,
  https only) and any-port localhost (http or https). allow_methods covers GET/POST/PUT;
  allow_headers covers Authorization and Content-Type. Other origins still get the response (CORS is
  browser-enforced) but no allow-origin header back. PATCH bump (non-breaking provider relaxation).

- ✨ Add GET /health liveness/readiness probe (closes #2)
  ([`58762a0`](https://github.com/Westfall-io/titan-tyr/commit/58762a010ba65e67730dad2b6e9b15bc159fc0b2))

New unauthenticated GET /health that returns 200 with {status, version, db} when the API can SELECT
  1 against Postgres, 503 with status="degraded" / db="unreachable" when it can't.

- No bearer required (orchestrators don't carry one). - version is read dynamically from the
  installed package metadata via importlib.metadata; fixes a pre-existing drift in main.py which had
  hardcoded "0.1.0" while pyproject was already at 0.3.0. - 4 new tests cover happy path, no-auth
  requirement, and DB-down via dependency override. Suite at 113 passing, coverage 95%. - README
  smoke test now uses /health (no auth) as the first probe.

Project version 0.3.0 → 0.4.0 (additive endpoint, no schema change).

Per the ticket's "consider /livez vs /readyz" note: starting with a single /health is sufficient for
  current orchestrator needs. Splitting into liveness vs readiness can be a separate ticket once
  there's an actual orchestrator that benefits from the distinction.

- ✨ Add listing endpoints with cursor pagination (closes #7)
  ([`b2b6f4a`](https://github.com/Westfall-io/titan-tyr/commit/b2b6f4ad3ae238dd85de70892966b6100481a7b9))

Three paginated listings now:

- GET /software — list every registered software node (latest version per node, summary fields). New
  endpoint. - GET /contracts — gets a list mode when owner+counterparty are both absent. Existing
  search behaviour (owner+counterparty both present) is unchanged. Half-filter rejected with 422. -
  GET /software/{name}/contracts — now paginated.

All three follow the same shape: - ?after=<cursor>&limit=<n>, default limit 50, max 100. - Cursor is
  opaque base64-url-safe of (updated_at, id) — invalid → 422. - Sort: most-recently-updated first. -
  Response: { "results": [...], "next": "<cursor>" | null }. - Listings omit `markdown` per ticket
  Notes — follow up with the per-row GET endpoint for the body.

Implementation uses Postgres DISTINCT ON to get the latest (semver) version per software / latest
  active per contract in one query, then tuple comparison for cursor filtering. Avoids the N+1
  pattern that the existing /software/{name}/contracts had.

Tests: 11 new in tests/test_listings.py covering empty / single page / multi-page / invalid cursor /
  limit bounds / half-filter rejection / search-mode unchanged. Suite at 144 passing, coverage 95%.

Breaking change in v0.6.0: GET /software/{name}/contracts response shape moved from {software,
  contracts: [{...markdown...}]} to {software, results: [{...no markdown...}], next}. titan-tyr is
  the only registered consumer; not used by any skill.

pyproject 0.5.0 → 0.6.0. Image titan-tyr:0.6.0 built locally; no migration needed.

Unblocks #12 (/learn-software resolution flow can now compose on top of GET /software for candidate
  listing).

- ✨ Add optional issue_tracker_uri to software (closes #10)
  ([`8b998ce`](https://github.com/Westfall-io/titan-tyr/commit/8b998ce1918873f732988ec8d391bd66e3ddb53a))

Adds a nullable issue_tracker_uri column to the software table for deterministic ticket-filing
  routing. When set, it is the canonical URL for filing tickets; when absent, consumers fall back to
  inferring GitHub Issues from repo_uri.

- Alembic 0003 adds the nullable column. - POST /software accepts optional issue_tracker_uri. - PUT
  /software/{name} accepts it with PATCH semantics: omitted = leave unchanged, "https://..." =
  replace, null = clear. - GET /software/{name} returns it. - Strict validation: must be a
  well-formed https:// URL with a host. http://, mailto:, bare paths all 422. - Test suite 104 → 112
  passing, coverage holds at 95%.

Project version bumped 0.1.0 → 0.2.0 (additive backward-compatible).

Resolves all four open questions from #10 per user adjudication: optional, PUT-mutable, strict
  format, template-line for symmetry (tracked separately as the software@2.2.0 template change).

- ✨ Compose Part subtype + member-of unblocked (closes #37)
  ([`ea35814`](https://github.com/Westfall-io/titan-tyr/commit/ea35814e6f834b7987d9929a4634d62105ef60a0))

Adds the `compose` Part subtype, representing a Docker Compose stack — a collection of services
  declared in a `docker-compose.yml` (or `compose.yaml`). The Compose Part is metadata *about* the
  file; the file itself remains the source of truth.

Unblocks the last remaining `connection_type` label deferred from #32:

- `member-of`: Container → Compose (a container is a service entry in a compose stack)

After this every `connection_type` arm has both Part subtypes implemented; the router's
  deferred-subtype guard is a no-op for the current rule set, but stays in place for any future rule
  that references a missing subtype.

Schema (migration 0010): extends `ck_parts_subtype_allowed` to {software, container, image, pod,
  compose} and `ck_templates_kind_allowed` to admit `compose`; seeds the `compose` template at
  v1.0.0 active. Drop+recreate per the established 0006/0007/0008/0009 ordering pattern; round-trips
  cleanly.

Router: `_PART_SUBTYPES_IMPLEMENTED` now includes `compose`, which is what actually unblocks
  `member-of`. The container-arm rule (`member-of` owner = container, counterparty = compose) was
  already in CONNECTION_RULES from #32 — the table didn't change.

Tests: `test_member_of_rejected_compose_not_implemented` was replaced with positive `member-of
  container → compose` plus the two negative-direction tests (owner-must-be-container,
  counterparty-must-be-compose).

Skills + docs: register-part / register-contract / propose-template-change /
  accept-template-proposal / docs/api.md all extended for the new subtype + kind. The "not yet
  implemented" branch in register-contract step 4 is gone; the router's guard remains documented as
  a safety net for future rules.

Bumps to 0.14.0.

- ✨ Connection contract subtype + connection_type discriminator (closes #32)
  ([`15ce626`](https://github.com/Westfall-io/titan-tyr/commit/15ce62647797f36bbea161df7eaf4891d72c088a))

Adds a third contract subtype, `connection`, for structural couplings declared in
  build/config/deploy artifacts where no data flows at runtime — Dockerfile builds, compose
  membership, k8s instantiations, git submodule includes, etc. Six labels distinguish the kinds of
  structural binding (`builds-from`, `instantiates`, `runs`, `member-of`, `depends-on`,
  `submodule`); these live in a new `connection_type` column required iff `subtype = 'connection'`.

Per-label From/To Part subtype rules enforced in the router (matches the binding precedent). Labels
  referencing un-implemented Part subtypes (`image`, `pod`, `compose`) reject at registration with a
  clear "not yet implemented" error rather than silently 404'ing. Today only `depends-on` (container
  ↔ container) and `submodule` (software ↔ software) work end-to-end; `image`/`pod`/`compose` Part
  subtype work tracked separately.

Migration 0007 round-trips clean against ephemeral PG. New `connection` template seeded at v1.0.0
  with the per-label rule table inside the instructional blockquote. All four contract-aware skills
  updated for the new subtype + new template kind.

- ✨ Contract subtype discriminator: interaction (existing) + binding (new) (closes #24)
  ([`d79b146`](https://github.com/Westfall-io/titan-tyr/commit/d79b14609d8aa97587f554ffcdb42b99a90fc52b))

Mirror the part-subtype work from #23, applied to contracts. Add a `subtype` column to contracts to
  discriminate between `interaction` (the existing protocol/schema agreement, default for backfill)
  and `binding` (a new env-specific deployment binding from a container to a software part). Rename
  templates kind `contract` → `interaction` so every template kind matches a subtype. Seed the
  binding template at v1.0.0 from the SysMLv2 definition supplied in #24.

Schema (single migration `0006_contract_subtype_and_binding`, round-trips clean): - add
  `contracts.subtype` NOT NULL with CHECK against ('interaction', 'binding'); existing rows backfill
  to 'interaction' - rename `templates.kind` 'contract' → 'interaction' (single UPDATE;
  template_versions ride along via template_id, no FK churn) - replace templates kind allow-list
  with ('software', 'container', 'interaction', 'binding') - seed `kind='binding'` template at
  v1.0.0 active

API: `POST /contracts` requires `subtype`. For `binding`, additional

enforcement: owner_part must be `subtype='container'`, counterparty_part must be
  `subtype='software'` (422 with a clear message otherwise; preserves today's
  `interaction`-as-catch-all behaviour). `GET /contracts` adds `?subtype=` filter (combines with
  both list and search modes). `subtype` returned in all detail/list/ search response items.
  Templates VALID_KINDS extended to the new four-kind set; `/templates/contract` is now a 404 (use
  `/templates/interaction`).

Skills: `register-contract` rewritten with subtype branching (10-step

flow: pick subtype, resolve parts with subtype-aware ?match=, subtype-specific source/target
  validation pre-flight, fetch matching template, fill, preview, POST). All other contract/template
  skills updated for the new kind names and the subtype field surfacing.

Docs: README + DESIGN.md + api.md updated. New Contracts subtype table; binding source/target rules
  called out; contract→interaction rename flagged as a breaking change in v0.10.0.

Tests: contracts subtype injection across 7 inline POSTs + helpers in
  test_contracts/test_parts/test_listings/test_proposals/test_history. New TestContractSubtype
  (required, unknown rejected, returned, filter, filter invalid) + TestBindingSubtype
  (container→software register, source must be container, counterparty must be software, interaction
  accepts any pair). Templates tests updated for the four-kind set including a new
  test_binding_template + test_interaction_template.

Version bumped 0.9.0 → 0.10.0. All 243 tests pass at 96% coverage. Migration round-trip (upgrade →
  downgrade → upgrade) verified clean against an ephemeral PG.

- ✨ Endpoint-shift (contracts) + name-shift (parts) proposal flows (closes #45)
  ([#55](https://github.com/Westfall-io/titan-tyr/pull/55),
  [`d05c125`](https://github.com/Westfall-io/titan-tyr/commit/d05c125e093f1a63cf3ace381f97aa36155b60ab))

Two new shift families that mirror the subtype-shift handshake from #33: contracts can re-point one
  or both endpoints, and parts can rename in place. Body, version, and proposal trail survive both
  shifts; only the structural row columns change on accept.

Renames don't cascade — contracts hold endpoints by id (not name), so contract responses surface the
  new name automatically on the next GET. Endpoint shifts re-validate against the widened uniqueness
  key from #42 and the per-subtype source/target rule.

Bumps API to 0.19.0; adds four new skills (propose/accept × name + endpoint).

- ✨ Image Part subtype + image template (closes #35)
  ([`d3b40f1`](https://github.com/Westfall-io/titan-tyr/commit/d3b40f1474c5b40fdb7858f0ace5c10d322c6707))

Adds the `image` Part subtype, representing the built artifact between Software (the source repo)
  and Container (the running instance), and unblocks two of the six `connection_type` labels
  deferred from #32:

- `builds-from`: Software → Image (Dockerfile + CI) - `instantiates`: Image → Container (the pod arm
  still waits on #36)

Schema (migration 0008): extends `ck_parts_subtype_allowed` to {software, container, image} and
  `ck_templates_kind_allowed` to admit `image`; seeds the `image` template at v1.0.0 active.
  Drop+recreate per the established 0006/0007 ordering pattern; round-trips cleanly.

Router: `_PART_SUBTYPES_IMPLEMENTED` now includes `image`, which is what actually unblocks the two
  connection_type labels above. CHECK constraint is the persistence guard; the router check is the
  validation layer.

Skills + docs: register-part / register-contract / propose-template-change /
  accept-template-proposal / learn-part / docs/api.md all extended for the new subtype + kind. The
  `builds-from` and `instantiates` (container arm) labels are now documented as end-to-end; only the
  `pod` and `compose` arms remain deferred.

Bumps to 0.12.0.

- ✨ Implement FastAPI + Postgres backend with tests (80 passing, 95% coverage)
  ([`c49f278`](https://github.com/Westfall-io/titan-tyr/commit/c49f27840589ad9339728b0bab364a07262c9056))

src/ implementation: - SQLAlchemy 2.x async models for software, software_versions, contracts,
  contract_versions with the schema from DESIGN.md (semver triple, prerelease nullable, NULLS NOT
  DISTINCT uniqueness, invariant CHECKs). - Caller-supplied semver versioning (versioning.py) with
  strict format, semver tuple ordering, RC-aware comparison. - Routers covering every documented
  endpoint: software, contracts, proposals (incl. RC chain + accept that flips stable in place vs
  copies to new stable for RC). - Bearer-password auth dependency (placeholder 'sysmlv2', hardcoded
  per DESIGN.md note on not promoting it to config). - Alembic 0001_initial migration matching the
  ORM schema. - Templates served verbatim from templates/ for /templates endpoints.

tests/: - testcontainers-postgres fixture (function-scoped engine with NullPool to avoid
  cross-event-loop connection sharing). - Per-test schema reset, dependency-injected session via app
  override. - Unit tests on the versioning module (parse, format, ordering, RC). - Integration tests
  on every endpoint, including RC chain promotion, duplicate conflicts, malformed versions, and
  unknown-resource 404s.

- ✨ Make CORS allow-list configurable via env vars (closes #15)
  ([`ba7a1cd`](https://github.com/Westfall-io/titan-tyr/commit/ba7a1cda636c8825d5dd6910d573548ea011885f))

CORS_ALLOWED_ORIGINS — comma-separated list of literal origins (scheme://host[:port]) replaces the
  source-hardcoded default verbatim. Per-entry validated at startup; '*', wildcards, paths, trailing
  slashes, and non-http(s) schemes fail-fast with a clear error.

CORS_ALLOW_ANY_ORIGIN=true — opt-in fully-open mode (allow_origins=*). Takes precedence over
  CORS_ALLOWED_ORIGINS.

Neither set → fall back to the existing hardcoded regex (digitalforge.app + subdomains over HTTPS,
  localhost any port).

PATCH bump (additive, fully backwards compatible — operators who don't set the env vars see no
  behavior change).

- ✨ Make repo_uri PUT-mutable on /software/{name} (closes #11)
  ([`c648aef`](https://github.com/Westfall-io/titan-tyr/commit/c648aefe3744176701144892d7e981c5e9f8f489))

repo_uri can now be updated when a repo is renamed, transferred, or migrated to a different host.
  PATCH semantics mirror issue_tracker_uri:

| Sent in body | Effect | | ------------------------- | ---------------------------- | | Field
  omitted | Existing value unchanged. | | "repo_uri": "https://..." | Replaces stored value. | |
  "repo_uri": null | 422 — cannot clear. | | "repo_uri": "" | 422 — cannot empty. |

Per #11 adjudication:

1. Validation stays open — repo_uri accepts any non-empty string (HTTPS URLs, SSH form like
  git@github.com:owner/repo.git, etc.) so existing callers using SSH form aren't broken. 2. Update
  stays coupled with the version bump (no separate PATCH endpoint). Updating repo_uri appends a new
  software_versions row the same way any other PUT does. 3. Audit trail of repo moves is out of
  scope for this ticket.

Tests 109 passing, coverage 95%. Project version 0.2.0 → 0.3.0.

- ✨ Per-resource version history endpoints (closes #20)
  ([`2384048`](https://github.com/Westfall-io/titan-tyr/commit/2384048e671b7f19ace29793557274a8083aaf41))

GET /software/{name}/history — every software_versions row GET /contracts/{contract_id}/history —
  every contract_versions row with status='active'

Cursor-paginated, most-recent first, default limit 50, max 100. Markdown omitted from listings (same
  rule as the other list endpoints — fetch bodies via GET /software/{name} or GET /contracts/{id}).
  Returns 404 if the parent doesn't exist.

Contract history naturally excludes RC proposals: the active_must_be_stable check constraint
  guarantees status='active' rows have a NULL prerelease, so the WHERE status='active' filter both
  removes pending RCs and keeps superseded ones out without client-side filtering. The proposal
  pipeline remains visible via GET /contracts/{id}/proposals.

Schemas live as a shared VersionHistoryItem / VersionHistoryResponse since both endpoints return the
  identical {version, updated_at} shape.

Cursor key on the contract endpoint sorts by created_at (consistent with _list_active_contracts) but
  the reported updated_at is accepted_at OR created_at, so RC promotions show their accept time.

MINOR bump (additive endpoints, no breaking changes).

- ✨ Pod Part subtype + binding source relax (closes #36)
  ([`9f3a0f2`](https://github.com/Westfall-io/titan-tyr/commit/9f3a0f26aecee53a2c4a5f59811a978bb11ab585))

Adds the `pod` Part subtype: the K8s sibling of `container`, a scheduled unit of one or more
  co-located containers sharing a network namespace and storage. Same "runtime instance of an image
  at an address in an environment" mental model — different orchestrator.

Unblocks the remaining `pod` arms of the connection labels deferred from #32, plus relaxes the
  `binding` source rule:

- `instantiates`: Image → Pod (in addition to the container arm shipped in #35) - `runs`: Pod →
  Software (in addition to the container arm) - `binding`: relaxed from owner.subtype == "container"
  to owner.subtype IN ("container", "pod")

The SysMLv2 binding spec was always permissive on the binding owner; the code only restricted to
  container because pod didn't exist yet.

Schema (migration 0009): extends `ck_parts_subtype_allowed` to {software, container, image, pod} and
  `ck_templates_kind_allowed` to admit `pod`; seeds the `pod` template at v1.0.0 active.
  Drop+recreate per the established 0006/0007/0008 ordering pattern; round-trips cleanly.

Router: `_PART_SUBTYPES_IMPLEMENTED` now includes `pod`, which is what actually unblocks the two
  connection_type label arms above. `_BINDING_OWNER_SUBTYPES` (new module-level constant) replaces
  the inline container-only check in register_contract.

Skills + docs: register-part / register-contract / propose-template-change /
  accept-template-proposal / docs/api.md all extended for the new subtype + kind. The `instantiates`
  and `runs` labels are now documented as end-to-end on both runtime arms; only `member-of`
  (compose) remains deferred.

Bumps to 0.13.0.

- ✨ Project tagging on parts and contracts (closes #44)
  ([`4842134`](https://github.com/Westfall-io/titan-tyr/commit/48421346e91256fd2236e698e3880a542cb56a18))

Adds a first-class `projects` table and nullable `project_id` foreign keys on `parts` and
  `contracts`. Lets one titan-tyr database hold multiple projects' worth of graph and lets consumers
  (titan-mimiron, agents) filter to one project at a time.

Membership is single-project (one project_id per row, not a junction table) and optional (NULL =
  unprojected). Existing rows keep working untouched. Project metadata is minimal: slug name +
  optional description + created_at + created_by_actor (mirrors the #39 attribution pattern). No
  deletion endpoint — projects accumulate; archive semantics deferred.

API surface: POST /projects — create (X-Actor recorded) GET /projects — list with part/contract
  counts GET /projects/{name} — read one PUT /projects/{name} — update description (name immutable)

Parts and contracts gain an optional `project` field on POST/PUT that resolves to a project_id (422
  if the slug is unknown). The existing list endpoints accept `?project=<slug>` to filter and
  `?project=__none__` (sentinel) to filter to unprojected rows; the sentinel is used because it
  cannot be a valid slug, so collision with a real project name is impossible. PUT /parts/{name}
  treats explicit `project: null` as "clear the tag" and field-absent as "unchanged."

Cross-project contracts are allowed: the contract's project_id is independent of its endpoints'
  projects, tagged with whichever project owns the *relationship*.

Migration 0015 adds the projects table + the two FK columns + two indexes. Data-safe — every
  existing row gets project_id=NULL and behaves as it does today; no backfill needed.

DESIGN.md Concepts table and example schema updated to reflect the five part subtypes, three
  contract subtypes, project metadata, and the eight templates.

Skill updates: new /register-project and /list-projects skills; /register-part and
  /register-contract document the optional project field with explicit guidance to tag proactively
  when the project context is obvious and to ask otherwise.

30 new tests cover projects CRUD, slug validation, duplicate-name 409, X-Actor attribution,
  part/contract project tagging, cross-project contracts, and the list filter (specific project +
  unprojected sentinel + combined with subtype filter). Full suite: 368 passed, 1 skipped, 93%
  coverage.

Bumps to 0.18.0.

- ✨ PUT /contracts + X-Actor backfill + history actor + scripts/ helpers (closes #47, #52, #53, #54)
  ([#56](https://github.com/Westfall-io/titan-tyr/pull/56),
  [`30c42fe`](https://github.com/Westfall-io/titan-tyr/commit/30c42fe2c8e8163eb62bbc50c9b6a14ce68743c4))

* 🔧 Add scripts/ for repeated curl-pipe-to-python one-liners

Four helpers for the live titan-tyr API: show-template, show-contract (read), propose-template,
  propose-contract (write). Each defaults to http://localhost:18000 + token sysmlv2 + X-Actor
  titan-tyr (the agent identity), with TITAN_TYR_URL / TITAN_TYR_TOKEN / TITAN_TYR_ACTOR overrides
  for dev/test runs.

These replace shapes I'd otherwise re-type in transcripts (curl … | python3 -c "import json,sys;
  …d['markdown']…").

* 🔧 scripts/show-issue.sh — pretty-print a GitHub issue

Same shape as show-template.sh / show-contract.sh: takes <issue_number>, prints
  title/state/labels/body and any comments. Replaces the inline gh issue view + python3 -c "import
  json,sys; …" pattern.

* ✨ POST /parts and PUT /parts/{name} echo full persisted row (closes #47)

Both responses gain `repo_uri`, `issue_tracker_uri`, `aliases`, `markdown`, `updated_at`,
  `created_by_actor`, and `project` — matching the GET shape exactly. Eliminates the verify-with-GET
  round-trip in update-part / register-part skills.

Purely additive on the wire; consumers reading only `name`/`version` keep working. Bumps API to
  0.20.0.

* 🔧 scripts/list-routes.sh — boot the FastAPI app and dump routes

Boots create_app() locally and prints method + path for every route, optionally filtered by a path
  substring (e.g. /contracts). Runs entirely against source — no live API. Useful as a wiring sanity
  check after adding or renaming a route.

* ✨ PUT /contracts/{id} + X-Actor backfill + per-version actor on contract history (closes #52, #53,
  #54)

Three related gaps surfaced when downstream consumers tried to retroactively project-tag and
  attribute legacy rows:

- New PUT /contracts/{id} accepts soft metadata (project today; PATCH semantics: omit/value/null).
  Body / version / subtype / endpoints remain on their dedicated propose-accept flows. No version
  bump on metadata-only updates. - created_by_actor backfill on PUT (parts + the new contracts PUT):
  X-Actor on PUT claims a row whose current actor is NULL. Once set, the field is immutable on PUT —
  first-write-wins prevents identity-spoofing of attributed rows. - /contracts/{id}/history entries
  gain proposer_actor / acceptor_actor / single_operator_override on every kind (body_bump,
  subtype_shift, endpoint_shift). Pre-#38 rows surface as null/false. - New update-contract SKILL
  wraps the new PUT; update-part SKILL step 5 gains a project row and notes the backfill semantics;
  register-{part,contract} SKILLs soften the "only attribution signal" wording. -
  /parts/{name}/history actor surfacing is deferred (PartVersion has no actor columns; needs a
  migration).

Bumps API to 0.21.0.

- ✨ Rename software→part + add subtype discriminator (closes #23)
  ([`0249e20`](https://github.com/Westfall-io/titan-tyr/commit/0249e20af4e14f424e0c2cd6ab34b2531ed901a6))

Rename `software` → `part` throughout the API, schema, ORM, tests, skills, and docs. Add a `subtype`
  column to parts to discriminate between `software` (a codebase / deployable boundary, the existing
  behaviour) and `container` (a running instance of an image, new in this drop). Seed the container
  template at v1.0.0 from the SysMLv2 definition supplied in the issue.

Schema: rename tables `software`→`parts`, `software_versions`→ `part_versions`; rename FK columns to
  match (`owner_part_id`, `counterparty_part_id`, `part_id`); add `subtype` NOT NULL with CHECK
  against (`software`, `container`); extend templates kind CHECK to include `container`. Single
  migration `0005_software_to_part_subtype`, round-trips clean (upgrade/downgrade/upgrade verified).
  Existing rows backfill `subtype='software'`.

API: `/software/*` → `/parts/*` everywhere (list, register, detail, update, history,
  contracts-touching). Register requires `subtype`; list supports `?subtype=` filter. Subtype is
  immutable on PUT. Contract endpoints now use `owner_part`/`counterparty_part` field names; the
  touching-contracts endpoint response key flips `software`→`part`. Templates endpoint now serves
  `software`, `container`, and `contract` kinds.

Skills: `register-part` rewritten with subtype branching (fetches the matching template; container
  path includes a pre-flight check that the referenced software part exists). All other skills
  updated for the rename and new endpoints; README skill table refreshed.

Docs: README/DESIGN.md/api.md/getting-started.md fully updated for the rename and the subtype model.
  DESIGN.md schema block reflects the new table names + subtype CHECK + three template kinds.

Version bumped 0.8.0 → 0.9.0. All 229 tests pass at 96% coverage.

- ✨ Subtype-aware uniqueness on contracts (closes #42)
  ([`3e80c88`](https://github.com/Westfall-io/titan-tyr/commit/3e80c884862220da8a7d19dc9cbeed23ad5bacde))

Widens the contract uniqueness key from (owner_part_id, counterparty_part_id) to (owner_part_id,
  counterparty_part_id, subtype, connection_type) NULLS NOT DISTINCT, so a directed pair can hold
  one interaction + one binding + one connection per connection_type simultaneously.

This makes the multi-row Connections tables in container@2.0.0 (closed by #34) and container@3.0.0
  (templates audit) realisable in the graph — registering a binding on a pair that already holds a
  connection/runs no longer 409s.

Migration 0014 drops uq_contracts_owner_part_id_counterparty_part_id and creates
  uq_contracts_subtype_pair as a unique index with NULLS NOT DISTINCT (the constraint name had to be
  shortened explicitly to stay under Postgres's 63-char identifier limit). The downgrade has a guard
  that fails fast if any pair has grown to hold multiple rows under the widened key, so callers
  can't silently corrupt the narrower constraint.

Application-layer existence check at /contracts now matches the DB key on all four columns; the 409
  detail names the offending subtype (and connection_type) so the caller can tell a "connection/runs
  already exists" collision from a "binding already exists" collision on the same pair.

Pre-flight audit on the live db before landing: 21 contracts, 21 unique pairs, zero pairs holding
  multiple rows. Migration is data-safe — no row participates in either the dropped or added
  constraint as a collision.

Six new integration tests cover: connection/runs + binding coexistence, connection/runs +
  interaction, interaction + binding (both NULL connection_type), two connection_types on the same
  pair, duplicate (subtype, connection_type) triples still 409, duplicate interaction still 409.

Skill notes in /register-contract refreshed: 409 row in the error table now describes the
  triple-collision shape, and the "one row per pair" rule replaced with "one row per (direction,
  subtype, connection_type) triple" — explains the up-to-eight-rows-per-direction ceiling and gives
  container/software as the canonical two-row example.

DESIGN.md uniqueness sentence updated. The earlier example schema still showed pre-#32 subtypes
  (interaction + binding only); fixed the subtype CHECK and the UNIQUE clause to match what's now
  shipping. The rest of that section is broader-stale — out of scope for this fix.

Bumps to 0.17.0.

- ✨ Subtype-shift proposal flow for parts and contracts (closes #33)
  ([`fce74c4`](https://github.com/Westfall-io/titan-tyr/commit/fce74c4202b484bcea2828028e7f7a98218e68a6))

Adds a separate propose/accept flow for correcting a row's structural subtype (and, for connection
  contracts, its `connection_type` label) without mutating the body or bumping the version.

Six new endpoints (3 per surface): POST/GET subtype-proposals + POST accept on /parts/{name}/ and
  /contracts/{contract_id}/. Two-party sign-off via X-Actor header with `?single_operator=true`
  override for solo setups. Part shifts soft-warn on related-row impact; contract shifts hard-block
  on source/target rule violations.

History endpoints now emit a `kind` discriminator (`body_bump` or `subtype_shift`) and merge the two
  event streams.

Migration 0011 adds nullable shift-tracking columns on parts/contracts plus two new proposal tables.
  Pre-v0.15.0 history responses lack the `kind` field; consumer parsers should default it to
  `body_bump`.

- ✨ Support RC pre-release versions on contract proposals
  ([`c359252`](https://github.com/Westfall-io/titan-tyr/commit/c35925299c4141a734a8d93d942a16237e95f07b))

- Add prerelease TEXT column to contract_versions (NULL = stable; pattern '^rc\d+$'); UNIQUE NULLS
  NOT DISTINCT on the version triple + prerelease so each RC iteration is a distinct row. - CHECK
  constraints enforce that active rows are always stable (no prerelease) and only proposals may
  carry an RC suffix. - Add promoted_from_prerelease column to record which RC produced an active
  row; new accept-flow creates a new stable row when promoting an RC and leaves all RC rows in place
  for posterity. - In-place flip is preserved for stable proposals (caller's version wins); RC
  acceptance strips the suffix. - Document the visibility rule: -rcN suffixes only appear in
  responses from proposal-specific endpoints; all other endpoints return stable versions only. -
  Update format regex to '^\d+\.\d+\.\d+(-rc\d+)?$' and the open question to cover broader
  pre-release labels (alpha/beta) instead.

- ✨ Templates are DB-backed and proposable
  ([`e740be0`](https://github.com/Westfall-io/titan-tyr/commit/e740be053ec3c0753c3f0151951b1f7fe0e9634b))

Templates ('software', 'contract') previously served verbatim from templates/ on disk are now
  versioned rows in Postgres, mutated through the same propose/accept/RC machinery as contracts.

Schema: - New templates table (kind UNIQUE in {software, contract}). - New template_versions table
  mirroring contract_versions exactly: semver triple + nullable prerelease, NULLS NOT DISTINCT
  uniqueness, invariant CHECKs (active rows are stable; prerelease grammar; etc.), accepted_at +
  promoted_from_prerelease for provenance. - Migration 0002 creates both tables and seeds v1.0.0 of
  each template with the current markdown bodies embedded as Python literals (so the migration is
  self-contained; no file dependency).

Endpoints: - GET /templates/{kind} — DB-backed; same text/markdown contract. - POST
  /templates/{kind}/proposals — propose a change. - GET /templates/{kind}/proposals — list open
  proposals (RCs included). - POST /templates/{kind}/proposals/{version}/accept — promote; stable
  in-place, RC creates new stable + retains RC row for posterity.

Other changes: - Drop templates/ directory and the COPY templates line in Dockerfile. - Drop
  templates_dir from config.py (vestigial). - Tests: conftest seeds two placeholder templates after
  schema create so the GET endpoint returns content; test_templates rewritten to cover the new
  propose/accept/RC flow. - Migration round-trip verified: alembic upgrade -> downgrade -> upgrade
  works against fresh PG. Image rebuilds cleanly without templates/.

Doc updates: - DESIGN.md: Templates row added to Concepts; templates + template_versions in Schema;
  full Templates section under Endpoints; Project layout no longer mentions templates/. - README.md:
  Features bullet for proposable templates; project layout updated. - docs/api.md: Templates section
  rewritten with the four new endpoints.

Bonus fix: shortened the 73-char uq_software_versions_* constraint name to
  uq_software_versions_version (was over Postgres's 63-char identifier limit; create_all silently
  truncated, but Alembic's stricter validator raised). Both 0001 migration and the ORM model updated
  to match.

- ✨ Tighten software-name validation to slug pattern (closes #3)
  ([`74d5e38`](https://github.com/Westfall-io/titan-tyr/commit/74d5e38901bc073677192ab2c6583942629053a5))

`name` on POST /software and the `owner_software` / `counterparty_software` fields on POST
  /contracts now match:

^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$

Lowercase letters, digits, hyphens; 1–64 chars; no leading/trailing hyphen; no spaces, dots,
  slashes, underscores, or other punctuation. Names appear in URL paths and contract markdown —
  anything that would need URL-encoding or be awkward to grep is rejected at the door.

- 20 new tests (positive + negative cases on POST /software, plus non-slug owner/counterparty
  rejection on POST /contracts). - Suite at 133 passing, coverage 95%. - software@2.3.0 template
  (accepted live) extends the instructional blockquote with the slug rule so register-software
  callers see it before they POST.

Project version 0.4.0 → 0.5.0. titan-tyr the only registered software today already conforms
  (`titan-tyr` is a valid slug); no callers broken by the tightening.

- ✨ X-Actor attribution end-to-end (closes #38, #39)
  ([`6962184`](https://github.com/Westfall-io/titan-tyr/commit/6962184bfe81a174bf2bc73ffe8c8b88d63d2cfc))

Extends the two-party rule shipped in #33 (subtype-shift endpoints only) to content + template
  proposals — the four endpoints that previously bypassed it. Closes the attribution gap on initial
  registration in the same release.

#38 — Two-party rule on content + template proposals. - Migration 0012: nullable proposer_actor /
  acceptor_actor / single_operator_override on contract_versions and template_versions;
  single_operator_override retrofit on the two existing shift tables (the override has been honored
  since #33 but wasn't recorded). - Routers: POST /contracts/{id}/proposals[/accept] and POST
  /templates/{kind}/proposals[/accept] read X-Actor; accept paths reuse enforce_two_party() from
  _subtype_helpers.py. ?single_operator=true override on both new accepts. RC promotion carries
  proposer/acceptor + override flag onto the new stable row. - Schemas surface the three new fields
  on listings + accept responses; shift entry/accept schemas also surface the override flag.

#39 — Initial-creation attribution. - Migration 0013: nullable created_by_actor on parts +
  contracts. - POST /parts and POST /contracts read X-Actor and store it; GET detail + listing
  surfaces include the field. No two-party rule — these are one-shot active creates with no acceptor
  to compare against; this is single-actor paper-trail attribution.

Skill + doc updates: - accept-contract-proposal / accept-template-proposal: X-Actor on the POST
  recipe; ?single_operator=true override; warning if TITAN_TYR_ACTOR is unset. -
  propose-contract-change / propose-template-change: X-Actor on the POST recipe; warning if unset. -
  register-part / register-contract: same. - docs/api.md: new "Two-party attribution" subsection
  under Proposals; X-Actor recipes on POST /parts + POST /contracts; attribution fields documented
  on listings + accept responses.

Pre-v0.16.0 rows surface as anonymous (NULL actors, FALSE override) and the rule treats anonymous as
  "unenforceable, allow" — clients with old proposers can still accept under any X-Actor. Existing
  consumers without X-Actor continue to work; the feature is strictly additive on the request side.

### 🎉

- 🎉 Add AGENTS.md with agent operating rules
  ([`5c4fc95`](https://github.com/Westfall-io/titan-tyr/commit/5c4fc95a05108b95f9a7a40b59f52359e21a3289))

### 🐛

- 🐛 Correct repo name to titan-norgannon (double-n)
  ([`e8ab342`](https://github.com/Westfall-io/titan-tyr/commit/e8ab34276c2a59ea90098f338073771180e20544))

### 📝

- 📝 /accept-template-proposal: 4-kind list + post-accept audit + patch-bump recipe (closes #29)
  ([`329fe8e`](https://github.com/Westfall-io/titan-tyr/commit/329fe8e35d812529c926026511add98d501412fe))

Updates step 1 from the pre-#24 two-kind list (software, contract) to the current four (software,
  container, interaction, binding). Adds step 8 (audit downstream resources) with a per-kind curl
  recipe and the realign-on-counterparty-side convention for contract templates. Adds step 9
  documenting the stamp-only patch-bump as a recognized recipe so future agents don't reinvent it
  (or worse, try to wedge the fix into a -rc2 against a sealed stable target).

- 📝 /audit-skill: stop auditing stale local copies (step 0 freshness check)
  ([`9b64176`](https://github.com/Westfall-io/titan-tyr/commit/9b6417623d2ebf7874e1446e7eae53ae761fdb12))

Adds a pre-load step that diffs the local SKILL.md against the canonical version in
  Westfall-io/titan-tyr@main. If the local is behind, the audit stops and tells the user to sync
  first — auditing a stale local would dutifully classify already-fixed bugs as new ones and produce
  duplicate issues. Override allowed only on explicit user confirmation; the default is to stop.

In-titan-tyr divergence (working on the skill itself, on a feature branch ahead of main) is treated
  separately — both audit-against-local and audit-against-canonical are legitimate, so we ask which.

- 📝 /find-part: fix broken endpoint, add subtype filter (closes #27)
  ([`d3c75fa`](https://github.com/Westfall-io/titan-tyr/commit/d3c75fadd81b82027684c319eb7ce5cb655a1cc1))

The skill was hitting the pre-rename /software route on every match call (404 since v0.9.0). Switch
  to /parts, sweep the rest of the doc for software→part where the rename applies, and surface the
  new ?subtype= filter as an optional input so callers can disambiguate colloquial labels that
  collide across the software/container subtype dimension (e.g. "payments" → payments-service vs
  payments-prod).

- 📝 /learn-part: rename response key software→part, surface subtype (closes #30)
  ([`b3bb232`](https://github.com/Westfall-io/titan-tyr/commit/b3bb2323193e9265729ea5b4c42bfde5dc9a9364))

Top-level response key was still `software` from the pre-#23 era, forcing every caller to
  special-case container parts. Renames to `part` and adds the `subtype` discriminator on both the
  part object and each contract entry, with a field note explaining how callers should branch on
  subtype (binding vs interaction, codebase vs running instance).

- 📝 /learn-part: surface open subtype-shift proposals (closes #40)
  ([`6ffe6b6`](https://github.com/Westfall-io/titan-tyr/commit/6ffe6b6843f61d1400d4d05bfd1b76e1b23cc31d))

Adds GET /parts/{name}/subtype-proposals to the fan-out so calling agents see pending shifts without
  an extra round trip. Filters client-side to status='proposal'; adds open_subtype_shifts to the
  documented response shape with a proposer_attribution label that handles the anonymous case
  explicitly. Pre-v0.16.0 servers degrade to an empty array instead of failing the whole skill.

- 📝 /propose-contract-change: subtype-aware stamp check + race pre-flight (closes #28)
  ([`ced7647`](https://github.com/Westfall-io/titan-tyr/commit/ced7647ca8ebee125a2304228c1a449b4471ea10))

Replaces the legacy `<!-- template: contract@X.Y.Z -->` stamp pattern (stale since v0.10.0 renamed
  contract→interaction) with a subtype-aware check keyed off the contract's interaction/binding
  subtype, and adds a new step 4b that fetches the matching template's proposal state so step 5 can
  detect the template-acceptance race that produced the phantom-stamp bug last week
  (titan-mimiron#21).

- 📝 /update-software: explicit re-stamp on migration + stamp-mismatch preview (closes #19)
  ([`37491c3`](https://github.com/Westfall-io/titan-tyr/commit/37491c3798b742196efe77b455151ad7282a7df9))

Two skill edits per #19:

- Step 4: Add an "Always re-stamp on structural migration" callout. The
  substitute-<template-version> rule from /register-software only fires when the stamp is still a
  placeholder; on update the stamp is a literal value, so the rule silently no-ops and stale stamps
  drift forward. - Step 7: Surface stamp value alongside active template version in the preview so
  any mismatch is visible at the confirmation gate.

- 📝 Add _model/00_index.md ICD knowledge base overview
  ([`e8040a1`](https://github.com/Westfall-io/titan-tyr/commit/e8040a16697c187fa173520b388af770c0eecb58))

- 📝 Add DESIGN.md developer brief
  ([`0865482`](https://github.com/Westfall-io/titan-tyr/commit/0865482a11f465ddfb3395e727443f168edd859d))

- 📝 Add docs/ (api + getting-started) and rewrite README for the implementation
  ([`cffc1b0`](https://github.com/Westfall-io/titan-tyr/commit/cffc1b04d64fc90f416e939b69b2e493ab79f652))

docs/api.md — endpoint-by-endpoint reference with curl examples, covering auth, status codes,
  semver/RC visibility rules, and the two acceptance paths (in-place stable vs RC-promotion).

docs/getting-started.md — local Postgres + alembic + uvicorn setup, test instructions
  (testcontainers default, TEST_DATABASE_URL escape hatch), and project layout.

README.md — replaced the GitHub-API-backed pitch with one that matches what actually ships: FastAPI
  + Postgres, semver/RC behaviour, the sysmlv2 placeholder auth, and pointers into docs/ +
  DESIGN.md.

- 📝 Add README based on DESIGN.md
  ([`9f90fc5`](https://github.com/Westfall-io/titan-tyr/commit/9f90fc5c5c63d7c3e410d424c1acc2fd67f8fdc2))

- 📝 Encode cross-team contract handshake in skills (closes #21)
  ([`18cd633`](https://github.com/Westfall-io/titan-tyr/commit/18cd6336af9cb4fa0fd279b4e6a3bc9c13c6e1cd))

Three operational rules that lived only in agent-private memory now live in the skill bodies, where
  they're authoritative for any agent driving the same skills (not just the one whose memory holds
  them).

/propose-contract-change — new step 10: notify the counterparty by commenting on a linked issue in
  their repo (or filing a new one), so the proposal doesn't sit unreviewed because the other side
  doesn't poll the contract endpoint. Also reframes the closing message: the proposer does not
  auto-accept, the counterparty is the natural acceptor.

/accept-contract-proposal — new "Before you start" guard: confirm THIS side did not originate the
  proposal you're about to accept; self-accepting defeats the cross-team review. Step 4
  cross-references the guard once a specific RC has been picked. Reconciles with the existing "Owner
  accepts is governance language" note: proposer-vs-acceptor is workflow-derived; in a cross-team
  setup it wins over the owner-acceptor role statement.

/register-contract — brief addition to step 3 (Confirm direction): note that direction also sets the
  future review handshake, with a forward reference to /accept-contract-proposal.

Once this lands, two private memory entries become redundant:
  feedback_notify_counterparty_on_proposal.md and feedback_contract_review_protocol.md. Pruning in
  the same session.

- 📝 Enrich contract template with protocol guidance and proposal flow
  ([`4d179d9`](https://github.com/Westfall-io/titan-tyr/commit/4d179d968db3560d6f2735bf0496b9316fb0e1a8))

Pulled from a prior template draft: protocol declaration, the protocol-to-schema mapping table
  (REST/Kafka/gRPC/GraphQL/JDBC/Webhook), explicit Provider/Consumer obligations as binding
  commitments, and schema subsections for request/response/errors.

Adapted to titan-tyr's API: the Change Protocol section points at POST /contracts/{id}/proposals +
  accept rather than the prior PR/tag flow. Dropped the in-body Open Proposals list because GET
  /contracts/{id}/proposals is authoritative for that, and dropped Type/Version/Git SHA/Last
  modified for the same drift reason as software.md.

- 📝 Enrich software template with ports table and direction conventions
  ([`be53394`](https://github.com/Westfall-io/titan-tyr/commit/be5339441f15e05e488ccc95ebcd67ec1b41712c))

Pulled from a prior template draft: explicit Purpose guidance ('two to four sentences, no prior
  context'), a Ports table whose entries reference contract counterparties, and the in/out direction
  conventions for REST, queues, and datastore access.

Dropped from the prior draft what titan-tyr already manages or doesn't model: in-body Version / Git
  SHA / Last-modified (the API stores those on the version row; duplicating in the body invites
  drift) and the SysMLv2 Connections-to-Image table (no Image Part type yet).

- 📝 Redesign DESIGN.md as FastAPI + Postgres graph API
  ([`fa457c6`](https://github.com/Westfall-io/titan-tyr/commit/fa457c649579bf411f5bec75b9fb837e9d4497fd))

- 📝 register-software skill: explicit fill rules, worked example, preview step
  ([`df9a618`](https://github.com/Westfall-io/titan-tyr/commit/df9a61864a39eecde667e108b2e26fd50ab47111))

Dogfooding the skill against the live API showed it told Claude WHAT to ask about per section but
  not HOW to convert template + answers into clean markdown — leaving five judgment calls
  unspecified (instructional blockquote, instructional H3 subsections, placeholder syntax,
  multi-counterparty notation, no preview before POST).

Changes: - Split fetch (step 3) from build (step 4) so the conversion gets its own treatment. - Add
  Fill rules block: <...> is a content slot; instructional blockquotes drop; ### Direction
  conventions always drops; ### What is *not* a Port drops if empty / keeps if you have real
  exclusions; pick one multi-counterparty convention and stick with it; resolve unknown
  counterparties by asking. - Add a before/after worked example so the rules are unambiguous. - New
  step 5: Preview filled body to user and require confirmation before POSTing. - Promoted the
  JSON-via-tool advice from 'prefer' to 'do this' with a concrete python3 one-liner; the markdown
  body has too many shell-hostile characters to escape by hand.

Pairs with #6 (template UX): if/when the template moves instructional content out of the saved body,
  rules 2 and 3 become trivial. The skill remains correct either way.

- 📝 Resolve Open Questions §1: no withdraw/reject by design (closes #5)
  ([`f0885c6`](https://github.com/Westfall-io/titan-tyr/commit/f0885c6a28d71c818b4758400607fddf7474a783))

Per the user's adjudication on #5: a proposal is the initiation of a conversation between two
  components because the current definition is insufficient — it must be resolved, not abandoned.
  The recourse when a proposal is wrong is to make a higher-version proposal on top (RC iteration
  handles this within a target version; counter-proposals across target versions work the same way).
  Stale proposals stay in *_versions for posterity and drop out of GET .../proposals once the active
  version moves past them.

- DESIGN.md Open Questions §1 marked resolved with the rationale. - Updated the schema-design note
  that previously cited "rejected, withdrawn, superseded" as example future status values to flag
  rejected/withdrawn as intentionally-not-planned. - /propose-template-change and
  /accept-template-proposal each grow a Notes bullet so callers don't reach for an endpoint that
  doesn't exist.

No code, no migration, no template change. Behavioural decision only.

- 📝 Skills: coordination-loop awareness + pre-impl acceptance guard (closes #22)
  ([`ea34daf`](https://github.com/Westfall-io/titan-tyr/commit/ea34dafb60cb606968e61ad3bc2acf82cdaea62a))

Items 1 and 2 from the ticket are no-ops here — README already lists both register-contract and
  propose-contract-change accurately (shipped earlier this session under #16-18, refined under #21).
  The mimiron-side snapshot was stale at filing time.

Item 3 (coordination-loop awareness): - accept-contract-proposal step 3 now mandates re-fetching the
  proposals list even if seen earlier, and defaults to the latest RC when multiple exist for the
  same target (earlier RCs are superseded review artifacts). - accept-contract-proposal step 5 adds
  a second diff: the prior-RC comparison ("changes since rc1 — counterparty's revision") in addition
  to the vs-active diff. Two diffs because they answer different questions: what will land vs what
  changed since you last looked. - A "Resuming work in flight" section in skills/README.md
  generalizes the re-fetch-before-acting principle for the propose side and any future skill that
  touches in-flight state.

Item 4 (don't accept stable before implementation): - accept-contract-proposal Notes: explicit guard
  about contracts promising behavior the API doesn't yet serve. Stay on -rcN until the provider has
  shipped and the consumer has verified. - accept-template-proposal Notes: lower-stakes parallel —
  templates affect future fills, not active runtime, but stable acceptance while the register/update
  skills haven't been updated to match warrants the same caution. - propose-contract-change step 6
  (Choose a version): symmetric guidance — implementation-pending proposals start as -rc1 even with
  no negotiation expected.

Item 5 (memory-class lessons in README): - "Common pitfalls" section: contract changes go through
  POST /contracts/{id}/proposals not GitHub issues; propose/accept separation is the review gate;
  proposer doesn't accept their own proposal. The proposer-doesn't-accept rule is also fully in
  /accept-contract-proposal — this is the cross-skill summary.

- 📝 Skills: keep scratch files inside the repo (.scratch/)
  ([`377aad2`](https://github.com/Westfall-io/titan-tyr/commit/377aad26541fd2b1da798273c62427b6e3f39da6))

Both skills previously suggested writing JSON payloads to /tmp/. Project agents are scoped to
  file-system changes within the repo per AGENTS.md, so swap to a gitignored .scratch/ directory at
  the repo root.

- 📝 Skills: recognize the DELETE WHEN FILLING IN marker (companion to #8)
  ([`bf6589a`](https://github.com/Westfall-io/titan-tyr/commit/bf6589a40abe87a7a833f2a125b836a898484261))

software@2.4.0 and contract@1.2.0 (accepted live) prefix every instructional blockquote with
  **DELETE WHEN FILLING IN.** per the Option B adjudication on #8. The skill fill rules already
  strip instructional blockquotes by judgment; tighten the rule wording so the marker is recognised
  explicitly and dropping the whole block becomes a deterministic call.

- 📝 Skills: surface optional issue_tracker_uri on register/update
  ([`a4fc014`](https://github.com/Westfall-io/titan-tyr/commit/a4fc0144d969d6596aeed30ff843015f8321156a))

- /register-software gather-inputs table grows an optional issue_tracker_uri row with the
  strict-https validation note. - /update-software gets a new step 5 documenting the field's PATCH
  semantics on PUT (omitted leaves unchanged, "https://..." replaces, null clears). Subsequent step
  numbers shift.

Per the decoupling principle, no template-specific knowledge added — just the API field that the
  skill needs to know about.

- 📝 Software template: clarify port granularity, multi-counterparty, datastore exclusion
  ([`012ec92`](https://github.com/Westfall-io/titan-tyr/commit/012ec9244cd462eb01d3e14b4ddc2d2729b39e3e))

Three fixes from dogfooding the template against titan-tyr itself:

1. Port granularity: a Port is one logical operation, not one HTTP method. Example: 'manage software
  records' covers POST + GET + PUT on /software/{name} as a single Port. 2. Multi-counterparty: a
  Port may serve multiple registered software nodes (titan-tyr is consumed by mimiron, algalon,
  etc.). Allow comma-separated or one-row-per-counterparty. 3. Datastore exclusion: drop datastore
  reads/writes from the direction conventions and add an explicit 'What is not a Port' section.
  Datastore access is internal; only interfaces with registered software count.

- 📝 Surface attribution + override on accept skill reports; add /check-titan-tyr-env
  ([`03731f1`](https://github.com/Westfall-io/titan-tyr/commit/03731f1d11a1b8fab9b6c670377e5a7ee55a8c2a))

Accept skills (contract / template / part-subtype) now lift proposer_actor, acceptor_actor, and
  single_operator_override out of the response and into the report, with an explicit warning when
  the override was used so the human auditor sees solo-operator landings at a glance.

New /check-titan-tyr-env skill is a read-only pre-flight that verifies TITAN_TYR_URL is set +
  reachable, the token authenticates, and TITAN_TYR_ACTOR is set, returning a structured
  ready/partial/ blocked verdict. Other titan-tyr skills can defer to it instead of each
  re-implementing their own probe.

- 📝 Sweep skills for staleness after v0.15.0 (subtype-shift)
  ([`c76516b`](https://github.com/Westfall-io/titan-tyr/commit/c76516b47e09458242228f72c45d2824ea7e7e28))

- find-part / learn-part: widen subtype enum from software|container to all five
  (software|image|container|pod|compose); these had been stale since #35 (v0.12.0). learn-part also
  surfaces the new subtype_shifted_from / subtype_shifted_at fields. - register-part / update-part:
  replace "register a new part if you need a different subtype" / silent omission with pointers at
  /propose-part-subtype-shift + /accept-part-subtype-shift as the in-place correction path;
  update-part notes the body_realign follow-up. - register-contract: drop the now-false "no in-place
  subtype change" claim; route at /propose-contract-subtype-shift. - propose-contract-change:
  distinguish content edits (this skill) from structural shifts (new skill) at the top; stamp-check
  table grows a row for the post-shift body_realign case.

- 📝 Treat migrations as first-class in DESIGN.md
  ([`76b21a6`](https://github.com/Westfall-io/titan-tyr/commit/76b21a6da30eded35baefa0adb3cf68da3be9c3a))

- Drop Postgres ENUM for contract status; use TEXT + CHECK so allowed values can evolve without
  ALTER TYPE pain. - Document the SQLAlchemy MetaData naming convention so Alembic autogenerate
  produces stable, reproducible constraint names. - Add a Migrations section covering tooling,
  runtime (separate step before API start), CI gate (alembic check + roundtrip), schema vs data
  migrations, and expand/contract for breaking changes.
