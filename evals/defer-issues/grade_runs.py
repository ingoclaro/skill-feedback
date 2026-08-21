#!/usr/bin/env python3
"""Programmatic grader for defer-issues eval runs.

Walks <iteration-dir>/eval-*/<config>/run-*/ and writes grading.json per run
(expectations use the exact fields text/passed/evidence the viewer needs).

Every assertion is checked mechanically — the run's git history, the files it
wrote, and its final message. Never by a model.

Mechanism handling. Which mechanism a run is graded against comes from the
config plus the eval's `expected_mechanism` in evals.json; this file
enumerates no evals of its own:

  without_skill           always `rules`
  with_skill              the hybrid skill, so each eval is graded against the
                          mechanism it is supposed to *choose* for that issue

Each assertion is then written once against the `Mech` adapter below, which
knows how a mechanism anchors an issue and resurfaces it on a file — instead of
once per mechanism. The record is *not* part of that variation: every issue's
record is `issues/issue-<id>.md` whichever mechanism anchors it, and a rule is
a pointer to one, never the issue itself. Where a run is expected to be blocked from
writing (.claude/ headlessly), the degraded path — content in the final
report — also passes.

Usage: python3 grade_runs.py <iteration-dir>
"""
import json
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

HERE = Path(__file__).resolve().parent
TODO_RE = re.compile(r"TODO \[issue-")
# Seeded fixture ids carry this prefix so they cannot be confused with the
# host repo's own local-<n> ids; see setup_fixtures.sh.
FX_ID_RE = re.compile(r"fx-\d+")


def load_evals():
    return {e["name"]: e
            for e in json.loads((HERE / "evals.json").read_text())["evals"]}


def git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    return p.stdout.strip()


