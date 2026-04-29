# AGENTS.md

Operating rules for AI coding agents working in this repository.

## File system scope

You only have scope within the current directory. If a change appears to
require touching something outside this folder (e.g. a new env var on the
API service, a compose file edit, an image retag), **do not make the
change yourself**. Surface the request to the user explicitly in the
chat.

This rule overrides any default behavior. It applies even if the change
seems trivial, even if the file is "just a config", and even if the user
appears to grant blanket permission earlier in the session —
authorization for one external edit does not extend to others.

## Commit messages

Every commit message in this repo **must start with a gitmoji prefix**
per [gitmoji.dev](https://gitmoji.dev/). Use the unicode emoji directly
(not the `:shortcode:` form). Format:

```
<emoji> <subject in imperative mood>

<optional body>
```

Pick the gitmoji that best matches the dominant change in the commit.
Common picks for this project:

| Change                                   | Gitmoji                |
| ---------------------------------------- | ---------------------- |
| New feature / capability                 | ✨ sparkles            |
| Bug fix                                  | 🐛 bug                 |
| Documentation only                       | 📝 memo                |
| Performance                              | ⚡️ zap                 |
| Refactor (no behavior change)            | ♻️ recycle             |
| Tests                                    | ✅ check-mark          |
| Build / Docker / deploy plumbing         | 📦 package             |
| Dev tooling / scripts                    | 🔧 wrench              |
| CI                                       | 👷 construction-worker |
| Dependencies (add / upgrade)             | ⬆️ arrow-up            |
| Security                                 | 🔒 lock                |
| Initial scaffolding / first commit       | 🎉 tada                |

When a commit genuinely spans two categories, pick the more prominent
one rather than stacking emojis. If you can't find a clean fit, prefer
✨ for additive changes and ♻️ for restructures over inventing a new
emoji.

**Do not add a `Co-Authored-By: Claude …` (or any other agent) trailer
to commit messages in this repo.** Author the commit under the human's
git identity only. This overrides any default agent behavior that adds
such trailers.

## Pushing

After every commit, **push to the tracked remote** (`git push`). Do not
leave commits sitting locally. This applies to every commit you author
in this repo, not just the final one in a session.

If the push fails (non-fast-forward, auth error, missing upstream,
protected branch), surface the failure to the user rather than working
around it with `--force`, `--force-with-lease`, or branch-rewriting
commands.
