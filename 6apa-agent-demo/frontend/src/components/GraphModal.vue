<script setup lang="ts">
/**
 * 关系图。
 *
 * 用 ECharts 的 graph 系列渲染 Tool 返回的 nodes / edges，
 * 与本体服务前端的关系图保持同一套视觉，现场演示时两边看起来是一个产品。
 * 若要换成 G6 / Cytoscape，只需替换本组件，其他代码不受影响。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAgentStore } from '@/stores/agent'

echarts.use([GraphChart, TooltipComponent, LegendComponent, CanvasRenderer])

const emit = defineEmits<{ close: [] }>()
const store = useAgentStore()

const index = ref(store.graphs.length - 1)
const host = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const current = computed(() => store.graphs[index.value] ?? null)

const PALETTE = ['#38bdf8', '#34d399', '#fbbf24', '#f87171', '#a78bfa', '#f472b6', '#22d3ee']

function typeColor(type: string | undefined, types: string[]): string {
  const position = Math.max(0, types.indexOf(type ?? ''))
  return PALETTE[position % PALETTE.length]
}

function draw() {
  const payload = current.value
  if (!chart || !payload) return

  const types = [...new Set((payload.nodes ?? []).map((node) => node.type ?? '未分类'))]
  const nodes = (payload.nodes ?? []).map((node) => ({
    id: node.id,
    name: node.label,
    category: types.indexOf(node.type ?? '未分类'),
    symbolSize: node.isRoot ? 42 : Math.min(34, 14 + (node.relationCount ?? 0) * 2.5),
    itemStyle: { color: typeColor(node.type, types), borderColor: node.isRoot ? '#fff' : 'transparent', borderWidth: 2 },
    label: { show: true, color: '#d7e0ea', fontSize: 11 },
    value: `${node.type ?? ''} · 关联 ${node.relationCount ?? 0}`,
  }))

  const links = (payload.edges ?? []).map((edge) => ({
    source: edge.source,
    target: edge.target,
    value: `${edge.predicate ?? ''}${edge.category ? ` · ${edge.category}` : ''}${
      edge.weight != null ? ` · 权重 ${edge.weight}` : ''
    }`,
    label: { show: true, formatter: edge.predicate ?? '', fontSize: 10, color: '#7c8ea3' },
    lineStyle: { color: '#2a3647', width: Math.max(1, Math.min(3, (edge.weight ?? 1) * 2)), curveness: 0.12 },
  }))

  chart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: { formatter: (item: { data?: { value?: string; name?: string } }) => item.data?.value ?? item.data?.name ?? '' },
      legend: [
        {
          data: types,
          textStyle: { color: '#94a3b8', fontSize: 11 },
          top: 8,
          left: 8,
          itemWidth: 10,
          itemHeight: 10,
        },
      ],
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          categories: types.map((name, position) => ({
            name,
            itemStyle: { color: PALETTE[position % PALETTE.length] },
          })),
          force: { repulsion: 260, edgeLength: [80, 180], gravity: 0.08 },
          edgeSymbol: ['none', 'arrow'],
          edgeSymbolSize: 7,
          emphasis: { focus: 'adjacency', lineStyle: { color: '#38bdf8', width: 3 } },
          data: nodes,
          links,
        },
      ],
    },
    true,
  )
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  if (host.value) {
    chart = echarts.init(host.value, undefined, { renderer: 'canvas' })
    draw()
    window.addEventListener('resize', resize)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})

watch(index, draw)
</script>

<template>
  <div class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" @click.self="emit('close')">
    <div class="panel w-full h-full max-w-6xl flex flex-col">
      <div class="h-11 shrink-0 px-4 flex items-center gap-3 border-b border-line">
        <h3 class="text-sm font-semibold text-slate-100">关系图</h3>
        <select
          v-if="store.graphs.length > 1"
          v-model.number="index"
          class="bg-ink-700 border border-line rounded px-2 py-1 text-xs"
        >
          <option v-for="(graph, position) in store.graphs" :key="position" :value="position">
            #{{ position + 1 }} {{ graph.tool }}（{{ graph.nodes?.length ?? 0 }} 节点）
          </option>
        </select>
        <span v-if="current" class="text-[11px] font-mono text-slate-500">
          {{ current.nodes?.length ?? 0 }} 节点 / {{ current.edges?.length ?? 0 }} 边
          <span v-if="current.truncated" class="text-warn">· 已截断</span>
        </span>
        <button class="btn ml-auto" @click="emit('close')">关闭</button>
      </div>
      <div ref="host" class="flex-1 min-h-0" />
      <p class="shrink-0 px-4 py-2 text-[11px] text-slate-500 border-t border-line">
        滚轮缩放、拖拽平移；节点大小表示关联关系数量，箭头方向为关系主体 → 客体。
      </p>
    </div>
  </div>
</template>
