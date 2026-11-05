<script setup lang="ts">
/**
 * 判定规则编辑器（递归）。直接修改传入的 rule 对象（父级持有 reactive 副本）。
 * 条件组：切换 与 / 或，增删条件或子组；条件：主体（本对象属性 / 位号 / 计算）+ 运算符 + 阈值（数值 / 限值引用）+ 持续时长。
 */
import { LIMIT_TEXT, OP_TEXT, AGG_TEXT, newCondition, newGroup } from './ruleText'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

const props = defineProps<{
  rule: Any
  params: Any[]
  limits: Any[]
  calcs: Any[]
  depth?: number
}>()
const emit = defineEmits<{ (e: 'remove'): void }>()

function addCond(): void { props.rule.children.push(newCondition()) }
function addGroup(): void { props.rule.children.push(newGroup(props.rule.op === 'AND' ? 'OR' : 'AND')) }
function removeChild(i: number): void { props.rule.children.splice(i, 1) }

function onSubjectKind(c: Any, kind: string): void {
  if (kind === 'parameter') c.subject = { kind, name: '' }
  else if (kind === 'tag') c.subject = { kind, tag: '' }
  else c.subject = { kind, calcId: props.calcs[0]?.id ?? '' }
}
function onOperator(c: Any, op: string): void {
  c.operator = op
  if (op === 'change') {
    delete c.threshold
    c.from ??= 1
    c.to ??= 0
  } else {
    c.threshold ??= { kind: 'value', value: 0 }
  }
}
function onThresholdKind(c: Any, kind: string): void {
  c.threshold = kind === 'limit' ? { kind, limitId: '', field: 'normalHigh' } : { kind, value: 0 }
}
function limitHint(c: Any): string {
  const l = props.limits.find((x: Any) => x.id === c.threshold?.limitId)
  if (!l) return ''
  const v = l[c.threshold.field]
  return `${l.appliesTo} · ${l.operatingMode || ''} · ${v ?? '无数值'} ${l.unit || ''}`
}
</script>

<template>
  <div class="rounded-md border p-2 space-y-2" :class="rule.op === 'AND' ? 'border-info/40 bg-info/[0.04]' : 'border-warn/40 bg-warn/[0.04]'">
    <div class="flex items-center gap-2">
      <select v-model="rule.op" class="inp !py-0.5">
        <option value="AND">同时满足（与）</option>
        <option value="OR">满足任一（或）</option>
      </select>
      <button class="ctl" @click="addCond">+ 条件</button>
      <button class="ctl" @click="addGroup">+ 条件组</button>
      <span class="flex-1" />
      <button v-if="(depth ?? 0) > 0" class="ctl" @click="emit('remove')">删除本组</button>
    </div>

    <div v-for="(c, i) in rule.children" :key="i">
      <RuleEditor v-if="c.type === 'group'" :rule="c" :params="params" :limits="limits" :calcs="calcs" :depth="(depth ?? 0) + 1" @remove="removeChild(i)" />
      <div v-else class="flex flex-wrap items-center gap-1.5 bg-ink-panel2 border border-line-soft rounded px-2 py-1.5">
        <select :value="c.subject.kind" class="inp" @change="onSubjectKind(c, ($event.target as HTMLSelectElement).value)">
          <option value="parameter">本对象属性</option>
          <option value="tag">DCS 位号</option>
          <option value="calc">计算组态</option>
        </select>
        <template v-if="c.subject.kind === 'parameter'">
          <input v-model="c.subject.name" class="inp w-40" list="v2-param-list" placeholder="属性名，如 反应体系pH" />
          <select v-model="c.aggregate" class="inp" title="属性落到多个测点时如何合并">
            <option v-for="(t, k) in AGG_TEXT" :key="k" :value="k">{{ t }}</option>
          </select>
        </template>
        <input v-else-if="c.subject.kind === 'tag'" v-model="c.subject.tag" class="inp w-32 font-mono" placeholder="如 TI_1303" />
        <select v-else v-model="c.subject.calcId" class="inp w-44">
          <option v-for="k in calcs" :key="k.id" :value="k.id">{{ k.name }}</option>
        </select>

        <select :value="c.operator" class="inp" @change="onOperator(c, ($event.target as HTMLSelectElement).value)">
          <option v-for="(t, k) in OP_TEXT" :key="k" :value="k">{{ t }}</option>
        </select>

        <template v-if="c.operator === 'change'">
          <span class="text-fg-mute text-xs">由</span>
          <input v-model.number="c.from" type="number" class="inp w-14" />
          <span class="text-fg-mute text-xs">变为</span>
          <input v-model.number="c.to" type="number" class="inp w-14" />
        </template>
        <template v-else>
          <select :value="c.threshold?.kind" class="inp" @change="onThresholdKind(c, ($event.target as HTMLSelectElement).value)">
            <option value="value">数值</option>
            <option value="limit">工艺限值</option>
          </select>
          <input v-if="c.threshold?.kind === 'value'" v-model.number="c.threshold.value" type="number" step="any" class="inp w-20" />
          <template v-else>
            <select v-model="c.threshold.limitId" class="inp w-44">
              <option value="">选择限值</option>
              <option v-for="l in limits" :key="l.id" :value="l.id">{{ l.id }} {{ l.appliesTo }}</option>
            </select>
            <select v-model="c.threshold.field" class="inp">
              <option v-for="(t, k) in LIMIT_TEXT" :key="k" :value="k">{{ t }}</option>
            </select>
          </template>
        </template>

        <span class="text-fg-mute text-xs">持续</span>
        <input v-model.number="c.durationSec" type="number" min="0" class="inp w-16" />
        <span class="text-fg-mute text-xs">秒</span>
        <span class="flex-1" />
        <button class="ctl" title="删除条件" @click="removeChild(i)">✕</button>
        <div v-if="c.threshold?.kind === 'limit' && c.threshold.limitId" class="w-full text-[11px] text-fg-mute pl-1">{{ limitHint(c) }}</div>
      </div>
    </div>
    <div v-if="!rule.children.length" class="text-xs text-err">条件组至少要有一个条件</div>
  </div>
</template>
