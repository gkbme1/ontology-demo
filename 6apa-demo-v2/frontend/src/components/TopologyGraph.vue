<script setup lang="ts">
/**
 * 拓扑关系图谱：本对象居中；上方 = 所属（工段 / 设备组 / 类），左侧 = 上游，右侧 = 下游，下方 = 部件 / 包含实例。
 * 同一对象的多条关系合并成一个节点；实线 = 本台自有（实例间），虚线 = 继承自设备组。
 * 节点是设备 / 设备组时可单击打开。
 */
import { computed, ref } from 'vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ items: Any[]; centerName: string; centerKind?: string }>()
const emit = defineEmits<{ (e: 'open', id: string): void }>()

const W = 1180
const SIDE_W = 250
const CENTER_W = 220
const CENTER_H = 56
const ROW = 36
const TOP_H = 30
const TYPE_COLOR: Record<string, [string, string]> = {
  物料流股: ['#eef2ff', '#818cf8'], 公用介质: ['#ecfdf5', '#34d399'], 生产设备: ['#ffffff', '#8197b3'],
  设备部件: ['#f8fafc', '#b6c2d1'], 实例: ['#ffffff', '#0e8fa3'], 归属: ['#f1f4f8', '#9fb3c8']
}
const hover = ref('')

interface Node { key: string; name: string; type: string; id?: string; preds: string[]; inherited: boolean; notes: string[]; x: number; y: number; w: number; h: number }

function merge(list: Any[], typeOf: (r: Any) => string): Node[] {
  const m = new Map<string, Node>()
  for (const r of list) {
    const key = r.target
    const n: Node = m.get(key) ?? { key, name: r.target, type: typeOf(r), id: r.targetId, preds: [], inherited: true, notes: [], x: 0, y: 0, w: 0, h: 0 }
    if (!n.preds.includes(r.predicate)) n.preds.push(r.predicate)
    if (!r.inherited) n.inherited = false
    if (r.mechanism) n.notes.push(`${r.predicate}：${r.mechanism}`)
    m.set(key, n)
  }
  return [...m.values()]
}

const layout = computed(() => {
  const its = props.items
  const top = merge(its.filter((r) => r.role === '所属'), () => '归属')
  const up = merge(its.filter((r) => r.role === '上游'), (r) => r.targetType || '生产设备')
  const down = merge(its.filter((r) => r.role === '下游'), (r) => r.targetType || '生产设备')
  const bottom = merge(its.filter((r) => r.role === '部件' || r.role === '包含实例'), (r) => (r.role === '包含实例' ? '实例' : '设备部件'))

  const topY = 8
  const sideY0 = topY + TOP_H + 56
  const sideRows = Math.max(up.length, down.length, 2)
  const centerY = sideY0 + Math.max(0, (sideRows * ROW - CENTER_H) / 2)
  const cx = (W - CENTER_W) / 2
  // 上方：所属
  const tw = 200
  const tx0 = (W - top.length * (tw + 16) + 16) / 2
  top.forEach((n, i) => Object.assign(n, { x: tx0 + i * (tw + 16), y: topY, w: tw, h: TOP_H }))
  // 左右：上游 / 下游
  const place = (list: Node[], x: number) => {
    const y0 = sideY0 + Math.max(0, ((sideRows - list.length) * ROW) / 2)
    list.forEach((n, i) => Object.assign(n, { x, y: y0 + i * ROW, w: SIDE_W, h: ROW - 8 }))
  }
  place(up, 16)
  place(down, W - SIDE_W - 16)
  // 下方：部件 / 实例，按行排
  const bw = 170
  const perRow = 6
  const by0 = sideY0 + sideRows * ROW + 50
  bottom.forEach((n, i) => {
    const row = Math.floor(i / perRow)
    const inRow = Math.min(perRow, bottom.length - row * perRow)
    const x0 = (W - inRow * (bw + 12) + 12) / 2
    Object.assign(n, { x: x0 + (i % perRow) * (bw + 12), y: by0 + row * 38, w: bw, h: 28 })
  })
  const height = (bottom.length ? by0 + Math.ceil(bottom.length / perRow) * 38 : sideY0 + sideRows * ROW) + 16
  const center = { x: cx, y: centerY, w: CENTER_W, h: CENTER_H }

  const edges: Any[] = []
  const cxm = cx + CENTER_W / 2
  for (const n of up) {
    const x1 = n.x + n.w, y1 = n.y + n.h / 2, x2 = cx, y2 = centerY + CENTER_H / 2
    edges.push({ key: n.key, d: `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2 - 2},${y2}`, n, lx: x1 + 6, ly: y1 - 4, anchor: 'start' })
  }
  for (const n of down) {
    const x1 = cx + CENTER_W, y1 = centerY + CENTER_H / 2, x2 = n.x, y2 = n.y + n.h / 2
    edges.push({ key: n.key, d: `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2 - 2},${y2}`, n, lx: x2 - 6, ly: y2 - 4, anchor: 'end' })
  }
  for (const n of top) {
    const x2 = n.x + n.w / 2, y2 = n.y + n.h
    edges.push({ key: n.key, d: `M${cxm},${centerY} C${cxm},${centerY - 30} ${x2},${y2 + 30} ${x2},${y2 + 2}`, n, lx: x2 + 4, ly: y2 + 14, anchor: 'start' })
  }
  for (const n of bottom) {
    const x2 = n.x + n.w / 2, y2 = n.y
    edges.push({ key: n.key, d: `M${cxm},${centerY + CENTER_H} C${cxm},${centerY + CENTER_H + 30} ${x2},${y2 - 30} ${x2},${y2 - 2}`, n, lx: 0, ly: 0, anchor: '' })
  }
  return { nodes: [...top, ...up, ...down, ...bottom], edges, center, height, sideY0, counts: { up: up.length, down: down.length, bottom: bottom.length } }
})

