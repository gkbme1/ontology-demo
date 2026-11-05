<script setup lang="ts">
/** 折线图（ECharts）：多条线 + 可选阈值线。 */
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

echarts.use([LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{
  times: string[]
  lines: { name: string; values: (number | null)[] }[]
  threshold?: number | null
  unit?: string
  height?: number
  step?: boolean
}>()

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null
const PALETTE = ['#0e8fa3', '#ca8a04', '#8b5cf6', '#16a34a', '#ea7a1a', '#2563eb']

function render(): void {
  if (!el.value) return
  chart ??= echarts.init(el.value, undefined, { renderer: 'canvas' })
  chart.setOption({
    backgroundColor: 'transparent',
    color: PALETTE,
    grid: { left: 48, right: 16, top: 28, bottom: 28 },
    tooltip: { trigger: 'axis', backgroundColor: '#ffffff', borderColor: '#c9d4e0', textStyle: { color: '#1f2937', fontSize: 11 } },
    legend: { top: 0, textStyle: { color: '#4b5563', fontSize: 11 }, itemHeight: 8 },
    xAxis: { type: 'category', data: props.times, axisLabel: { color: '#7b8798', fontSize: 10 }, axisLine: { lineStyle: { color: '#c9d4e0' } } },
    yAxis: { type: 'value', scale: true, name: props.unit ?? '', nameTextStyle: { color: '#7b8798', fontSize: 10 },
             axisLabel: { color: '#7b8798', fontSize: 10 }, splitLine: { lineStyle: { color: '#e6ebf1' } } },
    dataZoom: [{ type: 'inside' }],
    series: props.lines.map((l, i) => ({
      name: l.name, type: 'line', data: l.values, showSymbol: false, step: props.step ? 'end' : undefined,
      lineStyle: { width: 1.4 },
      markLine: i === 0 && props.threshold !== null && props.threshold !== undefined
        ? { symbol: 'none', data: [{ yAxis: props.threshold }], lineStyle: { color: '#dc2626', type: 'dashed' },
            label: { color: '#dc2626', fontSize: 10, formatter: `阈值 ${props.threshold}` } }
        : undefined
    }))
  }, true)
}

onMounted(render)
watch(() => [props.times, props.lines, props.threshold], render, { deep: true })
const ro = new ResizeObserver(() => chart?.resize())
onMounted(() => el.value && ro.observe(el.value))
onBeforeUnmount(() => { ro.disconnect(); chart?.dispose() })
</script>

<template>
  <div ref="el" :style="{ height: `${height ?? 200}px` }" class="w-full" />
</template>
