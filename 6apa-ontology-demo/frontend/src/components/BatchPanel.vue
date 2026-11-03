<script setup lang="ts">
/**
 * 「批次」页签：设备实例的运行上下文。
 * - 当前：所在罐批次、阶段（及对应的限值操作模式）、换酶后批次数、班次 —— /api/ontology/{id}/context
 * - 近期批次：每批各阶段的时间轴 —— /api/ontology/{id}/batches
 * - 化验结果（含人工录入）与操作记录 —— /lab-results、/operations（见 LabAndOperations）
 * - 阶段定义：工序与阶段表里登记的 EBR 阶段名与 DCS 识别条件（来自档案 process.stages）
 * 批次与排班由本体代调 EBR / MOM，组件不内置任何批号或时间。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import LabAndOperations from './LabAndOperations.vue'
import type { BatchesPayload, BatchRecord, ProcessInfo, RunContextPayload } from '@/api/types'

const props = defineProps<{ objectId: string; process: ProcessInfo }>()

const RANGES = [
  { label: '近 1 天', days: 1 },
  { label: '近 3 天', days: 3 },
  { label: '近 7 天', days: 7 }
] as const
const days = ref<number>(3)
const loading = ref(false)
const error = ref<string | null>(null)
const batches = ref<BatchesPayload | null>(null)
const ctx = ref<RunContextPayload | null>(null)
const ctxError = ref<string | null>(null)

const PHASE_COLOR: Record<string, string> = {
  进料: 'bg-info/70', 反应: 'bg-ok/75', 终点判定: 'bg-warn/75', 出料: 'bg-equip/75', 空闲: 'bg-line'
}
function phaseColor(name: string) {
  return PHASE_COLOR[name] ?? 'bg-part/60'
}

function fmt(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return ''
  const d = new Date(ms + 8 * 3600_000) // 东八区显示
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`
}
function minutes(a: number | null, b: number | null) {
  if (a === null || b === null) return null
  return Math.round((b - a) / 60_000)
}

async function load() {
  loading.value = true
  error.value = null
  ctxError.value = null
  const end = Date.now()
  try {
    batches.value = await api.batches(props.objectId, { startTime: end - days.value * 86_400_000, endTime: end, limit: 200 })
  } catch (e) {
    batches.value = null
    error.value = (e as Error).message
  }
  try {
    ctx.value = await api.runContext(props.objectId)
  } catch (e) {
    ctx.value = null
    ctxError.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

watch(() => [props.objectId, days.value], load, { immediate: true })

// 时间轴：所有批次画在同一时间轴上，按查询范围定比例
const span = computed(() => {
  const items = batches.value?.items ?? []
  if (!items.length) return null
  const now = Date.now()
  const start = Math.min(...items.map((b) => b.startTime))
  const end = Math.max(...items.map((b) => b.endTime ?? now))
  return { start, end, now }
})
function segStyle(start: number, end: number | null) {
  const s = span.value!
  const e = end ?? s.now
  const total = Math.max(1, s.end - s.start)
  return { left: `${((start - s.start) / total) * 100}%`, width: `${Math.max(0.3, ((e - start) / total) * 100)}%` }
}
const rows = computed<BatchRecord[]>(() => [...(batches.value?.items ?? [])].reverse())
const legend = computed(() => props.process.stages.map((s) => s.ebrPhase || s.name))
const stats = computed(() => {
  const items = batches.value?.items ?? []
  const durations = items.map((b) => minutes(b.reactionStart, b.reactionEnd)).filter((x): x is number => x !== null)
  const counts = items.map((b) => b.enzymeBatchCount).filter((x): x is number => typeof x === 'number')
  return {
    total: items.length,
    done: items.filter((b) => b.status === '已完成').length,
    reaction: durations.length ? `${Math.min(...durations)}~${Math.max(...durations)} 分钟` : '—',
    enzyme: counts.length ? `${Math.min(...counts)}~${Math.max(...counts)}` : '—'
  }
})
</script>

<template>
  <div class="p-4 space-y-4 text-[12.5px]">
    <!-- 当前运行上下文 -->
    <div class="grid gap-3 md:grid-cols-4">
      <div class="rounded border border-line-soft bg-ink-panel2/60 px-3 py-2">
        <div class="text-fg-mute text-[11px]">当前批次</div>
        <div v-if="ctx?.batch" class="font-mono text-fg text-[14px]">{{ ctx.batch.batchNo }}</div>
        <div v-else class="text-fg-dim">{{ ctx?.notice ?? (ctxError ? '取不到' : '—') }}</div>
        <div v-if="ctx?.batch" class="text-fg-mute text-[11px]">{{ ctx.batch.status }} · {{ fmt(ctx.batch.startTime) }} 开始</div>
      </div>
      <div class="rounded border border-line-soft bg-ink-panel2/60 px-3 py-2">
        <div class="text-fg-mute text-[11px]">当前阶段</div>
        <div class="text-fg text-[14px]">{{ ctx?.phase?.phase ?? '—' }}</div>
        <div v-if="ctx?.phase" class="text-fg-mute text-[11px]">
          {{ fmt(ctx.phase.startTime) }} 起<template v-if="ctx.phase.limitMode"> · 限值按「{{ ctx.phase.limitMode }}」</template>
        </div>
      </div>
      <div class="rounded border border-line-soft bg-ink-panel2/60 px-3 py-2">
        <div class="text-fg-mute text-[11px]">换酶后批次数</div>
        <div class="text-fg text-[14px]">
          <template v-if="ctx?.batch?.enzymeBatchCount">第 {{ ctx.batch.enzymeBatchCount }} 批</template><template v-else>—</template>
        </div>
        <div v-if="ctx?.batch?.enzymeLot" class="text-fg-mute text-[11px]">酶批号 {{ ctx.batch.enzymeLot }}</div>
      </div>
      <div class="rounded border border-line-soft bg-ink-panel2/60 px-3 py-2">
        <div class="text-fg-mute text-[11px]">班次（MOM）</div>
        <div class="text-fg text-[14px]">{{ ctx?.shift ? `${ctx.shift.shift} · ${ctx.shift.team}` : '—' }}</div>
        <div v-if="ctx?.shift" class="text-fg-mute text-[11px]">{{ ctx.shift.date }} {{ fmt(ctx.shift.startTime).slice(6) }}–{{ fmt(ctx.shift.endTime).slice(6) }}</div>
      </div>
    </div>
    <div v-if="ctxError" class="text-err text-[11.5px]">运行上下文：{{ ctxError }}</div>

    <!-- 近期批次 -->
    <div>
      <div class="flex flex-wrap items-center gap-2 mb-2">
        <span class="text-fg font-semibold">近期批次</span>
        <span class="text-fg-mute text-[11px]">
          {{ stats.total }} 批（已完成 {{ stats.done }}）· 反应时长 {{ stats.reaction }} · 换酶后批次数 {{ stats.enzyme }}
        </span>
        <span class="ml-auto flex gap-1">
          <button v-for="r in RANGES" :key="r.days" class="ctl" :class="days === r.days ? 'border-brand text-fg' : ''" @click="days = r.days">{{ r.label }}</button>
        </span>
      </div>
      <div v-if="batches?.dataSource" class="text-[11px] text-fg-mute mb-2">
        来源 {{ batches.dataSource.sourceTypeLabel }}（{{ batches.dataSource.endpoint }}）
        <span v-if="batches.dataSource.simulated" class="pill pill-warn !text-[10px] ml-1">模拟</span>
        <span v-if="batches.dataSource.notice" class="ml-1">{{ batches.dataSource.notice }}</span>
      </div>
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="error" class="empty text-err">{{ error }}</div>
      <div v-else-if="!rows.length" class="empty">查询范围内没有批次</div>
      <template v-else>
        <div class="flex flex-wrap gap-3 mb-2 text-[11px] text-fg-dim">
          <span v-for="name in legend" :key="name" class="flex items-center gap-1"><i class="inline-block w-3 h-2 rounded-sm" :class="phaseColor(name)" />{{ name }}</span>
        </div>
        <table class="tbl">
          <thead>
            <tr>
              <th class="w-[110px]">批号</th>
              <th class="w-[64px]">状态</th>
              <th class="w-[96px]">换酶后</th>
              <th class="w-[170px]">反应</th>
              <th>阶段时间轴<span v-if="span" class="ml-2 font-mono font-normal text-fg-mute text-[10.5px]">{{ fmt(span.start) }} → {{ fmt(span.end) }}</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in rows" :key="b.batchNo">
              <td class="font-mono text-equip">{{ b.batchNo }}</td>
              <td><span class="pill !text-[10px]" :class="b.status === '进行中' ? 'pill-info' : 'pill-plain'">{{ b.status }}</span></td>
              <td class="text-fg-dim">{{ b.enzymeBatchCount ? `第 ${b.enzymeBatchCount} 批` : '—' }}</td>
              <td class="text-fg-dim font-mono text-[11px] whitespace-nowrap">
                <template v-if="b.reactionStart">{{ fmt(b.reactionStart) }} · {{ minutes(b.reactionStart, b.reactionEnd) ?? '进行中' }}<template v-if="b.reactionEnd"> 分</template></template>
                <template v-else>—</template>
              </td>
              <td>
                <div class="relative h-4 rounded bg-ink/60">
                  <div
                    v-for="p in b.phases" :key="p.phase + p.startTime"
                    class="absolute top-0 h-4 rounded-sm" :class="phaseColor(p.phase)" :style="segStyle(p.startTime, p.endTime)"
                    :title="`${p.phase} ${p.startText} ~ ${p.endText ?? '进行中'}${p.limitMode ? '（限值：' + p.limitMode + '）' : ''}`"
                  />
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>

    <!-- 化验与操作记录 -->
    <LabAndOperations :object-id="objectId" :days="days" />

    <!-- 阶段定义 -->
    <div>
      <div class="text-fg font-semibold mb-1">工艺阶段定义<span class="ml-2 text-fg-mute text-[11px] font-normal">
        {{ process.step ? `工序 ${process.step.id} ${process.step.name}（${process.step.role}）· ` : '' }}阶段识别：EBR 阶段名优先，EBR 取不到时按 DCS 条件推断（{x} 为罐号）</span></div>
      <table class="tbl">
        <thead>
          <tr><th class="w-[60px]">编号</th><th class="w-[96px]">阶段</th><th>DCS 识别条件</th><th class="w-[110px]">对应限值模式</th><th>说明</th><th class="w-[110px]">状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in process.stages" :key="s.id">
            <td class="font-mono text-fg-mute">{{ s.id }}</td>
            <td class="whitespace-nowrap"><i class="inline-block w-2 h-2 rounded-sm mr-1" :class="phaseColor(s.ebrPhase || s.name)" />{{ s.name }}</td>
            <td class="font-mono text-[11px] text-info">{{ s.dcsCondition || '—' }}</td>
            <td class="text-fg-dim">{{ s.limitMode || '—' }}</td>
            <td class="text-fg-dim">{{ s.description }}</td>
            <td><span class="pill pill-plain !text-[10px]">{{ s.status }}</span></td>
          </tr>
        </tbody>
      </table>
      <div v-if="process.contexts.length" class="mt-2 text-[11px] text-fg-mute space-y-0.5">
        <div v-for="c in process.contexts" :key="c.type">
          <span class="text-fg-dim">{{ c.type }}</span> ← {{ c.system }}（{{ c.capabilityId }}）：{{ c.fields }}。{{ c.description }}
        </div>
      </div>
    </div>
  </div>
</template>
