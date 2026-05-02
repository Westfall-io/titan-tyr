# Project skills

Skills here are auto-discovered by [Claude Code](https://claude.com/claude-code)
when you run it from the titan-tyr repo root. Type `/<skill-name>` to invoke.

| Skill                                                            | What it does                                                          |
| ---------------------------------------------------------------- | --------------------------------------------------------------------- |
| [`register-software`](./register-software/SKILL.md)               | Register a software node with a running titan-tyr instance.           |
| [`update-software`](./update-software/SKILL.md)                   | Append a new version to an already-registered software node. Detects template-version drift and helps migrate. |
| [`learn-software`](./learn-software/SKILL.md)                     | Look up everything titan-tyr knows about a registered software node — description, ticket-filing target, contracts. Read-only; returns structured JSON. |
| [`find-software`](./find-software/SKILL.md)                       | Resolve a colloquial label or partial name (e.g. "front end") to a canonical software slug via `?match=`. Read-only; returns structured JSON. |
| [`propose-template-change`](./propose-template-change/SKILL.md)   | Draft and POST a proposal to update the `software` or `contract` template. Does not auto-accept. |
| [`accept-template-proposal`](./accept-template-proposal/SKILL.md) | Promote an open template proposal to the new active version. Mutates what every caller sees on the next `GET /templates/{kind}`. |

## Configuration

These skills hit a live titan-tyr API. Set the location via environment
variables before invoking:

```sh
export TITAN_TYR_URL=http://localhost:8000   # required, no trailing slash
export TITAN_TYR_TOKEN=sysmlv2               # optional; default sysmlv2
```

## Why env vars (and not a config file)

- **Per-shell scope** matches "I'm pointing at staging right now" without
  editing files.
- **No file to forget about** — `unset TITAN_TYR_URL` clears the state
  cleanly.
- **CI-friendly** — pipelines already inject env vars; no template
  rendering needed.
- **Composable** with the API's bearer header, which itself is just a
  string in env.

A config file would add a precedence question (file vs env vs flag) and
state to clean up. Re-evaluate if/when there are more than three settings.
