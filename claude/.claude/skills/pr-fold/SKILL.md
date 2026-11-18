---
name: pr-fold
description: "Write a PR body with a short human-readable opener on top and the full agent-written description collapsed in a `<details>` block named after the model. The visible part is judged with jev when the create-human-pr-body skill is installed, and approved by the author otherwise. Use when drafting or rewriting a PR description and the long version is worth keeping, before `gh pr create` or `gh pr edit`."
allowed-tools: Bash(python3 ~/.claude/skills/create-human-pr-body/scripts/judge.py:*), Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh pr edit:*), Bash(git diff:*), Read, Write
tier: advisory
---

# pr-fold

Produces a PR body in two layers. What a reader sees without clicking is one
opener line and one paragraph, the body the `create-human-pr-body` judge
calls CLEAN. The full agent-written account sits under it in a collapsed
`<details>` block whose summary names the model that wrote it. Nothing is
lost, and nobody has to read it.

The pattern is from
https://simonwillison.net/2026/Nov/9/details-summary/. Its promise to the
reader is that the visible part carries the author's judgement of what is
worth their time. A CLEAN verdict stands in for that judgement, so the body
is applied without asking. On any other verdict the author approves the
visible part before it is applied.

The judge is optional. It comes with the `create-human-pr-body` skill and
needs a TypeSafe key. Without it the author approves every visible part.

## When to use

When the long description holds something a reviewer may want later: design
decisions, alternatives ruled out, what was run to verify. For a small
change with nothing to add, skip the block: the visible part alone is the
body, which is what `create-human-pr-body` writes.

## Shape

```markdown
Shows admins why setting up their own cloud failed, instead of a generic error.

Admins whose install fails today see "Something went wrong" and file a ticket. They now see the failing step and the cloud's own message, so most can fix the permission themselves.

<details>
<summary>Claude Fable 5.2 High</summary>

## Problem

...

## Approach

...

## Verification

...

</details>

## Linear

Closes ENT-123
```

- **Visible part**: everything outside the block. It follows the table
  under [Visible part](#visible-part). Screenshots and sections the
  repository requires (Feature flags, Linear) stay visible, with the
  trailing ones after the block. An attribution footer goes last of all.
- **Summary line**: the name of the model writing the description, plus the
  effort level when you know it. Nothing else, so a reader knows what the
  block is before opening it.
- **Blank line after `</summary>` and before `</details>`**. Without them
  GitHub renders the Markdown inside as literal text.
- **Inside the block**: the description you would have written unprompted:
  problem, approach, decisions, verification. Headings and tables are fine
  here. The visible-part rules do not apply, with these exceptions:
  - Write only what the diff or the PR's history confirms. Leave a claim
    out rather than hedging it or passing the doubt to the author.
  - Report only verification that was run, with its real outcome, and keep
    to the target repository's rules on what counts as evidence.
  - Nothing that expires: no CI status, no review state.
  - Omit a section with nothing to report, Verification included.
- The opener is often already a sentence in the long version. Lift it
  rather than writing a new one.

## Visible part

The same table as "What passes" in `create-human-pr-body`. The right column
names the finding the judge reports when a rule is broken.

| Do | Because the judge flags |
| --- | --- |
| Line 1: one plain sentence, under 25 words, saying what the PR does. A teammate outside the area should get it from that line alone. Then a blank line. | `weak opener` for a heading, a second sentence, jargon, or background in its place |
| Then one paragraph: what the affected person hits today, and what changes for them. | `implementation inventory` when under a third of paragraphs say why or for whom |
| Say nothing a reader gets from the diff: file names, function names, what replaced what. | `restates the diff` when two sentences are recoverable from it; `mechanism dump` for a 100-word walk through the code |
| One line for what stays unchanged, when a reviewer would assume it changed. Stop there. | `defensive body` when paragraphs keep pre-empting objections nobody raised; `over_justified` |
| Give a term a plain-language clause at first use, or drop the term. | `written for insiders` when jargon averages above 0.70 |
| No Evidence, Testing, or Reviewer sections and no `Reviewer: confirm` lines. Don't claim it was tested; delete the sentence instead. Embed screenshots only where the repo requires them (UI changes). | `unverified claim` |
| At most one number per sentence; no parentheticals stuffed with figures. | `over-precise` |
| Report only what this change touched. | `off_topic` |
| Under about 100 words. No headings and no tables, except a table the repo requires (Feature flags). | `verbose for change size` above 10 words per changed line |

## Process

1. Read the diff: `git diff origin/main...HEAD`, or `gh pr diff NUMBER` for
   a PR whose branch is not checked out. Decide who is affected and what
   they see differently. When the PR already has a body with the right
   visible shape, start from it; the judge in step 4 still decides.
2. Write the long description to `DETAILS.md`.
3. Write the visible part to `VISIBLE.md`, unwrapped, including any required
   trailing sections.
4. Judge the visible part only. The block would fail every length rule by
   design.

   ```bash
   python3 ~/.claude/skills/create-human-pr-body/scripts/judge.py VISIBLE.md --title "TITLE"
   ```

   For a PR whose branch is not checked out, add `--pr NUMBER` so the draft
   is judged against that PR's diff. Run it from inside a checkout of the
   repository with absolute file paths, because the script calls `gh`
   without `--repo`.

   Fix what each finding points at and rerun. Stop at CLEAN or after three
   rounds, then show the author what is left. The judge sends the text and
   diff to TypeSafe; the data and setup notes in `create-human-pr-body`
   apply.

   Exit code 2 means no verdict: `create-human-pr-body` is not installed,
   it has no TypeSafe key, or jev is unreachable; the error output says
   which. Check `VISIBLE.md` against the table under
   [Visible part](#visible-part) yourself and go to step 5.
5. On CLEAN, do not ask: go to step 6, apply the body, and show the author
   the visible part and the verdict in the final report. Otherwise show the
   author the visible part with the verdict and its remaining findings, or
   with the reason the judge did not run, and wait for their approval or
   edits. Do not hand them a list of doubts: anything you could not confirm
   is already out of the body, and a missing required item (a ticket, a
   screenshot) is one question. In an unattended run, apply it and say in
   the final report that the opener has not been approved.
6. Assemble `BODY.md`: the visible prose and screenshots, the `<details>`
   block wrapping `DETAILS.md`, then the trailing required sections. Apply
   with `gh pr create --body-file` or `gh pr edit --body-file`.

When the PR changes after review, update both layers: the block goes stale
as easily as the opener.
