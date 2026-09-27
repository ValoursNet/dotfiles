#!/usr/bin/env python3
"""Judge a PR body the way a tired reviewer would: is it written for a human, or is it slop?

Usage:
  judge.py BODY.md [--base REF] [--title TITLE] [--json]   # draft body vs the local branch diff
  judge.py --pr NUMBER [--json]                             # an existing PR via gh
  judge.py BODY.md --pr NUMBER                              # a redraft, judged against that PR's diff
  judge.py --help

BODY.md is the draft (or - for stdin). The diff, changed files and line count come from
`git diff REF...HEAD` (default origin/main) so the judge can tell which sentences merely
restate the diff. Verdict CLEAN exits 0; SUSPECT or SLOP exits 1 with one finding per
line as `BODY.md:LINE — code — message`; a missing key or unreachable jev exits 2.

Judgments come from TypeSafe jev (System One), about a cent per body. Lexical tells come
from slopcop when ~/.claude/skills/slopcop is installed and are skipped otherwise.
Rules and thresholds were tuned against 38 hand-labelled PR bodies on 2026-09-19.
"""
import argparse, json, os, re, subprocess, sys, urllib.error, urllib.request

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
REVIEW_BAND = (0.35, 0.65)
USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0}  # printed with the verdict
_KEY = None


KEY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".typesafe_api_key")


def api_key():
    """Read TYPESAFE_API_KEY from the environment or the key file beside the skill."""
    global _KEY
    if _KEY:
        return _KEY
    if not os.environ.get("TYPESAFE_API_KEY") and os.path.exists(KEY_FILE):
        with open(KEY_FILE) as key_file:
            os.environ["TYPESAFE_API_KEY"] = key_file.read().strip()
    _KEY = os.environ.get("TYPESAFE_API_KEY")
    if not _KEY:
        sys.exit(f"judge.py: no TYPESAFE_API_KEY (export it, or write it to {KEY_FILE})")
    return _KEY
SLOPCOP = os.path.expanduser("~/.claude/skills/slopcop/slopcop")
# Structural rules misfire on Markdown that is correct in a PR body.
SLOPCOP_EXCLUDE = "bold-first-bullets,unicode-arrows,dramatic-fragment,colon-elaboration,parenthetical-qualifier,short-hook-paragraph,listicle-instinct,listicle-trench-coat,em-dash-pivot"


def noul(instructions, true, false):
    return {"type": "noul", "instructions": instructions, "criteria": {"true": true, "false": false}}


