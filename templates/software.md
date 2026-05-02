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

A Port is a specific function in the code that crosses the repository
boundary. Every external call this software makes or receives is a
Port. Each Port references an interface contract registered with
titan-tyr (`POST /contracts`).

| Port | Direction | Interface (counterparty software) |
| ---- | --------- | --------------------------------- |
| <port-name> | <in \| out> | <counterparty-software-name> |

### Direction conventions

Direction is from *this* software's perspective:

| Pattern                                                       | Direction      |
| ------------------------------------------------------------- | -------------- |
| Receives a request (HTTP endpoint, RPC handler, CLI command)  | `in`           |
| Makes an outbound request and ignores the response            | `out`          |
| Makes an outbound request and uses the response               | `out` and `in` |
| Subscribes to a queue, topic, or event stream                 | `in`           |
| Publishes to a queue, topic, or event stream                  | `out`          |
| Reads from a datastore (DB, cache, file, external API GET)    | `in`           |
| Writes to a datastore (DB, cache, file, external API mutation) | `out`         |

REST-specific cases follow the same rule. A `GET` you serve is `in`
because data flows into the request handler; a `GET` you make is `in`
because the response data flows back into your code. A `POST` you
serve is `in`; a `POST` you make and care about the response is
`out` + `in`; a `POST` you make and ignore the response is `out` only.

## Notes

Anything not captured above — unresolved questions, known gaps,
context worth recording at the software level.
