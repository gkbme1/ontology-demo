<script setup lang="ts">
/**
 * 资产导航树：本体域 → 分类 → 层级 → 实例，子节点按需从 /api/ontology/asset-tree 加载。
 * 搜索命中后按返回的 path 逐级展开并选中。树按"可见行"平铺渲染，大分支（几百台设备）也不卡。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { AssetNode, AssetSearchHit } from '@/api/types'

const props = defineProps<{ selectedObjectId?: string | null }>()
const emit = defineEmits<{ select: [objectId: string, node: AssetNode | null] }>()

const ROOT = '__root__'
const children = reactive<Record<string, AssetNode[]>>({})
const expanded = reactive(new Set<string>())
const loading = reactive(new Set<string>())
const selectedNodeId = ref<string | null>(null)
const error = ref<string | null>(null)

async function load(parent: string) {
  if (children[parent] || loading.has(parent)) return
  loading.add(parent)
  try {
    const res = await api.assetTree(parent === ROOT ? undefined : parent)
    children[parent] = res.items
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.delete(parent)
  }
}

async function toggle(node: AssetNode) {
  if (!node.hasChildren) return
  if (expanded.has(node.id)) {
    expanded.delete(node.id)
    return
  }
  expanded.add(node.id)
  await load(node.id)
}

function choose(node: AssetNode) {
  if (node.objectId) {
    selectedNodeId.value = node.id
    emit('select', node.objectId, node)
  }
  if (node.hasChildren && !expanded.has(node.id)) void toggle(node)
}

interface Row { node: AssetNode; depth: number }
const rows = computed<Row[]>(() => {
  const out: Row[] = []
  const walk = (parent: string, depth: number) => {
    for (const node of children[parent] ?? []) {
      out.push({ node, depth })
      if (expanded.has(node.id)) walk(node.id, depth + 1)
    }
  }
  walk(ROOT, 0)
  return out
})

/** 按路径逐级展开（搜索命中、外部跳转时用），最后一级选中。 */
async function expandPath(path: string[]) {
  await load(ROOT)
  for (const id of path.slice(0, -1)) {
    expanded.add(id)
    await load(id)
  }
  selectedNodeId.value = path[path.length - 1] ?? null
  requestAnimationFrame(() => {
    document.querySelector(`[data-node-id="${CSS.escape(selectedNodeId.value ?? '')}"]`)?.scrollIntoView({ block: 'center' })
  })
}
defineExpose({ expandPath })

// ---------------------------------------------------------------- 搜索

const keyword = ref('')
const hits = ref<AssetSearchHit[]>([])
const hitTotal = ref(0)
const searching = ref(false)
let timer: number | undefined

watch(keyword, (value) => {
  window.clearTimeout(timer)
  if (!value.trim()) {
    hits.value = []
    hitTotal.value = 0
    return
  }
  timer = window.setTimeout(async () => {
    searching.value = true
    try {
      const res = await api.assetSearch(value.trim())
      hits.value = res.items
      hitTotal.value = res.total
    } finally {
      searching.value = false
    }
  }, 250)
})

async function openHit(hit: AssetSearchHit) {
  keyword.value = ''
  await expandPath(hit.path)
  emit('select', hit.objectId, null)
}

const KIND_ICON: Record<string, string> = {
  domain: '◆', area: '▤', class: '▣', type: '▢', group: '◇', bucket: '▫', equipment: '●', entity: '○'
}
const KIND_LABEL: Record<string, string> = {
  equipment: '设备', group: '设备组', area: '工段', entity: '工艺对象'
}

onMounted(() => load(ROOT))
</script>

