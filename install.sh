#!/usr/bin/env bash
# Idempotent: safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

command -v stow >/dev/null || brew install stow
stow -t "$HOME" claude codex

(cd claude/.claude/skills/slopcop && npm ci --silent)

claude plugin marketplace add DietrichGebert/ponytail 2>/dev/null || true
claude plugin install ponytail@ponytail
