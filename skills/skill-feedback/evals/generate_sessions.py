#!/usr/bin/env python3
"""Generate session-store fixtures for the skill-feedback evals.

Creates fake Claude Code session JSONL files laid out like
~/.claude/projects/<sanitized-cwd>/<session-id>.jsonl, under two roots:

  evals/files/projects/        recent sessions (the main eval store)
  evals/files/projects-stale/  a single store whose only matching session
                               is ~30 days old (outside the 7-day window)

Session content is deterministic; timestamps are computed relative to *now*
so the skill's 7-day recency window works. File mtimes are set to each
session's last activity, because the skill narrows candidates with
`find ... -mtime -7`. Re-run this script immediately before every eval run,
and if you relocate fixtures, preserve mtimes (cp -p / rsync -t).

Standard library only; runs on any Python >= 3.6 (`python3
evals/generate_sessions.py` from the skill root).

Fixture cast (target skill: deploy-helper):
  A  confirmed  structured Skill invocation of deploy-helper, 1 tool failure,
                2 real user prompts (1 follow-up), plus harness noise: an
                isMeta record, a <command- record, and sidechain records
  B  mention    discusses deploy-helper in text, never invokes it
  C  maintenance edits deploy-helper's own SKILL.md via the Edit tool
  D  unrelated  never mentions deploy-helper (must not appear as candidate)
  E  stale      same shape as A but ~30 days old, in projects-stale/
"""

import json
import os
import shutil
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
FILES_DIR = os.path.join(EVALS_DIR, "files")
NOW = datetime.now(timezone.utc)

MODEL = "claude-haiku-4-5-20251001"
CLI_VERSION = "2.0.14"


def ts(days_ago, minutes=0):
    t = NOW - timedelta(days=days_ago) + timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def base(session_id, cwd, days_ago, minutes):
    return {
        "timestamp": ts(days_ago, minutes),
        "sessionId": session_id,
        "cwd": cwd,
        "gitBranch": "main",
        "version": CLI_VERSION,
    }


def user(session_id, cwd, days_ago, minutes, content, **extra):
    rec = base(session_id, cwd, days_ago, minutes)
    rec.update({"type": "user", "message": {"role": "user", "content": content}})
    rec.update(extra)
    return rec


def tool_result(session_id, cwd, days_ago, minutes, tool_use_id, content, is_error=False):
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return user(session_id, cwd, days_ago, minutes, [block])


def assistant(session_id, cwd, days_ago, minutes, blocks, **extra):
    rec = base(session_id, cwd, days_ago, minutes)
    rec.update({
        "type": "assistant",
        "message": {"role": "assistant", "model": MODEL, "content": blocks},
    })
    rec.update(extra)
    return rec


def text(t):
    return {"type": "text", "text": t}


def tool_use(tid, name, tool_input):
    return {"type": "tool_use", "id": tid, "name": name, "input": tool_input}


def ai_title(session_id, days_ago, minutes, title):
    return {"type": "ai-title", "sessionId": session_id, "aiTitle": title,
            "timestamp": ts(days_ago, minutes)}


