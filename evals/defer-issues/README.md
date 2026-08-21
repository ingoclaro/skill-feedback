# defer-issues evals

Two independent eval suites, measuring the two ways a skill fails:

- **Behaviour** (this directory) — given that the skill loads, does the agent
  do the right thing? Headless `claude -p` runs inside throwaway git repos,
  graded programmatically.
- **Triggering** ([`trigger-eval/`](trigger-eval/)) — does the skill load at
  all? A skill that behaves perfectly and never fires is worth nothing.

Stdlib Python and bash only; no network, no API key beyond the `claude` CLI's
own auth.

## Behaviour suite

Six evals, each a fixture git repo plus a prompt. Two of them (`record-local`,
`record-architecture`) start clean and test *recording* a deferred issue; the
other four seed pending issues: three test what happens when one **surfaces**
while the agent is doing unrelated work — the case the skill exists for — and
`audit-drift` asks for an explicit audit instead.

| # | Eval | What it measures |
|---|------|------------------|
| 1 | `record-local` | Records a file-specific issue, scoped tightly, without refactoring |
| 2 | `surface-resolve` | Does the requested task; fixes or explicitly reports the surfaced issue, never silently ignores it; keeps the fix in a separate commit |
| 3 | `accumulation-cluster` | **3** issues sharing one root cause → proposes a redesign that retires them together, without stalling the actual task |
| 4 | `audit-drift` | Repairs index/record/marker drift both directions (orphaned records, dangling markers) |
| 5 | `record-architecture` | Picks the rule mechanism for a package-wide issue and covers all affected paths with one record, not one per file |
| 6 | `accumulation-nits` | **9** unrelated issues sharing only an address → fixes the one at hand and does *not* propose a rewrite |

Evals 3 and 6 are a **pair**, and the pairing is the point. Same prompt, same
`invoice.py`, opposite correct answers, chosen so that the count and the
judgment disagree: 3 is below any threshold and 9 is above it, so a run that
answers by counting fails both, and only a run that reads the titles and asks
"would one redesign retire most of these?" passes both. They are graded with
the same rewrite-proposal detector, used positively in 3 and negatively in 6.

Assertions are checked by code, not a model: `grade_runs.py` reads the run's git
history, the files it wrote, and its final message. So "fixed in a separate
commit" means the commit graph actually says so.

### Configs

Each config swaps what is installed at `~/.claude/skills/defer-issues` and which
fixture set it runs against, so the comparisons isolate one variable at a time:

| Config | Skill | Fixtures | Answers |
|--------|-------|----------|---------|
| `with_skill` | the shipped skill | `fixtures-hybrid` | — |
| `without_skill` | none (`--disallowedTools Skill`) | `fixtures` | Does the skill beat the bare model? |

Every config is *present-tense*: each one is the shipped skill, or its absence.
Frozen copies of earlier versions are deliberately not kept — a snapshot stops
being the skill the moment the skill changes, and git history already records
what a past version said.

There used to be a third arm, `comments_skill` — the shipped skill built with
the rule mechanism disabled, to answer "does having rules available change
behaviour?". It was built by flipping the skill's own "this repo has no rule
mechanism" branch; the skill no longer has that branch, so the arm is gone
rather than kept as a fork. Reinstating it means reinstating the branch, not
maintaining a second SKILL.md — a fork drifts, and the comparison stops being
a comparison of one variable.

The grader is mechanism-aware, and the mechanism comes from the data, not from
a table in the grader: `without_skill` grades as rules, and `with_skill` against
each eval's `expected_mechanism` in `evals.json` — the mechanism the hybrid skill is
supposed to *choose* there. Each assertion is written once against a small
mechanism adapter.

### Running

```bash
./setup_fixtures.sh --mechanism rules    # fixtures/
./setup_fixtures.sh --mechanism mixed    # fixtures-hybrid/
python3 run_evals.py files/iteration-6 --runs 3
python3 grade_runs.py files/iteration-6
```

`with_skill,without_skill` is the default and the only pairing.

Fixtures are generated, not checked in — they are git repos, and nesting them
inside this one would turn each into a submodule. Regenerate them before a run;
`setup_fixtures.sh` is the source of truth for what each fixture contains.

One script builds both sets, because the arms have to see the *same* repo:
the sources and the issue set are written once and `--mechanism` decides only
how each issue is anchored (a `.claude/rules` pointer with `paths:` globs, a
TODO marker at the affected line, or — for `mixed` — whichever the hybrid skill
should have picked). Every set records the issue itself the same way, in
`issues/issue-<id>.md`, so `diff -r fixtures fixtures-hybrid` should show
differences only in the anchors and the records' `Affected:` scope; anything
else means the A/B has become a comparison of two different codebases.

Seeded fixture issues use the reserved `fx-` id prefix, and the script assembles
the marker line instead of writing it literally, so nothing in a fixture is
mistaken for a real pending-issue marker of *this* repo by `git grep` or by
`scripts/check_todo_markers.py`.

Run output lands wherever you point the runner (`files/` is gitignored). The
runner swaps a global symlink, so it refuses to run if `~/.claude/skills/
defer-issues` is a real directory, and restores whatever was there on exit.

### Results

**No benchmark output is checked in.** The suite is cheap to re-run and its
numbers age badly — a run is only comparable to another run of the same fixture
set, the same eval list, and the same skill. Point the runner at `files/`
(gitignored), read the run, and let it go.

Two things from the runs that *are* worth carrying forward, because they are
about the harness rather than any one score:

- **The generator compares against a stored baseline instead of re-running both
  arms.** Consecutive iterations can therefore carry a byte-identical column for
  the unchanged arm, and a "tie" can be one arm's data compared with itself.
  Only trust a comparison where both arms were measured in that run.
- **These evals say nothing about cost.** Nothing measured so far separates the
  two mechanisms on correctness; the argument for defaulting to comments is that
  a rule is paid for in context on every matching read while a comment costs
  nothing until someone opens the file. That is a claim about cost, and this
  suite doesn't measure it.

### What the evals caught

An early run was thrown out: every run in one arm had "failed" to produce a
record — and the transcripts showed why. The skill's
`references/*.md` live outside the run's working directory, so a headless run
was permission-blocked from reading them and stopped to ask. The runs weren't
failing the task, they were waiting for a human who was never coming, and the
grader dutifully scored that as the skill's fault.

The fix is two lines — `--add-dir` for the installed skill and for the symlink
that points at it. The lesson is the reason this note is here: a red eval is a
claim about the skill *or* about the harness, and it is worth about ten minutes
to find out which before you start editing the skill.

## Trigger suite

See [`trigger-eval/README.md`](trigger-eval/README.md) — twenty queries, ten
that should load the skill and ten near-misses that shouldn't.

It scores 19/20 — but it is here for the story rather than the score, because
the first version of it was wrong. It reported the description as badly
under-triggering, with a tidy explanation for why; the real cause was the
harness crediting successful triggers to the wrong parallel worker. The
write-up keeps both the retracted finding and what made it convincing.
