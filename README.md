# skill-feedback

A Claude Code skill that reviews your recent sessions for uses of a specific
agent or skill and files structured per-session feedback as GitHub issues —
with a synthesized conversation transcript, session stats (model, CLI
version, tool failures, follow-ups), duplicate detection, and a mandatory
redaction pass before anything is posted.

## Install

### As a plugin (recommended)

```
/plugin marketplace add ingoclaro/skill-feedback
/plugin install skill-feedback@ingoclaro
```

The skill is invoked as `/skill-feedback:feedback`, or triggers automatically
on phrases like "review my deploy-helper sessions" or "file skill feedback".

### Direct clone

```bash
git clone https://github.com/ingoclaro/skill-feedback ~/.claude/skills/skill-feedback
```

Restart Claude Code.

## Configuration

Set the two authored defaults in `skills/feedback/SKILL.md` frontmatter
(`metadata:` block) when installing, or answer when the skill asks:

- `target_name` — the agent or skill to collect feedback about; also used as
  the GitHub label on filed issues
- `feedback_repo` — the `owner/repo` where issues are filed

## Requirements

- `gh` CLI, authenticated with permission to open issues in `feedback_repo`
- `jq`
- A POSIX shell environment (macOS/Linux; native Windows is not supported)

## Privacy

Session transcripts can contain sensitive content. The skill treats session
data as untrusted, redacts credentials/URLs/personal data before posting
(see SKILL.md step 6c), and warns before filing into a public repo. Review
the drafted issue body when prompted — you are publishing session content.

## Evals

`evals/` contains a self-contained eval suite (Python stdlib only, no
network): generated fixture session stores, a headless runner, and a
programmatic grader. See `evals/README.md`. Run output lands in
`evals/files/` (gitignored).
