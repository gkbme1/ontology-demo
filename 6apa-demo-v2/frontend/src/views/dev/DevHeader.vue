<script setup lang="ts">
/** 开发态页头右侧：当前类库与版本状态、导出类库包、发布类库（图 4-3(a) ②）。 */
import { api } from '@/api/client'
import { act, lib, reloadLib } from '@/composables/useClassLib'
if (!lib.summary) reloadLib()
async function exportPkg(): Promise<void> {
  try { await api.download('/classlib/export') } catch (e) { alert((e as Error).message) }
}
async function publish(): Promise<void> {
  const v = lib.summary?.current
  if (!v) return
  const note = prompt(`发布类库 ${v.version}？发布后只读，修改须基于新版本进行。\n发布说明：`, '')
  if (note === null) return
  await act(() => api.clPublish(note), `已发布类库 ${v.version}`)
}
</script>

<template>
  <span v-if="lib.summary" class="rounded-md border px-2.5 py-1 text-xs"
        :class="lib.summary.current.status === '编辑中' ? 'border-warn/50 bg-warn/5 text-warn' : 'border-ok/40 bg-ok/5 text-ok'">
    类库：{{ lib.summary.library.name }} {{ lib.summary.current.version }} · {{ lib.summary.current.status }}
  </span>
  <button class="btn" @click="exportPkg">导出类库包</button>
  <button class="btn btn-primary" :disabled="lib.summary?.current?.status !== '编辑中'" @click="publish">发布类库</button>
</template>
