<script setup lang="ts">
/**
 * 工序图纸：有现场图纸（P&ID 截图 + 热区）时默认显示原图，可切换到本体示意图。
 * 图上对象单击 → 显示摘要（类型、所属类、测点数、现象数），双击 → pick 打开对象本体详情；
 * highlight 中的对象（或其所属设备组）高亮。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import PidCanvas from './PidCanvas.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ drawing: Any; highlight?: string[]; caption?: string; alarms?: Record<string, Any> }>()
// 运行态：热区按对象（或所属设备组）的异常现象着色
function alarmOf(h: Any): Any { return props.alarms?.[h.objectId]?.active?.length ? props.alarms[h.objectId] : null }
const alarmCount = computed(() => props.alarms ? Object.keys(props.alarms).filter((k) => props.alarms![k].active?.length && k.startsWith('equip-')).length : 0)
const emit = defineEmits<{ (e: 'pick', id: string, kind: 'group' | 'equipment', opId?: string): void }>()

const mode = ref<'image' | 'schematic'>(props.drawing?.image ? 'image' : 'schematic')
watch(() => props.drawing?.opId, () => { mode.value = props.drawing?.image ? 'image' : 'schematic' })
const showSpots = ref(true)
const zoom = ref(1)
const hover = ref<Any>(null)

const img = computed(() => props.drawing?.image)
const hl = computed(() => new Set(props.highlight ?? []))
// 高亮规则：选中设备 → 只亮该设备；选中设备组 → 亮组内全部成员
function lit(h: Any): boolean {
  const first = props.highlight?.[0]
  if (!first) return false
  if (first.startsWith('egrp-')) return h.groupId === first || h.objectId === first
  return h.objectId === first
}
function pick(h: Any): void {
  if (h.objectId) emit('pick', h.objectId, h.kind, h.opId)
}

// 单击摘要
const summary = ref<Any>(null)
let seq = 0
async function choose(id: string, kind: 'group' | 'equipment', opId?: string, note?: string): Promise<void> {
  const my = ++seq
  summary.value = { id, kind, opId, note, loading: true }
  try {
    const h = await api.object(id, opId ?? props.drawing?.opId)
    if (my === seq) summary.value = { id, kind, opId, note, head: h }
  } catch (e) {
    if (my === seq) summary.value = { id, kind, opId, note, error: String((e as Error).message) }
  }
}
function chooseSpot(h: Any): void {
  if (h.objectId) choose(h.objectId, h.kind, h.opId, h.note)
  else summary.value = { name: h.name, note: h.note, unresolved: true }
}
function openSummary(): void {
  const s = summary.value
  if (s?.id) emit('pick', s.id, s.kind, s.opId)
}
watch(() => props.drawing?.opId, () => { summary.value = null })
const TAB_NAMES: Record<string, string> = { phenomena: '现象', calc: '计算组态', procedures: '处置规程', causal: '根因', constraints: '约束' }
</script>

<template>
  <div class="space-y-2">
    <div class="flex items-center gap-2 text-xs flex-wrap">
      <span v-if="caption" class="font-medium text-fg-dim mr-1">{{ caption }}</span>
      <template v-if="img">
        <button class="ctl !py-0.5" :class="{ 'ctl-on': mode === 'image' }" @click="mode = 'image'">现场图纸</button>
        <button class="ctl !py-0.5" :class="{ 'ctl-on': mode === 'schematic' }" @click="mode = 'schematic'">本体示意图</button>
      </template>
      <template v-if="mode === 'image' && img">
        <label class="flex items-center gap-1 text-fg-dim ml-1"><input v-model="showSpots" type="checkbox" /> 热区</label>
        <button class="ctl !px-2 !py-0.5 ml-1" title="缩小" @click="zoom = Math.max(0.5, +(zoom - 0.25).toFixed(2))">−</button>
        <span class="tabular-nums w-9 text-center">{{ Math.round(zoom * 100) }}%</span>
        <button class="ctl !px-2 !py-0.5" title="放大" @click="zoom = Math.min(3, +(zoom + 0.25).toFixed(2))">＋</button>
        <span class="flex-1" />
        <span class="text-fg-mute whitespace-nowrap" :title="img.source">
          <span class="inline-block w-2.5 h-2.5 border-2 border-[#ca8a04] align-middle" /> 已对应
          <span class="inline-block w-2.5 h-2.5 border-2 border-dashed border-[#a855f7] align-middle ml-2" /> 待确认
        </span>
      </template>
      <span v-else class="text-fg-mute">{{ img ? '' : '本工序暂无现场图纸，显示本体示意图' }}</span>
      <span v-if="alarms" class="pill" :class="alarmCount ? 'pill-err' : 'pill-ok'" title="运行态：按现象当前状态着色（模拟数据）；红 = 严重，橙 = 警告">
        ● {{ alarmCount ? `${alarmCount} 台设备有异常现象` : '无异常现象' }}</span>
    </div>

    <!-- 单击摘要：双击图上对象或点「打开本体详情」进入对象本体详情 -->
    <div class="flex items-center gap-2 text-xs rounded-md border px-3 py-1.5 min-h-[34px]"
         :class="summary ? 'border-brand/40 bg-[#ecf8fa]' : 'border-line-soft bg-ink-panel text-fg-mute'">
      <template v-if="!summary">单击图上的设备 / 设备组查看摘要，双击打开对象本体详情</template>
      <template v-else-if="summary.unresolved">
        <span class="font-medium">{{ summary.name }}</span><span class="text-err">未对应到本体对象</span><span class="text-fg-mute truncate">{{ summary.note }}</span>
      </template>
      <template v-else>
        <span class="font-semibold text-fg">{{ summary.head?.name ?? '…' }}</span>
        <span class="pill pill-info">{{ summary.kind === 'group' ? '设备组' : '设备' }}</span>
        <span v-if="summary.head?.className" class="pill pill-plain">{{ summary.head.className }}</span>
        <span v-if="summary.head" class="text-fg-dim truncate" :title="summary.head.badges.join(' · ')">{{ summary.head.badges.join(' · ') }}</span>
        <template v-if="summary.head">
          <span v-for="k in ['phenomena', 'calc', 'procedures']" :key="k" v-show="summary.head.counts?.[k]" class="text-fg-mute whitespace-nowrap">{{ TAB_NAMES[k] }} {{ summary.head.counts[k] }}</span>
        </template>
        <span v-if="summary.error" class="text-err">{{ summary.error }}</span>
        <span class="flex-1" />
        <button class="btn btn-primary !py-0.5" @click="openSummary">打开本体详情</button>
        <button class="ctl !py-0.5 !px-2" title="关闭摘要" @click="summary = null">×</button>
      </template>
    </div>

    <div v-if="mode === 'image' && img" class="relative overflow-auto rounded-[10px] border border-line bg-black max-h-[calc(100vh-170px)]">
      <div class="relative" :style="{ width: `${zoom * 100}%`, minWidth: '900px' }">
        <img :src="img.url" class="block w-full select-none" draggable="false" />
        <svg class="absolute inset-0 w-full h-full" :viewBox="`0 0 ${img.width} ${img.height}`" preserveAspectRatio="none">
          <g v-for="(h, i) in img.hotspots" :key="i" class="cursor-pointer" @click="chooseSpot(h)" @dblclick="pick(h)" @mouseenter="hover = h" @mouseleave="hover = null">
            <rect :x="h.x" :y="h.y" :width="h.w" :height="h.h" rx="4"
                  :fill="alarmOf(h) ? 'rgba(239,68,68,0.28)' : lit(h) ? 'rgba(53,196,215,0.35)' : hover === h ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0)'"
                  :stroke="alarmOf(h) ? (alarmOf(h).severity === '严重' ? '#ef4444' : '#f97316') : lit(h) ? '#35c4d7' : showSpots || hover === h ? (h.confirmed ? '#f2c744' : '#d17bff') : 'transparent'"
                  :stroke-width="alarmOf(h) || lit(h) ? 4 : 2" :stroke-dasharray="h.confirmed || alarmOf(h) ? '' : '6 4'" />
            <title>{{ h.name }}{{ h.otherOp ? '（属于其他工序）' : '' }}：{{ h.note }}{{ alarmOf(h) ? '\n异常现象：' + alarmOf(h).active.join('、') : '' }}</title>
          </g>
        </svg>
      </div>
      <div v-if="hover" class="sticky bottom-0 left-0 bg-ink-panel2/95 border-t border-line px-3 py-1.5 text-xs">
        <span class="font-medium">{{ hover.name }}</span>
        <span v-if="!hover.objectId" class="text-err ml-2">未对应到本体对象</span>
        <span v-else-if="hover.otherOp" class="text-info ml-2">点表归属其他工序</span>
        <span class="text-fg-mute ml-2">{{ hover.note }}</span>
      </div>
    </div>
    <div v-if="mode === 'image' && img?.unresolved?.length" class="text-xs text-err">未对应到本体的热区：{{ img.unresolved.join('、') }}</div>

    <PidCanvas v-if="mode === 'schematic'" :drawing="drawing" :highlight="highlight" :alarms="alarms"
               @select="(id: string, k: 'group' | 'equipment') => choose(id, k)"
               @pick="(id: string, k: 'group' | 'equipment') => emit('pick', id, k)" />
  </div>
</template>
