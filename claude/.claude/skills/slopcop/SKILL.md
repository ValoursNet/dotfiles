---
name: slopcop
description: Flag LLM prose tells in text — overused intensifiers, "it's important to note", not-X-but-Y pivots, em-dash overuse, triple constructions, and 30+ more. Deterministic regex/POS detectors, no model judgment. Use when asked to slopcop / slop-check / de-slop a draft, check whether writing reads AI-generated, or lint prose before shipping docs, PR bodies, or release notes.
allowed-tools: Bash(~/.claude/skills/slopcop/slopcop:*), Read
tier: advisory
---

# slopcop

36 client-side detectors from [awnist/slop-cop](https://github.com/awnist/slop-cop),
vendored as a CLI. Every hit comes from a regex or a POS tag — nothing is
inferred by a model, so the same text always produces the same report.

## Run it

```bash
~/.claude/skills/slopcop/slopcop draft.md          # group by rule, worst first
cat draft.md | ~/.claude/skills/slopcop/slopcop    # stdin
~/.claude/skills/slopcop/slopcop --help
```

Reading text out of a conversation rather than a file: write it to the
scratchpad first, then pass the path. Do not retype the text into the report
yourself — run the tool.

| Flag | Effect |
| --- | --- |
| `--flat` | Order by position — use when doing an edit pass top to bottom |
| `--summary` | Counts per rule only |
| `--json` | `line`, `column`, `startIndex`, `endIndex`, `suggestedChange`, `tip` |
| `--rule a,b` / `--exclude a,b` | Filter by rule id (`--list-rules` to see them) |
| `--strict` | Exit 1 on any hit |

## Reading the output

The `→ word` / `delete` / `rewrite` column is the detector's own verdict:
`delete` means the span can be cut with no repair, `rewrite` means removing it
would break the sentence. `index.ts:117` downgrades `delete` to `rewrite`
whenever the match sits in predicate-adjective position.

Density (`hits/100 words`) is the headline number. Prose above ~10 reads
machine-written; formatted reference docs run high on structure rules alone.

## Caveats worth stating before you act on a report

Markdown structure trips the structural detectors — `**Term**: explanation`
bullets, `→` in tables, and short header-adjacent lines are flagged as
`bold-first-bullets`, `unicode-arrows`, and `dramatic-fragment` in documents
where they are correct. On reference docs, filter to the prose rules:

```bash
~/.claude/skills/slopcop/slopcop --exclude bold-first-bullets,unicode-arrows,dramatic-fragment,colon-elaboration doc.md
```

A hit is a candidate, not a defect. `triple-construction` fires on any
`X, Y, and Z`, and em-dashes are flagged by count. Report what fired; let the
author decide what to cut.

The 12 semantic rules upstream (throat-clearing, sycophantic frame, grandiose
stakes, fractal summaries) need a model and are deliberately absent — nothing
here calls an API.

## Maintenance

`lib/` is upstream `src/` at `a151b1e`, minus the React app and
`llmDetectors.ts`. Two edits: relative imports carry `.ts` extensions for Node
ESM, and `lib/detectors/nlpInstance.ts` reaches compromise's unlisted plugin
files by path instead of by Vite alias. Re-syncing means re-applying both, then
confirming upstream's 299 tests still pass against the patched loader.
