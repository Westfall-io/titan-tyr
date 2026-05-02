---
name: find-software
description: Resolve a colloquial label or partial name to a canonical software slug registered with titan-tyr. Use when an agent or user knows the software by a nickname ("front end", "billing", "前端") but not the canonical slug. Wraps GET /software?match= and returns structured JSON. Read-only. Distinct from /learn-software (which needs the slug already and returns the full description + contracts).
---

# find-software

You are resolving a colloquial label, partial name, or alias to a
canonical software slug registered with titan-tyr. The endpoint is
`GET /software?match=<query>`, which substring-matches case-insensitively
against each software's `name` AND its `aliases`.

This skill is **read-only and non-mutating**. It is the discovery
front-end for the rest of the titan-tyr skill family — once it returns
a slug, hand off to `/learn-software` for the full description.

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

| Input   | Required | Purpose                                                                                                |
| ------- | -------- | ------------------------------------------------------------------------------------------------------ |
| `query` | yes      | The colloquial label or partial name to resolve. 1–128 chars. Case-insensitive substring match.        |

## Workflow

### 1. Confirm reachability

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → wrong token. Stop.
- Connection refused → wrong URL or server down. Stop.

### 2. Run the match

URL-encode the query (it may contain spaces, slashes, Unicode). With
`curl --data-urlencode` against a `-G` GET, that's free:

```sh
curl -fsS -G \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     --data-urlencode "match=$query" \
     --data-urlencode "limit=100" \
     "$TITAN_TYR_URL/software"
```

- `200` → continue to step 3.
- `422` → query out of range (likely >128 chars). Surface verbatim.
- Anything else → surface the response body verbatim and stop.

### 3. Shape and return

The response is the standard paginated software listing
(`{"results": [...], "next": ...}`). Trim each entry down to the
fields a discovery caller actually needs, and surface the result count
explicitly so the caller can branch:

```json
{
  "status": "found",
  "query": "<original-query>",
  "match_count": 2,
  "results": [
    {
      "name": "admin-ui",
      "aliases": ["front end", "operator console"],
      "repo_uri": "https://github.com/example/admin-ui",
      "version": "1.4.0"
    },
    {
      "name": "user-ui",
      "aliases": ["customer front end"],
      "repo_uri": "https://github.com/example/user-ui",
      "version": "0.8.2"
    }
  ],
  "truncated": false,
  "hint": "Multiple matches. Pick one and call /learn-software target=<name> for the full description and contracts."
}
```

When `match_count == 0`, return:

```json
{
  "status": "not_found",
  "query": "<original-query>",
  "match_count": 0,
  "results": [],
  "hint": "No software matches '<query>' by name or alias. Try a shorter substring, or call /register-software to add it."
}
```

When `match_count == 1`, the hint becomes "Single match. Call /learn-software target=<name> for the full description and contracts."

`truncated` is `true` if `next` came back non-null (more than 100 hits
on the first page). v2 would page; v1 caps and signals.

## Caller-side composition notes

`/find-software` is meant to be called from another agent's context.
Common composition:

1. Agent has "file a bug against the front end."
2. Calls `/find-software query="front end"`.
3. Reads `results[0].name` (or disambiguates if `match_count > 1`).
4. Calls `/learn-software target=<that-name>` for full context.
5. Acts on `ticket_filing.resolved_to` from learn-software.

The skill itself does not print prose summaries or ask the user to
disambiguate — that's the calling agent's job. The structured JSON
return value is the contract.

## Error handling

| Status | Meaning                                  | What to do                                                  |
| ------ | ---------------------------------------- | ----------------------------------------------------------- |
| `401`  | Bad bearer token                         | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                 |
| `422`  | Query exceeds 128 characters             | Stop. Tell the caller to shorten the query.                 |
| `5xx`  | Server problem                           | Stop. Print response body verbatim.                         |

## Notes

- This skill is read-only. It never POSTs / PUTs / DELETEs anything.
- Substring matching is intentionally fuzzy and *not* deduplicated
  across software — a query like `service` may legitimately return
  every software whose name or alias contains "service". The caller
  is expected to disambiguate.
- `?match=` escapes ILIKE wildcards (`%`, `_`) on the server side, so
  user queries containing them are matched literally — no special
  escaping needed here.
- For the inverse direction ("I have the canonical slug, give me
  everything"), call `/learn-software` instead.
