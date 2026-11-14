<script setup lang="ts">
/**
 * 全局图谱：整个本体（层级、设备、工艺参数、物料、现象）一张图。
 * 视图 = 显示哪些节点 / 关系类型的预设；布局 = 工艺流程（按工序顺序左→右）/ 层级 / 力导向；
 * 中心 + 范围（1 / 2 / 3 跳）只看某个对象的邻域；图例可开关节点类型；单击节点看详情。
 */
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { enterSegment, nav, openDrawing, openObject } from '@/composables/useNav'

echarts.use([GraphChart, LegendComponent, TooltipComponent, CanvasRenderer])

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

const TYPES: { name: string; color: string; symbol: string; size: number; rank: number }[] = [
  { name: '车间', color: '#0f172a', symbol: 'roundRect', size: 34, rank: 0 },
  { name: '工艺段', color: '#1e40af', symbol: 'roundRect', size: 28, rank: 1 },
  { name: '工序', color: '#0e8fa3', symbol: 'roundRect', size: 22, rank: 2 },
  { name: '设备组', color: '#ea7a1a', symbol: 'circle', size: 15, rank: 3 },
  { name: '设备', color: '#f59e0b', symbol: 'circle', size: 8, rank: 4 },
  { name: '物料流股', color: '#6366f1', symbol: 'diamond', size: 12, rank: 3 },
  { name: '公用介质', color: '#10b981', symbol: 'diamond', size: 11, rank: 3 },
  { name: '工艺参数', color: '#22c55e', symbol: 'circle', size: 8, rank: 5 },
  { name: '质量指标', color: '#a855f7', symbol: 'triangle', size: 11, rank: 5 },
  { name: '工况', color: '#64748b', symbol: 'rect', size: 9, rank: 6 },
  { name: '现象', color: '#dc2626', symbol: 'circle', size: 10, rank: 6 }
]
const TYPE = Object.fromEntries(TYPES.map((t) => [t.name, t]))
const EDGE_TYPES: { name: string; color: string; dashed?: boolean }[] = [
  { name: '包含', color: '#cbd5e1' },
  { name: '工序衔接', color: '#0e8fa3' },
  { name: '物理拓扑', color: '#6366f1' },
  { name: '具有属性', color: '#86efac', dashed: true },
  { name: '工艺影响', color: '#16a34a' },
  { name: '挂载', color: '#fca5a5', dashed: true },
  { name: '导致', color: '#dc2626' }
]
const EDGE = Object.fromEntries(EDGE_TYPES.map((e) => [e.name, e]))
const VIEWS: Record<string, { label: string; nodes: string[]; edges: string[]; layout: string }> = {
  flow: { label: '工艺流程', nodes: ['工艺段', '工序', '设备组', '物料流股', '公用介质'], edges: ['包含', '工序衔接', '物理拓扑'], layout: 'flow' },
  asset: { label: '设备与参数', nodes: ['工序', '设备组', '设备', '工艺参数', '质量指标'], edges: ['包含', '具有属性', '工艺影响'], layout: 'force' },
  cause: { label: '现象因果', nodes: ['设备组', '设备', '现象', '工况'], edges: ['挂载', '导致'], layout: 'force' },
  all: { label: '全部', nodes: TYPES.map((t) => t.name), edges: EDGE_TYPES.map((e) => e.name), layout: 'force' }
}
const LAYOUTS: Record<string, string> = { flow: '工艺流程（左→右）', tree: '层级', force: '力导向' }

const data = ref<Any>(null)
const view = ref('flow')
const layoutMode = ref('flow')
const edgeOn = ref<Set<string>>(new Set(VIEWS.flow.edges))
const segFilter = ref('')
const centerId = ref('')
const hops = ref(0)
const centerQuery = ref('')
const selected = ref<Any>(null)
// 路径查找结果：只显示选中的路径（需求 SW-055 第 5 条）
const pathView = ref<{ nodes: Any[]; edges: Any[] } | null>(null)
const pathTarget = ref('')
const paths = ref<Any[] | null>(null)
const pathMsg = ref('')
const LIMIT = 200
const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const byId = computed<Record<string, Any>>(() => Object.fromEntries((data.value?.nodes ?? []).map((n: Any) => [n.id, n])))

