<script setup lang="ts">
/**
 * 画面图纸：有现场图纸（P&ID 截图 + 热区）时默认显示原图，可切换到本体示意图。
 * 热区单击 → pick（对象 id、类型、对象所在画面）；highlight 中的对象（或其所属设备组）高亮。
 */
import { computed, ref, watch } from 'vue'
import PidCanvas from './PidCanvas.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ drawing: Any; highlight?: string[]; caption?: string }>()
const emit = defineEmits<{ (e: 'pick', id: string, kind: 'group' | 'equipment', opId?: string): void }>()

const mode = ref<'image' | 'schematic'>(props.drawing?.image ? 'image' : 'schematic')
watch(() => props.drawing?.opId, () => { mode.value = props.drawing?.image ? 'image' : 'schematic' })
const showSpots = ref(true)
const zoom = ref(1)
const hover = ref<Any>(null)

const img = computed(() => props.drawing?.image)
const hl = computed(() => new Set(props.highlight ?? []))
// 高亮规则：选中设备 → 只亮该设备；选中设备组 → 亮组内全部成员
function lit(h: Any): boolean {
  const first = props.highlight?.[0]
  if (!first) return false
  if (first.startsWith('egrp-')) return h.groupId === first || h.objectId === first
  return h.objectId === first
}
function pick(h: Any): void {
  if (h.objectId) emit('pick', h.objectId, h.kind, h.opId)
}
</script>

<template>
  <div class="space-y-2">
    <div class="flex items-center gap-2 text-xs flex-wrap">
      <span v-if="caption" class="font-medium text-fg-dim mr-1">{{ caption }}</span>
      <template v-if="img">
        <button class="ctl !py-0.5" :class="{ 'ctl-on': mode === 'image' }" @click="mode = 'image'">现场图纸</button>
        <button class="ctl !py-0.5" :class="{ 'ctl-on': mode === 'schematic' }" @click="mode = 'schematic'">本体示意图</button>
      </template>
      <template v-if="mode === 'image' && img">
        <label class="flex items-center gap-1 text-fg-dim ml-1"><input v-model="showSpots" type="checkbox" /> 热区</label>
        <button class="ctl !px-2 !py-0.5 ml-1" title="缩小" @click="zoom = Math.max(0.5, +(zoom - 0.25).toFixed(2))">−</button>
        <span class="tabular-nums w-9 text-center">{{ Math.round(zoom * 100) }}%</span>
        <button class="ctl !px-2 !py-0.5" title="放大" @click="zoom = Math.min(3, +(zoom + 0.25).toFixed(2))">＋</button>
        <span class="flex-1" />
        <span class="text-fg-mute whitespace-nowrap" :title="img.source">
          <span class="inline-block w-2.5 h-2.5 border-2 border-[#ca8a04] align-middle" /> 已对应
          <span class="inline-block w-2.5 h-2.5 border-2 border-dashed border-[#a855f7] align-middle ml-2" /> 待确认
        </span>
      </template>
      <span v-else class="text-fg-mute">{{ img ? '' : '本画面暂无现场图纸，显示本体示意图' }}</span>
    </div>

    <div v-if="mode === 'image' && img" class="relative overflow-auto rounded-[10px] border border-line bg-black max-h-[calc(100vh-170px)]">
      <div class="relative" :style="{ width: `${zoom * 100}%`, minWidth: '900px' }">
        <img :src="img.url" class="block w-full select-none" draggable="false" />
        <svg class="absolute inset-0 w-full h-full" :viewBox="`0 0 ${img.width} ${img.height}`" preserveAspectRatio="none">
          <g v-for="(h, i) in img.hotspots" :key="i" class="cursor-pointer" @click="pick(h)" @mouseenter="hover = h" @mouseleave="hover = null">
            <rect :x="h.x" :y="h.y" :width="h.w" :height="h.h" rx="4"
                  :fill="lit(h) ? 'rgba(53,196,215,0.35)' : hover === h ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0)'"
                  :stroke="lit(h) ? '#35c4d7' : showSpots || hover === h ? (h.confirmed ? '#f2c744' : '#d17bff') : 'transparent'"
                  :stroke-width="lit(h) ? 4 : 2" :stroke-dasharray="h.confirmed ? '' : '6 4'" />
            <title>{{ h.name }}{{ h.otherOp ? '（属于其他画面）' : '' }}：{{ h.note }}</title>
          </g>
        </svg>
      </div>
      <div v-if="hover" class="sticky bottom-0 left-0 bg-ink-panel2/95 border-t border-line px-3 py-1.5 text-xs">
        <span class="font-medium">{{ hover.name }}</span>
        <span v-if="!hover.objectId" class="text-err ml-2">未对应到本体对象</span>
        <span v-else-if="hover.otherOp" class="text-info ml-2">点表归属其他画面</span>
        <span class="text-fg-mute ml-2">{{ hover.note }}</span>
      </div>
    </div>
    <div v-if="mode === 'image' && img?.unresolved?.length" class="text-xs text-err">未对应到本体的热区：{{ img.unresolved.join('、') }}</div>

    <PidCanvas v-if="mode === 'schematic'" :drawing="drawing" :highlight="highlight" @pick="(id: string, k: 'group' | 'equipment') => emit('pick', id, k)" />
  </div>
</template>
