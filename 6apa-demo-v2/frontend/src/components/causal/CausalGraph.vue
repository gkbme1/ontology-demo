<script setup lang="ts">
/**
 * 根因关系图谱（SVG）：节点 = 现象，边 = 「原因 → 结果」。
 * 按导致关系分层：最左是根因，越往右越接近结果；同层按上一层位置的重心排序以减少交叉。
 * 悬停高亮相邻关系；单击节点 → pick（父级弹窗查看它由什么导致）。
 */
import { computed, ref } from 'vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ graph: Any; height?: number }>()
const emit = defineEmits<{ (e: 'pick', id: string): void }>()

const CAT_COLOR: Record<string, string> = {
  工艺: '#35c4d7', 设备: '#ff9f45', 仪表: '#b07cff', 操作: '#f2c744', 物料: '#3fcf8e', 公用工程: '#4c8dff', 环境: '#9fb0cc'
}
const NODE_W = 176
const NODE_H = 30
const COL_W = 250
const ROW_H = 42
const PAD = 20
const TOP = 34

const hover = ref('')

const layout = computed(() => {
  const nodes: Any[] = props.graph?.nodes ?? []
  const links: Any[] = (props.graph?.links ?? []).filter((l: Any) => nodes.some((n) => n.id === l.cause) && nodes.some((n) => n.id === l.effect))
  const incoming: Record<string, string[]> = {}
  for (const l of links) (incoming[l.effect] ??= []).push(l.cause)
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
  nodes.forEach((n) => depth(n.id))
  const layers: Any[][] = []
  for (const n of nodes) (layers[memo[n.id]] ??= []).push(n)
  const pos: Record<string, { x: number; y: number }> = {}
  layers.forEach((layer, li) => {
    if (li === 0) layer.sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name))
    else {
      const bary = (n: Any) => {
        const ys = (incoming[n.id] ?? []).map((c) => pos[c]?.y).filter((y) => y !== undefined) as number[]
        return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 1e9
      }
      layer.sort((a, b) => bary(a) - bary(b))
    }
    layer.forEach((n, i) => { pos[n.id] = { x: PAD + li * COL_W, y: TOP + i * ROW_H } })
  })
  const maxRows = Math.max(1, ...layers.map((l) => l?.length ?? 0))
  const width = PAD * 2 + Math.max(1, layers.length) * COL_W - (COL_W - NODE_W)
  const height = TOP + maxRows * ROW_H + PAD
  const edges = links.map((l) => {
    const a = pos[l.cause], b = pos[l.effect]
    const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2
    if (x2 > x1) {
      const mx = (x1 + x2) / 2
      return { ...l, d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2 - 2},${y2}` }
    }
    // 同层（环）：从下方绕
    const low = Math.max(a.y, b.y) + NODE_H + 16
    return { ...l, d: `M${a.x + NODE_W / 2},${a.y + NODE_H} C${a.x + NODE_W / 2},${low} ${b.x + NODE_W / 2},${low} ${b.x + NODE_W / 2},${b.y + NODE_H}` }
  })
  return { nodes: nodes.map((n) => ({ ...n, ...pos[n.id] })), edges, width, height, layers: layers.length }
})

const adjacent = computed(() => {
  const s = new Set<string>()
  if (!hover.value) return s
  s.add(hover.value)
  for (const l of layout.value.edges) {
    if (l.cause === hover.value) s.add(l.effect)
    if (l.effect === hover.value) s.add(l.cause)
  }
  return s
})
function short(s: string): string {
  return s.length > 13 ? `${s.slice(0, 12)}…` : s
}
function dim(id: string): boolean {
  return !!hover.value && !adjacent.value.has(id)
}
</script>

<template>
  <div class="rounded-[10px] border border-line bg-[#0c1524]">
    <div class="flex flex-wrap gap-x-3 gap-y-1 px-3 pt-2 text-[10.5px] text-fg-mute">
      <span v-for="(c, k) in CAT_COLOR" :key="k" class="flex items-center gap-1"><i class="inline-block w-2.5 h-2.5 rounded-sm" :style="{ background: c }" />{{ k }}</span>
      <span>· 虚线框 = 判定规则待定义 · 虚线边 = 低置信度 · 左为原因、右为结果 · 悬停看相邻关系，单击节点看它由什么导致</span>
    </div>
    <div v-if="!layout.nodes.length" class="empty m-4">暂无根因影响关系</div>
    <div v-else class="overflow-auto" :style="{ maxHeight: `${height ?? 460}px` }">
      <svg :width="layout.width" :height="layout.height" class="block">
        <defs>
          <marker id="cg-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="#5d7aa3" />
          </marker>
        </defs>
        <text v-for="i in layout.layers" :key="`h${i}`" :x="PAD + (i - 1) * COL_W" y="20" font-size="10.5" fill="#6f819e">
          {{ i === 1 ? '根因' : `第 ${i} 层` }}
        </text>
        <path v-for="e in layout.edges" :key="e.id" :d="e.d" fill="none" marker-end="url(#cg-arr)"
              :stroke="hover && (e.cause === hover || e.effect === hover) ? '#35c4d7' : '#3b4f70'"
              :stroke-width="e.confidence === '高' ? 2 : 1.3" :stroke-dasharray="e.confidence === '低' ? '4 3' : ''"
              :opacity="hover && !(e.cause === hover || e.effect === hover) ? 0.15 : 1">
          <title>{{ e.causeName }} → {{ e.effectName }}：{{ e.mechanism }}（置信度 {{ e.confidence }}）</title>
        </path>
        <g v-for="n in layout.nodes" :key="n.id" :transform="`translate(${n.x},${n.y})`" class="cursor-pointer"
           :opacity="dim(n.id) ? 0.25 : n.inScope === false ? 0.6 : 1"
           @mouseenter="hover = n.id" @mouseleave="hover = ''" @click="emit('pick', n.id)">
          <rect :width="NODE_W" :height="NODE_H" rx="6" :fill="`${CAT_COLOR[n.category] ?? '#9fb0cc'}22`"
                :stroke="n.focus ? '#ffffff' : CAT_COLOR[n.category] ?? '#9fb0cc'" :stroke-width="n.focus ? 2.2 : 1.2"
                :stroke-dasharray="n.hasRule ? '' : '4 3'" />
          <text x="9" y="19" font-size="11.5" fill="#dde7f7">{{ short(n.name) }}</text>
          <text :x="NODE_W - 7" y="19" font-size="9.5" fill="#6f819e" text-anchor="end">{{ n.asEffect ? `←${n.asEffect}` : '' }}</text>
          <title>{{ n.name }}（{{ n.category }} · {{ n.anchor }}）作为原因 {{ n.asCause }} 次，作为结果 {{ n.asEffect }} 次{{ n.hasRule ? '' : '；判定规则待定义' }}</title>
        </g>
      </svg>
    </div>
  </div>
</template>