function applyView(v: string): void {
  view.value = v
  layoutMode.value = VIEWS[v].layout
  edgeOn.value = new Set(VIEWS[v].edges)
}
function toggleEdge(t: string): void {
  const s = new Set(edgeOn.value)
  if (s.has(t)) s.delete(t)
  else s.add(t)
  edgeOn.value = s
}

// 当前可见的子图：视图类型 ∩ 工艺段 ∩（中心 N 跳邻域）
const sub = computed(() => {
  const d = data.value
  if (!d) return { nodes: [] as Any[], edges: [] as Any[] }
  if (pathView.value) return pathView.value
  const types = new Set(VIEWS[view.value].nodes)
  if (centerId.value && byId.value[centerId.value]) types.add(byId.value[centerId.value].type)
  let nodes = d.nodes.filter((n: Any) => types.has(n.type) && (!segFilter.value || n.segId === segFilter.value || n.type === '车间'))
  let ids = new Set(nodes.map((n: Any) => n.id))
  let edges = d.edges.filter((e: Any) => edgeOn.value.has(e.type) && ids.has(e.s) && ids.has(e.t))
  // 当前关系类型下没有任何关系的节点不画（中心对象除外），避免散点铺满画布
  const touched = new Set<string>(edges.flatMap((e: Any) => [e.s, e.t]))
  nodes = nodes.filter((n: Any) => touched.has(n.id) || n.id === centerId.value)
  ids = new Set(nodes.map((n: Any) => n.id))
  if (centerId.value && hops.value > 0 && ids.has(centerId.value)) {
    const adj: Record<string, string[]> = {}
    for (const e of edges) { (adj[e.s] ??= []).push(e.t); (adj[e.t] ??= []).push(e.s) }
    const dist: Record<string, number> = { [centerId.value]: 0 }
    let frontier = [centerId.value]
    for (let h = 0; h < hops.value; h++) {
      const next: string[] = []
      for (const id of frontier) for (const m of adj[id] ?? []) if (dist[m] === undefined) { dist[m] = h + 1; next.push(m) }
      frontier = next
    }
    nodes = nodes.filter((n: Any) => dist[n.id] !== undefined).map((n: Any) => ({ ...n, hop: dist[n.id] }))
    ids = new Set(nodes.map((n: Any) => n.id))
    edges = edges.filter((e: Any) => ids.has(e.s) && ids.has(e.t))
  }
  return { nodes, edges }
})

// ---------------- 布局
function flowPositions(nodes: Any[]): Record<string, [number, number]> {
  // 按工序顺序从左到右排列；每列顶部是工序，下方依次是设备组、物料、参数、现象；工艺段居中放在它的工序上方
  const COL = 230, ROW = 46, MAXROWS = 16, SUB = 190
  const cols: Record<number, Any[]> = {}
  for (const n of nodes) (cols[n.opIndex ?? -1] ??= []).push(n)
  const pos: Record<string, [number, number]> = {}
  const colX: Record<number, number> = {}
  let x = 0
  for (const k of Object.keys(cols).map(Number).sort((a, b) => a - b)) {
    const list = cols[k].sort((a: Any, b: Any) => (TYPE[a.type]?.rank ?? 9) - (TYPE[b.type]?.rank ?? 9) || a.name.localeCompare(b.name))
    const rest = list.filter((n: Any) => !['车间', '工艺段', '工序'].includes(n.type))
    colX[k] = x
    list.filter((n: Any) => n.type === '工序').forEach((n: Any) => { pos[n.id] = [x, -80] })
    rest.forEach((n: Any, i: number) => { pos[n.id] = [x + Math.floor(i / MAXROWS) * SUB, (i % MAXROWS) * ROW] })
    x += COL + Math.max(0, Math.ceil(rest.length / MAXROWS) - 1) * SUB
  }
  const opsBySeg: Record<string, number[]> = {}
  for (const o of data.value?.ops ?? []) (opsBySeg[o.segId] ??= []).push(o.index)
  for (const n of nodes) {
    if (n.type === '工艺段') {
      const xs = (opsBySeg[n.id] ?? []).map((i) => colX[i]).filter((v) => v !== undefined)
      pos[n.id] = [xs.length ? (Math.min(...xs) + Math.max(...xs)) / 2 : 0, -170]
    } else if (n.type === '车间') pos[n.id] = [x / 2, -250]
  }
  return pos
}
function treePositions(nodes: Any[]): Record<string, [number, number]> {
  const rows: Record<number, Any[]> = {}
  for (const n of nodes) (rows[TYPE[n.type]?.rank ?? 9] ??= []).push(n)
  const pos: Record<string, [number, number]> = {}
  const SP = 70
  const widest = Math.max(...Object.values(rows).map((r) => r.length))
  for (const [rank, list] of Object.entries(rows)) {
    list.sort((a: Any, b: Any) => (a.opIndex ?? -1) - (b.opIndex ?? -1) || String(a.groupId ?? a.anchorId ?? '').localeCompare(String(b.groupId ?? b.anchorId ?? '')) || a.name.localeCompare(b.name))
    const step = (widest * SP) / Math.max(1, list.length)
    list.forEach((n: Any, i: number) => { pos[n.id] = [i * step + step / 2, Number(rank) * 220] })
  }
  return pos
}

