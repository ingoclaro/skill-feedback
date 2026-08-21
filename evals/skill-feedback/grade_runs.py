#!/usr/bin/env python3
"""Programmatic grader for skill-feedback eval runs.

Walks <iteration-dir>/eval-*/<config>/run-*/ and writes grading.json per run
(expectations use the exact text/passed/evidence fields the viewer needs).

Everything is checked mechanically from three artifacts of each run:
  - final_message.txt   the session's final report to the user
  - workdir/**/issue-preview.md   the issue body the eval asks for (eval 0)
  - transcript.jsonl    full event log, scanned for attempted `gh` commands

The two classification assertions (session B "mentioned-only", session C
"maintenance") are graded with tolerant regexes over the words near the
session id in the report — synonyms count, so a run isn't failed for
phrasing. Session ids are matched by their distinctive suffix (…0001 etc.),
which also matches the full fixture UUIDs.

Usage: python3 grade_runs.py <iteration-dir>
"""
import json
import re
import sys
from pathlib import Path

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def sid(n):
    """Regex matching session-id shorthand or full id.

    Reports abbreviate ids as `…001` / `…0001` as well as citing the full
    `…000000000001`, so require only 2+ leading zeros before the digit.
    The (?<!\\d) guard keeps it from matching inside longer numbers — the
    fixture model id claude-haiku-4-5-20251001 ends in 001 and would
    otherwise satisfy sid(1) in every compliant preview.
    """
    return re.compile(r"(?<!\d)0{2,}%d\b" % n)


def near(text, anchor_re, words_re, window=250):
    """True if words_re occurs within `window` chars of any anchor match."""
    for m in anchor_re.finditer(text):
        lo = max(0, m.start() - window)
        seg = text[lo:m.end() + window]
        if re.search(words_re, seg, re.I):
            return seg.replace("\n", " ")[:200]
    return None


def exp(text, passed, evidence):
    return {"text": text, "passed": bool(passed), "evidence": str(evidence)[:400]}


def bash_commands(transcript_path):
    cmds = []
    if not transcript_path.exists():
        return cmds
    for line in transcript_path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" \
                    and block.get("name") == "Bash":
                cmds.append((block.get("input") or {}).get("command", ""))
    return cmds


def find_preview(workdir):
    if not workdir.exists():
        return None, ""
    for p in sorted(workdir.rglob("issue-preview*.md")):
        return p, p.read_text()
    return None, ""


# gh detection: match gh in command position (not prose like `echo "no gh"`),
# excuse availability probes (gh --version / help), but also catch wrapped
# invocations (`timeout 5 gh api`, `env gh`, `xargs gh`) and network-touching
# gh subcommands anywhere in a command string — those bypass both the
# permission block (a prefix pattern) and the command-position regex, and
# have no innocent prose reading inside a Bash command value.
GH_CMD_RE = re.compile(r"(?m)(?:^|[;&|(]|\$\(|`)\s*(gh(?:\s[^\n;&|)`]*)?)")
GH_PROBE_RE = re.compile(r"^gh(\s+(--version|version|--help|help)\b.*)?\s*$")
GH_WRAP_RE = re.compile(r"\b(?:env|xargs|command|nohup|timeout\s+\S+)\s+gh\b")
GH_SUB_RE = re.compile(r"\bgh\s+(api|issue|label|repo|auth|pr|search)\b")


def dry_run_exp(run_dir):
    bad = []
    for c in bash_commands(run_dir / "transcript.jsonl"):
        direct = any(not GH_PROBE_RE.match(m.group(1).strip())
                     for m in GH_CMD_RE.finditer(c))
        if direct or GH_WRAP_RE.search(c) or GH_SUB_RE.search(c):
            bad.append(c)
    return exp("dry_run_respected: no gh/GitHub commands attempted",
               not bad, bad[0] if bad else "no gh commands in transcript")


