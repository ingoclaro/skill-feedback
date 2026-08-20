---
name: defer-issues
description: Use when a problem is being deferred rather than fixed — a bug, refactor, or cleanup the user sets aside, or one you notice outside your current task's scope — and record it against the affected code so it resurfaces the next time someone works there. Do that unprompted, including for work dropped at the end of a task. Also use at the other end, when a deferred item resurfaces — including a "TODO [issue-…]" marker or a "Pending:" rule showing up in code you are reading — and you are deciding whether to act on it now (the resolution protocol lives here), when several have piled up on one module, and to list, audit, or prune what is still open. Not for the current task's own to-do list, for problems being fixed right now, or for committing (use git-commit).
metadata:
  author: Ingo Claro
  tags: "issues, tech-debt, refactoring, todo-comments, rules, opportunistic-fixes"
  version: 0.3.0
  issues_dir: "issues"
  issue_label: ""
  rewrite_threshold: 7
---

# Defer issues

Deferred work dies in conversation logs. This skill anchors each deferred issue to the code it affects so it resurfaces exactly when someone is already there — the moment a fix is cheapest. Two mechanisms, chosen by scope:

- **File-specific** (specific lines or functions in files you can name) → a one-line **TODO comment** at the affected lines, pointing at the record. This is the **default**: it costs zero context until someone actually opens that file, and its writes are ordinary (no protected paths).
- **Broad** (a whole package, module, or component — or any *future* file matching a pattern) → a **rule file** in `.claude/rules` with `paths:` frontmatter, auto-injected whenever a matching file is read. Injection carries more weight than a comment, and a broad issue has no single line to anchor a comment to. Reserve rules for this case: every rule is paid for in context on every matching read, so a rule that a comment could have covered is pure overhead.