function render(): void {
  if (!el.value || !data.value) return
  chart ??= echarts.init(el.value)
  const { nodes, edges } = sub.value
  const big = nodes.length > 260
  const pos = layoutMode.value === 'flow' ? flowPositions(nodes) : layoutMode.value === 'tree' ? treePositions(nodes) : null
  const shownTypes = TYPES.filter((t) => nodes.some((n: Any) => n.type === t.name))
  const catIndex = Object.fromEntries(shownTypes.map((t, i) => [t.name, i]))
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: '#ffffff', borderColor: '#d6dde7', textStyle: { color: '#1f2937', fontSize: 12 },
      formatter: (p: Any) => p.dataType === 'edge'
        ? `${byId.value[p.data.source]?.name} →<b>${p.data.label || p.data.etype}</b>→ ${byId.value[p.data.target]?.name}${p.data.mechanism ? `<br/><span style="color:#7b8798">${p.data.mechanism}</span>` : ''}`
        : `<b>${p.data.name}</b><br/><span style="color:#7b8798">${p.data.raw.type}${p.data.raw.hop !== undefined ? ` · 第 ${p.data.raw.hop} 跳` : ''} · ${p.data.raw.degree} 条关系</span>`
    },
    legend: [{ data: shownTypes.map((t) => t.name), bottom: 8, left: 12, itemWidth: 12, itemHeight: 10, textStyle: { color: '#4b5563', fontSize: 11 } }],
    animationDurationUpdate: 600,
    series: [{
      type: 'graph',
      layout: pos ? 'none' : 'force',
      roam: true, draggable: true, zoom: 1,
      categories: shownTypes.map((t) => ({ name: t.name, itemStyle: { color: t.color }, symbol: t.symbol })),
      force: nodes.length < 40
        ? { repulsion: 600, edgeLength: [90, 170], gravity: 0.05, friction: 0.15 }  // 路径 / 小邻域：拉开排布，标签不重叠
        : { repulsion: big ? 60 : 160, edgeLength: big ? [20, 60] : [40, 110], gravity: big ? 0.15 : 0.08, friction: 0.15 },
      data: nodes.map((n: Any) => {
        const t = TYPE[n.type] ?? TYPES[3]
        const isCenter = n.id === centerId.value
        const size = t.size + Math.min(14, Math.sqrt(n.degree || 0) * (t.rank <= 3 ? 1.6 : 0.8)) + (isCenter ? 10 : 0)
        const p = pos?.[n.id]
        return {
          id: n.id, name: n.name, category: catIndex[n.type], symbolSize: ['工序', '工艺段', '车间'].includes(n.type) ? [Math.max(64, n.name.length * 12 + 18), t.size + (isCenter ? 6 : 0)] : size,
          x: p?.[0], y: p?.[1], raw: n,
          itemStyle: { borderColor: isCenter ? '#111827' : '#ffffff', borderWidth: isCenter ? 3 : 1, shadowBlur: isCenter ? 16 : 6, shadowColor: `${t.color}66` },
          label: {
            show: !big || t.rank <= 3 || isCenter,
            position: ['工序', '工艺段', '车间'].includes(n.type) ? 'inside' : 'right',
            color: ['工序', '工艺段', '车间'].includes(n.type) ? '#ffffff' : '#334155', fontSize: t.rank <= 2 ? 12 : 10,
            fontWeight: t.rank <= 2 ? 600 : 400,
            formatter: (x: Any) => (x.name.length > 14 ? `${x.name.slice(0, 13)}…` : x.name)
          }
        }
      }),
      links: edges.map((e: Any) => {
        const et = EDGE[e.type] ?? EDGE_TYPES[0]
        const color = e.type === '工艺影响' && e.label === '负向影响' ? '#ea7a1a' : et.color
        return {
          source: e.s, target: e.t, label: e.label, etype: e.type, mechanism: e.mechanism,
          lineStyle: { color, width: e.type === '工序衔接' ? 2.6 : e.type === '导致' ? 1.6 : 1, type: et.dashed ? 'dashed' : 'solid',
                       opacity: e.type === '包含' ? 0.55 : 0.85, curveness: layoutMode.value === 'force' ? 0.08 : 0.22 }
        }
      }),
      edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 6,
      emphasis: { focus: 'adjacency', lineStyle: { width: 2.5 }, label: { show: true } },
      blur: { itemStyle: { opacity: 0.12 }, lineStyle: { opacity: 0.05 }, label: { show: false } },
      labelLayout: { hideOverlap: true }
    }]
  }, true)
  chart.off('click')
  chart.on('click', (p: Any) => { if (p.dataType === 'node') selected.value = p.data.raw })
  chart.off('dblclick')
  chart.on('dblclick', (p: Any) => { if (p.dataType === 'node') showHops(p.data.raw.id, 1) })
}