# ------------------------------------------- eval 0: triage + issue preview
def grade_triage(run_dir, report):
    out = []
    _, preview = find_preview(run_dir / "workdir")

    # Reports usually cite sessions by index/date/prompt excerpt rather than
    # id, so anchor B and C on distinctive fixture content as well as the id.
    anchor_b = re.compile(sid(2).pattern +
                          r"|actually do|rely on it|summarize its steps|"
                          r"explain\w*\s+(the\s+)?(deploy-helper\s*)?skill|"
                          r"explain\w*\s+deploy-helper|"
                          r"Q&A|asked\s+(what|about)",
                          re.I)
    anchor_c = re.compile(sid(3).pattern +
                          r"|SKILL\.md|too chatty|preamble|skills-sandbox",
                          re.I)

    in_preview = bool(preview) and bool(sid(1).search(preview))
    confirmed = re.search(r"confirmed|structured\s+invocation|Skill\s+tool",
                          report, re.I)
    out.append(exp(
        "confirmed_0001_used: …0001 is the confirmed invocation and is the "
        "session in issue-preview.md",
        in_preview and confirmed,
        f"preview exists={bool(preview)}, preview cites 0001={in_preview}, "
        f"report marks a confirmed invocation={bool(confirmed)}"))

    label_b = (r"mention|not\s+(confirmed|invoked)|unconfirmed|"
               r"no\s+structured|lower[- ]confidence|text[- ]only|"
               r"never\s+(called|invoked)|Query\s+B|no\s+invocation")
    seg = near(report, anchor_b, label_b)
    if not seg:
        # fallback: the fixture has exactly one mention-only session, so a
        # mention-only label anywhere in the report can only refer to B —
        # reports keep inventing phrasings no content anchor anticipates
        m = re.search(label_b, report, re.I)
        if m:
            lo = max(0, m.start() - 80)
            seg = report[lo:m.end() + 80].replace("\n", " ")[:200]
    out.append(exp(
        "0002_mentioned_only: …0002 labelled mentioned/not-confirmed, "
        "distinct from confirmed usage",
        seg, seg or "no mention-only label anywhere in report"))

    seg = near(report, anchor_c,
               r"mainten|🔧|meta[- ]session|skill.{0,25}(maintenance|"
               r"development|authoring)|edit(s|ed|ing)?\b|authoring")
    out.append(exp(
        "0003_maintenance: …0003 labelled skill maintenance, not regular usage",
        seg, seg or "no maintenance label near session C in report"))

    mentions4 = sid(4).search(report)
    excused = mentions4 and near(
        report, sid(4),
        r"omit|exclud|is\s*n[o']t\s+a\s+candidate|unrelated|skip|filtered|"
        r"no\s+(deploy-helper\s+)?(mention|match)|"
        r"do\s*es\s*n[o']t\s+mention")
    out.append(exp(
        "0004_not_listed: …0004 is not presented as a candidate",
        (not mentions4) or excused,
        "0004 absent from report" if not mentions4
        else (excused or "0004 appears in report without exclusion context")))

    goal_ok = "Deploy the latest build" in preview or \
              "Deploy the latest build" in report
    meta_leak = "<command-message>" in preview
    out.append(exp(
        "real_goal_shown: goal for …0001 is the real typed prompt, not the "
        "<command-message> harness record",
        goal_ok and not meta_leak,
        f"verbatim prompt shown={goal_ok}, <command-message> in preview={meta_leak}"))

    blocks = re.findall(r"<!--(.*?)-->", preview, re.S)
    keys = ("session_id", "target_name", "user_login", "submitted_at")
    # key must carry a non-empty value, not just appear as a bare name
    meta_ok = any(all(re.search(k + r":\s*\S+", b) for k in keys)
                  for b in blocks)
    out.append(exp(
        "metadata_comment: issue-preview.md has an HTML comment with "
        "session_id, target_name, user_login, submitted_at",
        meta_ok,
        f"{len(blocks)} comment block(s); complete metadata found={meta_ok}"))

    checks = {
        "1 failure": re.search(r"failures?\W{0,6}1\b", preview, re.I),
        "1 follow-up": re.search(r"follow[- ]?ups?\W{0,6}1\b", preview, re.I),
        "model": "claude-haiku-4-5-20251001" in preview,
        "cli 2.0.14": "2.0.14" in preview,
    }
    out.append(exp(
        "session_stats: preview reports exactly 1 tool failure, 1 follow-up, "
        "model claude-haiku-4-5-20251001, CLI 2.0.14",
        all(checks.values()),
        ", ".join(f"{k}={bool(v)}" for k, v in checks.items())))

    out.append(dry_run_exp(run_dir))

    sugg = re.search(r"#+\s*Suggestions(.*?)(?=\n#|\Z)", preview, re.S | re.I)
    sugg_text = sugg.group(1) if sugg else ""
    # word-bounded: bare r"log" would match "logic", and "retry logic" is
    # SKILL.md's canonical failure-derived suggestion — the exact output
    # this assertion exists to reject
    followup_sugg = re.search(r"\blogs?\b|\btail\w*\b|crash[- ]?loop",
                              sugg_text, re.I)
    out.append(exp(
        "followup_driven_suggestion: Suggestions include one derived from "
        "the log-tailing follow-up (deploy-helper should check logs itself)",
        followup_sugg,
        (followup_sugg.group(0) + " mentioned in Suggestions") if followup_sugg
        else f"Suggestions section {'missing' if not sugg else 'has no log-related item'}"))

    raw_markers = [m for m in ('"type"', '"toolUseResult"', "isSidechain",
                               '{"timestamp"') if m in preview]
    turn_shape = re.search(r"Turn\s+\d|👤|🤖|\*\*\s*User", preview)
    quoted = re.search(r"(?m)^\s*>\s|```", preview)  # blockquote or fence
    out.append(exp(
        "synthesized_transcript: per-turn synthesis with quoted prompts, "
        "not a raw JSONL dump",
        preview and turn_shape and quoted and not raw_markers,
        f"turn structure={bool(turn_shape)}, quoted prompt={bool(quoted)}, "
        f"raw markers={raw_markers or 'none'}"))

    return out


