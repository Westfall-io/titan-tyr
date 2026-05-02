# <interface-name>

**Protocol:** <REST | Kafka | gRPC | GraphQL | JDBC | Webhook | Custom>
**Owner software:** <owner-name> port <port-name>
**Counterparty software:** <counterparty-name> port <port-name>

> An interface contract carries data between two Software nodes. It is
> the binding agreement on what is exchanged — protocol, schema, error
> handling. Environment-agnostic: no hostnames, no listening ports, no
> addresses.
>
> Note: titan-tyr stores `owner_software`, `counterparty_software`, and
> `version` separately on the API request — those JSON fields are
> canonical. The header above is for human readers; do not rely on it
> as machine-readable metadata.

## What this interface carries

One to two sentences. What data flows here, and what business or
technical purpose does the exchange serve?

## Provider obligations

Binding commitments of the **owner** software. Each item is a
commitment, not a description.

- ...

## Consumer obligations

Binding commitments of the **counterparty** software.

- ...

## Schema

What this section contains depends on the protocol:

| Protocol  | Schema should contain                                                              |
| --------- | ---------------------------------------------------------------------------------- |
| REST      | Path, HTTP method, request fields, response fields, status codes                   |
| Kafka     | Topic, message fields, partition key, delivery guarantee, consumer group           |
| gRPC      | Service, method, request message fields, response message fields                   |
| GraphQL   | Operation name, query / mutation fields, response fields                           |
| JDBC      | Schema, table or view, access type, connection constraints                         |
| Webhook   | Endpoint path, payload fields, signature verification, retry expectations          |

### Request / message

| Field   | Type   | Required | Description     |
| ------- | ------ | -------- | --------------- |
| <field> | <type> | <yes/no> | <description>   |

### Response (if applicable)

| Field   | Type   | Required | Description     |
| ------- | ------ | -------- | --------------- |
| <field> | <type> | <yes/no> | <description>   |

### Errors (if applicable)

| Code / condition | Meaning   | Consumer action          |
| ---------------- | --------- | ------------------------ |
| <code>           | <meaning> | <retry / fail / ignore>  |

## Change protocol

Propose a change by registering a new proposal:

```
POST /contracts/{contract_id}/proposals
{ "version": "1.X.0-rcN", "markdown": "..." }
```

Iterate on `-rcN` versions until both sides agree, then propose the
stable `1.X.0`. The **owner software** accepts the proposal:

```
POST /contracts/{contract_id}/proposals/{version}/accept
```

Acceptance flips the status to `active` and (for RCs) creates a new
stable active version. All RCs and superseded proposals are preserved
in titan-tyr for posterity.

Breaking changes (`MAJOR` bump) need an explicit migration window —
record it in the proposal's markdown so accepting the proposal locks
in the cutover plan.

## Notes

Anything not captured above — known gaps, unresolved questions,
context worth preserving.