def deploy_session(session_id, cwd, days_ago):
    """A session with a confirmed structured deploy-helper invocation."""
    d = days_ago
    return [
        user(session_id, cwd, d, 0,
             "<command-message>status</command-message>", isMeta=True),
        # record type the skill's queries must ignore (present in real stores)
        {"type": "queue-operation", "operation": "enqueue",
         "timestamp": ts(d, 0), "sessionId": session_id},
        user(session_id, cwd, d, 1,
             "Deploy the latest build of the webapp to staging and make sure "
             "the health checks pass."),
        assistant(session_id, cwd, d, 2, [
            text("I'll use the deploy-helper skill to run the staging deploy."),
            tool_use("toolu_01", "Skill", {"skill": "deploy-helper",
                                           "args": "staging"}),
        ]),
        tool_result(session_id, cwd, d, 2, "toolu_01",
                    "Skill deploy-helper loaded."),
        assistant(session_id, cwd, d, 3, [
            text("Running the deploy script against staging."),
            tool_use("toolu_02", "Bash", {"command": "./scripts/deploy.sh staging"}),
        ]),
        tool_result(session_id, cwd, d, 5, "toolu_02",
                    "deploy.sh: health check timed out after 60s", is_error=True),
        assistant(session_id, cwd, d, 6, [
            text("The health check timed out; retrying with a longer wait."),
            tool_use("toolu_03", "Bash",
                     {"command": "./scripts/deploy.sh staging --wait 120"}),
        ]),
        tool_result(session_id, cwd, d, 8, "toolu_03",
                    "Deployed revision 4f9c2ab to staging. Health checks: 3/3 passing."),
        user(session_id, cwd, d, 9,
             "Also tail the logs for a minute to make sure nothing is "
             "crash-looping."),
        assistant(session_id, cwd, d, 10, [
            text("Tailing the staging logs."),
            tool_use("toolu_04", "Bash",
                     {"command": "kubectl logs -n staging deploy/webapp --since=1m"}),
        ]),
        tool_result(session_id, cwd, d, 11, "toolu_04",
                    "No restarts observed; request handlers healthy."),
        assistant(session_id, cwd, d, 12, [
            text("Deployed revision 4f9c2ab to staging. Health checks are 3/3 "
                 "green and one minute of logs shows no crash loops."),
        ]),
        # Subagent (sidechain) records — must be excluded from the
        # reconstructed conversation.
        user(session_id, cwd, d, 13,
             "Verify the staging smoke-test suite passes.", isSidechain=True),
        assistant(session_id, cwd, d, 14,
                  [text("Smoke tests passed (12/12).")], isSidechain=True),
        ai_title(session_id, d, 15, "Deploy webapp to staging"),
    ]


SESSIONS = {
    # A — confirmed invocation, 2 days ago
    ("projects", "-Users-dev-webapp",
     "3f2a1b04-9c1d-4e6a-8b2f-000000000001"): deploy_session(
        "3f2a1b04-9c1d-4e6a-8b2f-000000000001", "/Users/dev/webapp", 2),

    # B — mentions deploy-helper, never invokes it, 3 days ago
    ("projects", "-Users-dev-webapp",
     "3f2a1b04-9c1d-4e6a-8b2f-000000000002"): [
        user("3f2a1b04-9c1d-4e6a-8b2f-000000000002", "/Users/dev/webapp", 3, 0,
             "Before I rely on it, what does the deploy-helper skill actually "
             "do? Summarize its steps."),
        assistant("3f2a1b04-9c1d-4e6a-8b2f-000000000002", "/Users/dev/webapp",
                  3, 1, [
            tool_use("toolu_01", "Read",
                     {"file_path": "/Users/dev/.claude/skills/deploy-helper/SKILL.md"}),
        ]),
        tool_result("3f2a1b04-9c1d-4e6a-8b2f-000000000002", "/Users/dev/webapp",
                    3, 1, "toolu_01", "# deploy-helper\n..."),
        assistant("3f2a1b04-9c1d-4e6a-8b2f-000000000002", "/Users/dev/webapp",
                  3, 2, [
            text("deploy-helper builds the app, pushes the image, applies the "
                 "staging manifest, and polls health checks before reporting."),
        ]),
        ai_title("3f2a1b04-9c1d-4e6a-8b2f-000000000002", 3, 3,
                 "Explain deploy-helper skill"),
    ],

    # C — maintenance: edits deploy-helper's own files, 1 day ago
    ("projects", "-Users-dev-skills-sandbox",
     "3f2a1b04-9c1d-4e6a-8b2f-000000000003"): [
        user("3f2a1b04-9c1d-4e6a-8b2f-000000000003",
             "/Users/dev/skills-sandbox", 1, 0,
             "Tighten the wording in deploy-helper's SKILL.md — the preamble "
             "is too chatty."),
        assistant("3f2a1b04-9c1d-4e6a-8b2f-000000000003",
                  "/Users/dev/skills-sandbox", 1, 1, [
            text("Trimming the preamble."),
            tool_use("toolu_01", "Edit", {
                "file_path": "/Users/dev/skills-sandbox/deploy-helper/SKILL.md",
                "old_string": "This skill helps you deploy",
                "new_string": "Deploy"}),
        ]),
        tool_result("3f2a1b04-9c1d-4e6a-8b2f-000000000003",
                    "/Users/dev/skills-sandbox", 1, 1, "toolu_01",
                    "Edit applied."),
        assistant("3f2a1b04-9c1d-4e6a-8b2f-000000000003",
                  "/Users/dev/skills-sandbox", 1, 2,
                  [text("Preamble trimmed to two sentences.")]),
        ai_title("3f2a1b04-9c1d-4e6a-8b2f-000000000003", 1, 3,
                 "Edit deploy-helper SKILL.md"),
    ],

    # D — unrelated session, must not surface, 1 day ago
    ("projects", "-Users-dev-webapp",
     "3f2a1b04-9c1d-4e6a-8b2f-000000000004"): [
        user("3f2a1b04-9c1d-4e6a-8b2f-000000000004", "/Users/dev/webapp", 1, 0,
             "Fix the flaky retry test in the auth module."),
        assistant("3f2a1b04-9c1d-4e6a-8b2f-000000000004", "/Users/dev/webapp",
                  1, 1, [
            tool_use("toolu_01", "Bash",
                     {"command": "npm test -- auth/retry.test.js"}),
        ]),
        tool_result("3f2a1b04-9c1d-4e6a-8b2f-000000000004", "/Users/dev/webapp",
                    1, 2, "toolu_01", "1 test failed (timeout)"),
        assistant("3f2a1b04-9c1d-4e6a-8b2f-000000000004", "/Users/dev/webapp",
                  1, 3, [text("Fixed by replacing the sleep with a fake timer.")]),
        ai_title("3f2a1b04-9c1d-4e6a-8b2f-000000000004", 1, 4,
                 "Fix flaky auth retry test"),
    ],

    # E — stale store: confirmed invocation but ~30 days old
    ("projects-stale", "-Users-dev-webapp",
     "3f2a1b04-9c1d-4e6a-8b2f-000000000005"): deploy_session(
        "3f2a1b04-9c1d-4e6a-8b2f-000000000005", "/Users/dev/webapp", 30),
}


