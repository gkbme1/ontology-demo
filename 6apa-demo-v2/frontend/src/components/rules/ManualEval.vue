<script setup lang="ts">
/**
 * 手工输入试算（需求 SW-046 第 3 条）：给规则用到的每个条件主体填一个当前值，按瞬时值判定各条件与整条规则。
 * 持续时长按「已满足」处理；限值引用取基础版本（V0）值（传入 limitOverrides 时按覆盖值）。不影响现象状态。
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { AGG_TEXT, LIMIT_TEXT, OP_TEXT, conditionText, subjectText } from './ruleText'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ rule: Any; calcNames?: Record<string, string>; limitOverrides?: Record<string, Any> }>()

const limits = ref<Record<string, Any>>({})
onMounted(async () => {
  try { limits.value = Object.fromEntries((await api.limits()).items.map((l: Any) => [l.id, l])) } catch { /* 无限值表时只能用数值阈值 */ }
})

const leaves: Any[] = []
function walk(r: Any): void {
  if (!r) return
  if (r.type === 'group') r.children.forEach(walk)
  else leaves.push(r)
}
walk(props.rule)
const keyOf = (c: Any) => `${subjectText(c.subject, props.calcNames)}${c.subject?.kind === 'parameter' && c.aggregate && c.aggregate !== 'any' ? `[${AGG_TEXT[c.aggregate]}]` : ''}`
const subjects = [...new Set(leaves.map(keyOf))]
const hasChange = leaves.some((c) => c.operator === 'change')
const values = ref<Record<string, string>>({})
const prevValues = ref<Record<string, string>>({})

function thresholdValue(t: Any): number | null {
  if (t?.kind === 'limit') {
    const ov = props.limitOverrides?.[t.limitId]
    if (ov?.disabled) return null
    const v = ov?.values?.[t.field] ?? limits.value[t.limitId]?.[t.field]
    return v === undefined || v === null ? null : Number(v)
  }
  const n = Number(t?.value)
  return Number.isFinite(n) ? n : null
}
function cond(c: Any): { ok: boolean | null; why: string } {
  const raw = values.value[keyOf(c)]
  if (raw === undefined || raw === '') return { ok: null, why: '未填值' }
  const v = Number(raw)
  if (c.operator === 'change') {
    const p = prevValues.value[keyOf(c)]
    if (p === undefined || p === '') return { ok: null, why: '未填上一时刻的值' }
    return { ok: Number(p) === Number(c.from) && v === Number(c.to), why: `上一时刻 ${p} → 当前 ${v}` }
  }
  const th = thresholdValue(c.threshold)
  if (th === null) return { ok: null, why: '阈值没有数值（限值待现场提供或本台已禁用）' }
  const ok = { '>': v > th, '>=': v >= th, '<': v < th, '<=': v <= th, '=': v === th, '!=': v !== th }[c.operator as string]
  return { ok: !!ok, why: `${v} ${OP_TEXT[c.operator]} ${th}` }
}
function evalRule(r: Any): boolean | null {
  if (r.type !== 'group') return cond(r).ok
  const parts = r.children.map(evalRule)
  if (r.op === 'AND') return parts.includes(false) ? false : parts.includes(null) ? null : true
  return parts.includes(true) ? true : parts.includes(null) ? null : false
}
const overall = computed(() => evalRule(props.rule))
</script>

<template>
  <div class="space-y-3 text-sm">
    <div class="text-xs text-fg-mute">填写各条件主体的当前值，按瞬时值判定；持续时长按已满足处理。手工试算不影响现象状态。</div>
    <table class="tbl">
      <thead><tr><th>条件主体</th><th class="w-40">当前值</th><th v-if="hasChange" class="w-40">上一时刻值（变化类条件）</th></tr></thead>
      <tbody>
        <tr v-for="s in subjects" :key="s" class="!cursor-default">
          <td>{{ s }}</td>
          <td><input v-model="values[s]" type="number" step="any" class="inp !w-32" /></td>
          <td v-if="hasChange"><input v-model="prevValues[s]" type="number" step="any" class="inp !w-32" /></td>
        </tr>
      </tbody>
    </table>
    <div class="flex items-center gap-2">
      <span class="text-fg-dim">整条规则：</span>
      <span class="pill" :class="overall === true ? 'pill-err' : overall === false ? 'pill-ok' : 'pill-mute'">
        {{ overall === true ? '成立' : overall === false ? '不成立' : '无法判定（有条件未填值）' }}
      </span>
    </div>
    <table class="tbl">
      <thead><tr><th>条件</th><th class="w-24">结果</th><th>取值</th></tr></thead>
      <tbody>
        <tr v-for="(c, i) in leaves" :key="i" class="!cursor-default">
          <td>{{ conditionText(c, calcNames) }}<span v-if="c.threshold?.kind === 'limit'" class="text-[11px] text-fg-mute"> （{{ c.threshold.limitId }} {{ LIMIT_TEXT[c.threshold.field] }}）</span></td>
          <td><span class="pill" :class="cond(c).ok === true ? 'pill-err' : cond(c).ok === false ? 'pill-ok' : 'pill-mute'">{{ cond(c).ok === true ? '满足' : cond(c).ok === false ? '不满足' : '—' }}</span></td>
          <td class="text-xs text-fg-mute">{{ cond(c).why }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
