# The record file: `issues/issue-<id>.md`

Every pending issue has exactly one record, and it always lives here — under
`issues/`, never in `.claude/rules`. The anchors differ by mechanism (a TODO
marker, a rule, or both), but they only point at this file; the issue itself is
written once, here. See [comment-template.md](comment-template.md) for the
marker format and [rule-template.md](rule-template.md) for the rule format.

Named `issue-142.md` when paired with GitHub issue #142, `issue-local-3.md`
when local-only (see SKILL.md for how `local-<n>` ids are allocated).

Template (GitHub-paired):

```markdown
# Pending: #142 — session refresh races under concurrent tabs
https://github.com/acme/app/issues/142

Affected: src/auth/refresh.ts, src/api/session.ts

Two tabs refreshing concurrently can both rotate the token; the loser gets
a 401. Fix direction: single-flight the refresh call.

Relevant to what you're doing? Invoke the defer-issues skill to resolve it
properly (gate, fix, verify, close). Not relevant? Note it as pending in
your final report.
```

Local-only variant: omit the URL line and title the heading
`# Pending: local-3 — <title>`.

Rules for the record:

- **The anchor is the trigger; this file is the record.** It gives enough to
  act: what the issue is, its extent (`Affected:` — files for a comment-anchored
  issue, the package/module for a rule-anchored one; the close-out greps against
  this), and a fix direction. The full protocol (gate, separate-commit rule,
  verification, closing) lives in the skill — don't inline it here.
- **The `# Pending: <id> — <title>` heading is the index entry.**
  `scripts/check_todo_markers.py --index` copies that title verbatim into
  `ISSUES.md`, so write it to stand alone in a list.
- **Keep the closing pointer line** and its explicit mention of "the
  defer-issues skill" — that's the phrase that gets the skill invoked when
  the issue is relevant, instead of it being half-handled from the summary.
- A short "Fix direction:" hint is encouraged — it is often the difference
  between a viable opportunistic fix and a skipped one.
- Long write-ups belong in the GitHub issue when one exists; this file then
  stays a summary plus the link.
- **Length is not rationed here.** This file is read only when someone opens
  the issue, so it can hold what the anchor cannot — the anchors are what pay
  context on every read, and they stay short.

## Anchoring invariant

Id allocation, the `ISSUES.md` line format, protected paths, and the
one-commit rule live in `SKILL.md`. The invariant across both mechanisms:
every record has at least one live anchor (a `TODO [issue-<id>]` marker in the
source, or a rule whose `paths:` still match a file), and every anchor points
at a record that exists — no dangling anchors, no unanchored records.
