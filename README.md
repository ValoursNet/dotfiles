# dotfiles

Stow-managed. `./install.sh` links everything into `$HOME` and installs Claude plugins; safe to re-run.

- `claude/` — public Claude Code skills (`~/.claude/skills/*`), linked per skill so private local skills stay out of the repo.
- Plugins (ponytail) are installed from their own repos by `install.sh`, not vendored.

The ASD-STE100 PDF used by `ste-writing` is gitignored (not redistributable); drop it into the skill folder by hand.
