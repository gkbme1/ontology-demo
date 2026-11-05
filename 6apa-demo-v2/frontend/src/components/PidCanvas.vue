<script setup lang="ts">
/**
 * 工序图纸（示意）：设备组为框、成员为框内设备块，按拓扑分层从左到右排布；
 * 左侧为进入本工序的物料 / 公用介质，右侧为产出；顶部写子工序。
 * 单击设备块 / 设备组标题 → pick；highlight 中的对象高亮。
 */
import { computed } from 'vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

const props = defineProps<{ drawing: Any; highlight?: string[]; compact?: boolean }>()
const emit = defineEmits<{ (e: 'pick', id: string, kind: 'group' | 'equipment'): void }>()

const NODE_W = 230
const COL_GAP = 90
const STREAM_W = 150
const HEAD_H = 30
const CHIP_H = 22
const CHIP_COLS = 2
const MAX_CHIPS = 14
const TOP = 70

const hl = computed(() => new Set(props.highlight ?? []))

const layout = computed(() => {
  const d = props.drawing
  if (!d) return null
  const nodes = d.nodes.map((n: Any) => {
    const shown = n.members.slice(0, MAX_CHIPS)
    const rows = Math.max(1, Math.ceil(shown.length / CHIP_COLS)) + (n.members.length > MAX_CHIPS ? 1 : 0)
    return { ...n, shown, more: n.members.length - shown.length, h: HEAD_H + rows * CHIP_H + 10 }
  })
  const left = d.inlets.length ? STREAM_W + 40 : 20
  const yByLayer: Record<number, number> = {}
  const sorted = [...nodes].sort((a, b) => a.layer - b.layer || a.row - b.row)
  for (const n of sorted) {
    const y0 = yByLayer[n.layer] ?? TOP
    n.x = left + n.layer * (NODE_W + COL_GAP)
    n.y = y0
    yByLayer[n.layer] = y0 + n.h + 26
  }
  const byId: Record<string, Any> = Object.fromEntries(nodes.map((n: Any) => [n.id, n]))
  const maxLayer = Math.max(0, ...nodes.map((n: Any) => n.layer))
  const right = left + (maxLayer + 1) * (NODE_W + COL_GAP) - COL_GAP
  const heightNodes = Math.max(TOP + 40, ...Object.values(yByLayer))
  const inlets = d.inlets.map((s: Any, i: number) => ({ ...s, x: 16, y: TOP + i * 34 }))
  const outlets = d.outlets.map((s: Any, i: number) => ({ ...s, x: right + 40, y: TOP + i * 34 }))
  const height = Math.max(heightNodes, TOP + inlets.length * 34 + 20, TOP + outlets.length * 34 + 20) + 10
  const width = right + (outlets.length ? STREAM_W + 60 : 30)

  const edges = d.edges
    .filter((e: Any) => byId[e.from] && byId[e.to])
    .map((e: Any) => {
      const a = byId[e.from]
      const b = byId[e.to]
      if (b.layer > a.layer) {
        const x1 = a.x + NODE_W, y1 = a.y + HEAD_H / 2, x2 = b.x, y2 = b.y + HEAD_H / 2
        const mx = (x1 + x2) / 2
        return { ...e, d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, back: false }
      }
      // 同层或回流：从下方绕
      const x1 = a.x + NODE_W / 2, y1 = a.y + a.h, x2 = b.x + NODE_W / 2, y2 = b.y + b.h
      const low = Math.max(y1, y2) + 24
      return { ...e, d: `M${x1},${y1} C${x1},${low} ${x2},${low} ${x2},${y2}`, back: true }
    })
  const streamLinks: Any[] = []
  for (const s of inlets) {
    for (const t of s.to) {
      const b = byId[t]
      if (b) streamLinks.push({ d: `M${s.x + STREAM_W},${s.y + 11} C${b.x - 30},${s.y + 11} ${b.x - 30},${b.y + HEAD_H / 2} ${b.x},${b.y + HEAD_H / 2}`, kind: s.type })
    }
  }
  for (const s of outlets) {
    for (const f of s.from) {
      const a = byId[f]
      if (a) streamLinks.push({ d: `M${a.x + NODE_W},${a.y + HEAD_H / 2 + 6} C${s.x - 20},${a.y + HEAD_H / 2 + 6} ${s.x - 20},${s.y + 11} ${s.x},${s.y + 11}`, kind: s.type })
    }
  }
  return { nodes, edges, inlets, outlets, streamLinks, width, height }
})

function chipX(i: number): number {
  return 8 + (i % CHIP_COLS) * ((NODE_W - 16) / CHIP_COLS)
}
function chipY(i: number): number {
  return HEAD_H + 4 + Math.floor(i / CHIP_COLS) * CHIP_H
}
function short(s: string, n = 13): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s
}
</script>

