# claude-skills

Agent skills by Ingo Claro. Each one ships with a graded eval suite, because a
skill that isn't measured drifts the moment the model underneath it changes.

Skills follow the portable `SKILL.md` convention, so they work with Claude Code
and the other agents [`skills`](https://github.com/vercel-labs/skills) supports.

## Skills

### `skill-feedback`

Reviews your recent Claude Code sessions for uses of a specific agent or skill
and files structured per-session feedback as GitHub issues — with a synthesized
conversation transcript, session stats (model, CLI version, tool failures,
follow-ups), duplicate detection, and a mandatory redaction pass before anything
is posted.

The premise: the corrections you make mid-session are the highest-signal
evidence of where a skill fails, and they are almost always lost to the session
log.

```bash
npx skills add ingoclaro/claude-skills --skill skill-feedback
```

Invoked as `/skill-feedback`, or triggers on phrases like "review my
deploy-helper sessions" or "file skill feedback".

**Configuration.** Set the two authored defaults in
`skills/skill-feedback/SKILL.md` frontmatter (`metadata:` block) when
installing, or answer when the skill asks:

- `target_name` — the agent or skill to collect feedback about; also used as the
  GitHub label on filed issues
- `feedback_repo` — the `owner/repo` where issues are filed

**Requirements.** `gh` (authenticated, with permission to open issues in
`feedback_repo`), `jq`, and a POSIX shell — macOS/Linux; native Windows is not
supported.

**Privacy.** Session transcripts can contain sensitive content. The skill treats
session data as untrusted, redacts credentials/URLs/personal data before posting
(see SKILL.md step 6c), and warns before filing into a public repo. Review the
drafted issue body when prompted — you are publishing session content.

## Install

```bash
npx skills add ingoclaro/claude-skills            # pick interactively
npx skills add ingoclaro/claude-skills --list     # see what's here
npx skills add ingoclaro/claude-skills --skill '*'
```

Add `-g` to install for your user rather than the current project, `-y` to skip
prompts, and `-a claude-code` to target a specific agent.

### Direct clone

Skills are discovered at `~/.claude/skills/<name>/SKILL.md`, so clone the repo
somewhere neutral and link in the ones you want:

```bash
git clone https://github.com/ingoclaro/claude-skills ~/src/claude-skills
ln -s ~/src/claude-skills/skills/skill-feedback ~/.claude/skills/skill-feedback
```

Restart Claude Code.

## Evals

Every skill carries its own eval suite at `skills/<name>/evals/` — self-contained
(Python stdlib only, no network), with generated fixture session stores, a
headless runner, and a programmatic grader. They live next to the skill so a
change and the evidence it didn't regress travel together.

For `skill-feedback`, see
[`skills/skill-feedback/evals/README.md`](skills/skill-feedback/evals/README.md).
Run output lands in that skill's `evals/files/` (gitignored).

## License

MIT — see [LICENSE](LICENSE).
