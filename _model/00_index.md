# Interface Control Documentation — Agent Knowledge Base

## Model Structure

This knowledge base is organised as a set of SysMLv2-inspired models.
There is a common foundation that all environment models import, and
a separate top-level model for each deployment environment.

```
icd-docs/
  common/                    ← type definitions, imported by all models
  instances/
    common/                  ← Parts and Interaction Interfaces shared across environments
    local/                   ← local development environment model
    staging/                 ← staging environment model
    production/              ← production environment model
```

---

## The Two Layers

### Common (type definitions)

The `common/` folder at the root contains the **definitions** —
the SysMLv2 `part def` and `interface def` declarations that
establish the type system. These are read-only reference documents.
No actual architecture elements live here — only the types that
elements are declared as.

An agent must read the relevant definition file before creating
any contract. The definition tells the agent what fields are
required, what the allowed values are, and what the document
format looks like.

| Folder | Contents |
|---|---|
| `common/parts/` | Part type definitions (SoftwarePart, ImagePart, etc.) |
| `common/ports/` | Port type definitions |
| `common/interfaces/` | Interface type definitions |
| `common/connections/` | Connection definition |

### Instances (architecture elements)

The `instances/` folder contains the actual architecture — the
named elements typed against the definitions in `common/`.

`instances/common/` holds elements that exist in every environment
— SoftwareParts (repositories) and Interaction Interfaces
(software-level data contracts). These are environment-agnostic.

Each environment folder (`local/`, `staging/`, `production/`)
is a complete, self-contained model. It imports everything from
`instances/common/` and adds the environment-specific elements —
ContainerParts or PodParts, Binding Interfaces with resolved
addresses, and environment-specific Connections.

---

## The Four SysMLv2 Concepts

Every file in this knowledge base is one of four things:

| Concept | Definition file | Instance location |
|---|---|---|
| **Part** | `common/parts/part.md` | `instances/*/parts/` |
| **Port** | `common/ports/port.md` | described within Part contracts |
| **Interface** | `common/interfaces/interface.md` | `instances/*/interfaces/` |
| **Connection** | `common/connections/connection.md` | `instances/*/connections/` |

---

## Versioning

Every contract file is versioned by Git. Three version signals exist:

**Semantic version** — declared inside the document body as
`**Version:** 1.2.0`. This is the human-negotiated version,
bumped when both parties agree a change is significant.
Part and Port contracts carry a version for tracking purposes.
Interface and Connection contracts carry a version as a binding
commitment — a version bump signals a change that consumers
must be aware of.

**Git SHA** — the immutable blob hash of the file at a given
commit. Machines use this to pin to an exact version of a
contract. An agent resolving a dependency should record the
SHA it read, not just the semantic version.

**Last modified date** — the date of the most recent commit
that touched this file. A contract that has not been updated
while the software around it has changed is a documentation
gap worth flagging.

---

## How Agents Use This

**Reading the architecture** — start with the `model.md` file
in the target environment folder. It declares what the model
contains and what it imports from `instances/common/`. Follow
references to read individual Part, Interface, and Connection
contracts.

**Writing new contracts** — read the definition file for the
concept type first. Write the contract in the correct instance
folder for the target environment. Environment-agnostic elements
go in `instances/common/`. Environment-specific elements go in
the appropriate environment folder.

**Proposing changes** — add a proposal to the Open Proposals
section of the relevant Interface or Connection contract and
open a pull request. Do not modify Provider or Consumer
Obligations until the PR is merged.

**Checking versions** — compare the semantic version in the
contract body against the version referenced by the consuming
element. Flag mismatches as documentation gaps.
