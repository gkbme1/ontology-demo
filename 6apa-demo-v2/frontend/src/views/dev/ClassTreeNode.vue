<script setup lang="ts">
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
defineProps<{ node: Any; depth: number; sel: string; open: Record<string, boolean>; kw: string }>()
const emit = defineEmits<{ (e: 'pick', id: string): void; (e: 'toggle', id: string): void }>()
</script>

<template>
  <div>
    <div class="flex items-center gap-1 rounded px-1.5 py-[3px] cursor-pointer text-[13px]" :style="{ paddingLeft: `${6 + depth * 16}px` }"
         :class="sel === node.id ? 'bg-brand/10 text-brand font-semibold' : 'hover:bg-ink-panel2 text-fg-dim'" @click="emit('pick', node.id)">
      <span class="w-3 text-fg-mute text-[10px]" @click.stop="emit('toggle', node.id)">{{ node.children.length ? (open[node.id] || kw ? '▾' : '▸') : '•' }}</span>
      <span class="flex-1 truncate" :class="{ italic: node.abstract }">{{ node.name }}<template v-if="node.abstract">（抽象）</template></span>
      <span class="text-[10.5px] text-fg-mute tabular-nums">{{ node.instances || '—' }}</span>
    </div>
    <template v-if="open[node.id] || kw">
      <ClassTreeNode v-for="c in node.children" :key="c.id" :node="c" :depth="depth + 1" :sel="sel" :open="open" :kw="kw"
                     @pick="(id: string) => emit('pick', id)" @toggle="(id: string) => emit('toggle', id)" />
    </template>
  </div>
</template>
