#!/usr/bin/env node
import { readFileSync } from 'node:fs'
import { runClientDetectors } from './detectors/index.ts'
import { RULES } from './rules.ts'
import type { Violation, ViolationRule } from './types.ts'

const RULE_BY_ID = new Map<string, ViolationRule>(RULES.map(r => [r.id, r]))

const HELP = `slopcop — detect LLM prose tells. Regex + POS tagging, no model calls.

USAGE
  slopcop [file ...]          analyze files
  slopcop                     analyze stdin
  cat draft.md | slopcop -

OUTPUT
  --flat                grouped by position instead of by rule
  --summary             per-rule counts only
  --json                machine-readable violations
  --no-tips             omit the fix advice under each rule
  --no-color            plain text (also honors NO_COLOR)

FILTERING
  --rule id,id          only these rules
  --exclude id,id       skip these rules
  --list-rules          print every rule id

EXIT
  --strict              exit 1 when anything is flagged (default: always 0)
`

type Opts = {
  files: string[]
  flat: boolean
  summary: boolean
  json: boolean
  tips: boolean
  color: boolean
  only: Set<string> | null
  exclude: Set<string>
  strict: boolean
}

function parseArgs(argv: string[]): Opts | 'help' | 'list' {
  const o: Opts = {
    files: [], flat: false, summary: false, json: false, tips: true,
    color: process.stdout.isTTY === true && !process.env.NO_COLOR,
    only: null, exclude: new Set(), strict: false,
  }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const ids = () => (argv[++i] ?? '').split(',').map(s => s.trim()).filter(Boolean)
    switch (a) {
      case '-h': case '--help': return 'help'
      case '--list-rules': return 'list'
      case '--flat': o.flat = true; break
      case '--summary': o.summary = true; break
      case '--json': o.json = true; break
      case '--no-tips': o.tips = false; break
      case '--no-color': o.color = false; break
      case '--color': o.color = true; break
      case '--strict': o.strict = true; break
      case '--rule': o.only = new Set(ids()); break
      case '--exclude': for (const id of ids()) o.exclude.add(id); break
      default:
        if (a.startsWith('--')) { process.stderr.write(`slopcop: unknown flag ${a}\n`); process.exit(2) }
        o.files.push(a)
    }
  }
  return o
}

function readStdin(): string {
  try {
    return readFileSync(0, 'utf8')
  } catch {
    return ''
  }
}

// ── formatting ────────────────────────────────────────────────────────────────

function paint(color: boolean) {
  const c = (code: string) => (s: string | number) => (color ? `\x1b[${code}m${s}\x1b[0m` : String(s))
  return { dim: c('2'), bold: c('1'), red: c('31'), yellow: c('33'), cyan: c('36'), green: c('32') }
}

function lineStarts(text: string): number[] {
  const starts = [0]
  for (let i = 0; i < text.length; i++) if (text[i] === '\n') starts.push(i + 1)
  return starts
}

function locate(starts: number[], index: number): string {
  let lo = 0, hi = starts.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (starts[mid] <= index) lo = mid
    else hi = mid - 1
  }
  return `${lo + 1}:${index - starts[lo] + 1}`
}

function oneLine(s: string, max = 68): string {
  const flat = s.replace(/\s+/g, ' ').trim()
  return flat.length > max ? flat.slice(0, max - 1) + '…' : flat
}

// undefined/'' = delete the span; null = no safe mechanical fix; string = replacement
function action(v: Violation, rule: ViolationRule | undefined): string {
  if (v.suggestedChange === null) return 'rewrite'
  if (v.suggestedChange) return `→ ${oneLine(v.suggestedChange, 30)}`
  return rule?.canRemove ? 'delete' : 'rewrite'
}

