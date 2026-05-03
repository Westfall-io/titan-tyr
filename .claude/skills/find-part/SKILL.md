---
name: find-part
description: Resolve a colloquial label or partial name to a canonical part slug registered with titan-tyr. Use when an agent or user knows the part by a nickname ("front end", "billing", "前端") but not the canonical slug. Wraps GET /parts?match= and returns structured JSON. Read-only. Distinct from /learn-part (which needs the slug already and returns the full description + contracts).
---

# find-part

You are resolving a colloquial label, partial name, or alias to a
canonical part slug registered with titan-tyr. The endpoint is
`GET /parts?match=<query>`, which substring-matches case-insensitively
against each part's `name` AND its `aliases`.

This skill is **read-only and non-mutating**. It is the discovery
front-end for the rest of the titan-tyr skill family — once it returns
a slug, hand off to `/learn-part` for the full description.

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

| Input     | Required | Purpose                                                                                                                                                                                                |
| --------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `query`   | yes      | The colloquial label or partial name to resolve. 1–128 chars. Case-insensitive substring match.                                                                                                        |
| `subtype` | no       | Restrict results to a single part subtype: one of `software`, `image`, `container`, `pod`, or `compose`. Use when the caller already knows which dimension they want — e.g. "the payments software" vs "the payments-prod container" vs "the payments image". Unknown values → `422`. |

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
`curl --data-urlencode` against a `-G` GET, that's free. Append
`--data-urlencode "subtype=$subtype"` only when the caller passed
`subtype`; otherwise omit the flag entirely (don't send empty string).

```sh
curl -fsS -G \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     --data-urlencode "match=$query" \
     --data-urlencode "limit=100" \
     ${subtype:+--data-urlencode "subtype=$subtype"} \
     "$TITAN_TYR_URL/parts"
```

- `200` → continue to step 3.
- `422` → query out of range (>128 chars) or unknown `subtype`. Surface verbatim.
- Anything else → surface the response body verbatim and stop.

### 3. Shape and return

The response is the standard paginated part listing
(`{"results": [...], "next": ...}`). Trim each entry down to the
fields a discovery caller actually needs, and surface the result count
explicitly so the caller can branch. Preserve `subtype` on every entry
— it's the discriminator that tells the calling agent which kind of
part they're looking at (one of `software`, `image`, `container`,
`pod`, or `compose`):

```json
{
  "status": "found",
  "query": "<original-query>",
  "match_count": 2,
  "results": [
    {
      "name": "admin-ui",
      "subtype": "software",
      "aliases": ["front end", "operator console"],
      "repo_uri": "https://github.com/example/admin-ui",
      "version": "1.4.0"
    },
    {
      "name": "user-ui",
      "subtype": "software",
      "aliases": ["customer front end"],
      "repo_uri": "https://github.com/example/user-ui",
      "version": "0.8.2"
    }
  ],
  "truncated": false,
  "hint": "Multiple matches. Pick one and call /learn-part target=<name> for the full description and contracts."
}
```

When `match_count == 0`, return:

```json
{
  "status": "not_found",
  "query": "<original-query>",
  "match_count": 0,
  "results": [],
  "hint": "No part matches '<query>' by name or alias. Try a shorter substring, drop the `subtype` filter if set, or call /register-part to add it."
}
```

When `match_count == 1`, the hint becomes "Single match. Call /learn-part target=<name> for the full description and contracts."

`truncated` is `true` if `next` came back non-null (more than 100 hits
on the first page). v2 would page; v1 caps and signals.

## Caller-side composition notes

`/find-part` is meant to be called from another agent's context.
Common composition:

1. Agent has "file a bug against the front end."
2. Calls `/find-part query="front end"`.
3. Reads `results[0].name` (or disambiguates if `match_count > 1`).
4. Calls `/learn-part target=<that-name>` for full context.
5. Acts on `ticket_filing.resolved_to` from learn-part.

The skill itself does not print prose summaries or ask the user to
disambiguate — that's the calling agent's job. The structured JSON
return value is the contract.

**Disambiguation via `subtype`.** Colloquial labels often collide
across the five part subtypes — e.g. `payments` may match the
software part `payments-service`, the image `payments-image`,
container parts like `payments-prod` / `payments-staging`, the K8s
pod `payments-pod`, and a compose stack member. If the calling agent
already knows which dimension it cares about, pass `subtype` to cut
the ambiguity at the API rather than after the fact. Examples:
filing a bug against the codebase → `subtype=software`; checking
which environments of a service are deployed → `subtype=container`
or `subtype=pod`; finding the built artifact → `subtype=image`;
listing services in a stack → `subtype=compose`.

## Error handling

| Status | Meaning                                  | What to do                                                  |
| ------ | ---------------------------------------- | ----------------------------------------------------------- |
| `401`  | Bad bearer token                         | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                 |
| `422`  | Query exceeds 128 characters, or `subtype` is not one of `software`/`image`/`container`/`pod`/`compose` | Stop. Surface `detail` so the caller can fix the offending input. |
| `5xx`  | Server problem                           | Stop. Print response body verbatim.                         |

## Notes

- This skill is read-only. It never POSTs / PUTs / DELETEs anything.
- Substring matching is intentionally fuzzy and *not* deduplicated
  across parts — a query like `service` may legitimately return every
  part whose name or alias contains "service". The caller is expected
  to disambiguate (or pass `subtype` if it narrows the question).
- `?match=` escapes ILIKE wildcards (`%`, `_`) on the server side, so
  user queries containing them are matched literally — no special
  escaping needed here.
- For the inverse direction ("I have the canonical slug, give me
  everything"), call `/learn-part` instead.
