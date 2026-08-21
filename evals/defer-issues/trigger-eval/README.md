# Trigger eval

The behaviour suite measures what the agent does *once the skill has loaded*.
This one measures whether it loads at all — which, for a skill whose whole
premise is catching work nobody explicitly asked you to record, is the harder
half.

Twenty queries in [`eval_set.json`](eval_set.json): ten that should trigger
`defer-issues`, ten that should not. The negatives are the interesting ones,
because they are deliberately adjacent:

| Negative | Why it's a near-miss |
|---|---|
| "create a github issue for the login bug" | files an issue, but nothing is being *deferred* |
| "fix issue #142 from our github repo" | acting on a tracker item, not recording one |
| "add a TODO comment above the parse function" | writes the same artifact for a different reason |
| "what does the .claude/rules directory do?" | asks about the mechanism, doesn't want it used |
| "the retry loop in src/foo.py is copy-pasted — refactor it into a shared helper" | duplicated code worth extracting, but the user wants it done **now** |

That last one carries the most weight. Set it against the positive "the email
templating is copy-pasted across mailer.py, digest.py and notify.py. not doing
it today — add it to the debt list so it comes up when someone edits those
files": same observation about duplicated code, same request to extract a
helper, opposite correct behaviour, and the only signal separating them is
deferral. The eval splits them 0/3 against 3/3.

(They are different files rather than literally the same code. The exact same
snippet phrased both ways lives in the behaviour suite, as eval 1's prompt —
this suite measures loading, that one measures what happens next.)

