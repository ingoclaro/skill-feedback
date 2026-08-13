# Comment mechanism: the TODO marker

The anchor format for file-specific pending issues. Follow it exactly — audits
and the CI marker check assume it. The issue itself goes in the record file,
whichever mechanism you pick — see
[record-template.md](record-template.md). (Broad, module-scoped issues are
anchored with a rule instead — see [rule-template.md](rule-template.md).)

## TODO marker (in source, at the affected lines)

```
# TODO [issue-142](@/issues/issue-142.md): session refresh races under concurrent tabs — fix or flag as pending, never ignore (defer-issues skill)
```

- Use the file's native comment leader (`#`, `//`, `--`, `<!-- -->`).
- `@/` means repo root; the link target is the record file.
- Exactly one line: `TODO [issue-<id>](@/issues/issue-<id>.md): <short summary> — fix or flag as pending, never ignore (defer-issues skill)`.
  The summary is the relevance teaser — a reader decides from it whether to
  open the record. Keep the summary under ~80 characters.
- **Keep the imperative tail.** A bare TODO reads as decoration; the tail is
  what obliges whoever touches this code to either resolve the issue (via the
  defer-issues skill) or flag it as pending in their summary.
- **Placement is the quality lever.** Directly above the implicated function
  or block, so it is in view exactly when someone works on that code. Issue
  about a whole file → top of that file. A handful of known spots across
  files → a marker at each spot. (If the spots can't be enumerated, that's
  the signal it isn't file-specific — use a rule.)
- Adding or removing markers is a real source change and travels in a commit
  like any other — but a recording change must contain *only* markers, never
  code edits.

## Anchoring invariant

Every `issues/issue-*.md` record anchored this way has at least one
`TODO [issue-<id>]` marker in the source, and every marker points at a record
file that exists — no dangling markers, no unanchored records.
