<script setup lang="ts">
/**
 * 局部语义图（ECharts Graph）。
 *
 * 节点颜色、边样式、线型、边宽全部取自 /api/ontology/graph 返回的 style 字段，
 * 组件本身不推断任何语义，也不补充 Excel 中不存在的关系。
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { GraphEdge, GraphNode, GraphPayload } from '@/api/types'

echarts.use([GraphChart, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps<{ graph: GraphPayload | null; height?: string }>()
const emit = defineEmits<{
  (e: 'node-click', node: GraphNode): void
  (e: 'edge-click', edge: GraphEdge): void
}>()

const host = ref<HTMLDivElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)

const SHAPE: Record<string, string> = { circle: 'circle', roundRect: 'roundRect', diamond: 'diamond' }

function symbolSize(n: GraphNode): number {
  if (n.isRoot) return 46
  if (n.nodeKind === 'tag') return 18
  if (n.nodeKind === 'area') return 34
  return 26
}

function buildOption(g: GraphPayload) {
  const nodes = g.nodes.map((n) => {
    const unmatched = n.matchStatus === 'UNMATCHED'
    return {
      id: n.id,
      name: n.label,
      symbol: SHAPE[n.style.shape] ?? 'circle',
      symbolSize: symbolSize(n),
      category: n.type ?? '外部对象',
      value: n.relationCount ?? n.tagCount ?? 0,
      itemStyle: {
        color: unmatched ? 'transparent' : n.style.color,
        borderColor: n.style.color,
        borderWidth: n.isRoot ? 3 : 1.6,
        borderType: unmatched ? 'dashed' : 'solid',
        opacity: unmatched ? 1 : n.isRoot ? 1 : 0.88
      },
      label: {
        show: true,
        position: 'bottom',
        color: n.isRoot ? '#dde7f7' : '#9fb0cc',
        fontSize: n.isRoot ? 12 : 10.5,
        fontWeight: n.isRoot ? 600 : 400,
        formatter: (p: { name: string }) => (p.name.length > 14 ? p.name.slice(0, 13) + '…' : p.name)
      },
      raw: n
    }
  })

  const links = g.edges.map((e) => ({
    source: e.source,
    target: e.target,
    value: e.label ?? '',
    lineStyle: {
      color: e.style.color,
      width: e.style.width,
      opacity: e.style.opacity,
      type: e.style.lineStyle === 'dashed' ? 'dashed' : e.style.lineStyle === 'dotted' ? 'dotted' : 'solid',
      curveness: 0.08
    },
    // 对象映射边数量可能很多，重复标签会淹没关系谓词
    label: {
      show: e.edgeKind !== 'mapping',
      formatter: () => e.label ?? '',
      fontSize: 9.5,
      color: e.style.color,
      textBorderColor: '#0b1322',
      textBorderWidth: 3
    },
    symbol: ['none', 'arrow'],
    symbolSize: [0, 7],
    raw: e
  }))

  const categories = (g.nodeStyles ?? []).map((s) => ({ name: s.type, itemStyle: { color: s.color } }))

  return {
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: '#16233a',
      borderColor: '#23344f',
      textStyle: { color: '#dde7f7', fontSize: 12 },
      formatter: (p: { dataType: string; data: { raw?: GraphNode | GraphEdge } }) => {
        const raw = p.data.raw
        if (!raw) return ''
        if (p.dataType === 'node') {
          const n = raw as GraphNode
          return [n.label, n.type, n.matchStatusLabel, n.owlSubject].filter(Boolean).join('<br/>')
        }
        const e = raw as GraphEdge
        return [e.label, e.category, e.domainDescription].filter(Boolean).join('<br/>')
      }
    },
    legend: [{
      data: categories.map((c) => c.name),
      textStyle: { color: '#9fb0cc', fontSize: 10.5 },
      bottom: 8, left: 12, itemWidth: 9, itemHeight: 9, icon: 'circle'
    }],
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      data: nodes,
      links,
      categories,
      force: {
        repulsion: g.rootId ? 420 : 900,
        edgeLength: g.rootId ? [70, 140] : [110, 220],
        gravity: g.rootId ? 0.08 : 0.02,
        friction: 0.2
      },
      emphasis: { focus: 'adjacency', lineStyle: { width: 3.6 } },
      edgeLabel: { show: true }
    }]
  }
}

function render() {
  if (!chart.value || !props.graph) return
  chart.value.setOption(buildOption(props.graph), true)
}

onMounted(async () => {
  await nextTick()
  if (!host.value) return
  chart.value = echarts.init(host.value)
  chart.value.on('click', (p: { dataType?: string; data?: { raw?: GraphNode | GraphEdge } }) => {
    const raw = p.data?.raw
    if (!raw) return
    if (p.dataType === 'node') emit('node-click', raw as GraphNode)
    else if (p.dataType === 'edge') emit('edge-click', raw as GraphEdge)
  })
  render()
  window.addEventListener('resize', onResize)
})

const onResize = () => chart.value?.resize()

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart.value?.dispose()
  chart.value = null
})

watch(() => props.graph, render)
</script>

<template>
  <div class="relative" :style="{ height: height ?? '560px', background: 'radial-gradient(circle at 50% 42%, #132139 0%, #0b1322 72%)' }">
    <div ref="host" class="absolute inset-0"></div>
    <div v-if="graph" class="absolute right-3 bottom-3 text-fg-mute text-[10.5px] bg-ink/85 border border-line rounded-md px-2.5 py-1.5">
      节点 {{ graph.nodeCount }} · 边 {{ graph.edgeCount }}
      <span v-if="graph.truncated" class="text-warn"> · 已截断，请收紧筛选</span>
      · 滚轮缩放 / 拖拽平移 / 点击查看详情
    </div>
  </div>
</template>
