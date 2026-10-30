<script setup lang="ts">
/**
 * 类间关系示意图：对象居中，所属在上、上游在左、下游在右、部件 / 实例在下。
 * 每侧最多画 4 个，其余以"+N"汇总，完整清单见下方关系表。点击带 ID 的节点可跳转到该对象。
 */
import { computed } from 'vue'
import type { ProfileRelation } from '@/api/types'

const props = defineProps<{ name: string; className: string; relations: ProfileRelation[] }>()
const emit = defineEmits<{ open: [objectId: string] }>()

const W = 640
const H = 380
const CX = W / 2
const CY = H / 2
const BOX_W = 132
const BOX_H = 34
const PER_SIDE = 4

type Side = 'top' | 'left' | 'right' | 'bottom'
const SIDE_OF_ROLE: Record<string, Side> = {
  所属: 'top', 上游: 'left', 报警联锁: 'left', 下游: 'right', 控制: 'right',
  部件: 'bottom', 同组实例: 'bottom', 包含实例: 'bottom'
}

interface Placed { rel: ProfileRelation; x: number; y: number; w: number }
interface SideLayout { items: Placed[]; overflow: number; overflowAt: { x: number; y: number } }

const layout = computed(() => {
  const bySide: Record<Side, ProfileRelation[]> = { top: [], left: [], right: [], bottom: [] }
  for (const rel of props.relations) bySide[SIDE_OF_ROLE[rel.role] ?? 'bottom'].push(rel)
  const out = {} as Record<Side, SideLayout>
  ;(Object.keys(bySide) as Side[]).forEach((side) => {
    const list = bySide[side]
    const shown = list.slice(0, PER_SIDE)
    const n = shown.length + (list.length > PER_SIDE ? 1 : 0)
    const items: Placed[] = []
    // 上下两侧横排，节点多时按间距收窄，避免相邻框重叠
    const w = side === 'top' || side === 'bottom' ? Math.min(BOX_W, (W - 40) / Math.max(n, 1) - 10) : BOX_W
    const pos = (i: number) => {
      if (side === 'top' || side === 'bottom') {
        const gap = (W - 40) / Math.max(n, 1)
        return { x: 20 + gap * i + gap / 2, y: side === 'top' ? 34 : H - 34 }
      }
      const gap = (H - 150) / Math.max(n, 1)
      return { x: side === 'left' ? 82 : W - 82, y: 75 + gap * i + gap / 2 }
    }
    shown.forEach((rel, i) => items.push({ rel, w, ...pos(i) }))
    out[side] = { items, overflow: list.length - shown.length, overflowAt: pos(shown.length) }
  })
  return out
})

function edgeEnd(x: number, y: number) {
  // 线从中心框边缘连到目标框边缘，避免压字
  const dx = x - CX
  const dy = y - CY
  const scale = Math.min(Math.abs((BOX_W / 2 + 14) / (dx || 1e-6)), Math.abs((BOX_H / 2 + 10) / (dy || 1e-6)))
  return { x1: CX + dx * scale, y1: CY + dy * scale }
}

function clip(text: string, n = 9) {
  return text.length > n ? text.slice(0, n) + '…' : text
}

const ROLE_COLOR: Record<string, string> = {
  所属: '#4c8dff', 上游: '#3fcf8e', 下游: '#35c4d7', 控制: '#ffb86b', 报警联锁: '#f2557a',
  部件: '#b07cff', 同组实例: '#ffc08a', 包含实例: '#ffc08a'
}
</script>

<template>
  <svg :viewBox="`0 0 ${W} ${H}`" class="w-full h-auto" role="img" :aria-label="`${name} 类间关系`">
    <template v-for="(side, key) in layout" :key="key">
      <g v-for="p in side.items" :key="p.rel.target + p.rel.role + p.rel.predicate">
        <line
          :x1="edgeEnd(p.x, p.y).x1" :y1="edgeEnd(p.x, p.y).y1" :x2="p.x" :y2="p.y"
          :stroke="ROLE_COLOR[p.rel.role] ?? '#6f819e'" stroke-width="1.4" stroke-opacity="0.75"
        />
        <text
          :x="(edgeEnd(p.x, p.y).x1 + p.x) / 2" :y="(edgeEnd(p.x, p.y).y1 + p.y) / 2 - 4"
          text-anchor="middle" class="fill-fg-mute" font-size="10.5"
        >{{ clip(p.rel.role === '所属' ? (p.rel.predicate ?? '属于') : p.rel.role, 6) }}</text>
        <g
          :class="p.rel.targetId ? 'cursor-pointer' : ''"
          @click="p.rel.targetId && emit('open', p.rel.targetId)"
        >
          <title>{{ p.rel.role }} · {{ p.rel.predicate }} · {{ p.rel.target }}{{ p.rel.mechanism ? '\n' + p.rel.mechanism : '' }}</title>
          <rect
            :x="p.x - p.w / 2" :y="p.y - BOX_H / 2" :width="p.w" :height="BOX_H" rx="7"
            fill="#16233a" :stroke="ROLE_COLOR[p.rel.role] ?? '#23344f'" stroke-width="1.2"
          />
          <text :x="p.x" :y="p.y + 4" text-anchor="middle" class="fill-fg" font-size="12">{{ clip(p.rel.target, Math.floor(p.w / 13)) }}</text>
        </g>
      </g>
      <text
        v-if="side.overflow > 0"
        :x="side.overflowAt.x" :y="side.overflowAt.y + 4" text-anchor="middle" class="fill-fg-mute" font-size="11.5"
      >+{{ side.overflow }} 项</text>
    </template>

    <rect :x="CX - BOX_W / 2 - 14" :y="CY - BOX_H / 2 - 10" :width="BOX_W + 28" :height="BOX_H + 20" rx="10"
          fill="#155e75" stroke="#35c4d7" stroke-width="1.6" />
    <text :x="CX" :y="CY - 2" text-anchor="middle" fill="#ffffff" font-size="14" font-weight="600">{{ clip(name, 11) }}</text>
    <text :x="CX" :y="CY + 15" text-anchor="middle" fill="#bfe9f0" font-size="10.5">{{ clip(className, 13) }}</text>
  </svg>
</template>