# ---- per paragraph: state = {paragraph, earlier_paragraphs, title?, files?} ----
PARAGRAPH_QUESTIONS = {
    "specific_claim": {
        "type": "choice",
        "instructions": "Does `paragraph` make a specific, checkable claim, or does it only gesture at one?",
        "criteria": {
            "specific": "States a concrete fact, number, behavior, or decision that a reader could verify or falsify.",
            "gesture": "Uses vague language (improves, streamlines, addresses potential issues, enhances) without a checkable statement.",
            "neither": "Neither a claim nor a gesture: a list of links, a question, a label.",
        },
    },
    "evidence_type": {
        "type": "choice",
        "instructions": "What kind of evidence does `paragraph` offer for what it says?",
        "criteria": {
            "measurement": "A number, rate, latency, count, or score observed before/after.",
            "media": "References a screenshot, recording, or video.",
            "link": "Links to a run, dashboard, ticket, trace, or eval result.",
            "repro": "Gives steps a reader could follow to reproduce the behavior.",
            "quote": "Quotes an observed log line, error, or output.",
            "assertion_only": "Claims something was tested, verified, or works, with nothing a reader could inspect.",
            "none": "Makes no claim that needs evidence, or offers nothing at all.",
        },
    },
    "states_motivation": noul(
        "Does `paragraph` say who is affected by the change or why it matters to them?",
        "Names a user, team, service, or reviewer and what changes for them, or a constraint that forced the change.",
        "Describes code, tests, or internal mechanism only.",
    ),
    "explains_mechanism": noul(
        "Does `paragraph` explain the internal mechanism of a failure or a fix?",
        "Walks through how code, a test, or a system behaved and why, step by step.",
        "No mechanism is described.",
    ),
    "undefined_jargon": noul(
        "Does `paragraph` use a specialist term, internal codename, or acronym that a teammate outside this area would need to look up, without a plain-language clause explaining it at first use?",
        "Such a term appears with no explanation in the paragraph.",
        "Every specialist term is explained, or only common engineering vocabulary appears. Company, product, package, and person names are not jargon.",
    ),
    "unverifiable_verification": noul(
        "Does `paragraph` claim something was tested, verified, confirmed, or works, without any artifact a reader could inspect?",
        "Words like tested, verified, confirmed, works as expected, with no measurement, link, screenshot, or steps.",
        "No verification claim is made, or the claim comes with something inspectable.",
    ),
    "actionable": noul(
        "Could a reviewer do something specific because of `paragraph`, such as open a named path, run a step, check a value, or answer a stated question?",
        "Names a concrete thing to open, run, check, or decide.",
        "Nothing here changes what the reviewer would do next.",
    ),
    # Semantic tells only; lexical ones come from slopcop. Retired tells live in retired.py.
    "throat_clearing": noul(
        "Does `paragraph` spend sentences announcing, framing, or reassuring instead of informing, regardless of the exact wording?",
        "Sentences about the importance, care, or thoroughness of what follows, or that announce what the paragraph will do, without themselves carrying information.",
        "Every sentence states something a reviewer needs.",
    ),
    "over_justified": noul(
        "Does `paragraph` defend or qualify a choice against objections no reader has raised?",
        "Explains why an alternative was not taken, insists a limit is deliberate, or notes that a pattern is already used elsewhere, when nothing in the paragraph shows the question came up.",
        "States what was done and why it matters, without pre-empting review.",
    ),
    "off_topic": noul(
        "Does `paragraph` report results, failures, or details about things this change did not touch?",
        "Mentions test suites, services, or behavior outside the change and their outcomes, e.g. unrelated failing checks or tooling errors.",
        "Everything reported concerns the change itself.",
    ),
    "redundant": noul(
        "Does `paragraph` repeat information already present in `earlier_paragraphs`?",
        "The main point of the paragraph is already stated in an earlier paragraph, even if reworded.",
        "The paragraph adds information not found earlier, or there are no earlier paragraphs.",
    ),
}

# Only asked when the PR's changed-file list is in state.
DIFF_CAP = 60_000  # chars of diff per call; jev rejects roughly 300 KB of state with max_tokens_exceeded
TEXT_CAP = 40_000  # chars of body / earlier paragraphs per call


def rederivable_questions(sentences):
    return {f"rederivable_{i}": noul(
        f"Could a reviewer recover the content of `sentences[{i}]` by reading `diff` alone?",
        "Every fact in the sentence is visible in the diff: which lines changed, what replaced what, which file or test.",
        "The sentence carries something the diff cannot show: a cause, a constraint, an observation, a decision, who is affected, or how it was verified.",
    ) for i in range(len(sentences))}


def sentences(p):
    parts = re.split(r"(?<=[.!?:])\s+(?=[A-Z`\"\d(])|\n+", p)
    return [x.strip() for x in parts if len(x.split()) >= 4]


FILES_QUESTIONS = {
    "supported_by_files": noul(
        "Given the changed `files` list, is the change described in `paragraph` plausible?",
        "The kind of change described could be made in the listed files, or the paragraph makes no claim about the change.",
        "The described change would require files not in the list (e.g. a UI change with no frontend files, a migration with no schema files).",
    ),
}

# ---- whole document: state = {body, title?, files?} ----
DOCUMENT_QUESTIONS = {
    "problem_stated": noul(
        "Does `body` state what problem or need the change addresses?",
        "A defect, gap, or request is named, not just the change itself.",
        "The body describes only what changed.",
    ),
    "problem_names_affected": noul(
        "Does `body` say who is affected by the problem it fixes or the change it makes (users, a team, a service, a cohort)?",
        "A specific affected party is named.",
        "No affected party is named, or only the code is described.",
    ),
    "changed_behavior_stated": noul(
        "Does `body` state what happens differently after the change, in terms of observable behavior?",
        "A before/after or new behavior a reviewer could look for in the diff or the product.",
        "Only files, functions, or intentions are described.",
    ),
    "scope_names_unchanged": noul(
        "Does `body` state which users, cases, or behavior stay unchanged?",
        "Explicitly names something that does not change or is out of scope.",
        "Only the changed behavior is described.",
    ),
    "evidence_section_real": noul(
        "If `body` has an evidence, proof, testing, or screenshots section, does it contain something inspectable rather than prose?",
        "The section holds images, links, numbers, or steps. Also true when there is no such section.",
        "The section exists but contains only sentences asserting that things were tested or work.",
    ),
    "linear_section_ok": noul(
        "Does every ticket reference in `body` (an identifier like DX-123) appear in a Linear section using exactly one of 'Closes XX-123', 'Part of XX-123', or 'Related to XX-123'?",
        "Every ticket reference uses one of the three forms, or there is no ticket reference at all.",
        "A ticket is referenced outside that form, or the section uses a different verb.",
    ),
}
TITLE_QUESTIONS = {
    "title_matches_body": noul(
        "Does the semantic-commit type at the start of `title` (fix, feat, refactor, chore, docs, test, perf) match what `body` describes?",
        "The body describes the kind of change the type names, e.g. fix with a defect, feat with new behavior, refactor with no behavior change.",
        "The body describes a different kind of change, e.g. a refactor title with new user-visible behavior, or a fix title with no defect described.",
    ),
}
FLAG_QUESTIONS = {
    "flag_table_present": noul(
        "Does `body` contain a Feature flags table with the columns Flag, Treatment, and Effect on app, with one row per flag/treatment pair?",
        "The table is present with those columns.",
        "The table is missing or has other columns.",
    ),
}