def realism_pass(session_id, records):
    """Add the per-record fields real session stores carry.

    Real records all have `uuid`, `parentUuid` (linear chain), explicit
    `isSidechain: false`, `userType` on user records, and `requestId` on
    assistant records. Fixtures must too, or a future query that keys on
    them would pass evals while breaking on real stores. Deterministic
    (uuid5), so fixture content stays reproducible.
    """
    prev = None
    for i, rec in enumerate(records):
        rec["uuid"] = str(uuidlib.uuid5(uuidlib.NAMESPACE_URL,
                                        "%s:%d" % (session_id, i)))
        rec["parentUuid"] = prev
        prev = rec["uuid"]
        if rec.get("type") in ("user", "assistant"):
            rec.setdefault("isSidechain", False)
        if rec.get("type") == "user":
            rec.setdefault("userType", "external")
        if rec.get("type") == "assistant":
            rec.setdefault("requestId", "req_" + rec["uuid"][:12])
    return records


def main():
    for root in ("projects", "projects-stale"):
        path = os.path.join(FILES_DIR, root)
        if os.path.isdir(path):
            shutil.rmtree(path)

    for (root, project_dir, session_id), records in SESSIONS.items():
        out_dir = os.path.join(FILES_DIR, root, project_dir)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, session_id + ".jsonl")
        with open(out_path, "w") as f:
            for rec in realism_pass(session_id, records):
                f.write(json.dumps(rec) + "\n")
        # find -mtime narrowing relies on the file's mtime tracking the
        # session's last activity.
        last = records[-1]["timestamp"]
        epoch = datetime.strptime(
            last, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=timezone.utc).timestamp()
        os.utime(out_path, (epoch, epoch))
        print("wrote %s (mtime %s)" % (os.path.relpath(out_path, EVALS_DIR), last))


if __name__ == "__main__":
    main()