function short(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s
}
function canOpen(n: Node): boolean {
  return !!n.id && /^(equip-|egrp-)/.test(n.id)
}
</script>

<template>
  <div class="rounded-[10px] border border-line bg-[#fbfcfe]">
    <div class="flex flex-wrap gap-x-4 gap-y-1 px-3 pt-2 text-[10.5px] text-fg-mute">
      <span>上：所属　左：上游（{{ layout.counts.up }}）　右：下游（{{ layout.counts.down }}）　下：{{ centerKind === 'group' ? '部件 / 包含实例' : '部件 / 同组设备' }}（{{ layout.counts.bottom }}）</span>
      <span class="flex items-center gap-1"><i class="inline-block w-5 border-t-2 border-[#8197b3]" />本台自有</span>
      <span class="flex items-center gap-1"><i class="inline-block w-5 border-t-2 border-dashed border-[#8197b3]" />继承自设备组</span>
      <span v-for="(c, k) in TYPE_COLOR" :key="k" class="flex items-center gap-1"><i class="inline-block w-3 h-3 rounded-sm border" :style="{ background: c[0], borderColor: c[1] }" />{{ k }}</span>
    </div>
    <div v-if="!items.length" class="empty m-4">暂无拓扑关系</div>
    <svg v-else :viewBox="`0 0 ${W} ${layout.height}`" class="w-full block" :style="{ maxHeight: `${layout.height * 1.1}px` }">
      <defs>
        <marker id="tg-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#8197b3" />
        </marker>
      </defs>
      <g v-for="e in layout.edges" :key="`e-${e.key}-${e.n.y}`" :opacity="hover && hover !== e.key ? 0.2 : 1">
        <path :d="e.d" fill="none" :stroke="hover === e.key ? '#0e8fa3' : '#8197b3'" stroke-width="1.3"
              :stroke-dasharray="e.n.inherited ? '5 4' : ''" marker-end="url(#tg-arr)" />
        <text v-if="e.anchor" :x="e.lx" :y="e.ly" font-size="10" fill="#7b8798" :text-anchor="e.anchor">{{ short(e.n.preds.join(' / '), 14) }}</text>
      </g>
      <!-- 中心：本对象 -->
      <g :transform="`translate(${layout.center.x},${layout.center.y})`">
        <rect :width="layout.center.w" :height="layout.center.h" rx="10" fill="#dff3f6" stroke="#0e8fa3" stroke-width="2" />
        <text :x="layout.center.w / 2" y="25" font-size="14" font-weight="600" fill="#1f2937" text-anchor="middle">{{ short(centerName, 15) }}</text>
        <text :x="layout.center.w / 2" y="43" font-size="10.5" fill="#7b8798" text-anchor="middle">{{ centerKind === 'group' ? '设备组' : '设备' }}</text>
      </g>
      <g v-for="n in layout.nodes" :key="`n-${n.key}-${n.y}`" :transform="`translate(${n.x},${n.y})`"
         :class="canOpen(n) ? 'cursor-pointer' : ''" :opacity="hover && hover !== n.key ? 0.35 : 1"
         @mouseenter="hover = n.key" @mouseleave="hover = ''" @click="canOpen(n) && emit('open', n.id!)">
        <rect :width="n.w" :height="n.h" rx="6" :fill="(TYPE_COLOR[n.type] ?? TYPE_COLOR['生产设备'])[0]"
              :stroke="(TYPE_COLOR[n.type] ?? TYPE_COLOR['生产设备'])[1]" :stroke-dasharray="n.inherited ? '4 3' : ''" />
        <text x="8" :y="n.h / 2 + 4" font-size="11" fill="#1f2937">{{ short(n.name, Math.floor(n.w / 12)) }}</text>
        <title>{{ n.name }}（{{ n.type }}）{{ n.inherited ? '· 继承自设备组' : '· 本台' }}&#10;{{ n.preds.join('、') }}{{ n.notes.length ? '\n' + n.notes.join('\n') : '' }}</title>
      </g>
    </svg>
  </div>
</template>