The ten positives were rewritten on 2026-08-12 to use vocabulary the
description does **not** contain — "park this", "backlog it", "don't lose
this", "add it to the debt list", "stuff we've punted on". Before that they
were near-verbatim restatements of phrases in the description ("note this for
later", "file this as tech debt", "what's pending?"), which made a pass
substantially a test of string overlap. Keeping them disjoint is a maintenance
rule, not a one-off: **if you edit the description, check no positive query
starts quoting it.**

## Running it

The harness is `run_eval.py` from Anthropic's `skill-creator` plugin, which is
Apache-2.0 and not vendored here — only the query set is. Install the plugin in
Claude Code (`/plugin install skill-creator@claude-plugins-official`); it lands
under `~/.claude/plugins/cache/`.

```bash
# the path segment after skill-creator/ is a version dir and differs per install
SC=$(echo ~/.claude/plugins/cache/claude-plugins-official/skill-creator/*/skills/skill-creator)
REPO=/path/to/claude-skills

cd /any/project/with/a/.claude/dir          # see "project root" below
PYTHONPATH="$SC" python3 -m scripts.run_eval \
    --eval-set "$REPO/evals/defer-issues/trigger-eval/eval_set.json" \
    --skill-path "$REPO/skills/defer-issues" \
    --runs-per-query 3 --num-workers 1 --timeout 180 --verbose
```

Four things will silently ruin the numbers if you skip them. Every one of them
fails the same way — plausible-looking zeros, no error — which is why they are
written out at length rather than left as a "note:".

**`--num-workers 1` is mandatory.** This is not a politeness about CPU. The
harness advertises the skill by writing a uniquely-named command file into
`.claude/commands/`, then counts a trigger only when the model names *that*
file. Every worker writes into the same directory, so with N workers the model
sees N identical commands — and it picks the same one every time (first by name,
in every run I checked — three concurrent sessions offered five command files
and all three chose the same one). The other N−1 workers watch the model trigger
perfectly and score it a miss. Measured 2026-08-12, five queries × 3 runs with
everything else held constant: 12/12 positive runs trigger at 1 worker, 2/12 at
5 workers.

**Uninstall the skill first.** If `~/.claude/skills/defer-issues` exists, the
model invokes the real skill rather than the harness's synthetic command, and
the harness — watching for its own command name — records a miss. Every query
reads 0.00, and the whole suite finishes suspiciously fast, because each run
returns at the first tool call.

Move the directory or symlink aside for the duration and restore it after; a
`trap ... EXIT` around the run is worth the ten seconds. Renaming a scratch copy
of the skill and pointing `--skill-path` at that does **not** work — the model
still reaches for whatever is genuinely installed, whatever the copy is called.

**Project root.** `run_eval.py` walks up from the cwd looking for a `.claude/`
directory and writes its command file there, so run it from inside a project
that has one. An empty `.claude/` in a scratch directory is enough.

**Start from an empty project directory every time.** The harness deletes its
command file in a `finally`, but a killed or timed-out run leaks one — and a
leaked file poisons every subsequent run in that directory, because the model
picks one command from those on offer and only the worker owning that exact name
gets the credit. Runs also leave behind whatever the model wrote (the skill's
whole job is to write issue records), and a query asking to record something
that is *already recorded* doesn't behave like the query you thought you were
testing.

This one cost me an entire 60-run pass. The same query measured 3/3 in a clean
directory and 0/3 in one that had accumulated a stray command file and an issue
record — and the eval reports both with equal confidence.

## Result

Raw run output is not kept (`.gitignore` drops it): the harness scores one
description per pass, so comparing candidates means running each of them now —
a stored JSON is never the other arm. The numbers below are the finding.

3 runs per query, Sonnet, serial, clean directory, all passes on 2026-08-12.
**The rows are not a like-for-like comparison** — the query set changed after
the first one, which is the point: the 20/20 was scored against positives that
quoted the description back at it.

| description | queries | positive runs | negative runs | chars |
|---|---|---|---|---|
| original, original queries | 20 / 20 | 29 / 30 | 0 / 30 | 1130 |
| situation-led rewrite, new queries | 19 / 20 | 27 / 30 | 0 / 30 | 673 |
| + artifact cues | 19 / 20 | 28 / 30 | 0 / 30 | 765 |
| **shipped** (b, one comma) | 20 / 20 | 29 / 30 | 0 / 30 | 765 |

**Call it 19 / 20, not the 20 / 20 in the last row** — see below. Either way it
is down from the original 20/20, on a description a third shorter and a query
set that no longer shares its vocabulary. Not one of the thirty negative runs
triggered in any pass, including the near-misses.

The whole difference is one query, and it is diagnostic rather than noisy:
*"I keep seeing this `TODO [issue-local-3]` comment at the top of
billing/invoice.py — deal with it properly, whatever the protocol is."* It is
the one positive with **no deferral vocabulary at all** — nothing is being put
off, the user is looking at an artifact and asking what to do with it. Its only
route to the skill is the skill being known as the owner of those markers, and
the rewrite dropped the description's mechanism paragraph, which is where that
was said.

Pass A (0 / 3) confirmed the mechanism. Pass B put the artifact names back as
*inbound cues* — a `TODO [issue-…]` marker or a `Pending:` rule showing up in
code you are reading — while still leaving out the comment-vs-rule choice, which
is made inside the skill and cannot help selection. That read 1 / 3; pass C, on
a description differing from B by a single comma, read 2 / 3 and so flipped the
whole suite to 20/20.

Three runs cannot tell those apart, so the query was re-run on its own at 9 runs
against the shipped text: **1 / 9**. Pooled over the shipped
description that is **3 / 12, ~25%** — comfortably under the 0.5 threshold. The
20/20 row is a lucky sample of a failing query, which is worth stating plainly
in a file that already documents one confidently-wrong number: *a 3-run pass
resolves a query at 0% or 100%, and nothing in between.* When one query decides
the headline, sample that query harder before believing the headline.

**Open, and deliberately left open**: naming the artifact is worth ~90 chars and
does not buy the query back. Whether the rest is worth more description budget
is a judgment nobody has made yet — don't close it by pasting the query's
wording into the description, which is the failure this eval was rebuilt to
stop rewarding.

The negative column is the one worth trusting least, in the sense that it is
easy to score well on: a skill that never fires gets 10/10 there. It only means
anything next to a positive column that is also full — which is why the
refactor-now / refactor-later contrast above is the measurement to look at, and
why a single 3-run pass is worth exactly one 3-run pass.

## What this eval got wrong the first time

The July 2026 run reported the skill as badly under-triggering. It was not a plain pass of this
suite: it was the plugin's description-*optimisation* loop, which splits the set
12 train / 8 test and rewrites the description five times. The shipped
description passed **1 of 10** positives; the best of the five rewrites managed
2, with the resolve-and-audit queries at or near 0.00 throughout. Specificity was
perfect in every iteration — 0 triggers across all 100 negative runs.

That went into an earlier draft of this file as a known weakness in the
description, complete with a plausible explanation: the description leads with
recording and buries resolution behind subordinate clauses, so the resolve path
must be undiscoverable.

The explanation was fiction. The run had used the harness's default parallelism.
Re-run serially in a clean directory, the same queries against the same
description score 20/20. (That pair — the 1,130-char description and the
quote-it-back query set — is the "original" row in the table above; both were
replaced later the same day, which is why the shipped number is now 19/20.)

The head-to-head — five queries, 3 runs each, everything else held constant:

| | positive runs that triggered |
|---|---|
| 5 workers | 2 / 12 |
| 1 worker | 12 / 12 |

Same harness, same description, same model. That pass also measured the patched
harness under both conditions, which is how the patch discussed below was
retired.

Getting that number took four attempts, and the three failures are the reason
the setup notes above are so long. Each one produced a full set of confident
zeros: once because the skill was installed and the model reached for the real
one, once because a previous run had left a command file and an issue record in
the directory, and once because a background job's cleanup restored the skill
symlink halfway through. None of them errored.

Two things are worth taking from that. The failure had a *coherent story* — the
0.00 queries really were all resolve-and-audit ones, which is exactly the shape
you would expect if the description were the problem, and that coherence is what
made it convincing. And the story survived five iterations of automated
description rewriting without the scores moving — 1, 0, 0, 2, 0 positives passed
— which should have been the tell: if rewording the thing under test barely
moves the number, you are probably not measuring the thing under test.

There was also a patch here, against the harness's exact-name matching, which
made the detector accept any worker's command file. It is gone. It addressed a
real defect, but it only papered over the parallelism bug — and at
`--num-workers 1`, the case where the numbers are trustworthy anyway, it changes
nothing: run head-to-head, the two harness variants agree on every query serially
(12/12 each) and both collapse in parallel (2/12 unpatched, 4/12 patched).