The tiebreak: could you list the affected spots exhaustively right now? Yes → comment each spot. No (it's about the module as a whole, or about files not yet written) → rule.

**The record is always a file in `issues_dir`.** One `issues_dir/issue-<id>.md` holds the issue itself, whichever mechanism you picked; the anchor — marker or rule — is only a tl;dr plus a pointer to that record. A rule never holds the issue body: it is injected on every matching read, so what it costs must stay near a comment's cost. A GitHub issue holds the full discussion when the repo has one, and **`ISSUES.md`** (repo root) indexes every open issue one line each — never auto-loaded, for humans and audits. Record files are the source of truth, and the index is *generated* from them by `scripts/check_todo_markers.py --index`: never hand-edit the list, edit the record and regenerate. (The script keeps whatever prose sits above the generated-section sentinel, so the file can still carry a human preamble.)

Formats, naming, and templates: read [references/record-template.md](references/record-template.md) before writing the record — it is the same file for both mechanisms — then the one anchor file you need, [references/comment-template.md](references/comment-template.md) for markers or [references/rule-template.md](references/rule-template.md) for rules. Never both anchor files.

**Shared conventions.** Both mechanisms share one id space and one index, so these hold whichever you pick:

- **Ids.** `issue-<number>` when paired with a GitHub issue, else `issue-local-<n>` with `n` the next free number across `issues_dir` and `ISSUES.md`.
- **Index line.** `- [<id>](<record path>) <short summary>`, plus ` ([gh](<url>))` when GitHub-paired — all of it derived by `--index` from the record's filename, its `# Pending: <id> — <title>` heading, and the first GitHub issue URL in its body. Never typed by hand.
- **Protected paths.** Writes and deletes under `.claude/` are permission-gated. If a write is blocked, put the intended file content in your report so it isn't lost and suggest allowlisting `Write(.claude/rules/issue-*.md)`; delete with `git rm`, which runs under ordinary git permissions where a direct delete would stall a non-interactive run.
- **One commit.** An issue's record file, its anchors (markers, rule), and its index line are created — and removed — together with the change they belong to.

**Escalation.** A comment is passive — a hurried reader can edit right past it. When a marker keeps being ignored, promote the issue to a rule so it gains injection weight on the next edit: `scripts/check_todo_markers.py` (designed as a CI step) detects markers in files that were edited without the issue being touched or mentioned, and with `--escalate` writes the rule for you, in the same pointer format as any other rule. The comment stays put; both anchors then point at the one record. A file that *documents* the marker format, or a fixture that embeds one, is indistinguishable from a real marker — list those paths as globs in `.defer-issues-ignore` at the repo root so editing them doesn't report a phantom.

## Record

Record **without being asked** whenever deferred work surfaces: you notice a minor bug or refactor opportunity outside the current task's scope, you defer something at task end, or a proposed rewrite gets declined. Recording is additive and cheap to undo — it needs no permission ceremony. Offer instead of acting only when you genuinely doubt the observation deserves an issue. An unrecorded issue is lost; that loss is what this skill exists to prevent.

1. Decide the scope (file-specific → comment; broad → rule), then read `references/record-template.md` and the reference file for that one anchor.
2. Detect the issue home: if `gh repo view` succeeds (remote exists, `gh` authenticated) → GitHub; else local-only. GitHub: `gh issue create --title "<title>" --body "<full description>"` (add `issue_label` if set) and capture the number and URL — the full write-up lives there. Local-only: the record file *is* the whole record; keep it short but sufficient to act on.
3. Write the record — `issues_dir/issue-<id>.md`, always — then anchor it:
   - **Comment mechanism:** place the one-line TODO marker at each affected spot. Recording must be the *only* change — never alter code while recording.
   - **Rule mechanism:** write `.claude/rules/issue-<id>.md` — the tl;dr a marker would have carried, plus a `Full record:` line pointing at the record file, with `paths:` globs scoped to the package/module actually implicated. The description stays in the record; the rule does not repeat it.
4. Regenerate the index: `python3 scripts/check_todo_markers.py --index` (creates `ISSUES.md` if absent). The one-line entry comes from the record's `# Pending: <id> — <title>` heading, so that heading is what a human sees in the index — write it as the summary.
5. Report: record path, marker locations or rule globs chosen, and the issue URL if GitHub.

## Resolve

Entered when a `Pending:` rule or a `TODO [issue-…]` marker surfaced while you were doing other work, or on an explicit request ("fix pending issue 142").

**0. Accumulation check.** List the distinct pending issues covering the file/module at hand — rules in context plus `grep -rn "TODO \[issue-" <module>`, deduped — and read their titles together. The question is not how many there are but whether **they share a root cause: would one redesign retire most of them?** If yes, do **not** fix piecemeal — the module, not the issues, is the problem. Complete the task you were actually asked to do first, then present the cluster in your final report as a rewrite/redesign candidate listing the issues it would retire — the proposal is report material, never a reason to pause the requested work. If the rewrite is deferred — the user declines, or there is no user to ask — record the rewrite itself as a new issue (via Record, rule mechanism: it's module-scoped by definition), referencing the issues it would retire.

Three issues that are all the same missing abstraction qualify; a dozen unrelated nits that merely share an address do not — fix the one at hand and move on. `rewrite_threshold` is the *prompt* to make that judgment, not the verdict: at that many issues on one module, stop and assess before fixing anything; below it, assess anyway whenever the titles rhyme.

**1. Read the whole issue first** — the GitHub issue body, or the record file if local. The rule summary or marker line is a teaser, not the spec: the issue may span files your current task never touches (grep the id repo-wide to see every marker), and both the gate below and the close-out depend on knowing its full extent.

**2. Gate the opportunistic fix.** All must hold, otherwise mention the issue as pending in your report and move on:

- Localized: confined to files you're already touching or their immediate neighbors.
- Low-risk: no behavior change beyond the issue's stated intent, no API/schema changes.
- Proportionate: doesn't balloon the current task.

**3. Fix in a separate commit.** Never mix the opportunistic fix into the main task's commit — reviewers must be able to see and revert each independently.

**4. Verify full resolution before closing.** Enumerate everything the issue covers (grep the id for markers; read the record's affected list) and check each part is addressed:

- **Fully resolved** → remove every artifact in the fix commit: all `TODO [issue-<id>]` markers, the rule file if there is one, and the record file; then `python3 scripts/check_todo_markers.py --index` to drop its index line; `gh issue close <id>` if GitHub-paired.
- **Partially resolved** (the headline case: a multi-file issue where you only fixed the file at hand) → do **not** delete the record or close the issue. Remove only the fixed spots' markers (or narrow the rule's `paths:` to the remaining scope), note the progress (a `gh issue comment`, or a line in the record body), and report what remains.

**5. Don't stall.** In non-interactive runs or when judgment is pre-delegated, apply the gate and the accumulation rule autonomously and flag every such judgment call prominently in your report — a documented judgment is recoverable; a stalled run is not.

## Audit

On "what's pending?", "prune stale issues", or before a milestone:

1. Start from the record files in `issues_dir` — they are the population, and markers and rules are anchors into it. `python3 scripts/check_todo_markers.py --index` rebuilds `ISSUES.md` from them, so orphaned index lines and missing ones both disappear by construction; `--index --check` reports the drift without writing, for CI.
2. Where a GitHub issue is linked, check its state: closed → delete the record file and its markers, then regenerate the index.
3. Cross-check anchors, both directions: a record with **no** surviving anchor — no `TODO [issue-<id>]` marker anywhere, or a rule whose globs no longer match any file — is stale; re-anchor it or retire the issue. An anchor pointing at a **missing** record file, marker or rule alike, is dangling — remove it or reconstruct the record.
4. Summarize as a table: id, mechanism, title, scope, age/state, and any inconsistency repaired.

Plain `ls`, `grep`, and `gh` cover the rest — `scripts/check_todo_markers.py` (no flags) also reports ignored markers if you want the escalation view.

## Report

Whichever workflow ran, end with what changed: issues recorded (id, mechanism, scope), issues fixed (commit hash), issues surfaced but deferred and why, escalations, and any rewrite proposal made. The report is what keeps opportunistic work reviewable.