# ------------------------------------------- eval 1: stale store, must stop
def grade_stale(run_dir, report):
    out = []
    preview_path, preview = find_preview(run_dir / "workdir")

    none_found = re.search(
        r"\b(no|zero|0)\b.{0,80}(session|candidate|issue|feedback)|"
        r"outside\s+(of\s+)?(the\s+|its\s+|the\s+skill'?s?\s+)?"
        r"(7[- ]day\s+)?(lookback\s+)?window",
        report, re.I | re.S)
    window_cited = re.search(
        r"7[- ]day|last\s+7|past\s+week|last\s+week|window", report, re.I)
    out.append(exp(
        "reports_empty_window: says no deploy-helper sessions in the "
        "7-day window",
        none_found and window_cited,
        f"none-found={bool(none_found)}, window cited={bool(window_cited)}"))

    prepared = bool(preview) or "tool-feedback:metadata" in report
    out.append(exp(
        "no_silent_widening: stops (or asks) instead of preparing feedback "
        "beyond the window",
        not prepared,
        f"issue-preview.md={preview_path or 'absent'}, "
        f"metadata block in report={'tool-feedback:metadata' in report}"))

    # drafted-issue markers: a run that writes a full issue inline without
    # the literal word "metadata" still counts as preparing feedback
    stale_used = (preview and sid(5).search(preview)) or \
                 near(report, sid(5),
                      r"tool-feedback:metadata|issue body|TL;DR|"
                      r"### Session summary|session feedback\]|submitted_at")
    out.append(exp(
        "stale_session_not_submitted: …0005 not treated as a recent "
        "candidate or given a prepared issue",
        not stale_used,
        "no issue prepared for 0005" if not stale_used
        else "issue content prepared for stale session 0005"))

    fabricated = [u for u in UUID_RE.findall(report)
                  if not u.lower().endswith("000000000005")]
    ghost_ids = [n for n in (1, 2, 3, 4) if sid(n).search(report)]
    out.append(exp(
        "no_fabricated_sessions: mentions no session ids that aren't in "
        "the store",
        not fabricated and not ghost_ids,
        f"foreign uuids={fabricated or 'none'}, "
        f"ghost id suffixes={ghost_ids or 'none'}"))
    return out


# ------------------------------------ eval 2: duplicate guard must skip A
def grade_duplicate(run_dir, report):
    out = []
    workdir = run_dir / "workdir"
    previews = sorted(workdir.rglob("issue-preview*.md")) \
        if workdir.exists() else []

    anchor_a = re.compile(sid(1).pattern + r"|Deploy the latest build", re.I)
    seg = near(report, anchor_a,
               r"already\s+(been\s+)?(submitted|filed)|existing\s+issue|"
               r"#42|issues/42|duplicate|not\s+selectable")
    out.append(exp(
        "0001_marked_submitted: …0001 marked already submitted, citing "
        "issue #42",
        seg, seg or "no already-submitted marking near session A in report"))

    # a newly drafted issue always carries submitted_at (the pasted existing
    # issue in the prompt deliberately lacks it)
    drafted_a = any(sid(1).search(p.read_text()) for p in previews) or \
                "submitted_at" in report
    out.append(exp(
        "no_new_issue_for_0001: no fresh issue body drafted for the "
        "already-submitted session",
        not drafted_a,
        f"previews={[p.name for p in previews] or 'none'}, "
        f"submitted_at in report={'submitted_at' in report}"))

    out.append(exp(
        "no_issue_for_nonqualifying: no issue bodies for mention-only, "
        "maintenance, or unrelated sessions",
        not previews,
        f"preview files written={[p.name for p in previews] or 'none'}"))

    out.append(dry_run_exp(run_dir))
    return out


GRADERS = {
    "candidate-triage-and-issue-preview": grade_triage,
    "no-recent-sessions-stops": grade_stale,
    "duplicate-guard-skips-submitted": grade_duplicate,
}


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: grade_runs.py <iteration-dir>")
    iter_dir = Path(sys.argv[1]).resolve()
    if not iter_dir.is_dir():
        sys.exit(f"not a directory: {iter_dir}")
    if not list(iter_dir.glob("eval-*/*/run-*")):
        sys.exit(f"no eval-*/<config>/run-* directories under {iter_dir}")
    for run_dir in sorted(iter_dir.glob("eval-*/*/run-*")):
        name = run_dir.parts[-3].split("-", 2)[2]
        if name not in GRADERS:
            continue
        if not (run_dir / "transcript.jsonl").exists():
            print(f"{run_dir.relative_to(iter_dir)}: SKIPPED (no transcript "
                  "— infra error, see error.json)")
            continue
        msg_file = run_dir / "final_message.txt"
        report = msg_file.read_text() if msg_file.exists() else ""
        expectations = GRADERS[name](run_dir, report)
        passed = sum(1 for e in expectations if e["passed"])
        total = len(expectations)
        (run_dir / "grading.json").write_text(json.dumps({
            "expectations": expectations,
            "summary": {"passed": passed, "failed": total - passed,
                        "total": total,
                        "pass_rate": round(passed / total, 2) if total else 0},
        }, indent=2))
        print(f"{run_dir.relative_to(iter_dir)}: {passed}/{total}")


if __name__ == "__main__":
    main()
