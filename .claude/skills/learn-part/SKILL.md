---
name: learn-part
description: Look up everything titan-tyr knows about a registered part — its description, aliases, version, where to file tickets, and any contracts touching it. Use when an agent needs to understand another part before acting (filing a bug against it, integrating with it, summarising a conversation involving it). Returns structured JSON. Distinct from /find-part (the discovery flow when the target name isn't known yet).
---

# learn-part

You are answering an agent's "tell me about part X" question by
pulling everything titan-tyr knows about it: subtype, description,
repo, ticket-filing target, version, and the contracts that touch it.
Works for any registered part subtype (`software`, `image`,
`container`, `pod`, `compose`) — the subtype discriminator is
preserved in the response so callers can branch on it.

This skill is **read-only and non-mutating**. It composes existing
titan-tyr GET endpoints into a single structured response so a
calling agent doesn't have to fetch and stitch four endpoints itself.

## Server location

Same env vars as the other titan-tyr skills:

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |

If `TITAN_TYR_URL` is unset, **stop and tell the user**:

> `TITAN_TYR_URL` is not set. Set it to the titan-tyr base URL before running this skill, e.g.
> `export TITAN_TYR_URL=http://localhost:8000`.

Don't guess. Don't default to localhost silently.

## Inputs

| Input    | Required | Purpose                                                                                  |
| -------- | -------- | ---------------------------------------------------------------------------------------- |
| `target` | yes      | Canonical part name (slug) to look up. May be a `software` or `container` part.         |
| `caller` | no       | The part the requesting agent represents. When provided, contracts are filtered to caller↔target. When absent, every contract touching `target` is returned. |

`/learn-part` does **not** do interactive discovery. If the agent
doesn't know which canonical name to ask for, call `/find-part`
first — it uses `GET /parts?match=<query>` to resolve a colloquial
label to a canonical slug, then hand the slug to `/learn-part`.

## Workflow

### 1. Confirm reachability

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → wrong token. Stop.
- Connection refused → wrong URL or server down. Stop.

### 2. Look up the target

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/$target"
```

- `200` → continue to step 3.
- `404` → unknown target. Branch to step 6.
- Anything else → surface the response body verbatim and stop.

### 3. Pull contracts touching the target

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/$target/contracts?limit=100"
```

The listing endpoint is paginated. For v1, fetch the first page
(limit=100) and surface a `truncated: true` flag in the response if
`next` is non-null. A real "give me everything" mode would loop the
pages — out of scope for v1.

If `caller` was provided, filter the returned `results` to entries
where `owner == caller` or `counterparty == caller`. Do this in the
skill (the listing endpoint doesn't support a counterparty filter).

For each contract entry kept, fetch its body so the agent has the
full markdown — the listing omits it per #7:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/<contract_id>"
```

### 3b. Fetch open subtype-shift proposals (#40, provider v0.16.0+)

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/$target/subtype-proposals"
```

Filter the response client-side to entries with
`status == "proposal"` — accepted shifts are historical and surface
on the part's `/history` endpoint instead. Surface every open
proposal in a top-level `open_subtype_shifts` field of the response
(see step 5). When there are no open shifts, return
`open_subtype_shifts: []`.

This call is independent of the contracts fan-out; run it in
parallel with step 3 if convenient. Pre-v0.16.0 servers return
`404` on this endpoint — degrade gracefully and emit
`open_subtype_shifts: []` with a brief note rather than failing the
whole skill.

### 4. Resolve the ticket-filing target

Apply this precedence (per #10's design):

1. If `target.issue_tracker_uri` is set → use as-is.
   `ticket_filing.source = "issue_tracker_uri"`.
2. Else, if `target.repo_uri` parses as a GitHub URL (HTTPS form
   `https://github.com/<owner>/<repo>` or SSH form
   `git@github.com:<owner>/<repo>.git`), build
   `https://github.com/<owner>/<repo>/issues`.
   `ticket_filing.source = "repo_uri_inferred"`.
3. Else, no automatic answer.
   `ticket_filing.source = "unknown"`,
   `ticket_filing.resolved_to = null`.

The skill resolves this inline so consumers don't reimplement the
precedence.

### 5. Return the "found" response

```json
{
  "status": "found",
  "part": {
    "name": "<target>",
    "subtype": "software",
    "repo_uri": "...",
    "issue_tracker_uri": null,
    "aliases": ["payments", "billing"],
    "version": "1.2.0",
    "updated_at": "2026-04-29T14:30:00Z",
    "markdown": "..."
  },
  "contracts": [
    {
      "contract_id": "...",
      "owner": "...",
      "counterparty": "...",
      "subtype": "interaction",
      "version": "1.0.0",
      "updated_at": "...",
      "markdown": "..."
    }
  ],
  "open_subtype_shifts": [
    {
      "proposal_id_short": "9b1f2c3d",
      "proposal_id": "9b1f2c3d-...",
      "current_subtype": "software",
      "new_subtype": "container",
      "rationale": "...",
      "proposer_actor": "alice",
      "proposer_attribution": "alice",
      "created_at": "2026-05-02T10:30:00Z",
      "impact": {
        "body_realign_required": true,
        "source_target_validation": "n/a",
        "related_rows_potentially_affected": []
      },
      "next_step": "to accept: /accept-part-subtype-shift target=<name>"
    }
  ],
  "ticket_filing": {
    "resolved_to": "https://github.com/example/payments-service/issues",
    "source": "repo_uri_inferred"
  },
  "truncated": false
}
```

Field notes:

- `part.subtype` is the discriminator (one of `software`, `image`,
  `container`, `pod`, `compose`) — branch on it when the calling
  agent's behavior depends on which dimension the target represents.
  E.g. binding contracts only make sense with the runtime end as
  `container` or `pod`; filing a bug against a codebase is appropriate
  for `software` but for a runtime the right action is usually to find
  the underlying software part via its inbound `binding` contract;
  for an `image` the right action is usually to find the source repo
  via its `builds-from` connection.
- `part.subtype_shifted_from` / `part.subtype_shifted_at` (nullable)
  surface when this part's subtype has been corrected post-registration
  via the shift flow. `subtype_shifted_from` records the previous
  subtype value at the most recent shift; `null` means the part has
  never been shifted. Surface these to callers so they understand the
  current `subtype` may differ from how the part was originally
  registered.
- `part.markdown` is the full body of the latest version (not the
  listing summary).
- `contracts[].subtype` is the contract subtype (one of `interaction`,
  `binding`, `connection`).
- `contracts[].connection_type` (nullable, `connection` only) is the
  per-label sub-discriminator drawn from the closed enum
  `{builds-from, instantiates, runs, member-of, depends-on, submodule}`.
- `contracts[].markdown` is the full body of each contract's latest
  active version.
- `open_subtype_shifts` is the list of pending shift proposals on
  the part (filtered to `status == "proposal"`). Always present;
  empty array when none. Calling agents should branch on whether
  the array is non-empty before acting on `part.subtype` — a
  pending shift means the discriminator is in flight and the agent
  may be looking at stale information. `proposer_attribution` is
  the human-readable label: the `proposer_actor` value when set,
  else `"anonymous (two-party rule unenforceable)"`. `next_step`
  gives the canonical skill name to invoke for acceptance.
- `truncated` is `true` when there were more contracts than the v1
  fetch surfaced (more than 100 touching the target). v2 would page.

### 6. Unknown target — server-side fuzzy lookup

When step 2 returns `404`, ask the API to fuzzy-resolve. `?match=`
substring-matches against name **and** aliases (case-insensitive),
catching both typos (`payment` → `payments-service`) and colloquial
labels (`front end` → `admin-ui`):

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts?match=$target&limit=100"
```

Return each hit's `name` and `aliases` as `suggestions`. If `?match=`
returns nothing and the registered population is small (≤10 total —
re-fetch with no `match=` to count), return every registered name so
the agent sees what *is* there. Otherwise return an empty list.

```json
{
  "status": "not_found",
  "target": "<target>",
  "suggestions": [
    {"name": "admin-ui", "aliases": ["front end"]},
    {"name": "user-ui", "aliases": []}
  ],
  "hint": "No part named '<target>' is registered. The closest matches by name or alias are listed in `suggestions`. Pick one and call /learn-part again, or call /register-part to add it."
}
```

## Caller-side composition notes

`/learn-part` is meant to be called from another agent's context.
The structured JSON return value is the contract — agents parse the
fields they need. The skill itself does not print prose summaries
or render the response for human consumption; that's the calling
agent's job.

A common composition:

1. Calling agent has a request like "file a bug against payments-service
   about the timeout we observed."
2. Calls `/learn-part target=payments-service caller=<self>`.
3. Reads `part.subtype` to confirm it's the codebase, not a deployment.
4. Reads `ticket_filing.resolved_to` to know where to file.
5. Reads `contracts` to understand the interface that observed the
   timeout.
6. Reads `part.markdown` if it needs the broader context.

## Error handling

| Status | Meaning                                                     | What to do                                                                  |
| ------ | ----------------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                            | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `404`  | Target part not registered                                  | Branch to step 6 (substring suggestions).                                   |
| `5xx`  | Server problem on any sub-call                              | Stop. Print response body verbatim.                                         |

## Notes

- This skill is read-only. It never POSTs / PUTs / DELETEs anything.
  Safe to call as often as the calling agent likes; titan-tyr is local
  infrastructure and the calls are cheap. (No caching in v1; revisit
  if hot paths emerge.)
- The unknown-target lookup uses the server's `?match=` endpoint so
  alias resolution lives in one place (the API) and stays consistent
  across `/learn-part`, `/find-part`, and any other consumer.
- Counterparty fan-out (fetching the *other* part's full
  description for each contract) is out of scope for v1. The contract
  entries carry the counterparty's name — call `/learn-part` again
  on that name if the agent needs more.
- For deep contract detail (open content proposals, open subtype
  shifts, attribution), call `/learn-contract` with the
  `contract_id` from this response's `contracts[].contract_id`.
  This skill surfaces the contract's body and basic discriminators;
  `/learn-contract` adds the pending-state surfaces.
- Pagination across contract listings is left to v2. The current cap
  (100 first-page entries) is enough for the registered scale today
  and surfaces a `truncated` flag for callers that need to know.
