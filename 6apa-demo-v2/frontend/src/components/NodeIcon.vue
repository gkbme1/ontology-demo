<script setup lang="ts">
/**
 * 树节点图标：按节点类型给线性图标与颜色；设备按名称区分 罐 / 泵 / 离心机 / 阀 / 换热器 / 塔 / 过滤器 / 风机 / 管网 / 干燥；
 * 其他分类里的实体按所在分类（工艺参数 / 物料 / 质量 / 经营）区分。图标为内置 SVG，不依赖外部图标库。
 */
import { computed } from 'vue'

const props = defineProps<{ kind: string; label?: string; category?: string; size?: number }>()

// 24×24 线性图标（stroke = currentColor）
const SVG: Record<string, string> = {
  factory: '<path d="M2 20V9l5 3V9l5 3V9l5 3V4h5v16z"/><path d="M6 16h2M11 16h2M16 16h2"/>',
  layers: '<path d="M12 3 2 8l10 5 10-5z"/><path d="m2 13 10 5 10-5"/><path d="m2 17.5 10 5 10-5"/>',
  workflow: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><path d="M6.5 10v3a3 3 0 0 0 3 3H14"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  folderDashed: '<path stroke-dasharray="3 2.5" d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  tank: '<ellipse cx="12" cy="5" rx="7" ry="2.5"/><path d="M5 5v14c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V5"/><path d="M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
  pump: '<circle cx="10" cy="13" r="6"/><path d="M10 7h10v4"/><circle cx="10" cy="13" r="1.6"/><path d="M6.5 19 5 22h10l-1.5-3"/>',
  centrifuge: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.2"/><path d="M12 3v4M21 12h-4M12 21v-4M3 12h4"/>',
  valve: '<path d="M3 8v9l9-4.5zM21 8v9l-9-4.5z"/><path d="M12 12.5V5M9 5h6"/>',
  heat: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M6 12c1.5-2.5 3 2.5 4.5 0s3 2.5 4.5 0 3 2.5 3 0"/>',
  tower: '<rect x="8" y="2" width="8" height="20" rx="4"/><path d="M8 8h8M8 13h8M8 18h8"/>',
  filter: '<path d="M3 4h18l-7 8.5V19l-4 2v-8.5z"/>',
  fan: '<circle cx="12" cy="12" r="9"/><path d="M12 12c0-3 1-5.5 3.5-5.5M12 12c2.6 1.5 4.3 3.6 3 5.8M12 12c-2.6 1.5-5.3 1.3-6.5-.9"/><circle cx="12" cy="12" r="1.3"/>',
  pipe: '<path d="M3 8h9a5 5 0 0 1 5 5v8"/><path d="M3 14h7a1 1 0 0 1 1 1v6"/>',
  thermo: '<path d="M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z"/><path d="M12 9v7"/>',
  cube: '<path d="M21 16V8l-9-5-9 5v8l9 5z"/><path d="M3.3 7.2 12 12l8.7-4.8M12 22V12"/>',
  sigma: '<path d="M18 7V4H6l6 8-6 8h12v-3"/>',
  func: '<path d="M9.5 20c2.5 0 2.7-3 3-8s.5-8 3-8"/><path d="M8 11h7"/><path d="M4 7c-1 1.5-1 8.5 0 10M20 7c1 1.5 1 8.5 0 10"/>',
  activity: '<path d="M22 12h-4l-3 8L9 4l-3 8H2"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  tag: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.3"/>',
  gauge: '<path d="M3.3 18a10 10 0 1 1 17.4 0"/><path d="m12 14 4.5-4.5"/><circle cx="12" cy="14" r="1.3"/>',
  flask: '<path d="M9 3h6M10 3v6l-5.5 9.5A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-2.5L14 9V3"/><path d="M7.5 15h9"/>',
  badge: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  trend: '<path d="m3 17 6-6 4 4 8-8"/><path d="M14 7h7v7"/>',
  dot: '<circle cx="12" cy="12" r="3"/>'
}

// 设备按名称关键字选图标（先匹配的优先）
const EQUIP_RULES: [RegExp, string, string][] = [
  [/离心机/, 'centrifuge', '#0e8fa3'],
  [/泵/, 'pump', '#2563eb'],
  [/阀/, 'valve', '#7c3aed'],
  [/换热器|冷凝器|加热|热水|冷却|沸器|过冷器|空冷器|蒸发器|锅炉|炉|散热片/, 'heat', '#dc2626'],
  [/塔|吸附柱|色谱柱|吸附器|火炬|精馏柱/, 'tower', '#0f766e'],
  [/过滤|除尘器|阻火器/, 'filter', '#0891b2'],
  [/风机|压缩机|鼓风|排风|送风|膨胀|丙烷机|空压机|制氮机/, 'fan', '#475569'],
  [/管网|管线|管道|总管|来气|调气|外输|返输|汇管|球筒|计量/, 'pipe', '#64748b'],
  [/干燥/, 'thermo', '#ea580c'],
  [/罐|槽|仓|釜|混合器|结晶器|分离器|除油器|水站|经济器|回油器|缸|水箱|水池|射流器/, 'tank', '#d97706']
]

const spec = computed<[string, string]>(() => {
  const k = props.kind
  const label = props.label ?? ''
  switch (k) {
    case 'workshop': return ['factory', '#1e293b']
    case 'segment': case 'area': return ['layers', '#4338ca']
    case 'op': return ['workflow', '#0e8fa3']
    case 'group': return ['folder', '#d97706']
    case 'bucket': return ['folderDashed', '#94a3b8']
    case 'class': return ['grid', '#4338ca']
    case 'type': return ['tag', '#6366f1']
    case 'global:calc': case 'calc': return ['sigma', '#0e8fa3']
    case 'global:algo': return ['func', '#7c3aed']
    case 'global:cond': return ['activity', '#dc2626']
    case 'global:docs': return ['file', '#2563eb']
    case 'equipment': {
      const hit = EQUIP_RULES.find(([re]) => re.test(label))
      return hit ? [hit[1], hit[2]] : ['cube', '#78716c']
    }
    case 'entity': {
      const c = props.category
      if (c === 'material') return ['flask', '#4f46e5']
      if (c === 'quality') return ['badge', '#9333ea']
      if (c === 'business') return ['trend', '#2563eb']
      return ['gauge', '#16a34a']
    }
    default: return ['dot', '#94a3b8']
  }
})
const markup = computed(() => SVG[spec.value[0]] ?? SVG.dot)
</script>

<template>
  <svg :width="size ?? 15" :height="size ?? 15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"
       stroke-linecap="round" stroke-linejoin="round" class="shrink-0" :style="{ color: spec[1] }" aria-hidden="true" v-html="markup" />
</template>
