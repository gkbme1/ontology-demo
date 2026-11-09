<script setup lang="ts">
/** 计算组态列表 + 试算曲线（模拟数据）。 */
import { ref, watch } from 'vue'
import { api } from '@/api/client'
import LineChart from './LineChart.vue'
import InheritBox from './InheritBox.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ items: Any[]; opId?: string; targetId?: string; focusId?: string; showInherit?: boolean }>()

const openId = ref(props.focusId ?? '')
const runs = ref<Record<string, Any>>({})

async function run(c: Any): Promise<void> {
  openId.value = c.id
  runs.value[c.id] = null
  runs.value[c.id] = await api.runCalc(c.id, { hours: 6, opId: props.opId, targetId: props.targetId })
}
watch(() => props.focusId, (id) => {
  const c = props.items.find((x) => x.id === id)
  if (c) run(c)
}, { immediate: true })

</script>

<template>
  <div class="space-y-3">
    <div v-if="!items.length" class="empty">暂无计算组态</div>
    <div v-for="c in items" :key="c.id" class="card">
      <div class="flex items-center gap-2">
        <span class="text-brand font-mono">ƒ</span>
        <span class="font-medium">{{ c.name }}</span>
        <span class="text-[11px] text-fg-mute">{{ c.id }} · {{ c.unit }}</span>
        <span class="pill pill-plain">{{ c.scopeText }}：{{ c.anchor?.name }}</span>
        <span v-if="c.crossDevice" class="pill pill-info">跨设备统计</span>
        <span v-if="showInherit" class="inline-flex items-center gap-1 text-[11px] text-fg-mute"><InheritBox :checked="c.inherited" :from="c.inheritedFrom" />继承</span>
        <span class="pill pill-warn">{{ c.status === '已确认' ? '已确认' : '草案' }}</span>
        <span class="flex-1" />
        <button class="btn" @click="run(c)">试算（模拟数据）</button>
      </div>
      <div class="mt-2 grid grid-cols-[1fr_1.4fr] gap-4">
        <dl class="kv">
          <dt>引用算法</dt>
          <dd>
            <span class="font-medium">{{ c.algorithm?.name }}</span>
            <span class="text-[11px] text-fg-mute font-mono ml-1">{{ c.algorithm?.id }} v{{ c.algorithm?.version }}</span>
            <div class="text-[11px] text-fg-mute font-mono">{{ c.algorithm?.invoke?.protocol }} {{ c.algorithm?.invoke?.method }} {{ c.algorithm?.invoke?.endpoint }}</div>
          </dd>
          <dt>输出</dt><dd>{{ c.algorithm?.output?.label }}（{{ c.unit || c.algorithm?.output?.unit }}）</dd>
          <dt>作用范围</dt><dd>{{ c.anchor?.name }}<span v-if="c.anchor?.kind === 'group' && c.bindingRows?.some((r: Any) => r.binding?.kind === 'parameter')" class="text-fg-mute">（组内每台分别计算）</span></dd>
          <dt>说明</dt><dd class="text-fg-dim">{{ c.description }}</dd>
          <dt>依据</dt><dd class="text-fg-dim">{{ c.basis }}</dd>
          <template v-if="c.usedBy?.length">
            <dt>被引用</dt><dd><span v-for="u in c.usedBy" :key="u.id" class="pill pill-plain mr-1">{{ u.name }}</span></dd>
          </template>
        </dl>
        <div>
          <div class="sec-title">参数绑定（算法参数 → 本体）</div>
          <table class="w-full text-xs border border-line-soft rounded">
            <thead><tr class="bg-ink-panel2 text-fg-mute">
              <th class="text-left px-2 py-1 font-medium">算法参数</th><th class="text-left px-2 py-1 font-medium">类型</th>
              <th class="text-left px-2 py-1 font-medium">绑定到</th>
            </tr></thead>
            <tbody>
              <tr v-for="r in c.bindingRows" :key="r.name" class="border-t border-line-soft">
                <td class="px-2 py-1"><span class="font-mono">{{ r.name }}</span> {{ r.label }}<span v-if="r.required" class="text-err">*</span></td>
                <td class="px-2 py-1 text-fg-dim">{{ r.type }}{{ r.unit ? ` · ${r.unit}` : '' }}</td>
                <td class="px-2 py-1" :class="r.binding ? 'text-fg' : 'text-fg-mute italic'">{{ r.bindingText }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div v-if="openId === c.id && runs[c.id] === null" class="text-fg-mute text-xs mt-2">计算中…</div>
      <div v-if="openId === c.id && runs[c.id]" class="mt-3">
        <div class="flex items-center gap-2 text-xs mb-1">
          <span class="sim-tag">{{ runs[c.id].dataSource.label }}</span>
          <span class="text-fg-mute">最近 6 小时</span>
        </div>
        <table class="tbl mb-2">
          <thead><tr><th>对象</th><th>当前</th><th>均值</th><th>最大</th><th>最小</th><th>输入测点</th></tr></thead>
          <tbody>
            <tr v-for="r in runs[c.id].results" :key="r.targetId" class="!cursor-default">
              <td>{{ r.targetName }}</td>
              <template v-if="r.values">
                <td class="tabular-nums">{{ r.current }}</td><td class="tabular-nums">{{ r.mean }}</td>
                <td class="tabular-nums">{{ r.max }}</td><td class="tabular-nums">{{ r.min }}</td>
              </template>
              <td v-else colspan="4" class="text-warn">输入未落到测点：{{ r.unresolved.join('、') }}</td>
              <td class="font-mono text-[11px] text-fg-mute">{{ r.inputs.map((i: Any) => `${i.var}:${i.tags.join(',')}`).join(' ') }}</td>
            </tr>
          </tbody>
        </table>
        <LineChart
          :times="runs[c.id].times"
          :lines="runs[c.id].results.filter((r: Any) => r.values).slice(0, 6).map((r: Any) => ({ name: r.targetName, values: r.values }))"
          :unit="runs[c.id].unit"
          :height="200"
        />
      </div>
    </div>
  </div>
</template>
