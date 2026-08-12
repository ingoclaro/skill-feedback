# skill-feedback evals

Self-contained eval suite for the `skill-feedback` skill. No network access,
GitHub auth, or real session store is needed: fixtures are fake Claude Code
session JSONL files, and both eval prompts are explicit dry runs (no `gh`
calls; the issue body is written to a local file instead of posted).

## Layout

- `evals.json` — the eval definitions: prompt, ground truth, and the
  assertion strings a grader (human or LLM judge) checks each run against.
- `generate_sessions.py` — writes the fixture session stores under
  `files/projects/` (four recent sessions) and `files/projects-stale/` (one
  ~30-day-old session). Stdlib only. The fixture cast is documented at the
  top of the script.
- `files/` — generated output. Not checked in: timestamps and file mtimes
  must be recent relative to the run for the skill's 7-day window to behave,
  so fixtures are regenerated rather than committed.

- `run_evals.py` — headless runner. Regenerates fixtures, then runs each
  eval × config × N repeats via `claude -p` (default model Sonnet 5,
  override with `--model`), each in its own working directory with a fresh
  fixture copy (mtimes preserved). `gh` is hard-blocked for every run.
  Writes `transcript.jsonl`, `final_message.txt`, `timing.json`, and an
  `outputs/` dir per run; infra failures produce `error.json` instead.
  Configs: `with_skill` (the skill at `skills/skill-feedback/`), `old_skill`
  (a pre-edit snapshot at `files/skill-snapshot/SKILL.md` you create with
  `cp -p` before editing), `without_skill` (Skill tool disabled).
  The runner temporarily symlinks the config's skill into
  `~/.claude/skills/skill-feedback` and restores whatever was there; it
  refuses to run if a real (non-symlink) install occupies that path.
  Unix only (uses symlinks and POSIX tools).
- `grade_runs.py` — programmatic grader. Checks each run's final report,
  `issue-preview.md`, and transcript against the assertions and writes a
  `grading.json` per run (`text`/`passed`/`evidence` fields). Runs that
  errored out (no transcript) are skipped, not scored.

## Running

```bash
# from the repo root; iteration output is gitignored under evals/files/
python3 evals/run_evals.py evals/files/iteration-1 --runs 3
python3 evals/grade_runs.py evals/files/iteration-1
```

Repeat runs (3× per config minimum) before trusting a delta — single runs
are noisy, and for a close call on a single assertion compare per-assertion
pass rates across runs, not run-level scores.

To run an eval by hand instead, regenerate fixtures first
(`python3 evals/generate_sessions.py`) — stale fixtures silently empty the
candidate list — and if you relocate `files/`, preserve file mtimes
(`cp -p` / `rsync -t`); the skill narrows candidates with `find -mtime -7`.
