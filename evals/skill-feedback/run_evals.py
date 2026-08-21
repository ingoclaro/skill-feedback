#!/usr/bin/env python3
"""Run the skill-feedback evals headlessly.

Each run is a `claude -p` session executed inside a fresh per-run working
directory containing a freshly generated copy of the eval's fixture session
store (copied with mtimes preserved — the skill narrows candidates with
`find -mtime -7`, so stale mtimes silently empty the candidate list).

Fixtures are regenerated once at startup via generate_sessions.py, so run
this script immediately before you need results, not hours ahead.

Configs:
  with_skill     dev skill symlinked at ~/.claude/skills/skill-feedback
  without_skill  same session, but `--disallowedTools Skill` (baseline)

`gh` is hard-blocked for every config via `--disallowedTools "Bash(gh:*)"` —
the evals are dry runs and must not contact GitHub even if the model tries.
The grader still fails a run that *attempts* a gh call (transcript scan).

Output layout (iteration dir normally evals/skill-feedback/files/iteration-N — gitignored):
  <iter>/eval-<id>-<name>/<config>/run-<M>/
      workdir/          the run's cwd (fixture store + any files it wrote)
      transcript.jsonl  full stream-json event log
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

HERE = Path(__file__).resolve().parent          # evals/skill-feedback/
REPO = HERE.parent.parent
SKILL_DIR = REPO / "skills" / "skill-feedback"  # the skill itself
FIXTURE_ROOT = HERE.parent                      # evals.json "files" (evals/files/...) are relative to this
DEFAULT_MODEL = "claude-sonnet-5"
SKILL_LINK = Path.home() / ".claude" / "skills" / "skill-feedback"
# config -> skill dir to install (None = Skill tool disabled).
# old_skill is a pre-edit snapshot: `cp -p skills/skill-feedback/SKILL.md evals/skill-feedback/files/skill-snapshot/`
CONFIGS = {
    "with_skill": SKILL_DIR,
    "old_skill": HERE / "files" / "skill-snapshot",
    "without_skill": None,
}


def run_job(ev, config, m, iter_dir, model):
    run_dir = iter_dir / f"eval-{ev['id']}-{ev['name']}" / config / f"run-{m}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    workdir = run_dir / "workdir"
    workdir.mkdir(parents=True)
    # copytree uses copy2, preserving the file mtimes the 7-day window needs
    for rel in ev["files"]:
        src = FIXTURE_ROOT / rel
        shutil.copytree(src, workdir / rel)
    cmd = [
        "claude", "-p", "--model", model,
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "acceptEdits",
        "--allowedTools", "Bash",
    ]
    disallowed = ["Bash(gh:*)"]
    if config == "without_skill":
        disallowed.append("Skill")
    cmd += ["--disallowedTools", *disallowed]
    # an infra failure (timeout, missing CLI) must not abort the batch or
    # masquerade as a graded 0-score run — record it and let the grader skip
    try:
        proc = subprocess.run(
            cmd, input=ev["prompt"], text=True, capture_output=True,
            cwd=workdir, timeout=1200,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        (run_dir / "error.json").write_text(json.dumps(
            {"error": type(e).__name__, "detail": str(e)[:500]}, indent=2))
        return (f"eval-{ev['id']}-{ev['name']}/{config}/run-{m} "
                f"ERROR={type(e).__name__}")
    (run_dir / "transcript.jsonl").write_text(proc.stdout)
    (run_dir / "stderr.log").write_text(proc.stderr)
    result = {}
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result = event
    (run_dir / "final_message.txt").write_text(result.get("result", ""))
    usage = result.get("usage") or {}
    total = sum(v for v in usage.values() if isinstance(v, (int, float)))
    ms = result.get("duration_ms", 0)
    (run_dir / "timing.json").write_text(json.dumps({
        "total_tokens": total,
        "duration_ms": ms,
        "total_duration_seconds": round(ms / 1000, 1),
        "returncode": proc.returncode,
        "result_subtype": result.get("subtype", "missing"),
    }, indent=2))
    # outputs/ holds the user-facing artifacts; the eval viewer discovers
    # runs by the presence of this directory
    outputs = run_dir / "outputs"
    outputs.mkdir()
    shutil.copy2(run_dir / "final_message.txt", outputs / "report.md")
    for p in workdir.rglob("issue-preview.md"):
        shutil.copy2(p, outputs / "issue-preview.md")
        break
    return f"eval-{ev['id']}-{ev['name']}/{config}/run-{m} exit={proc.returncode}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("iteration_dir")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--only", help="comma-separated eval ids to run (default: all)")
    ap.add_argument("--configs", default="with_skill,without_skill")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    iter_dir = Path(args.iteration_dir).resolve()
    evals = json.loads((HERE / "evals.json").read_text())["evals"]
    if args.only:
        keep = {int(x) for x in args.only.split(",")}
        evals = [e for e in evals if e["id"] in keep]

    # fresh fixtures: timestamps/mtimes must be recent relative to this run
    subprocess.run([sys.executable, str(HERE / "generate_sessions.py")],
                   check=True)

    for ev in evals:
        d = iter_dir / f"eval-{ev['id']}-{ev['name']}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "eval_metadata.json").write_text(json.dumps({
            "eval_id": ev["id"], "eval_name": ev["name"],
            "prompt": ev["prompt"], "assertions": ev["assertions"],
        }, indent=2))

    # The ~/.claude/skills symlink is global state, so configs that install
    # different skill versions run as sequential phases (jobs within a phase
    # in parallel). Never destroy a user's own install: refuse to touch a
    # real directory, and restore a pre-existing symlink on exit.
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
        for config in args.configs.split(","):
            skill_dir = CONFIGS[config]
            if skill_dir is not None and not (skill_dir / "SKILL.md").exists():
                sys.exit(f"{config}: no SKILL.md in {skill_dir}")
            set_link(skill_dir)
            if skill_dir is not None:
                print(f"[{config}] skill -> {skill_dir}", flush=True)
            jobs = [(ev, config, m) for ev in evals
                    for m in range(1, args.runs + 1)]
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = [pool.submit(run_job, ev, c, m, iter_dir, args.model)
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