<template>
  <div v-if="layout" class="overflow-auto rounded-[10px] border border-line bg-[#fbfcfe]">
    <svg :width="layout.width" :height="layout.height" class="block select-none" style="font-family: inherit">
      <defs>
        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#8197b3" />
        </marker>
        <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">
          <path d="M24 0 L0 0 0 24" fill="none" stroke="#edf1f6" stroke-width="1" />
        </pattern>
      </defs>
      <rect x="0" y="0" :width="layout.width" :height="layout.height" fill="url(#grid)" />
      <!-- 标题与子工序 -->
      <text x="16" y="24" fill="#1f2937" font-size="14" font-weight="600">{{ drawing.name }}</text>
      <text x="16" y="24" :dx="drawing.name.length * 14 + 12" fill="#7b8798" font-size="11">流程画面：{{ drawing.screen }}</text>
      <g v-if="drawing.subSteps?.length">
        <text x="16" y="46" fill="#7b8798" font-size="11">子工序</text>
        <g v-for="(s, i) in drawing.subSteps" :key="s">
          <rect :x="60 + i * 112" y="34" width="104" height="18" rx="9" fill="#eef3f8" stroke="#c9d4e0" />
          <text :x="112 + i * 112" y="47" fill="#4b5563" font-size="10.5" text-anchor="middle">{{ short(s, 9) }}</text>
          <text v-if="i < drawing.subSteps.length - 1" :x="166 + i * 112" y="47" fill="#0e8fa3" font-size="10" text-anchor="middle">›</text>
        </g>
      </g>

      <!-- 物料进出 -->
      <path v-for="(l, i) in layout.streamLinks" :key="`sl${i}`" :d="l.d" fill="none" stroke="#a9b8cb" stroke-dasharray="4 3" stroke-width="1.2" marker-end="url(#arr)" />
      <g v-for="s in layout.inlets" :key="`in${s.name}`">
        <rect :x="s.x" :y="s.y" :width="STREAM_W" height="22" rx="4" :fill="s.type === '公用介质' ? '#ecfdf5' : '#eef2ff'" :stroke="s.type === '公用介质' ? '#6ee7b7' : '#a5b4fc'" />
        <text :x="s.x + 8" :y="s.y + 15" font-size="11" :fill="s.type === '公用介质' ? '#047857' : '#334155'">{{ short(s.name, 12) }}<title>{{ s.type }}：{{ s.name }}</title></text>
      </g>
      <g v-for="s in layout.outlets" :key="`out${s.name}`">
        <rect :x="s.x" :y="s.y" :width="STREAM_W" height="22" rx="4" fill="#fff7ed" stroke="#fdba74" />
        <text :x="s.x + 8" :y="s.y + 15" font-size="11" fill="#c2410c">{{ short(s.name, 12) }}<title>{{ s.type }}：{{ s.name }}</title></text>
      </g>

      <!-- 设备组间连线 -->
      <path v-for="(e, i) in layout.edges" :key="`e${i}`" :d="e.d" fill="none" :stroke="e.back ? '#9b7bc4' : '#8197b3'" stroke-width="1.6" marker-end="url(#arr)">
        <title>{{ e.predicate }}：{{ e.label }}</title>
      </path>

      <!-- 设备组 -->
      <g v-for="n in layout.nodes" :key="n.id" :transform="`translate(${n.x},${n.y})`">
        <rect :width="NODE_W" :height="n.h" rx="8"
              :fill="hl.has(n.id) ? '#dff3f6' : '#ffffff'"
              :stroke="hl.has(n.id) ? '#0e8fa3' : n.kind === 'ungrouped' ? '#b6c2d1' : '#9fb3c8'"
              :stroke-dasharray="n.kind === 'ungrouped' ? '5 3' : ''" :stroke-width="hl.has(n.id) ? 2 : 1" />
        <g class="cursor-pointer" @click="n.kind === 'group' && emit('pick', n.id, 'group')">
          <rect :width="NODE_W" :height="HEAD_H" rx="8" fill="transparent" />
          <text x="10" y="19" font-size="12" font-weight="600" :fill="n.kind === 'ungrouped' ? '#4b5563' : '#1f2937'">{{ short(n.name, 16) }}<title>{{ n.name }}{{ n.type ? `（${n.type}）` : '' }}</title></text>
          <text :x="NODE_W - 10" y="19" font-size="10.5" fill="#7b8798" text-anchor="end">{{ n.members.length }} 台</text>
        </g>
        <g v-for="(m, i) in n.shown" :key="m.id" class="cursor-pointer" @click="emit('pick', m.id, 'equipment')">
          <rect :x="chipX(i)" :y="chipY(i)" :width="(NODE_W - 16) / CHIP_COLS - 6" :height="CHIP_H - 4" rx="4"
                :fill="hl.has(m.id) ? '#0e8fa3' : '#eef3f8'" :stroke="hl.has(m.id) ? '#0e8fa3' : '#c9d4e0'" />
          <text :x="chipX(i) + 6" :y="chipY(i) + 13" font-size="10.5" :fill="hl.has(m.id) ? '#ffffff' : '#334155'">{{ short(m.name, 9) }}<title>{{ m.name }} · {{ m.tagCount }} 个测点</title></text>
        </g>
        <text v-if="n.more > 0" x="10" :y="n.h - 10" font-size="10.5" fill="#7b8798">另有 {{ n.more }} 台（见左侧树）</text>
      </g>
    </svg>
  </div>
</template>
