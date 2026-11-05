<script setup lang="ts">
/**
 * 左侧导航：分类切换 + 树。
 * 空间层级第一屏只有车间与工艺段；双击工艺段进入工艺段内的层级树，「返回车间导航」退回。
 * 工艺段内：单击工序选中，双击工序打开图纸。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { backToWorkshop, enterSegment, nav, openDrawing, openObject, select } from '@/composables/useNav'
import TreeNode from './TreeNode.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

const space = ref<Any>(null)
const segTree = ref<Any>(null)
const domainRoots = ref<Any[]>([])
const domainInfo = ref<Any>(null)
const loading = ref(false)
const error = ref('')

const categories = computed(() => nav.meta?.categories ?? [])
const expandKeys = computed(() => {
  const s = new Set<string>()
  if (nav.selection.opId) {
    s.add(nav.selection.opId)
    s.add(`${nav.selection.opId}|devices`)
    const id = nav.selection.id
    if (id && nav.selection.type === 'object') {
      // 展开设备所在的设备组
      for (const op of segTree.value?.items ?? []) {
        for (const sec of op.children ?? []) {
          for (const g of sec.children ?? []) {
            if ((g.children ?? []).some((c: Any) => c.objectId === id)) s.add(g.id)
          }
        }
      }
    }
  }
  return s
})

async function loadSpace(): Promise<void> {
  space.value = await api.navSpace()
}
async function loadSegment(): Promise<void> {
  if (!nav.segmentId) return
  loading.value = true
  try { segTree.value = await api.navSegment(nav.segmentId) } finally { loading.value = false }
}
async function loadDomain(): Promise<void> {
  const r = await api.navDomain(nav.category)
  domainInfo.value = r
  domainRoots.value = r.items ?? []
}

onMounted(async () => {
  try { await loadSpace() } catch (e) { error.value = String(e) }
})
watch(() => [nav.mode, nav.segmentId], () => { if (nav.mode === 'segment') loadSegment() }, { immediate: true })
watch(() => nav.category, (c) => { if (c !== 'space') loadDomain() })
watch(() => nav.version, () => { if (nav.mode === 'segment') loadSegment() })

const keyOf = (n: Any) => n.id as string

function onSpaceSelect(n: Any): void {
  if (n.kind === 'workshop') select({ type: 'workshop', id: n.id }, n.id)
  else if (n.kind === 'segment') select({ type: 'segment', id: n.id }, n.id)
}
function onSpaceDbl(n: Any): void {
  if (n.kind === 'segment') enterSegment(n.id)
}

function onSegSelect(n: Any): void {
  if (n.kind === 'op') select({ type: 'op', id: n.opId, opId: n.opId }, n.id)
  else if (n.kind?.startsWith('section:')) select({ type: n.kind, id: n.opId, opId: n.opId }, n.id)
  else if (n.kind === 'calc') select({ type: 'calc', id: n.calcId, opId: n.opId }, n.id)
  else if (n.kind === 'group' || n.kind === 'equipment') openObject(n.objectId, n.opId)
}
function onSegDbl(n: Any): void {
  if (n.kind === 'op') openDrawing(n.opId)
}

async function domainLoader(n: Any): Promise<Any[]> {
  const r = await api.navDomain(nav.category, n.id)
  return r.items ?? []
}
function onDomainSelect(n: Any): void {
  const raw = String(n.id).split('|').pop() ?? n.id
  if (/^(equip-|egrp-|robj-|area-)/.test(raw)) select({ type: 'domain-object', id: raw, label: n.label }, n.id)
  else nav.activeKey = n.id
}

function pickCategory(key: string): void {
  nav.category = key
  const cat = categories.value.find((c: Any) => c.key === key)
  if (cat?.pending) select({ type: 'domain-pending', label: cat.label })
}

const segmentActiveKey = computed(() => {
  const s = nav.selection
  if (s.type === 'object' && s.opId) return `${s.opId}|${s.id}`
  if (s.type === 'drawing' || s.type === 'op') return s.opId ?? ''
  return nav.activeKey
})
</script>

<template>
  <aside class="flex flex-col h-full border-r border-line bg-ink-panel min-h-0">
    <!-- 分类 -->
    <div class="px-3 pt-3 pb-2 border-b border-line-soft">
      <div class="flex flex-wrap gap-1">
        <button
          v-for="c in categories"
          :key="c.key"
          class="ctl !px-2 !py-0.5"
          :class="{ 'ctl-on': nav.category === c.key, 'opacity-60': c.pending }"
          :title="c.hint"
          @click="pickCategory(c.key)"
        >
          {{ c.label }}
        </button>
      </div>
    </div>

    <div class="flex-1 overflow-auto py-2 min-h-0">
      <div v-if="error" class="empty mx-3">{{ error }}</div>

      <!-- 空间层级 · 车间导航 -->
      <template v-if="nav.category === 'space' && nav.mode === 'root' && space">
        <div class="px-3 pb-1 text-[11px] text-fg-mute">双击工艺段进入工艺段内的层级树</div>
        <TreeNode
          v-for="ws in space.items"
          :key="ws.id"
          :node="ws"
          :active-key="nav.activeKey"
          :node-key="keyOf"
          :expand-keys="new Set([ws.id])"
          @select="onSpaceSelect"
          @dbl="onSpaceDbl"
        />
      </template>

      <!-- 空间层级 · 工艺段内 -->
      <template v-if="nav.category === 'space' && nav.mode === 'segment'">
        <div class="px-3 pb-2 flex items-center gap-2">
          <button class="btn !py-1" @click="backToWorkshop">← 返回车间导航</button>
          <span class="font-semibold truncate">{{ segTree?.segment?.name }}</span>
        </div>
        <div class="px-3 pb-1 text-[11px] text-fg-mute">单击工序选中，双击工序打开图纸</div>
        <div v-if="loading && !segTree" class="px-3 text-fg-mute">加载中…</div>
        <TreeNode
          v-for="op in segTree?.items ?? []"
          :key="op.id"
          :node="op"
          :active-key="segmentActiveKey"
          :node-key="keyOf"
          :expand-keys="expandKeys"
          @select="onSegSelect"
          @dbl="onSegDbl"
        />
      </template>

      <!-- 其他分类 -->
      <template v-if="nav.category !== 'space'">
        <div v-if="domainInfo?.pending" class="empty mx-3">「{{ domainInfo.category.label }}」待建：暂无数据源</div>
        <div v-else-if="domainInfo" class="px-3 pb-1 text-[11px] text-fg-mute">{{ domainInfo.category.hint }}</div>
        <TreeNode
          v-for="n in domainRoots"
          :key="n.id"
          :node="n"
          :active-key="nav.activeKey"
          :node-key="keyOf"
          :loader="domainLoader"
          @select="onDomainSelect"
        />
      </template>
    </div>
  </aside>
</template>
