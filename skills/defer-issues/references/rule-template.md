# Rule mechanism: the rule file

The anchor format for broad (package/module/component-scoped) pending issues.
Follow it exactly — audits and tooling assume it. The issue itself goes in the
record file, whichever mechanism you pick — see
[record-template.md](record-template.md). (File-specific issues are anchored
with a TODO marker instead — see [comment-template.md](comment-template.md).)

## Rule file: `.claude/rules/issue-<id>.md`

Named to match its record: `issue-142.md` alongside `issues/issue-142.md`,
`issue-local-3.md` alongside `issues/issue-local-3.md`.

Template:

```markdown
---
paths:
  - "src/auth/**"
  - "src/api/session.ts"
---
# Pending: #142 — session refresh races under concurrent tabs
Full record: issues/issue-142.md

Relevant here? Invoke the defer-issues skill to resolve it properly (gate,
fix, verify, close). Not relevant? Note it as pending in your final report.
```

Rules for the rule:

- **A pointer, not the record.** Heading + the `Full record:` line + the
  closing pointer, and at most one short sentence of tl;dr if the heading
  alone doesn't convey relevance. The body is injected on every read of a
  matching file, so every word is paid for repeatedly — it needs only enough
  to decide *relevance*. The description, the affected scope, and the fix
  direction live in `issues/issue-<id>.md`; the gate, separate-commit rule,
  verification and closing live in `defer-issues/SKILL.md`.
- **Never duplicate the description here.** Two copies of an issue drift, and
  the one that gets injected is the one nobody edits. If the rule seems to
  need more text, that text belongs in the record.
- **The `# Pending: <id> — <title>` heading matches the record's heading.**
  `--index` builds `ISSUES.md` from the record, so a divergent title in the
  rule just misleads whoever reads the injected copy.
- **Keep the closing pointer line** and its explicit mention of "the
  defer-issues skill" — that's the phrase that gets the skill invoked when
  it's relevant, instead of the issue being silently skipped or half-handled
  from the rule text alone.
- **Tight `paths:` globs.** Name the files/directories actually implicated.
  Broad globs (`**/*`, `src/**` on a large tree) make the rule fire where it
  is irrelevant; noisy rules teach readers to ignore all rules.

## Escalation rule

A comment-mechanism issue that keeps being ignored (see
`scripts/check_todo_markers.py`) gets a rule too — the same format, with one
extra line naming why it exists and `paths:` set to the files carrying the
marker:

```markdown
---
paths:
  - "src/report.py"
---
# Pending: local-3 — build_report crashes on rows missing "total"
Escalated: the TODO marker for this issue was ignored in a recent change.
Full record: issues/issue-local-3.md

Relevant here? Invoke the defer-issues skill to resolve it properly (gate,
fix, verify, close). Not relevant? Note it as pending in your final report.
```

The marker and record stay where they are; the rule only adds injection
weight. `scripts/check_todo_markers.py --escalate` emits exactly this format,
so a change here needs the same change there.

## Anchoring invariant

Every rule has a record at `issues/issue-<id>.md` — a rule without one is
dangling, and reconstructing the record is the repair. Every rule's `paths:`
must still match at least one file: globs matching nothing mean the rule is
stale, and a partial resolution narrows `paths:` to the remaining scope rather
than deleting the rule.
