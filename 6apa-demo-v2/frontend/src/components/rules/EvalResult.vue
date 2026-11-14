<script setup lang="ts">
/** 判定规则试算结果：逐台设备的成立情况、成立时段、各条件曲线。数据为模拟数据。 */
import { ref } from 'vue'
import LineChart from '../LineChart.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ result: Any }>()
const openTarget = ref<string>(props.result?.results?.[0]?.targetId ?? '')
</script>

<template>
  <div v-if="result" class="space-y-3">
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <span class="sim-tag">{{ result.dataSource?.label }}</span>
      <span class="text-fg-mute">{{ result.window.start }} ～ {{ result.window.end }}（{{ result.window.hours }} 小时，{{ result.window.stepSec }} 秒一个点）</span>
      <span class="text-fg-mute">· {{ result.limitVersion }}</span>
    </div>
    <div class="text-xs bg-ink-panel2 rounded px-2 py-1.5 font-mono">{{ result.ruleText }}</div>
    <table class="tbl">
      <thead><tr><th>判定对象</th><th>当前</th><th>成立次数</th><th>累计时长</th><th>最近一次</th></tr></thead>
      <tbody>
        <template v-for="r in result.results" :key="r.targetId">
          <tr :class="{ 'bg-ink-panel2': openTarget === r.targetId }" @click="openTarget = openTarget === r.targetId ? '' : r.targetId">
            <td>{{ r.targetName }}<div v-if="r.overrideNote" class="text-[11px] text-warn">{{ r.overrideNote }}</div></td>
            <td><span v-if="r.disabled" class="pill pill-mute">已禁用</span>
              <span v-else class="pill" :class="r.current ? 'pill-err' : 'pill-ok'">{{ r.current ? '成立' : '不成立' }}</span></td>
            <td class="tabular-nums">{{ r.eventCount }}</td>
            <td class="tabular-nums">{{ r.totalMinutes }} 分钟</td>
            <td class="text-fg-dim">{{ r.events.length ? `${r.events[r.events.length - 1].start} 起 ${r.events[r.events.length - 1].minutes} 分钟` : '—' }}</td>
          </tr>
          <tr v-if="openTarget === r.targetId" class="!cursor-default hover:!bg-transparent">
            <td colspan="5" class="!p-3">
              <div v-for="(c, i) in r.conditions" :key="i" class="mb-3">
                <div class="flex items-center gap-2 text-xs mb-1">
                  <span class="pill" :class="c.status === '成立' ? 'pill-err' : c.status === '无法判定' ? 'pill-mute' : 'pill-ok'">{{ c.status }}</span>
                  <span class="font-mono">{{ c.text }}</span>
                  <span v-if="c.trueRatio !== undefined" class="text-fg-mute">成立占比 {{ (c.trueRatio * 100).toFixed(1) }}%</span>
                  <span v-if="c.reason" class="text-warn">{{ c.reason }}</span>
                  <span v-if="c.overridden" class="text-warn">{{ c.overridden }}</span>
                </div>
                <LineChart v-if="c.chart" :times="c.chart.times" :lines="c.chart.lines" :threshold="c.threshold" :height="150" />
              </div>
              <div v-if="r.events.length" class="text-xs text-fg-dim">
                成立时段：
                <span v-for="(e, i) in r.events" :key="i" class="pill pill-plain mr-1 mb-1">{{ e.start }} · {{ e.minutes }} 分钟{{ e.ongoing ? '（持续中）' : '' }}</span>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>