def ask(state, questions):
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(URL, body, {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
    except urllib.error.URLError as e:
        if not isinstance(e, urllib.error.HTTPError):
            sys.exit(f"judge.py: cannot reach {URL}: {e.reason}")
        detail = e.read()[:300].decode(errors="replace")
        if "max_tokens_exceeded" in detail and state.get("diff"):
            state = {**state, "diff": state["diff"][: len(state["diff"]) // 2] or None}
            if state["diff"] is None:
                del state["diff"]
            return ask(state, questions)
        sys.exit(f"judge.py: jev HTTP {e.code} ({len(body)} bytes sent): {detail}")
    USAGE["calls"] += 1
    USAGE["input_tokens"] += data["usage"]["input_tokens"]
    USAGE["output_tokens"] += data["usage"]["output_tokens"]
    return data["answers"]


def is_prose(p):
    return not p.startswith(("#", "|", "http", "```", "<!--", "![")) and len(p.split()) >= 6


def paragraphs(text):
    """(start_offset, paragraph) for every prose paragraph."""
    out, pos = [], 0
    for chunk in text.split("\n\n"):
        stripped = chunk.strip()
        if stripped and is_prose(stripped):
            out.append((pos + chunk.index(stripped), stripped))
        pos += len(chunk) + 2
    return out


def lexical_hits(text, paras):
    """slopcop rule ids per paragraph index, mapped by character offset; empty when slopcop is not installed."""
    hits = [[] for _ in paras]
    if not os.path.exists(SLOPCOP):
        return hits
    r = subprocess.run([SLOPCOP, "--json", "--exclude", SLOPCOP_EXCLUDE], input=text, capture_output=True, text=True)
    if r.returncode not in (0, 1) or not r.stdout.strip():
        return hits
    for v in json.loads(r.stdout)["violations"]:
        for i, (start, p) in enumerate(paras):
            if start <= v["startIndex"] < start + len(p):
                hits[i].append(v["ruleId"])
    return hits


def precision(p):
    """Parenthetical groups plus standalone numbers, per sentence."""
    n = len(sentences(p)) or 1
    return (len(re.findall(r"\([^)]{3,}\)", p)) + len(re.findall(r"(?<![\w`/.-])\d[\d.,]*(?:s|ms|px|%|h|x)?\b", p))) / n


def flags(a, lexical, words, text="", ignore=()):
    """Reasons a paragraph counts as slop; empty list means clean.

    Strong signals flag alone. Weak ones need two, because each fires on ordinary
    human prose (an essay's framing sentence, a blog post's transition)."""
    strong, weak = [], []
    def on(rule): return rule not in ignore
    if on("unverified claim") and a["unverifiable_verification"]["noul"] > 0.7:
        strong.append("unverified claim")
    if on("lexical") and 100 * len(lexical) / words >= 8:  # slopcop: >10 hits/100 words reads machine-written
        strong.append("lexical:" + ",".join(lexical))
    if on("mechanism dump") and words > 100 and a["explains_mechanism"]["noul"] > 0.9:
        strong.append(f"mechanism dump ({words} words)")
    if on("throat_clearing") and a["throat_clearing"]["noul"] > 0.6:
        weak.append("throat_clearing")
    if on("over_justified") and a["over_justified"]["noul"] > 0.6:
        weak.append("over_justified")
    if on("off_topic") and a["off_topic"]["noul"] > 0.6:
        weak.append("off_topic")
    if on("over-precise") and precision(text) >= 1.0:
        weak.append(f"over-precise ({precision(text):.1f} parentheticals+numbers per sentence)")
    if on("lexical") and 100 * len(lexical) / words >= 4:
        weak.append("lexical:" + ",".join(lexical))
    return strong + (weak if len(weak) >= 2 else [])


def document_flags(par_answers, doc, words, changed_lines, ignore=()):
    """Body-level findings; thresholds are guesses until labels.tsv has enough rows."""
    out = []
    if not par_answers:
        return out
    n = len(par_answers)
    def on(rule): return rule not in ignore
    # ponytail: 10 body words per changed line is a guess; tune against labels.tsv
    if on("verbose for change size") and changed_lines and words / changed_lines > 10:
        out.append(f"verbose for change size ({words / changed_lines:.0f} words/line)")
    motivated = sum(a["states_motivation"]["noul"] > 0.5 for a in par_answers)
    if on("implementation inventory") and n >= 2 and motivated / n < 1 / 3:  # a single paragraph is too little to call a share
        out.append(f"implementation inventory ({motivated}/{n} paragraphs say why or for whom)")
    jargon = sum(a["undefined_jargon"]["noul"] for a in par_answers) / n
    if on("written for insiders") and jargon > 0.7:
        out.append(f"written for insiders (jargon {jargon:.2f})")
    defensive = sum(a["over_justified"]["noul"] for a in par_answers) / n
    if on("defensive body") and n >= 2 and defensive >= 0.5:
        out.append(f"defensive body (over-justification {defensive:.2f} across paragraphs)")
    if on("evidence that isn't") and doc["evidence_section_real"]["noul"] < 0.3:
        out.append("evidence that isn't (section holds only assertions)")
    red = [v["noul"] for a in par_answers for k, v in a.items() if k.startswith("rederivable_")]
    if on("restates the diff") and sum(x > 0.5 for x in red) >= 2:  # one borderline sentence flipped 3-sentence bodies
        out.append(f"restates the diff ({sum(x > 0.5 for x in red)}/{len(red)} sentences)")
    return out


def verdict(flag_lists, doc_flags=()):
    """One label. Paragraph share sets the level; each document finding bumps it one step."""
    if not flag_lists:
        return "no prose"
    n = sum(1 for f in flag_lists if f)
    share = n / len(flag_lists)
    level = 2 if share >= 0.5 else 1 if share >= 0.2 else 0
    level = min(2, level + len(doc_flags))
    reasons = [f"{n}/{len(flag_lists)} paragraphs flagged", *doc_flags]
    return f"{['CLEAN', 'SUSPECT', 'SLOP'][level]} ({'; '.join(reasons)})"


def load_pr(number):
    pr = json.loads(subprocess.check_output(["gh", "pr", "view", str(number), "--json", "title,body,files,additions,deletions"]))
    r = subprocess.run(["gh", "pr", "diff", str(number)], capture_output=True, text=True)
    diff = r.stdout[:DIFF_CAP] if r.returncode == 0 else None  # GitHub refuses diffs over ~20k lines
    return pr["title"], pr["body"], [f["path"] for f in pr["files"]], diff, pr["additions"] + pr["deletions"]


def load_branch(base):
    rng = f"{base}...HEAD"
    diff = subprocess.run(["git", "diff", rng], capture_output=True, text=True)
    if diff.returncode != 0:
        sys.exit(f"judge.py: git diff {rng} failed: {diff.stderr.strip()}")
    files = subprocess.run(["git", "diff", "--name-only", rng], capture_output=True, text=True).stdout.split()[:200]  # a wrong --base lists the whole repo
    stat = subprocess.run(["git", "diff", "--numstat", rng], capture_output=True, text=True).stdout
    changed = sum(int(a) + int(b) for a, b, *_ in (l.split("\t") for l in stat.splitlines()) if a.isdigit() and b.isdigit())
    return files, diff.stdout[:DIFF_CAP] or None, changed


HINTS = {
    "unverified claim": "says tested/verified/works with nothing a reader can open; link a run, number, screenshot or steps, or write `Reviewer: confirm …`",
    "lexical": "slopcop tells; cut the phrase rather than reword it",
    "mechanism dump": "a walk through the code; the diff already shows it, keep the reason it was needed",
    "throat_clearing": "a sentence that announces or reassures instead of informing; delete it",
    "over_justified": "defends a choice nobody questioned; one line of scope is enough",
    "off_topic": "reports on things this change did not touch; move it to the ticket or drop it",
    "over-precise": "figures and parentheticals per sentence; keep one number, move the rest to the evidence table",
    "verbose for change size": "too many words for the diff; a short change earns a short body",
    "implementation inventory": "too few paragraphs say who is affected or why; open with what the reader hits today",
    "written for insiders": "jargon a teammate outside the area would look up; add a plain clause at first use or drop the term",
    "evidence that isn't": "the evidence section holds only assertions; link, measure, screenshot, or say there is none",
    "restates the diff": "sentences a reviewer recovers from the diff; delete them",
    "defensive body": "the body keeps pre-empting objections; state the change and one line of scope",
}


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("body", nargs="?", help="draft PR body file, or - for stdin")
    p.add_argument("--pr", type=int, help="judge an existing PR instead of a draft")
    p.add_argument("--base", default="origin/main", help="merge base for the local diff (default origin/main)")
    p.add_argument("--title", default=None, help="PR title, so the judge can check its type against the body")
    p.add_argument("--json", action="store_true", help="machine-readable verdict and findings")
    args = p.parse_args()
    if args.pr:
        title, text, files, diff, changed_lines = load_pr(args.pr)
        label = f"pr-{args.pr}"
        if args.body:  # a redraft for that PR: its diff, your body
            text = sys.stdin.read() if args.body == "-" else open(args.body).read()
            label = args.body
    elif args.body:
        text = sys.stdin.read() if args.body == "-" else open(args.body).read()
        files, diff, changed_lines = load_branch(args.base)
        title, label = args.title, ("stdin" if args.body == "-" else args.body)
    else:
        p.print_usage()
        return 2
    extra = {k: v for k, v in {"title": title, "files": files}.items() if v}

    paras = paragraphs(text)
    if not paras:
        print(f"{label}:1 — no-prose — nothing to judge (headings, tables and fragments are skipped)")
        return 1
    lexical = lexical_hits(text, paras)
    pq = {**PARAGRAPH_QUESTIONS, **(FILES_QUESTIONS if files else {})}
    findings, all_flags, all_answers, restated = [], [], [], []
    for i, (start, para) in enumerate(paras):
        state = {"paragraph": para, "earlier_paragraphs": "\n\n".join(q for _, q in paras[:i])[-TEXT_CAP:], **extra}
        q = dict(pq)
        if diff:
            state.update(sentences=sentences(para), diff=diff)
            q.update(rederivable_questions(state["sentences"]))
        answers = ask(state, q)
        if diff:
            restated += [f"{v['noul']:.2f} “{state['sentences'][int(k.split('_')[1])][:90]}”"
                         for k, v in answers.items() if k.startswith("rederivable_") and v["noul"] > 0.5]
        f = flags(answers, lexical[i], len(para.split()), para)
        all_flags.append(f)
        all_answers.append(answers)
        for reason in f:
            code = reason.split(" (")[0].split(":")[0]
            findings.append({"line": line_of(text, start), "code": code, "message": f"{reason}; {HINTS.get(code, '')}".rstrip("; "), "paragraph": para[:80]})

    dq = {**DOCUMENT_QUESTIONS, **(TITLE_QUESTIONS if title else {}),
          **(FLAG_QUESTIONS if files and any(f.startswith("confidence/flags/") for f in files) else {})}
    doc = ask({"body": text[:TEXT_CAP], **extra}, dq)
    words = sum(len(q.split()) for _, q in paras)
    df = document_flags(all_answers, doc, words, changed_lines)
    for reason in df:
        code = reason.split(" (")[0]
        msg = f"{reason}; {HINTS.get(code, '')}".rstrip("; ")
        if code == "restates the diff":
            msg += "\n    " + "\n    ".join(restated)
        findings.append({"line": 1, "code": code, "message": msg, "paragraph": "(whole body)"})
    v = verdict(all_flags, df)

    if args.json:
        print(json.dumps({"verdict": v.split()[0], "summary": v, "findings": findings, "usage": USAGE}, indent=2))
    else:
        for f in findings:
            print(f"{label}:{f['line']} — {f['code']} — {f['message']}")
        print(f"verdict: {v}  (jev calls {USAGE['calls']}, input tokens {USAGE['input_tokens']})")
    return 0 if v.startswith("CLEAN") else 1


if __name__ == "__main__":
    sys.exit(main())
