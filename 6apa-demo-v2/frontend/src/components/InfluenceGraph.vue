<script setup lang="ts">
/**
 * 工艺影响关系图谱：节点 = 工艺属性，边 = 影响方 → 被影响方。
 * 按影响关系分层（左 → 右），同层按上一层重心排序；正向影响绿色、负向影响橙色、其他灰色。
 * 本对象的参数（蓝框）与其他对象的参数区分；悬停高亮相邻关系。
 */
import { computed, ref } from 'vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ items: Any[]; own?: string[]; height?: string }>()

const NODE_W = 170
const NODE_H = 30
const COL_W = 250
const ROW_H = 42
const PAD = 20
const TOP = 30
const EDGE: Record<string, string> = { 正向影响: '#16a34a', 负向影响: '#ea7a1a' }
const SIGN: Record<string, string> = { 正向影响: '+', 负向影响: '−' }
const hover = ref('')

const layout = computed(() => {
  const own = new Set(props.own ?? [])
  const names = new Set<string>()
  for (const r of props.items) { names.add(r.from); names.add(r.to) }
  const incoming: Record<string, string[]> = {}
  for (const r of props.items) (incoming[r.to] ??= []).push(r.from)
  const memo: Record<string, number> = {}
  const visiting = new Set<string>()
  const depth = (id: string): number => {
    if (memo[id] !== undefined) return memo[id]
    if (visiting.has(id)) return 0
    visiting.add(id)
    const d = Math.max(-1, ...(incoming[id] ?? []).map(depth)) + 1
    visiting.delete(id)
    return (memo[id] = d)
  }
  names.forEach((n) => depth(n))
  const layers: string[][] = []
  for (const n of names) (layers[memo[n]] ??= []).push(n)
  const pos: Record<string, { x: number; y: number }> = {}
  layers.forEach((layer, li) => {
    if (li === 0) layer.sort()
    else {
      const bary = (n: string) => {
        const ys = (incoming[n] ?? []).map((c) => pos[c]?.y).filter((y) => y !== undefined) as number[]
        return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 1e9
      }
      layer.sort((a, b) => bary(a) - bary(b))
    }
    layer.forEach((n, i) => { pos[n] = { x: PAD + li * COL_W, y: TOP + i * ROW_H } })
  })
  const maxRows = Math.max(1, ...layers.map((l) => l?.length ?? 0))
  const width = PAD * 2 + Math.max(1, layers.length) * COL_W - (COL_W - NODE_W)
  const height = TOP + maxRows * ROW_H + PAD
  const edges = props.items.map((r, i) => {
    const a = pos[r.from], b = pos[r.to]
    const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2
    let d: string
    if (x2 > x1) {
      const mx = (x1 + x2) / 2
      d = `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2 - 2},${y2}`
    } else {
      const low = Math.max(a.y, b.y) + NODE_H + 16
      d = `M${a.x + NODE_W / 2},${a.y + NODE_H} C${a.x + NODE_W / 2},${low} ${b.x + NODE_W / 2},${low} ${b.x + NODE_W / 2},${b.y + NODE_H}`
    }
    return { ...r, key: `${i}`, d, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 }
  })
  const nodes = [...names].map((n) => ({ name: n, own: own.has(n), ...pos[n],
    inCount: props.items.filter((r) => r.to === n).length, outCount: props.items.filter((r) => r.from === n).length }))
  return { nodes, edges, width, height, layers: layers.length }
})

function near(name: string): boolean {
  if (!hover.value) return true
  return name === hover.value || props.items.some((r) => (r.from === hover.value && r.to === name) || (r.to === hover.value && r.from === name))
}
function short(s: string): string {
  return s.length > 12 ? `${s.slice(0, 11)}…` : s
}
</script>

<template>
  <div class="rounded-[10px] border border-line bg-[#fbfcfe]">
    <div class="flex flex-wrap gap-x-4 gap-y-1 px-3 pt-2 text-[10.5px] text-fg-mute">
      <span class="flex items-center gap-1"><i class="inline-block w-5 border-t-2 border-[#16a34a]" />正向影响（+）</span>
      <span class="flex items-center gap-1"><i class="inline-block w-5 border-t-2 border-[#ea7a1a]" />负向影响（−）</span>
      <span class="flex items-center gap-1"><i class="inline-block w-5 border-t-2 border-[#94a3b8]" />影响 / 质量关系</span>
      <span class="flex items-center gap-1"><i class="inline-block w-3 h-3 rounded-sm border-2 border-[#0e8fa3] bg-[#dff3f6]" />本对象的参数</span>
      <span class="flex items-center gap-1"><i class="inline-block w-5 border-t-2 border-dashed border-[#94a3b8]" />继承自设备组</span>
      <span>· 左为影响方、右为被影响方 · 悬停看相邻关系与机理</span>
    </div>
    <div v-if="!items.length" class="empty m-4">暂无工艺影响关系</div>
    <div v-else class="overflow-auto" :style="{ maxHeight: height ?? 'calc(100vh - 290px)' }">
      <svg :width="layout.width" :height="layout.height" class="block">
        <defs>
          <marker v-for="(c, k) in { pos: '#16a34a', neg: '#ea7a1a', oth: '#94a3b8' }" :id="`ig-${k}`" :key="k" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" :fill="c" />
          </marker>
        </defs>
        <text v-for="i in layout.layers" :key="`h${i}`" :x="PAD + (i - 1) * COL_W" y="18" font-size="10.5" fill="#7b8798">{{ i === 1 ? '源头参数' : `第 ${i} 层` }}</text>
        <g v-for="e in layout.edges" :key="e.key" :opacity="hover && !(e.from === hover || e.to === hover) ? 0.12 : 1">
          <path :d="e.d" fill="none" :stroke="EDGE[e.predicate] ?? '#94a3b8'" :stroke-width="hover && (e.from === hover || e.to === hover) ? 2.2 : 1.3"
                :stroke-dasharray="e.inherited ? '5 3' : ''"
                :marker-end="`url(#ig-${e.predicate === '正向影响' ? 'pos' : e.predicate === '负向影响' ? 'neg' : 'oth'})`">
            <title>{{ e.from }} →{{ e.predicate }}→ {{ e.to }}：{{ e.mechanism }}</title>
          </path>
          <text v-if="SIGN[e.predicate]" :x="e.mx" :y="e.my - 3" font-size="11" font-weight="700" :fill="EDGE[e.predicate]" text-anchor="middle">{{ SIGN[e.predicate] }}</text>
        </g>
        <g v-for="n in layout.nodes" :key="n.name" :transform="`translate(${n.x},${n.y})`" class="cursor-default"
           :opacity="near(n.name) ? 1 : 0.25" @mouseenter="hover = n.name" @mouseleave="hover = ''">
          <rect :width="NODE_W" :height="NODE_H" rx="6" :fill="n.own ? '#dff3f6' : '#ffffff'" :stroke="n.own ? '#0e8fa3' : '#b6c2d1'" :stroke-width="n.own ? 1.6 : 1" />
          <text x="8" y="19" font-size="11.5" fill="#1f2937">{{ short(n.name) }}</text>
          <text :x="NODE_W - 6" y="19" font-size="9.5" fill="#7b8798" text-anchor="end">{{ n.inCount ? `←${n.inCount}` : '' }}</text>
          <title>{{ n.name }}{{ n.own ? '（本对象参数）' : '' }}：受 {{ n.inCount }} 个参数影响，影响 {{ n.outCount }} 个参数</title>
        </g>
      </svg>
    </div>
  </div>
</template>
