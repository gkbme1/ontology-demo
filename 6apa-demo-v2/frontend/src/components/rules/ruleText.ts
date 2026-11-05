// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

export const OP_TEXT: Record<string, string> = {
  '>': '大于', '>=': '大于等于', '<': '小于', '<=': '小于等于', '=': '等于', '!=': '不等于', change: '由…变为…'
}
export const LIMIT_TEXT: Record<string, string> = {
  lowLow: '低低限', low: '低限', normalLow: '正常下限', normalHigh: '正常上限', high: '高限', highHigh: '高高限'
}
export const AGG_TEXT: Record<string, string> = { any: '任一测点', all: '全部测点', mean: '测点均值' }

export function subjectText(s: Any, calcNames: Record<string, string> = {}): string {
  if (!s) return '?'
  if (s.kind === 'parameter') return `本对象.${s.name || '?'}`
  if (s.kind === 'tag') return `位号 ${s.tag || '?'}`
  if (s.kind === 'calc') return `计算 ${calcNames[s.calcId] ?? s.calcId ?? '?'}`
  return '?'
}

export function thresholdText(t: Any): string {
  if (!t) return '?'
  if (t.kind === 'limit') return `${t.limitId || '?'} ${LIMIT_TEXT[t.field] ?? t.field ?? '?'}`
  return t.value === undefined || t.value === null || t.value === '' ? '?' : String(t.value)
}

export function durationText(sec: Any): string {
  const n = Number(sec || 0)
  if (!n) return ''
  return n % 60 === 0 ? `持续 ${n / 60} 分钟` : `持续 ${n} 秒`
}

export function conditionText(c: Any, calcNames: Record<string, string> = {}): string {
  const agg = c.subject?.kind === 'parameter' && c.aggregate && c.aggregate !== 'any' ? `[${AGG_TEXT[c.aggregate]}]` : ''
  const subj = subjectText(c.subject, calcNames) + agg
  const dur = durationText(c.durationSec)
  if (c.operator === 'change') return `${subj} 由 ${c.from} 变为 ${c.to} ${dur}`.trim()
  return `${subj} ${OP_TEXT[c.operator] ?? c.operator} ${thresholdText(c.threshold)} ${dur}`.trim()
}

export function newCondition(): Any {
  return { type: 'condition', subject: { kind: 'parameter', name: '' }, operator: '>', aggregate: 'any',
           threshold: { kind: 'value', value: 0 }, durationSec: 60 }
}

export function newGroup(op: 'AND' | 'OR' = 'AND'): Any {
  return { type: 'group', op, children: [newCondition()] }
}
