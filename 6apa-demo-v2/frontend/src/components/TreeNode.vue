<script setup lang="ts">
/** 通用树节点：单击选中、双击（由父级决定含义）、展开收起、可选懒加载子节点。 */
import { computed, ref, watch } from 'vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

const props = defineProps<{
  node: Any
  depth?: number
  activeKey: string
  nodeKey: (n: Any) => string
  loader?: (n: Any) => Promise<Any[]>
  expandKeys?: Set<string>
}>()
const emit = defineEmits<{ (e: 'select', n: Any): void; (e: 'dbl', n: Any): void }>()

const depth = computed(() => props.depth ?? 0)
const key = computed(() => props.nodeKey(props.node))
const loaded = ref<Any[] | null>(props.node.children ?? null)
const open = ref(props.expandKeys?.has(key.value) ?? false)
const loading = ref(false)
const hasChildren = computed(() => (loaded.value ? loaded.value.length > 0 : !!props.node.hasChildren))

watch(() => props.node.children, (c) => { if (c) loaded.value = c })
watch(() => props.expandKeys?.has(key.value), (v) => { if (v) open.value = true })

async function toggle(): Promise<void> {
  if (!hasChildren.value) return
  if (!open.value && !loaded.value && props.loader) {
    loading.value = true
    try { loaded.value = await props.loader(props.node) } finally { loading.value = false }
  }
  open.value = !open.value
}

function onClick(): void {
  emit('select', props.node)
}

const ICON: Record<string, string> = {
  workshop: '▣', segment: '◧', op: '▤', group: '▢', equipment: '•', calc: 'ƒ',
  'section:devices': '⚙', 'section:calc': 'Σ', 'section:cond': '⚠', 'section:docs': '☰',
  domain: '◆', class: '▢', type: '▢', area: '◧', entity: '•'
}
const icon = computed(() => ICON[props.node.kind] ?? '·')
</script>

<template>
  <div>
    <div
      class="tree-row"
      :class="{ 'tree-on': activeKey === key }"
      :style="{ paddingLeft: `${8 + depth * 14}px` }"
      :title="node.hint || node.description || node.label"
      @click="onClick"
      @dblclick.stop="emit('dbl', node)"
    >
      <span class="w-3 text-center text-fg-mute" @click.stop="toggle">
        <template v-if="hasChildren">{{ loading ? '…' : open ? '▾' : '▸' }}</template>
      </span>
      <span class="w-3 text-center" :class="node.kind === 'op' ? 'text-brand' : 'text-fg-mute'">{{ icon }}</span>
      <span class="truncate flex-1" :class="{ 'italic text-fg-mute': node.ungrouped }">{{ node.label }}</span>
      <span v-if="node.status && node.status !== '已确认'" class="pill pill-warn" title="拆分口径待工艺确认">草案</span>
      <span v-if="node.count !== undefined && node.count !== null" class="text-[10.5px] text-fg-mute tabular-nums">{{ node.count }}</span>
    </div>
    <div v-if="open && loaded">
      <TreeNode
        v-for="child in loaded"
        :key="nodeKey(child)"
        :node="child"
        :depth="depth + 1"
        :active-key="activeKey"
        :node-key="nodeKey"
        :loader="loader"
        :expand-keys="expandKeys"
        @select="(n: Any) => emit('select', n)"
        @dbl="(n: Any) => emit('dbl', n)"
      />
    </div>
  </div>
</template>