def read(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def snippet(text, pattern, ctx=60):
    m = re.search(pattern, text, re.I | re.S)
    if not m:
        return None
    s = max(0, m.start() - ctx)
    return text[s:m.end() + ctx].replace("\n", " ")


def exp(text, passed, evidence):
    return {"text": text, "passed": bool(passed), "evidence": str(evidence)[:400]}


def strip_todo(src):
    return "\n".join(l for l in src.splitlines() if not TODO_RE.search(l))


def src_diff(repo, path="src"):
    """Added/removed lines between the fixture's initial commit and the
    worktree, under `path`.

    Untracked files count as added: `git diff` never reports them, so a run
    that dropped an uncommitted `src/retry_helper.py` — precisely the refactor
    evals 1 and 5 forbid — used to pass the no-code-change assertion.
    """
    diff = git(repo, "diff", initial_commit(repo), "--", path)
    added = [l[1:] for l in diff.splitlines()
             if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for l in diff.splitlines()
               if l.startswith("-") and not l.startswith("---")]
    for f in git(repo, "ls-files", "--others", "--exclude-standard",
                 "--", path).splitlines():
        added += read(Path(repo) / f).splitlines() or [f]
    return added, removed


def initial_commit(repo):
    """Empty only when `repo` isn't a usable git repo — the caller reports that
    run as infra breakage rather than crashing the whole grading pass."""
    return next(iter(git(repo, "rev-list", "--max-parents=0",
                         "HEAD").splitlines()), "")


def seeded_ids(repo):
    """Issue ids setup_fixtures.sh seeded, read from the fixture's initial
    commit — so the grader can't drift from the fixture it grades."""
    tree = git(repo, "ls-tree", "-r", "--name-only", initial_commit(repo))
    ids = {m.group(1) for m in re.finditer(r"issue-(fx-\d+)\.md", tree)}
    return sorted(ids, key=lambda i: int(i.split("-")[1]))


def globs_in(corpus):
    pblocks = re.findall(r'paths:\s*((?:\s*-\s*["\']?[^\n]+\n?)+)', corpus)
    return re.findall(r'-\s*["\']?([^"\'\n]+)', "\n".join(pblocks))


def glob_matches(g, path):
    g = g.strip()
    return fnmatch(path, g) or fnmatch(path, g.replace("**", "*"))


# ------------------------------------------------------------ mechanism adapter
class Mech:
    """Where a mechanism keeps its records, and how it resurfaces on a file.

    Assertions are written against this, once, instead of once per mechanism.
    """

    def __init__(self, name):
        if name not in ("comments", "rules", "mixed"):
            sys.exit(f"unknown mechanism: {name}")
        self.name = name
        self.comments = name in ("comments", "mixed")
        self.rules = name in ("rules", "mixed")

    @property
    def degraded_ok(self):
        """The rule anchor lives under .claude/, whose writes are
        permission-gated in a headless run, so its content in the final report
        also counts. (The record itself is an ordinary write either way.)"""
        return self.rules

    def record_dirs(self):
        """Where the *issue* lives — always `issues/`, whatever anchors it."""
        return ["issues"]

    def anchor_dirs(self):
        """Every dir this mechanism writes artifacts into, records included."""
        return self.record_dirs() + ([".claude/rules"] if self.rules else [])

    def records(self, repo):
        out = []
        for d in self.record_dirs():
            if (repo / d).exists():
                out += sorted((repo / d).glob("issue-*.md"))
        return out

    def record_for(self, repo, iid):
        for d in self.record_dirs():
            p = repo / d / f"issue-{iid}.md"
            if p.exists():
                return p
        return None

    def glob_corpus(self, repo):
        """Text carrying the `paths:` globs — the rule files, not the records:
        under this skill a rule is an anchor pointing at a record, so the globs
        are never in the record itself."""
        d = repo / ".claude" / "rules"
        if not (self.rules and d.exists()):
            return ""
        return "\n".join(p.read_text(errors="replace")
                         for p in sorted(d.glob("issue-*.md")))

    def anchored(self, repo, rel, corpus):
        """(passed, evidence): does this mechanism resurface on `rel`?"""
        if self.comments and TODO_RE.search(read(repo / rel)):
            return True, f"TODO marker in {rel}"
        if self.rules:
            hits = [g for g in globs_in(corpus) if glob_matches(g, rel)]
            if hits:
                return True, f"glob {hits[0]!r} matches {rel}"
            return False, f"no glob matches {rel} (globs={globs_in(corpus)})"
        return False, f"no TODO marker in {rel}"


def mech_for(config, name, evals):
    if config == "with_skill":
        ev = evals[name]
        if "expected_mechanism" not in ev:
            sys.exit(f"evals.json: eval '{name}' has no expected_mechanism")
        return Mech(ev["expected_mechanism"])
    return Mech("rules")


# ------------------------------------------------------------ shared assertions
def no_code_change_exp(repo, label="source_intact", path="src"):
    """Recording is additive: only comment or blank lines may appear, and
    nothing may be removed. Mechanism-independent — a TODO marker is a comment.
    """
    added, removed = src_diff(repo, path)
    clean = not removed and all(
        not l.strip() or l.lstrip().startswith("#") for l in added)
    return exp(f"{label}: no code changes under {path}/ (comment lines, "
               "including the mechanism's TODO marker, are allowed)",
               clean, f"added={added[:4]} removed={removed[:4]}")


def record_produced_exp(repo, msg, mech, topic, what):
    """A record about `topic` exists (or, when writes may be blocked, its
    content is in the report)."""
    recs = mech.records(repo)
    texts = [p.read_text(errors="replace") for p in recs]
    # re.S so a topic spanning two lines of a short record still matches
    on_disk = any(re.search(topic, t, re.I | re.S) for t in texts)
    in_msg = mech.degraded_ok and bool(re.search(topic, msg, re.I | re.S)) and \
        bool(re.search(r"paths:|issue-[\w.-]+\.md|# Pending", msg))
    return exp(f"record_produced: a pending-issue record about {what}"
               + (" (on disk or in the final report)" if mech.degraded_ok else ""),
               on_disk or in_msg,
               f"records={[p.name for p in recs]}, on_disk={on_disk}"
               + ("" if on_disk else
                  f" | msg: {snippet(msg, 'issue-|paths:') or 'no record reference'}"))


def surfaces_exp(repo, msg, mech, label, on, off=(), what=""):
    """The mechanism resurfaces on every path in `on` and on none in `off`."""
    corpus = mech.glob_corpus(repo)
    if mech.degraded_ok:
        corpus += "\n" + msg
    hits = [mech.anchored(repo, f, corpus) for f in on]
    misses = [mech.anchored(repo, f, corpus) for f in off]
    passed = all(ok for ok, _ in hits) and not any(ok for ok, _ in misses)
    return exp(f"{label}: {what}", passed,
               "; ".join(ev for _, ev in hits)
               + ("" if not off else
                  " | must NOT surface: " + "; ".join(
                      ("SURFACES: " if ok else "clear: ") + ev
                      for ok, ev in misses)))


def index_exp(repo, msg, mech):
    text = read(repo / "ISSUES.md")
    on_disk = any(f"{d}/issue-" in text for d in mech.record_dirs())
    in_msg = mech.degraded_ok and "ISSUES.md" in msg and \
        bool(re.search(r"issue-[\w.-]+\.md", msg))
    return exp("index_line_produced: ISSUES.md line linking the record"
               + (" (on disk or in report)" if mech.degraded_ok else ""),
               on_disk or in_msg,
               text.strip() if on_disk
               else (snippet(msg, r"ISSUES\.md") or "no index reference"))


# a rule reported instead of written (protected path) still shows its frontmatter
PATHS_BLOCK_RE = re.compile(r"paths:\s*\n?\s*-")


def mechanism_choice_exp(repo, msg, want):
    """with_skill only: the hybrid skill must pick the right mechanism."""
    rules = sorted((repo / ".claude" / "rules").glob("issue-*.md")) \
        if (repo / ".claude" / "rules").exists() else []
    reported = bool(PATHS_BLOCK_RE.search(msg))
    got = "rules" if (rules or reported) else "comments"
    return exp(f"mechanism_choice: recorded with the {want} mechanism",
               got == want,
               f"rule files={[p.name for p in rules]}, "
               f"paths: block in report={reported}")


# Detects a *proposal* to rewrite/redesign the module (not a passing mention,
# and not a rejected one). Used positively by accumulation-cluster and
# negatively by accumulation-nits — the same detector, opposite expectations,
# which is what makes the pair a dissociation rather than two counts.
REWRITE_RE = re.compile(
    r"(rewrite|redesign|overhaul|rework|consolidat\w*|refactor\w*)\s+"
    r"(?:of\s+|the\s+|this\s+|that\s+|whole\s+|entire\s+)*"
    r"(billing|invoice|module|package)"
    r"|(billing|invoice|module|package)[\s-]+"
    r"(rewrite|redesign|overhaul|rework)", re.I)
PROPOSAL_RE = re.compile(
    r"propos|suggest|recommend|candidate|worth|should|would retire|retire",
    re.I)
NEGATED_RE = re.compile(
    r"\b(not|no|never|avoid|against|rather than|instead of|didn'?t|"
    r"don'?t|isn'?t|wasn'?t|without)\b[^.;]{0,60}$", re.I)


def rewrite_proposal(msg):
    for m in REWRITE_RE.finditer(msg):
        if NEGATED_RE.search(msg[max(0, m.start() - 70):m.start()]):
            continue
        window = msg[max(0, m.start() - 200):m.end() + 200]
        if PROPOSAL_RE.search(window):
            return window.replace("\n", " ")
    return None


def no_spree_exp(repo, mech):
    """A run that goes off closing seeded issues one by one, instead of doing
    the task and judging the cluster, shows up as commits plus deleted
    records."""
    n_commits = len(git(repo, "log", "--oneline").splitlines()) - 1
    gone = [i for i in seeded_ids(repo) if mech.record_for(repo, i) is None]
    return exp("no_piecemeal_spree: did not go off fixing the seeded issues "
               "one by one",
               n_commits <= 2 and len(gone) <= 1,
               f"commits_after_initial={n_commits}, records_closed={gone}")


# ---------------------------------------------------------------- eval 1
def grade_record_local(repo, msg, mech, config):
    out = [
        no_code_change_exp(repo),
        record_produced_exp(repo, msg, mech, r"retry|foo\.py",
                            "the duplicated retry loop"),
        surfaces_exp(repo, msg, mech, "scoped_tightly",
                     on=["src/foo.py"], off=["src/bar.py"],
                     what="resurfaces on src/foo.py and not on the unrelated "
                          "src/bar.py"),
        index_exp(repo, msg, mech),
    ]
    names = [p.name for p in mech.records(repo)] or \
        re.findall(r"issue-[\w.-]+\.md", msg)
    out.append(exp("local_naming: record named issue-local-<n>.md",
                   any(re.fullmatch(r"issue-local-\d+\.md", n) for n in names),
                   f"names={sorted(set(names))[:5]}"))
    if config == "with_skill":  # file-specific -> comment, not rule
        out.append(mechanism_choice_exp(repo, msg, "comments"))
    return out


# ---------------------------------------------------------------- eval 2
def grade_surface_resolve(repo, msg, mech, config):
    out = []
    src = read(repo / "src" / "report.py")
    code = strip_todo(src)
    commits = git(repo, "log", "--oneline", "--", "src/report.py").splitlines()
    out.append(exp("task_done: count_rows added and committed",
                   "def count_rows" in code and len(commits) >= 2,
                   f"commits touching report.py={commits}"))

    fixed = ".get(" in code
    mentioned = bool(re.search(
        r"pending|keyerror|missing ['\"]?total|known issue|existing issue|"
        r"issue-fx|fx-1", msg, re.I))
    out.append(exp("not_silently_ignored: pending issue fixed or mentioned",
                   fixed or mentioned,
                   ("fixed in source" if fixed else "")
                   + (" | " + (snippet(msg, r"pending|keyerror|issue") or "")
                      if mentioned else "") or "no fix, no mention"))

    fix_commits = set(git(repo, "log", "-S", ".get(", "--format=%h").split())
    task_commits = set(git(repo, "log", "-S", "count_rows", "--format=%h").split())
    if fixed:
        sep = fix_commits and task_commits and not (fix_commits & task_commits)
        out.append(exp("separate_commit_if_fixed: fix not in the count_rows commit",
                       sep, f"fix={fix_commits} task={task_commits}"))
    else:
        out.append(exp("separate_commit_if_fixed: fix not in the count_rows commit",
                       True, "vacuous: no fix applied"))

    record_dirs = tuple(f"{d}/" for d in mech.anchor_dirs())
    contaminated = False
    detail = "no task commit found"
    for h in task_commits:
        files = git(repo, "show", "--name-only", "--format=", h).split()
        extra = [f for f in files
                 if f.startswith(record_dirs) or f == "ISSUES.md"]
        show = git(repo, "show", h)
        adds_fix = bool(re.search(r"^\+.*\.get\(", show, re.M))
        drops_marker = bool(re.search(r"^-.*TODO \[issue-", show, re.M))
        if extra or (fixed and adds_fix) or drops_marker:
            contaminated = True
        detail = f"commit {h}: files={files}"
    out.append(exp("task_commit_uncontaminated: count_rows commit touches only the task",
                   bool(task_commits) and not contaminated, detail))

    if fixed:
        record = mech.record_for(repo, "fx-1")
        marker_left = [p.relative_to(repo).as_posix()
                       for p in sorted((repo / "src").rglob("*"))
                       if p.is_file() and re.search(r"TODO \[issue-fx-1\]",
                                                    read(p))]
        line_gone = "fx-1" not in read(repo / "ISSUES.md")
        rule_left = mech.rules and (repo / ".claude" / "rules"
                                    / "issue-fx-1.md").exists()
        out.append(exp("closeout_if_fixed: record file, every anchor, and the "
                       "index line all removed",
                       record is None and not marker_left and not rule_left
                       and line_gone,
                       f"record={record.name if record else 'gone'}, "
                       f"markers_left={marker_left}, rule_left={rule_left}, "
                       f"line_gone={line_gone}"))
    else:
        out.append(exp("closeout_if_fixed: record removed along with the fix",
                       True, "vacuous: no fix applied"))
    return out


# ---------------------------------------------------------------- eval 3
def grade_accumulation_cluster(repo, msg, mech, config):
    out = [task_done_discount(repo)]
    rw = rewrite_proposal(msg)
    out.append(exp("rewrite_proposed: final message proposes a rewrite/redesign "
                   "of the billing module (3 issues, one root cause — below "
                   "any counting threshold)",
                   rw is not None, rw or "no rewrite proposal found"))
    out.append(no_spree_exp(repo, mech))

    ids = len(set(FX_ID_RE.findall(msg)))
    manyword = bool(re.search(r"\b(3|three|several|multiple|all)\b.{0,40}"
                              r"(pending|issues|debt|markers)", msg, re.I))
    out.append(exp("cluster_not_ignored: message acknowledges the clustered issues",
                   ids >= 2 or manyword,
                   f"distinct ids mentioned={ids}, count-language={manyword}"))
    return out


# ---------------------------------------------------------------- eval 6
def grade_accumulation_nits(repo, msg, mech, config):
    out = [task_done_discount(repo)]
    rw = rewrite_proposal(msg)
    out.append(exp("no_rewrite_proposed: final message does NOT propose a "
                   "rewrite/redesign (9 unrelated nits — over any counting "
                   "threshold, but no shared root cause)",
                   rw is None, rw or "no rewrite proposal found"))

    at_hand = mech.record_for(repo, "fx-3") is None or \
        bool(re.search(r"fx-3|qty|unit_price|keys exist|KeyError", msg, re.I))
    out.append(exp("issue_at_hand_not_ignored: fx-3, on the function being "
                   "edited, is fixed or mentioned",
                   at_hand,
                   f"record_closed={mech.record_for(repo, 'fx-3') is None} | "
                   + (snippet(msg, r"fx-3|qty|unit_price") or "no mention")))
    out.append(no_spree_exp(repo, mech))
    return out


def task_done_discount(repo):
    code = strip_todo(read(repo / "src" / "billing" / "invoice.py"))
    commits = git(repo, "log", "--oneline", "--",
                  "src/billing/invoice.py").splitlines()
    return exp("task_done: discount support added and committed",
               "discount" in code and len(commits) >= 2,
               f"commits touching invoice.py={commits}")


# ---------------------------------------------------------------- eval 4
def grade_audit_drift(repo, msg, mech, config):
    out = []
    ids = [f"fx-{i}" for i in range(1, 5)]
    listed = sum(1 for i in ids if i in msg)
    out.append(exp("lists_issues: final message enumerates the pending issues",
                   listed >= 3, f"{listed}/4 ids mentioned"))

    issues = read(repo / "ISSUES.md")
    out.append(exp("orphan_record_detected: fx-2 re-indexed or reported",
                   "fx-2" in issues or "fx-2" in msg,
                   f"in ISSUES.md={'fx-2' in issues}, in message={'fx-2' in msg}"))

    out.append(exp("dangling_line_detected: fx-4 removed from index or reported",
                   "fx-4" not in issues or "fx-4" in msg,
                   f"removed from ISSUES.md={'fx-4' not in issues}, "
                   f"in message={'fx-4' in msg}"))

    stale_words = (r"stale|no longer|match|deleted|missing|doesn't exist|"
                   r"does not exist|removed|no (todo|comment|marker|reference)")
    stale = snippet(msg, r"fx-3.{0,200}(" + stale_words + ")") or \
        snippet(msg, r"legacy_sync.{0,160}(" + stale_words + ")")
    out.append(exp("stale_record_detected: fx-3 flagged (dead paths / no "
                   "surviving marker)", stale is not None, stale or "not flagged"))
    return out


# ---------------------------------------------------------------- eval 5
STORAGE_FILES = ["src/storage/blob.py", "src/storage/cache.py",
                 "src/storage/catalog.py"]


def grade_record_architecture(repo, msg, mech, config):
    out = [
        no_code_change_exp(repo, label="no_behavior_change"),
        record_produced_exp(repo, msg, mech,
                            r"storage.{0,400}(async|blocking|sync\b|thread|"
                            r"event.?loop)",
                            "the storage sync/async migration"),
    ]
    disk_ids = {p.stem for p in mech.records(repo)}
    n = len(disk_ids) if disk_ids else len(set(re.findall(r"issue-[\w-]+\.md", msg)))
    out.append(exp("single_issue: one package-scoped record, not one per file",
                   1 <= n <= 2,
                   f"distinct records={sorted(disk_ids) or 'from report'}, n={n}"))
    out.append(surfaces_exp(repo, msg, mech, "full_coverage",
                            on=STORAGE_FILES,
                            what="resurfaces on all three storage files"))
    out.append(index_exp(repo, msg, mech))
    if config == "with_skill":  # package-wide -> rule, not comment
        out.append(mechanism_choice_exp(repo, msg, "rules"))
    return out


GRADERS = {
    "record-local": grade_record_local,
    "surface-resolve": grade_surface_resolve,
    "accumulation-cluster": grade_accumulation_cluster,
    "audit-drift": grade_audit_drift,
    "record-architecture": grade_record_architecture,
    "accumulation-nits": grade_accumulation_nits,
}


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: grade_runs.py <iteration-dir>")
    evals = load_evals()
    if set(evals) != set(GRADERS):
        sys.exit(f"evals.json and GRADERS disagree: "
                 f"only in evals.json={sorted(set(evals) - set(GRADERS))}, "
                 f"only in grade_runs.py={sorted(set(GRADERS) - set(evals))}")
    iter_dir = Path(sys.argv[1]).resolve()
    if not iter_dir.is_dir():
        sys.exit(f"not a directory: {iter_dir}")
    if not list(iter_dir.glob("eval-*/*/run-*")):
        sys.exit(f"no eval-*/<config>/run-* directories under {iter_dir}")
    for run_dir in sorted(iter_dir.glob("eval-*/*/run-*")):
        name = run_dir.parts[-3].split("-", 2)[2]
        config = run_dir.parts[-2]
        rel = run_dir.relative_to(iter_dir)
        if name not in GRADERS:
            print(f"{rel}: SKIPPED (no grader for eval '{name}')")
            continue
        repo = run_dir / "repo"
        if not (run_dir / "result.json").exists() or not repo.exists():
            print(f"{rel}: SKIPPED (no result.json/repo — infra error, "
                  "see error.json)")
            continue
        # A repo git can't read has no baseline to diff against, so every
        # source assertion would pass vacuously. Skip the run, don't score it —
        # and don't let one broken repo take the whole grading pass down.
        if not initial_commit(repo):
            print(f"{rel}: SKIPPED (repo has no commits — infra error)")
            continue
        mech = mech_for(config, name, evals)
        expectations = GRADERS[name](repo, read(run_dir / "final_message.txt"),
                                     mech, config)
        passed = sum(1 for e in expectations if e["passed"])
        total = len(expectations)
        (run_dir / "grading.json").write_text(json.dumps({
            "mechanism": mech.name,
            "expectations": expectations,
            "summary": {"passed": passed, "failed": total - passed,
                        "total": total,
                        "pass_rate": round(passed / total, 2) if total else 0},
        }, indent=2))
        print(f"{rel}: {passed}/{total}")


if __name__ == "__main__":
    main()