function applyFocus(): void {
  const f = nav.graphFocus
  if (!f?.id || !data.value) return
  // 中心对象不在当前视图的节点类型里时切到「全部」
  if (byId.value[f.id] && !VIEWS[view.value].nodes.includes(byId.value[f.id].type)) applyView('all')
  pathView.value = null
  centerId.value = f.id
  hops.value = f.hops ?? 1
  centerQuery.value = byId.value[f.id]?.name ?? ''
  selected.value = byId.value[f.id] ?? null
  nav.graphFocus = null
}
onMounted(async () => {
  data.value = await api.globalGraph()
  if (nav.graphFocus?.id) applyView('all')
  applyFocus()
  await nextTick()
  render()
})
watch(() => nav.graphFocus, applyFocus)
watch(() => [sub.value, layoutMode.value], () => nextTick(render))
const ro = new ResizeObserver(() => chart?.resize())
onMounted(() => el.value && ro.observe(el.value))
onBeforeUnmount(() => { ro.disconnect(); chart?.dispose() })

// ---------------- 中心与详情
const nameOptions = computed(() => (data.value?.nodes ?? []).filter((n: Any) => n.type !== '设备' || n.degree > 1))
function pickCenter(): void {
  const q = centerQuery.value.trim()
  if (!q) return
  const n = data.value.nodes.find((x: Any) => x.name === q) ?? data.value.nodes.find((x: Any) => x.name.includes(q))
  if (n) setCenter(n.id)
}
// 范围按钮：有中心用中心；没有中心但选中了节点，就以选中的节点为中心
const hopHint = ref(false)
function chooseHops(h: number): void {
  if (h === 0) { hops.value = 0; return }
  const id = centerId.value || selected.value?.id
  if (!id) { hopHint.value = true; setTimeout(() => (hopHint.value = false), 4000); return }
  showHops(id, h)
}
function showHops(id: string, h: number): void {
  centerId.value = id
  hops.value = h
  centerQuery.value = byId.value[id]?.name ?? ''
  selected.value = byId.value[id] ?? null
}
function setCenter(id: string): void {
  centerId.value = id
  if (!hops.value) hops.value = 1
  centerQuery.value = byId.value[id]?.name ?? ''
  selected.value = byId.value[id] ?? null
}
function clearCenter(): void {
  centerId.value = ''
  hops.value = 0
  centerQuery.value = ''
}
const selectedEdges = computed(() => {
  if (!selected.value) return []
  return sub.value.edges.filter((e: Any) => e.s === selected.value.id || e.t === selected.value.id).slice(0, 40)
})
// 图谱 → 本体详情：按当前视角定位到相应页签（需求 SW-056）
const VIEW_TAB: Record<string, string> = { flow: 'topology', asset: 'parameters', cause: 'causal', all: 'drawing' }
function openInBrowse(n: Any): void {
  nav.page = 'browse'
  if (n.type === '工艺段') enterSegment(n.id)
  else if (n.type === '工序') openDrawing(n.id, n.segId)
  else if (n.type === '设备组' || n.type === '设备') {
    const tab = VIEW_TAB[view.value]
    enterSegment(n.segId, { type: 'object', id: n.objectId, opId: n.opId, tab }); openObject(n.objectId, n.opId, tab)
  } else if (n.type === '现象' || n.type === '工况') {
    const a = byId.value[n.anchorId]
    const tab = view.value === 'cause' ? 'causal' : 'phenomena'
    if (a) { enterSegment(a.segId, { type: 'object', id: a.objectId, opId: a.opId, tab }); openObject(a.objectId, a.opId, tab) }
  } else if (n.opId) openDrawing(n.opId, n.segId)
}

