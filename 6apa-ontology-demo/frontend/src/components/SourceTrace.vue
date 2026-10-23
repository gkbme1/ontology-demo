<script setup lang="ts">
/** 数据来源追溯块（需求文档第二十二章）：文件 / Sheet / 行号 / 原始字段 / 原始值。 */
import { computed } from 'vue'
import type { Provenance, SourceType } from '@/api/types'

const props = defineProps<{
  title?: string
  source?: Provenance | null
  sourceType?: SourceType | string | null
}>()

const rows = computed(() => {
  const s = props.source
  if (!s) return []
  const out: [string, string][] = []
  if (props.sourceType) out.push(['sourceType', String(props.sourceType)])
  if (s.file) out.push(['文件', s.file])
  if (s.sheet) out.push(['Sheet', s.sheet])
  if (s.row) out.push(['行号', String(s.row)])
  if (s.field) out.push(['原始字段', s.field])
  if (s.value) out.push(['原始值', s.value])
  return out
})
</script>

<template>
  <div v-if="rows.length" class="border border-dashed border-line rounded-md bg-info/[0.05] px-3 py-2.5 text-[11.5px]">
    <div class="text-info text-[10.5px] tracking-widest uppercase mb-1.5">{{ title ?? '数据来源' }}</div>
    <dl class="kv">
      <template v-for="[k, v] in rows" :key="k">
        <dt>{{ k }}</dt>
        <dd class="font-mono">{{ v }}</dd>
      </template>
    </dl>
  </div>
</template>
