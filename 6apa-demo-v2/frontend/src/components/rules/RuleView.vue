<script setup lang="ts">
/** 判定规则只读展示：条件组画成带「且 / 或」标识的框，可任意嵌套。 */
import { conditionText } from './ruleText'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
defineProps<{ rule: Any; calcNames?: Record<string, string> }>()
</script>

<template>
  <div v-if="!rule" class="text-fg-mute italic text-xs">判定规则待定义</div>
  <div v-else-if="rule.type === 'group'" class="border-l-2 pl-2 py-0.5 space-y-1" :class="rule.op === 'AND' ? 'border-info/70' : 'border-warn/70'">
    <div class="text-[10.5px] font-semibold" :class="rule.op === 'AND' ? 'text-info' : 'text-warn'">
      {{ rule.op === 'AND' ? '同时满足（与）' : '满足任一（或）' }}
    </div>
    <RuleView v-for="(c, i) in rule.children" :key="i" :rule="c" :calc-names="calcNames" />
  </div>
  <div v-else class="text-xs font-mono text-fg bg-ink-panel2 rounded px-2 py-1 border border-line-soft">
    {{ conditionText(rule, calcNames) }}
  </div>
</template>
