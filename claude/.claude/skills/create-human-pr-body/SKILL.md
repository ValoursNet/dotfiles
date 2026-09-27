---
name: create-human-pr-body
description: "Write a PR body a human wants to read, then judge it with jev and revise until it passes. Use when drafting or rewriting a PR description, before `gh pr create` or `gh pr edit`."
allowed-tools: Bash(python3 ~/.claude/skills/create-human-pr-body/scripts/judge.py:*), Bash(~/.claude/skills/create-human-pr-body/scripts/*), Bash(gh pr view:*), Bash(gh pr edit:*), Bash(git diff:*), Read, Write
tier: advisory
---

# create-human-pr-body

Drafts a PR body, judges it with `scripts/judge.py`, and revises until the
judge says CLEAN. The judge asks TypeSafe jev a fixed set of yes/no questions
about each paragraph and the body as a whole, then applies the rules below in
code. A run costs about a cent and takes under a minute. It replaces the
author's taste with the taste of 38 hand-labelled bodies, so a CLEAN verdict
means "reads like the bodies engineers here called clean", not "correct".

## When to use

Any time a PR description is about to be written or rewritten: `gh pr
create`, `gh pr edit`, the `create-pr` skill's body step, or a reviewer asking
for a better description. Not for commit messages or Linear tickets; the rules
assume a diff to judge against.

## What passes

The bodies that passed share one shape. Copy it before running anything:

| Do | Because the judge flags |
| --- | --- |
| First sentence: what the affected person hits today. Second: what changes for them. | `implementation inventory` when under a third of paragraphs say why or for whom |
| Say nothing a reader gets from the diff: file names, function names, what replaced what. | `restates the diff` when two sentences are recoverable from it; `mechanism dump` for a 100-word walk through the code |
| One line for what stays unchanged, when a reviewer would assume it changed. Stop there. | `defensive body` when paragraphs keep pre-empting objections nobody raised; `over_justified` |
| Give a term a plain-language clause at first use, or drop the term. | `written for insiders` when jargon averages above 0.70 |
| Evidence is a link, a number, a screenshot, or steps. Without one, say so and write the `Reviewer: confirm …` line. | `unverified claim`, `evidence that isn't` |
| At most one number per sentence; no parentheticals stuffed with figures. | `over-precise` |
| Report only what this change touched. | `off_topic` |
| Under about 100 words of prose unless a table of evidence needs more. | `verbose for change size` above 10 words per changed line |

Follow the target repository's PR requirements and any applicable `AGENTS.md`
instructions. The judge also checks Feature flags tables and Linear ticket formatting.

## Data sent to TypeSafe

The judge sends PR text, titles, changed file names, and the selected diff to
`https://api.typesafe.ai/v1/systemone`, including revision rounds. Use it only
when the user has authorized sending that content to TypeSafe. Keep personal
standing approvals in private configuration, not in this shared skill.

## Process

1. Read the diff, not the commits: `git diff origin/main...HEAD`. Decide who
   is affected and what they see differently. If you cannot say, the body
   cannot either; ask the author.
2. Draft the body to a file, unwrapped (GitHub soft-wraps), following the
   table above.
3. Judge it:

   ```bash
   python3 ~/.claude/skills/create-human-pr-body/scripts/judge.py BODY.md --title "TITLE"
   ```

   Each finding names a line and a rule. Fix the paragraph the line points at;
   a `(whole body)` finding means the shape, not a sentence. Rerun. Stop at
   CLEAN, or after three rounds: show the remaining findings to the author
   rather than rewriting past them, because at that point the disagreement is
   about the change, not the prose.
4. Apply with `gh pr create --body-file` or `gh pr edit --body-file`.

To judge a PR that already exists, `--pr NUMBER` reads title, body and diff
through `gh`. `--json` returns the verdict, findings and token usage for
scripting. Exit 0 is CLEAN, 1 has findings, 2 is a missing key or an
unreachable jev.

## Setup

The key is read from `TYPESAFE_API_KEY` if exported, else from
`~/.claude/skills/create-human-pr-body/.typesafe_api_key` (mode 600, one line,
Git-ignored). Supply your own key using either option. Lexical tells use
`~/.claude/skills/slopcop` when present and are skipped otherwise.

## Reference

- Rules, thresholds and the jev questions: `scripts/judge.py`, one dict per
  question, one `if` per rule.
- PR body requirements: the target repository's contribution guidelines and `AGENTS.md`, if present.
- jev: https://docs.typesafe.ai/api.
