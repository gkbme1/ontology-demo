<script setup lang="ts">
/** 批量变更状态（需求 SW-062 第 2 条）：勾选若干现象 / 导致关系后批量设为 生效 / 草案 / 停用。 */
import { api } from '@/api/client'
import { bump } from '@/composables/useNav'

const props = defineProps<{ kind: 'phenomena' | 'links' | 'calculations'; ids: string[] }>()
const emit = defineEmits<{ (e: 'done'): void }>()
async function set(status: string): Promise<void> {
  try {
    const r = await api.statusBatch({ kind: props.kind, ids: props.ids, status })
    alert(`已将 ${r.changed} 条设为「${status === '草案·待工艺确认' ? '草案' : status}」`)
    bump()
    emit('done')
  } catch (e) {
    alert((e as Error).message)
  }
}
</script>

<template>
  <div v-if="ids.length" class="flex items-center gap-2 text-xs rounded-md border border-brand/40 bg-[#ecf8fa] px-3 py-1.5">
    <span>已选 {{ ids.length }} 条，批量设为：</span>
    <button class="ctl" @click="set('生效')">生效</button>
    <button class="ctl" @click="set('草案·待工艺确认')">草案</button>
    <button class="ctl" @click="set('停用')">停用</button>
    <span class="text-fg-mute">只有「生效」的进入发布版本</span>
  </div>
</template>