// ---------------- 两个对象之间的关系路径（最多 3 跳，按当前视图开启的关系类型，不分方向走、显示方向）
function findPaths(): void {
  paths.value = null
  pathMsg.value = ''
  const from = selected.value
  const q = pathTarget.value.trim()
  const to = data.value.nodes.find((x: Any) => x.name === q) ?? data.value.nodes.find((x: Any) => x.name.includes(q))
  if (!from || !to) { pathMsg.value = '没有找到终点对象'; return }
  if (from.id === to.id) { pathMsg.value = '起点与终点相同'; return }
  const adj: Record<string, Any[]> = {}
  for (const e of data.value.edges) {
    if (!edgeOn.value.has(e.type)) continue
    ;(adj[e.s] ??= []).push({ e, other: e.t, forward: true })
    ;(adj[e.t] ??= []).push({ e, other: e.s, forward: false })
  }
  const out: Any[] = []
  const walk = (cur: string, nodes: string[], steps: Any[]): void => {
    if (out.length >= 30) return
    if (cur === to.id) { out.push({ nodes: [...nodes], steps: [...steps] }); return }
    if (steps.length >= 3) return
    for (const x of adj[cur] ?? []) {
      if (nodes.includes(x.other)) continue
      nodes.push(x.other); steps.push(x)
      walk(x.other, nodes, steps)
      nodes.pop(); steps.pop()
    }
  }
  walk(from.id, [from.id], [])
  out.sort((a, b) => a.steps.length - b.steps.length)
  paths.value = out.map((p) => ({ ...p, lowConf: p.steps.some((x: Any) => x.e.type === '导致' && x.e.confidence === '低') }))
  if (!out.length) pathMsg.value = `「${from.name}」与「${to.name}」在当前关系类型下 3 跳内没有路径`
}
function showPaths(list: Any[]): void {
  const ids = new Set<string>(list.flatMap((p) => p.nodes))
  const edges = [...new Set(list.flatMap((p) => p.steps.map((x: Any) => x.e)))]
  pathView.value = { nodes: data.value.nodes.filter((n: Any) => ids.has(n.id)), edges }
}
const tooMany = computed(() => !pathView.value && centerId.value && hops.value > 0 && sub.value.nodes.length > LIMIT)
const tooManyByEdge = computed(() => {
  const c: Record<string, number> = {}
  for (const e of sub.value.edges) c[e.type] = (c[e.type] ?? 0) + 1
  return Object.entries(c).sort((a, b) => b[1] - a[1])
})
const canOpen = (n: Any) => ['工艺段', '工序', '设备组', '设备', '现象', '工况'].includes(n?.type) || !!n?.opId
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <!-- 工具条 -->
    <div class="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 border-b border-line bg-ink-panel text-xs">
      <label class="flex items-center gap-1.5"><span class="text-fg-mute">视图</span>
        <select class="inp font-medium" :value="view" @change="applyView(($event.target as HTMLSelectElement).value)">
          <option v-for="(v, k) in VIEWS" :key="k" :value="k">{{ v.label }}</option>
        </select>
      </label>
      <label class="flex items-center gap-1.5"><span class="text-fg-mute">布局</span>
        <select v-model="layoutMode" class="inp font-medium"><option v-for="(v, k) in LAYOUTS" :key="k" :value="k">{{ v }}</option></select>
      </label>
      <label class="flex items-center gap-1.5"><span class="text-fg-mute">工艺段</span>
        <select v-model="segFilter" class="inp"><option value="">全部</option><option v-for="s in data?.segments ?? []" :key="s.id" :value="s.id">{{ s.name }}</option></select>
      </label>
      <span class="flex items-center gap-1.5"><span class="text-fg-mute">中心</span>
        <span v-if="centerId" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-brand text-white font-medium">
          {{ byId[centerId]?.name }}<button class="opacity-80 hover:opacity-100" title="清除中心，回到全部" @click="clearCenter">✕</button>
        </span>
        <input v-else v-model="centerQuery" list="gg-names" class="inp w-44" placeholder="输入名称，或单击图中节点" @change="pickCenter" @keydown.enter="pickCenter" />
        <datalist id="gg-names"><option v-for="n in nameOptions" :key="n.id" :value="n.name">{{ n.type }}</option></datalist>
      </span>
      <span class="relative flex items-center gap-1"><span class="text-fg-mute">范围</span>
        <button v-for="h in [0, 1, 2, 3]" :key="h" class="ctl !py-0.5" :class="{ 'ctl-on': hops === h }"
                :title="h === 0 ? '显示全部' : `只看中心对象 ${h} 步以内能连到的对象`" @click="chooseHops(h)">{{ h === 0 ? '全部' : `${h} 跳` }}</button>
        <span v-if="hopHint" class="absolute left-0 top-full mt-1 z-20 whitespace-nowrap rounded-md bg-fg text-white px-2 py-1 shadow-lg">
          先单击图中一个节点（或在「中心」框输入名称），再点 1 / 2 / 3 跳
        </span>
      </span>
      <span class="flex items-center gap-1 flex-wrap"><span class="text-fg-mute">关系</span>
        <button v-for="e in EDGE_TYPES" :key="e.name" class="ctl !py-0.5" :class="{ 'ctl-on': edgeOn.has(e.name) }" @click="toggleEdge(e.name)">
          <i class="inline-block w-3 border-t-2" :class="e.dashed ? 'border-dashed' : ''" :style="{ borderColor: e.color }" />{{ e.name }}
        </button>
      </span>
      <span class="flex-1" />
      <span v-if="centerId && hops" class="text-brand">显示与「{{ byId[centerId]?.name }}」相隔 {{ hops }} 步以内的对象</span>
      <span class="text-fg-mute">节点 {{ sub.nodes.length }} · 关系 {{ sub.edges.length }}</span>
    </div>

    <div class="flex-1 flex min-h-0">
      <div class="relative flex-1 min-w-0 gg-bg">
        <div ref="el" class="absolute inset-0" />
        <div v-if="!data" class="absolute inset-0 grid place-items-center text-fg-mute">加载中…</div>
        <div v-else-if="!sub.nodes.length" class="absolute inset-0 grid place-items-center text-fg-mute">当前筛选下没有节点</div>
        <div v-if="pathView" class="absolute left-3 top-3 z-10 rounded-md border border-brand/40 bg-white/95 px-3 py-1.5 text-xs shadow">
          只显示查到的关系路径（{{ pathView.nodes.length }} 个对象）<button class="ctl !py-0 ml-2" @click="pathView = null">返回图谱</button>
        </div>
        <div v-if="tooMany" class="absolute left-3 top-3 z-10 max-w-[560px] rounded-md border border-warn/50 bg-white/95 px-3 py-1.5 text-xs shadow">
          展开的对象有 {{ sub.nodes.length }} 个，超过 {{ LIMIT }}，图会比较密。可减少跳数，或关掉部分关系类型：
          <button v-for="[t, n] in tooManyByEdge" :key="t" class="ctl !py-0 ml-1" @click="toggleEdge(t)">{{ t }} {{ n }} ✕</button>
        </div>
        <div class="absolute right-3 bottom-2 text-[11px] text-fg-mute bg-white/80 rounded px-2 py-0.5">
          单击节点看详情 · 双击节点看它的 1 跳邻域 · 选中节点后点「1 / 2 / 3 跳」看更远 · 滚轮缩放 · 拖拽平移
        </div>
      </div>
      <!-- 详情 -->
      <aside v-if="selected" class="w-[300px] shrink-0 border-l border-line bg-ink-panel overflow-auto p-4 space-y-3 text-xs">
        <div class="flex items-start gap-2">
          <i class="inline-block w-3 h-3 rounded-full mt-1" :style="{ background: TYPE[selected.type]?.color }" />
          <div class="flex-1">
            <div class="text-[14px] font-semibold text-fg">{{ selected.name }}</div>
            <div class="text-fg-mute">{{ selected.type }}{{ selected.etype ? ` · ${selected.etype}` : '' }} · {{ selected.degree }} 条关系</div>
          </div>
          <button class="ctl !px-1.5 !py-0" @click="selected = null">✕</button>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <span class="text-fg-mute self-center">以它为中心看：</span>
          <button v-for="h in [1, 2, 3]" :key="h" class="btn" :class="{ 'btn-primary': centerId === selected.id && hops === h }" @click="showHops(selected.id, h)">{{ h }} 跳</button>
          <button v-if="canOpen(selected)" class="btn btn-primary" :title="`按当前视角打开对应页签`" @click="openInBrowse(selected)">在本体浏览中打开</button>
        </div>
        <dl class="kv">
          <template v-if="selected.opId"><dt>所在工序</dt><dd>{{ byId[selected.opId]?.name }}</dd></template>
          <template v-if="selected.segId"><dt>工艺段</dt><dd>{{ byId[selected.segId]?.name }}</dd></template>
          <template v-if="selected.anchorId"><dt>挂载对象</dt><dd>{{ byId[selected.anchorId]?.name }}</dd></template>
          <template v-if="selected.hop !== undefined"><dt>距中心</dt><dd>{{ selected.hop }} 跳</dd></template>
        </dl>
        <div class="space-y-1.5">
          <div class="sec-title">查找关系路径（最多 3 跳）</div>
          <div class="flex gap-1">
            <input v-model="pathTarget" list="gg-names" class="inp flex-1 min-w-0" placeholder="终点对象名称" @keydown.enter="findPaths" />
            <button class="btn" @click="findPaths">查找</button>
          </div>
          <div class="text-[11px] text-fg-mute">按当前开启的关系类型查找；低置信度的导致关系标「低」</div>
          <div v-if="pathMsg" class="text-fg-mute">{{ pathMsg }}</div>
          <template v-if="paths?.length">
            <div class="flex items-center gap-2"><span class="text-fg-dim">共 {{ paths.length }} 条</span>
              <button class="ctl !py-0" @click="showPaths(paths)">图中只看这些路径</button></div>
            <div v-for="(p, i) in paths" :key="i" class="py-1 border-b border-line-soft cursor-pointer hover:bg-ink-panel2" @click="showPaths([p])">
              <span class="text-fg-mute">{{ p.steps.length }} 跳 </span>
              <template v-for="(x, j) in p.steps" :key="j">
                <span v-if="j === 0">{{ byId[p.nodes[0]]?.name }}</span>
                <span class="text-fg-mute"> {{ x.forward ? '—' : '←' }}{{ x.e.label || x.e.type }}{{ x.forward ? '→' : '—' }} </span>
                <span>{{ byId[p.nodes[j + 1]]?.name }}</span>
                <span v-if="x.e.type === '导致' && x.e.confidence === '低'" class="pill pill-warn !py-0 ml-0.5">低</span>
              </template>
            </div>
          </template>
        </div>
        <div>
          <div class="sec-title">当前图中的关系（{{ selectedEdges.length }}）</div>
          <div v-for="(e, i) in selectedEdges" :key="i" class="py-1 border-b border-line-soft">
            <span :class="e.s === selected.id ? 'text-fg' : 'text-brand cursor-pointer'" @click="e.s !== selected.id && (selected = byId[e.s])">{{ byId[e.s]?.name }}</span>
            <span class="text-fg-mute"> —{{ e.label || e.type }}→ </span>
            <span :class="e.t === selected.id ? 'text-fg' : 'text-brand cursor-pointer'" @click="e.t !== selected.id && (selected = byId[e.t])">{{ byId[e.t]?.name }}</span>
          </div>
          <div v-if="!selectedEdges.length" class="text-fg-mute">当前筛选下没有关系</div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.gg-bg {
  background-color: #fbfcfe;
  background-image: radial-gradient(#dbe3ee 1px, transparent 1px);
  background-size: 18px 18px;
}
</style>