<template>
  <div class="flex flex-col h-full min-h-0">
    <div class="px-3 pt-3 pb-2 border-b border-line-soft">
      <div class="relative">
        <input
          v-model="keyword"
          type="search"
          placeholder="搜索设备 / 位号 / 工段 / 工艺量…"
          class="w-full px-3 py-1.5 rounded-md border border-line bg-ink-panel2 text-[12.5px] text-fg placeholder:text-fg-mute
                 focus:outline-none focus:border-brand"
        />
        <div
          v-if="keyword.trim()"
          class="absolute z-20 left-0 right-0 mt-1 max-h-[60vh] overflow-y-auto rounded-md border border-line bg-ink-raised shadow-xl"
        >
          <div v-if="searching" class="px-3 py-2 text-fg-mute text-xs">搜索中…</div>
          <div v-else-if="!hits.length" class="px-3 py-2 text-fg-mute text-xs">没有匹配的对象</div>
          <button
            v-for="hit in hits" :key="hit.objectId + hit.hint"
            class="block w-full text-left px-3 py-1.5 hover:bg-brand/[0.13] border-b border-line-soft last:border-0"
            @click="openHit(hit)"
          >
            <div class="flex items-center gap-2 text-[12.5px]">
              <span class="pill pill-plain">{{ KIND_LABEL[hit.kind] ?? hit.kind }}</span>
              <span class="text-fg truncate">{{ hit.label }}</span>
            </div>
            <div class="text-fg-mute text-[11px] truncate mt-0.5">{{ hit.hint }}</div>
          </button>
          <div v-if="hitTotal > hits.length" class="px-3 py-1.5 text-fg-mute text-[11px]">共 {{ hitTotal }} 条，仅显示前 {{ hits.length }} 条</div>
        </div>
      </div>
    </div>

    <div v-if="error" class="m-3 px-3 py-2 border-l-2 border-err bg-err/[0.07] text-fg-dim text-xs">{{ error }}</div>

    <div class="flex-1 min-h-0 overflow-y-auto py-1.5 select-none">
      <div v-if="!rows.length && loading.has(ROOT)" class="px-4 py-3 text-fg-mute text-xs">加载中…</div>
      <div
        v-for="{ node, depth } in rows" :key="node.id"
        :data-node-id="node.id"
        class="group flex items-center gap-1.5 pr-2 py-[3px] cursor-pointer text-[12.5px] border-l-2"
        :class="[
          selectedNodeId === node.id || (node.objectId && node.objectId === props.selectedObjectId && !selectedNodeId)
            ? 'bg-brand/[0.13] border-brand text-fg'
            : 'border-transparent hover:bg-ink-panel2',
          node.kind === 'domain' && !node.hasChildren ? 'opacity-50 cursor-default' : ''
        ]"
        :style="{ paddingLeft: `${8 + depth * 14}px` }"
        :title="node.hint ?? ''"
        @click="choose(node)"
      >
        <span
          class="w-3.5 shrink-0 text-center text-fg-mute text-[10px]"
          @click.stop="toggle(node)"
        >{{ node.hasChildren ? (loading.has(node.id) ? '…' : expanded.has(node.id) ? '▾' : '▸') : '' }}</span>
        <span
          class="shrink-0 text-[10px]"
          :class="{
            'text-brand': node.kind === 'domain',
            'text-equip': node.kind === 'equipment' || node.kind === 'group',
            'text-prop': node.kind === 'entity',
            'text-info': node.kind === 'area',
            'text-fg-mute': ['class', 'type', 'bucket'].includes(node.kind)
          }"
        >{{ KIND_ICON[node.kind] ?? '·' }}</span>
        <span
          class="truncate"
          :class="node.kind === 'domain' ? 'font-medium text-fg' : node.objectId ? 'text-fg' : 'text-fg-dim'"
        >{{ node.label }}</span>
        <span class="ml-auto flex items-center gap-1 shrink-0">
          <span v-if="node.badge" class="pill pill-plain !text-[10px]">{{ node.badge }}</span>
          <span v-if="node.count !== undefined" class="font-mono text-[10.5px] text-fg-mute tabular-nums">{{ node.count }}</span>
        </span>
      </div>
    </div>
  </div>
</template>