function report(text: string, violations: Violation[], label: string | null, o: Opts): string {
  const k = paint(o.color)
  const starts = lineStarts(text)
  const words = text.trim() ? text.trim().split(/\s+/).length : 0
  const density = words ? (violations.length / words) * 100 : 0
  const out: string[] = []

  const heading = [
    label ? k.bold(label) : k.bold('slopcop'),
    `${words.toLocaleString()} words`,
    `${violations.length} hit${violations.length === 1 ? '' : 's'}`,
    `${density.toFixed(1)}/100 words`,
  ].join(k.dim('  ·  '))
  out.push(heading, '')

  if (!violations.length) {
    out.push(k.green('  clean — no client-side tells matched'), '')
    return out.join('\n')
  }

  const byRule = new Map<string, Violation[]>()
  for (const v of violations) {
    if (!byRule.has(v.ruleId)) byRule.set(v.ruleId, [])
    byRule.get(v.ruleId)!.push(v)
  }
  const ranked = [...byRule.entries()].sort((a, b) =>
    b[1].length - a[1].length || a[0].localeCompare(b[0]))

  const name = (id: string) => RULE_BY_ID.get(id)?.name ?? id
  const heat = (n: number) => (n >= 5 ? k.red(n) : n >= 2 ? k.yellow(n) : k.dim(n))

  if (o.summary) {
    const w = Math.max(...ranked.map(([id]) => name(id).length))
    for (const [id, vs] of ranked) {
      out.push(`  ${String(vs.length).padStart(3)}  ${name(id).padEnd(w)}  ${k.dim(id)}`)
    }
    out.push('')
    return out.join('\n')
  }

  if (o.flat) {
    const sorted = [...violations].sort((a, b) => a.startIndex - b.startIndex)
    const locW = Math.max(...sorted.map(v => locate(starts, v.startIndex).length))
    const nameW = Math.max(...sorted.map(v => name(v.ruleId).length))
    for (const v of sorted) {
      const rule = RULE_BY_ID.get(v.ruleId)
      out.push(
        `  ${k.dim(locate(starts, v.startIndex).padStart(locW))}  ` +
        `${k.cyan(name(v.ruleId).padEnd(nameW))}  ` +
        `${oneLine(v.matchedText, 50).padEnd(50)}  ${k.dim(action(v, rule))}`,
      )
    }
    out.push('')
    return out.join('\n')
  }

  for (const [id, vs] of ranked) {
    const rule = RULE_BY_ID.get(id)
    out.push(`${heat(vs.length)}×  ${k.bold(k.cyan(name(id)))}  ${k.dim(rule?.category ?? '')}  ${k.dim(id)}`)
    if (o.tips && rule?.tip) out.push(k.dim(`     ${oneLine(rule.tip, 96)}`))
    const locW = Math.max(...vs.map(v => locate(starts, v.startIndex).length))
    for (const v of vs.sort((a, b) => a.startIndex - b.startIndex)) {
      out.push(
        `     ${k.dim(locate(starts, v.startIndex).padStart(locW))}  ` +
        `${oneLine(v.matchedText, 60).padEnd(60)}  ${k.dim(action(v, rule))}`,
      )
    }
    out.push('')
  }
  return out.join('\n')
}

// ── main ──────────────────────────────────────────────────────────────────────

const parsed = parseArgs(process.argv.slice(2))

if (parsed === 'help') {
  process.stdout.write(HELP)
  process.exit(0)
}

if (parsed === 'list') {
  const w = Math.max(...RULES.map(r => r.id.length))
  for (const r of RULES.filter(r => !r.requiresLLM)) {
    process.stdout.write(`${r.id.padEnd(w)}  ${r.name}  (${r.category})\n`)
  }
  process.exit(0)
}

const o = parsed
const inputs: { label: string | null; text: string }[] =
  o.files.length && !(o.files.length === 1 && o.files[0] === '-')
    ? o.files.map(f => ({ label: f, text: readFileSync(f, 'utf8') }))
    : [{ label: null, text: readStdin() }]

let total = 0
const jsonOut: unknown[] = []
const chunks: string[] = []

for (const { label, text } of inputs) {
  let violations = runClientDetectors(text)
  if (o.only) violations = violations.filter(v => o.only!.has(v.ruleId))
  if (o.exclude.size) violations = violations.filter(v => !o.exclude.has(v.ruleId))
  violations.sort((a, b) => a.startIndex - b.startIndex)
  total += violations.length

  if (o.json) {
    const starts = lineStarts(text)
    jsonOut.push({
      file: label,
      words: text.trim() ? text.trim().split(/\s+/).length : 0,
      count: violations.length,
      violations: violations.map(v => {
        const rule = RULE_BY_ID.get(v.ruleId)
        const [line, column] = locate(starts, v.startIndex).split(':').map(Number)
        return {
          ruleId: v.ruleId,
          rule: rule?.name ?? v.ruleId,
          category: rule?.category ?? null,
          line,
          column,
          startIndex: v.startIndex,
          endIndex: v.endIndex,
          matchedText: v.matchedText,
          suggestedChange: v.suggestedChange ?? null,
          canRemove: rule?.canRemove ?? false,
          tip: rule?.tip ?? null,
        }
      }),
    })
  } else {
    chunks.push(report(text, violations, label, o))
  }
}

process.stdout.write(o.json ? JSON.stringify(inputs.length > 1 ? jsonOut : jsonOut[0], null, 2) + '\n' : chunks.join('\n'))
process.exit(o.strict && total > 0 ? 1 : 0)
