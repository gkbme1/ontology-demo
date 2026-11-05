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
const PALETTE = ['#35c4d7', '#f2c744', '#b07cff', '#3fcf8e', '#ff9f45', '#4c8dff']

function render(): void {
  if (!el.value) return
  chart ??= echarts.init(el.value, undefined, { renderer: 'canvas' })
  chart.setOption({
    backgroundColor: 'transparent',
    color: PALETTE,
    grid: { left: 48, right: 16, top: 28, bottom: 28 },
    tooltip: { trigger: 'axis', backgroundColor: '#16233a', borderColor: '#23344f', textStyle: { color: '#dde7f7', fontSize: 11 } },
    legend: { top: 0, textStyle: { color: '#9fb0cc', fontSize: 11 }, itemHeight: 8 },
    xAxis: { type: 'category', data: props.times, axisLabel: { color: '#6f819e', fontSize: 10 }, axisLine: { lineStyle: { color: '#23344f' } } },
    yAxis: { type: 'value', scale: true, name: props.unit ?? '', nameTextStyle: { color: '#6f819e', fontSize: 10 },
             axisLabel: { color: '#6f819e', fontSize: 10 }, splitLine: { lineStyle: { color: '#1a2940' } } },
    dataZoom: [{ type: 'inside' }],
    series: props.lines.map((l, i) => ({
      name: l.name, type: 'line', data: l.values, showSymbol: false, step: props.step ? 'end' : undefined,
      lineStyle: { width: 1.4 },
      markLine: i === 0 && props.threshold !== null && props.threshold !== undefined
        ? { symbol: 'none', data: [{ yAxis: props.threshold }], lineStyle: { color: '#f2557a', type: 'dashed' },
            label: { color: '#f2557a', fontSize: 10, formatter: `阈值 ${props.threshold}` } }
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
