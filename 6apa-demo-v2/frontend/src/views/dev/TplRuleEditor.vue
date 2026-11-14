<script setup lang="ts">
/** 判定规则模板编辑（需求 SW-007）：条件引用「本对象.参数模板」，阈值可引用约束模板的限值等级；可重复参数可选 任一 / 全部 / 均值。 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ rule: Any; params: Any[]; constraints: Any[]; disabled?: boolean; depth?: number }>()
const emit = defineEmits<{ (e: 'remove'): void }>()
const OPS: Record<string, string> = { '>': '大于', '>=': '大于等于', '<': '小于', '<=': '小于等于', '=': '等于', '!=': '不等于', change: '由…变为…' }
const LIM: Record<string, string> = { lowLow: '低低限', low: '低限', normalLow: '正常下限', normalHigh: '正常上限', high: '高限', highHigh: '高高限' }
function addCond(): void {
  props.rule.children.push({ type: 'condition', subject: { kind: 'parameter', name: props.params[0]?.name ?? '' }, aggregate: 'any', operator: '>',
                             threshold: { kind: 'value', value: 0 }, durationSec: 60 })
}
function addGroup(): void { props.rule.children.push({ type: 'group', op: 'AND', children: [] }) }
</script>

<template>
  <div class="border-l-[3px] pl-3 py-1 space-y-1.5" :class="rule.op === 'AND' ? 'border-info' : 'border-warn'">
    <div class="flex items-center gap-1.5">
      <select v-model="rule.op" class="inp !w-32 font-semibold" :class="rule.op === 'AND' ? 'text-info' : 'text-warn'" :disabled="disabled">
        <option value="AND">满足全部（与）</option><option value="OR">满足任一（或）</option>
      </select>
      <button class="ctl !py-0" :disabled="disabled" @click="addCond">+ 条件</button>
      <button v-if="(depth ?? 0) < 2" class="ctl !py-0" :disabled="disabled" @click="addGroup">+ 条件组</button>
      <button v-if="depth" class="ctl !py-0 !px-1.5" :disabled="disabled" @click="emit('remove')">×</button>
    </div>
    <template v-for="(c, i) in rule.children" :key="i">
      <TplRuleEditor v-if="c.type === 'group'" :rule="c" :params="params" :constraints="constraints" :disabled="disabled" :depth="(depth ?? 0) + 1" @remove="rule.children.splice(i, 1)" />
      <div v-else class="flex flex-wrap items-center gap-1 rounded border border-line-soft bg-white px-2 py-1 text-xs">
        <template v-if="c.subject?.kind === 'parameter'">
          <span class="text-fg-mute">本对象.</span>
          <select v-model="c.subject.name" class="inp !w-36" :disabled="disabled"><option v-for="p in params" :key="p.code" :value="p.name">{{ p.name }}{{ p.repeatable ? '[*]' : '' }}</option><option v-if="c.subject.name && !params.some((p) => p.name === c.subject.name)" :value="c.subject.name">{{ c.subject.name }}（实例参数）</option></select>
          <select v-model="c.aggregate" class="inp !w-20" :disabled="disabled"><option value="any">任一</option><option value="all">全部</option><option value="mean">均值</option></select>
        </template>
        <span v-else class="font-mono">{{ c.subject?.kind === 'calc' ? `计算 ${c.subject.calcId}` : c.subject?.kind === 'tag' ? `位号 ${c.subject.tag}` : `上下文.${c.subject?.name}` }}</span>
        <select v-model="c.operator" class="inp !w-24" :disabled="disabled"><option v-for="(t, k) in OPS" :key="k" :value="k">{{ t }}</option></select>
        <template v-if="c.operator === 'change'">
          <input v-model.number="c.from" class="inp !w-12" :disabled="disabled" /> → <input v-model.number="c.to" class="inp !w-12" :disabled="disabled" />
        </template>
        <template v-else>
          <select v-model="c.threshold.kind" class="inp !w-20" :disabled="disabled"><option value="value">数值</option><option value="limit">约束</option></select>
          <input v-if="c.threshold.kind === 'value'" v-model.number="c.threshold.value" class="inp !w-20" :disabled="disabled" />
          <template v-else>
            <select v-model="c.threshold.limitId" class="inp !w-32" :disabled="disabled"><option v-for="k in constraints" :key="k.code" :value="k.code">{{ k.code }} {{ k.param }}</option></select>
            <select v-model="c.threshold.field" class="inp !w-24" :disabled="disabled"><option v-for="(t, k) in LIM" :key="k" :value="k">{{ t }}</option></select>
          </template>
        </template>
        <span class="text-fg-mute">持续</span><input v-model.number="c.durationSec" class="inp !w-16" :disabled="disabled" /><span class="text-fg-mute">秒</span>
        <span class="flex-1" /><button class="ctl !py-0 !px-1.5" :disabled="disabled" @click="rule.children.splice(i, 1)">×</button>
      </div>
    </template>
  </div>
</template>
