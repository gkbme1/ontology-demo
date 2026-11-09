<script setup lang="ts">
/**
 * 装置 / 单元 / 画面 概览。
 * 装置：单元卡片（双击进入单元）；单元：画面卡片（单击选中，双击或「进入」打开图纸）；
 * 画面：概要 + 4 个节点入口 + 「进入图纸」。
 */
import { ref, watch } from 'vue'
import { api } from '@/api/client'
import { enterSegment, nav, openDrawing, select } from '@/composables/useNav'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ kind: 'workshop' | 'segment' | 'op'; id?: string }>()

const space = ref<Any>(null)
const seg = ref<Any>(null)
const op = ref<Any>(null)
const picked = ref('')

async function load(): Promise<void> {
  if (props.kind === 'workshop') space.value = await api.navSpace()
  if (props.kind === 'segment' && props.id) seg.value = await api.segment(props.id)
  if (props.kind === 'op' && props.id) op.value = await api.op(props.id)
}
watch(() => [props.kind, props.id, nav.version], load, { immediate: true })

function enterOp(o: Any): void {
  if (nav.mode !== 'segment') enterSegment(o.segmentId, { type: 'drawing', id: o.id, opId: o.id })
  else openDrawing(o.id)
}
const SECTIONS = [
  { key: 'section:devices', label: '设备', hint: '设备组与设备', count: 'equipmentCount' },
  { key: 'global:calc', label: '计算组态 ↗', hint: '全局视图，已筛选到本画面', count: 'calcCount' },
  { key: 'global:cond', label: '工况与根因 ↗', hint: '全局视图，已筛选到本画面', count: 'phenomenonCount' },
  { key: 'global:docs', label: '文档提取 ↗', hint: '全局视图，已筛选到本画面', count: '' }
]
</script>

<template>
  <div class="p-6 space-y-5 overflow-auto h-full">
    <!-- 装置 -->
    <template v-if="kind === 'workshop' && space">
      <div v-for="ws in space.items" :key="ws.id">
        <h2 class="text-[20px] font-semibold">{{ ws.label }}</h2>
        <p class="text-fg-dim mt-1">{{ ws.description }}</p>
        <div class="grid grid-cols-3 gap-3 mt-4">
          <div v-for="s in ws.children.filter((c: Any) => c.kind === 'segment')" :key="s.id" class="card cursor-pointer hover:border-brand"
               @click="select({ type: 'segment', id: s.id }, s.id)" @dblclick="enterSegment(s.id)">
            <div class="flex items-center gap-2"><span class="font-semibold text-[15px]">{{ s.label }}</span><span class="text-fg-mute text-xs">{{ s.count }} 道画面</span></div>
            <p class="text-xs text-fg-dim mt-1">{{ s.description }}</p>
            <button class="btn mt-3" @click.stop="enterSegment(s.id)">进入单元 →</button>
          </div>
        </div>
      </div>
      <div v-if="space.notIncluded?.length" class="card">
        <div class="sec-title">未纳入导航树的工段（原 Demo 点表中存在）</div>
        <div class="flex flex-wrap gap-1.5">
          <span v-for="n in space.notIncluded" :key="n['工段编号']" class="pill pill-mute" :title="n['原因']">{{ n['工段编号'] }} {{ n['工段名称'] }}</span>
        </div>
      </div>
    </template>

    <!-- 单元 -->
    <template v-if="kind === 'segment' && seg">
      <div class="flex items-center gap-3">
        <h2 class="text-[20px] font-semibold">{{ seg.name }}</h2>
        <button v-if="nav.mode === 'root'" class="btn" @click="enterSegment(seg.id)">进入单元 →</button>
      </div>
      <p class="text-fg-dim">{{ seg.description }}</p>
      <div class="text-xs text-fg-mute">每道画面对应一张流程画面（P&ID）。单击选中画面，双击或点「进入」打开图纸。</div>
      <div class="grid grid-cols-2 gap-3">
        <div v-for="o in seg.ops" :key="o.id" class="card cursor-pointer"
             :class="picked === o.id ? 'border-brand' : 'hover:border-line'"
             @click="picked = o.id" @dblclick="enterOp(o)">
          <div class="flex items-center gap-2">
            <span class="font-semibold text-[15px]">{{ o.name }}</span>
            <span class="text-xs text-fg-mute">画面 {{ o.screen }} · 工段 {{ o.areaCodes.join(',') }}</span>
            <span v-if="o.status !== '已确认'" class="pill pill-warn">{{ o.status }}</span>
            <span class="flex-1" />
            <button class="btn btn-primary" @click.stop="enterOp(o)">进入</button>
          </div>
          <div class="text-xs text-fg-dim mt-2">子流程：{{ o.subSteps.join(' → ') }}</div>
          <div class="flex gap-4 mt-2 text-xs text-fg-mute">
            <span>设备组 {{ o.groupCount }}</span><span>设备 {{ o.equipmentCount }}</span>
            <span>现象 {{ o.phenomenonCount }}</span><span>计算组态 {{ o.calcCount }}</span>
          </div>
          <div v-if="o.note" class="text-[11px] text-warn mt-1">{{ o.note }}</div>
        </div>
      </div>
    </template>

    <!-- 画面 -->
    <template v-if="kind === 'op' && op">
      <div class="text-[11px] text-fg-mute"><span v-for="(p, i) in op.path" :key="p.id">{{ p.name }}<span v-if="i < op.path.length - 1"> › </span></span></div>
      <div class="flex items-center gap-3">
        <h2 class="text-[20px] font-semibold">{{ op.name }}</h2>
        <span class="text-xs text-fg-mute">流程画面 {{ op.screen }} · 工段 {{ op.areaCodes.join(',') }}</span>
        <span v-if="op.status !== '已确认'" class="pill pill-warn">{{ op.status }}</span>
        <span class="flex-1" />
        <button class="btn btn-primary" @click="openDrawing(op.id)">进入图纸</button>
      </div>
      <div class="text-xs text-fg-dim">子流程（写在图纸上）：{{ op.subSteps.join(' → ') }}</div>
      <div v-if="op.note" class="text-xs text-warn">{{ op.note }}</div>
      <div class="grid grid-cols-4 gap-3">
        <div v-for="s in SECTIONS" :key="s.key" class="card cursor-pointer hover:border-brand" @click="select({ type: s.key as Any, id: op.id, opId: op.id }, `${op.id}|${s.key.split(':')[1]}`)">
          <div class="font-semibold">{{ s.label }}</div>
          <div class="text-xs text-fg-mute">{{ s.hint }}</div>
          <div v-if="s.count" class="text-[22px] font-semibold mt-1 tabular-nums">{{ op[s.count] }}</div>
        </div>
      </div>
    </template>
  </div>
</template>
