# <software-name>

**Owner:** <team or person>
**Repository:** <repo-uri>

> A Software node is a unit of software ownership — one codebase, one
> deployable boundary, one owning team. It describes *what* the
> software does and *what* it exposes or consumes at its boundary, not
> where it runs.
>
> Note: titan-tyr stores `name`, `repo_uri`, and `version` separately
> on the API request — the values you supply in the JSON body are
> canonical. Owner / Repository above are for human readers; do not
> rely on them as machine-readable metadata.

## Purpose

Two to four sentences. What does this software do and why does it
exist? Written for a reader with no prior context.

## Ports

A Port is a **logical operation** at the repository boundary — not a
single HTTP method. One Port covers all the routes/methods that
together implement the same operation. For example, "manage software
records" is one Port (covering `POST /software`, `GET /software/{name}`,
`PUT /software/{name}`), not three.

Each Port references an interface contract registered with titan-tyr
(`POST /contracts`). A single Port may have multiple counterparties:
list them all (comma-separated, or one row per counterparty — your
call, but be consistent within this software's contract).

| Port | Direction | Counterparty software |
| ---- | --------- | --------------------- |
| <port-name> | <in \| out> | <counterparty-name>[, <counterparty-name>...] |

### What is *not* a Port

- **Datastore access** (your own DB, cache, files on disk). This is
  internal implementation detail. Only model interfaces with
  *registered software* as ports. If a datastore matters to the
  contract, describe it in Notes.
- **Cross-cutting concerns** like auth middleware, logging, metrics
  emission. Mention in Notes if relevant.

### Direction conventions

Direction is from *this* software's perspective:

| Pattern                                                       | Direction      |
| ------------------------------------------------------------- | -------------- |
| Receives a request (HTTP endpoint, RPC handler, CLI command)  | `in`           |
| Makes an outbound request and ignores the response            | `out`          |
| Makes an outbound request and uses the response               | `out` and `in` |
| Subscribes to a queue, topic, or event stream                 | `in`           |
| Publishes to a queue, topic, or event stream                  | `out`          |

REST-specific cases follow the same rule. A `GET` you serve is `in`
because data flows into the request handler; a `GET` you make is `in`
because the response data flows back into your code. A `POST` you
serve is `in`; a `POST` you make and care about the response is
`out` + `in`; a `POST` you make and ignore the response is `out` only.

## Notes

Anything not captured above — unresolved questions, known gaps,
context worth recording at the software level.
