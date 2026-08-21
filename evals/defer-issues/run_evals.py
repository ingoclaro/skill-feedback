#!/usr/bin/env python3
"""Run the defer-issues evals.

Each run is a headless `claude -p` session executed inside a fresh copy of the
eval's fixture repo (path-scoped rules load by cwd, so subagents can't be used).
Configs: with_skill (skill installed at ~/.claude/skills/defer-issues) and
without_skill (--disallowedTools Skill).

Build the fixture repos first — they are generated, not checked in:

    ./setup_fixtures.sh --mechanism rules   # fixtures/        (without_skill)
    ./setup_fixtures.sh --mechanism mixed   # fixtures-hybrid/ (with_skill)

The runner passes --add-dir for the installed skill so runs can read its
references/, which live outside the run's cwd. Without it every run stalls
asking permission and the grader scores a harness failure as a skill failure —
see README.md ("What the evals caught").

Output layout (iteration dir normally evals/files/iteration-N — gitignored):
  <iter>/eval-<id>-<name>/<config>/run-<M>/
      repo/             the run's cwd (fixture copy + anything it wrote)
      result.json       raw `claude -p --output-format json` payload
      final_message.txt / timing.json / stderr.log

Usage: python3 run_evals.py <iteration-dir> [--runs 3] [--concurrency 6]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent          # evals/defer-issues/
REPO = HERE.parent.parent
DEFAULT_MODEL = "claude-sonnet-5"
SKILL_LINK = Path.home() / ".claude" / "skills" / "defer-issues"
SKILL_DEV = REPO / "skills" / "defer-issues"    # the skill itself
BUILD = HERE / "files"                          # gitignored
# config -> (skill dir to install, fixture root)
CONFIGS = {
    "with_skill": (SKILL_DEV, "fixtures-hybrid"),   # the shipped hybrid skill
    "without_skill": (None, "fixtures"),
}
ALLOWED = [
    "Bash(git:*)", "Bash(gh:*)", "Bash(ls:*)", "Bash(cat:*)",
    "Bash(mkdir:*)", "Bash(grep:*)", "Bash(find:*)", "Bash(rg:*)",
]


def run_job(ev, config, m, iter_dir, model, skill_dir):
    run_dir = iter_dir / f"eval-{ev['id']}-{ev['name']}" / config / f"run-{m}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    repo = run_dir / "repo"
    fixture = HERE / CONFIGS[config][1] / ev["fixture"]
    if not fixture.exists():
        sys.exit(f"missing fixture {fixture} — run ./setup_fixtures.sh "
                 f"--mechanism {{rules,mixed}} first")
    shutil.copytree(fixture, repo)
    cmd = [
        "claude", "-p", "--model", model, "--output-format", "json",
        "--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED,
    ]
    if skill_dir is not None:
        # let runs read the installed skill's references/ (outside the cwd,
        # otherwise permission-blocked headlessly); cover the symlink too
        cmd += ["--add-dir", str(skill_dir.resolve()),
                "--add-dir", str(SKILL_LINK)]
    if config == "without_skill":
        cmd += ["--disallowedTools", "Skill"]
    # an infra failure (timeout, missing CLI) must not abort the batch or
    # masquerade as a graded 0-score run — record it and let the grader skip
    try:
        proc = subprocess.run(
            cmd, input=ev["prompt"], text=True, capture_output=True,
            cwd=repo, timeout=1200,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        (run_dir / "error.json").write_text(json.dumps(
            {"error": type(e).__name__, "detail": str(e)[:500]}, indent=2))
        return (f"eval-{ev['id']}-{ev['name']}/{config}/run-{m} "
                f"ERROR={type(e).__name__}")
    (run_dir / "result.json").write_text(proc.stdout)
    (run_dir / "stderr.log").write_text(proc.stderr)
    try:
        r = json.loads(proc.stdout)
    except json.JSONDecodeError:
        r = None
    # Same rule as the timeout above, and the reason it is a separate branch: a
    # CLI that exits non-zero, or prints something that isn't the result JSON,
    # leaves an empty final message. Graded, that scores 0 on every assertion
    # and reads as a skill failure — the exact masquerade this guards against.
    if r is None or proc.returncode != 0:
        (run_dir / "error.json").write_text(json.dumps(
            {"error": "CLIFailure", "returncode": proc.returncode,
             "parsed_result_json": r is not None,
             "detail": (proc.stderr or proc.stdout)[:500]}, indent=2))
        return (f"eval-{ev['id']}-{ev['name']}/{config}/run-{m} "
                f"ERROR=CLIFailure exit={proc.returncode}")
    (run_dir / "final_message.txt").write_text(r.get("result", ""))
    usage = r.get("usage") or {}
    total = sum(v for v in usage.values() if isinstance(v, (int, float)))
    ms = r.get("duration_ms", 0)
    (run_dir / "timing.json").write_text(json.dumps({
        "total_tokens": total,
        "duration_ms": ms,
        "total_duration_seconds": round(ms / 1000, 1),
        "returncode": proc.returncode,
        "result_subtype": r.get("subtype", "missing"),
    }, indent=2))
    return f"eval-{ev['id']}-{ev['name']}/{config}/run-{m} exit={proc.returncode}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("iteration_dir")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--only", help="comma-separated eval ids to run (default: all)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--configs", default="with_skill,without_skill",
                    help="comma-separated configs: with_skill (the shipped "
                         "skill), without_skill (skills off)")
    args = ap.parse_args()

    iter_dir = Path(args.iteration_dir).resolve()
    evals = json.loads((HERE / "evals.json").read_text())["evals"]
    if args.only:
        keep = {int(x) for x in args.only.split(",")}
        evals = [e for e in evals if e["id"] in keep]

    configs = args.configs.split(",")
    unknown = [c for c in configs if c not in CONFIGS]
    if unknown:
        sys.exit(f"unknown config(s): {unknown}; known: {sorted(CONFIGS)}")
    skill_dirs = {c: CONFIGS[c][0] for c in configs}

    # Preflight every fixture before any job is submitted. Inside a worker,
    # sys.exit only surfaces at f.result(), and the executor's shutdown then
    # waits out every job already in flight — up to `timeout` each.
    missing = sorted({str(HERE / CONFIGS[c][1] / ev["fixture"])
                      for c in configs for ev in evals
                      if not (HERE / CONFIGS[c][1] / ev["fixture"]).exists()})
    if missing:
        sys.exit("missing fixture(s):\n  " + "\n  ".join(missing)
                 + "\nrun ./setup_fixtures.sh --mechanism {rules,mixed}")

    for ev in evals:
        d = iter_dir / f"eval-{ev['id']}-{ev['name']}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "eval_metadata.json").write_text(json.dumps({
            "eval_id": ev["id"], "eval_name": ev["name"],
            "prompt": ev["prompt"], "assertions": ev["assertions"],
        }, indent=2))

    # Configs that install a different skill version must not run concurrently
    # with each other (the ~/.claude/skills symlink is global state), so run
    # config phases sequentially, jobs within a phase in parallel. Never
    # destroy a user's own install: refuse to touch a real directory, and
    # restore whatever was there on exit.
    if SKILL_LINK.exists() and not SKILL_LINK.is_symlink():
        sys.exit(f"{SKILL_LINK} is a real directory (an installed copy of "
                 "the skill). Refusing to touch it — move it aside to run "
                 "evals.")
    saved_target = os.readlink(SKILL_LINK) if SKILL_LINK.is_symlink() else None

    def set_link(target):
        if SKILL_LINK.is_symlink():
            SKILL_LINK.unlink()
        if target is not None:
            os.symlink(target, SKILL_LINK)

    try:
        for config in configs:
            skill_dir = skill_dirs[config]
            if skill_dir is not None and not (skill_dir / "SKILL.md").exists():
                sys.exit(f"{config}: no SKILL.md in {skill_dir}")
            set_link(skill_dir)
            if skill_dir is not None:
                print(f"[{config}] skill -> {skill_dir}", flush=True)
            jobs = [(ev, config, m) for ev in evals
                    for m in range(1, args.runs + 1)]
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = [pool.submit(run_job, ev, c, m, iter_dir,
                                       args.model, skill_dir)
                           for ev, c, m in jobs]
                for f in futures:
                    print(f.result(), flush=True)
    finally:
        set_link(saved_target)
        print(f"restored skill link -> {saved_target}" if saved_target
              else "removed temporary skill symlink", flush=True)
    print("ALL RUNS COMPLETE")


if __name__ == "__main__":
    sys.exit(main())
