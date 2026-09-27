# dotfiles

Managed with GNU Stow. Run `./install.sh` to link everything into `$HOME` and install the Claude plugins. You can run it again at any time.

## Claude Code skills

Each skill is linked into `~/.claude/skills/` on its own, so private skills on the machine stay out of this repo.

| Skill | What it does |
| --- | --- |
| `bro` | Rewrites Claude's last reply in plain words, without the jargon. |
| `create-human-pr-body` | Writes a pull request description, then revises it until a judge model says a person would want to read it. |
| `deslop` | Detects AI writing patterns and rewrites prose in a natural voice. |
| `slopcop` | Lists the AI writing habits it finds in a piece of text. |
| `ste-writing` | Rewrites docs in Simplified Technical English, the plain-English standard used in aerospace manuals. |
| `stop-slop` | Edits a draft to remove predictable AI writing patterns. |

`ste-writing` can use the ASD-STE100 spec PDF, which is not in this repo. Get it free from asd-ste100.org and put it in the skill folder.

## Codex skills

Skills are linked into `~/.codex/skills/`.

| Skill | What it does |
| --- | --- |
| `write-like-michael` | Drafts and rewrites prose in Michael's natural voice, using writing guidance and examples. |

## Plugins

| Plugin | What it does |
| --- | --- |
| `ponytail` | Makes Claude choose the simplest working solution. `install.sh` installs it from its own repo. |
