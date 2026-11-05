<script setup lang="ts">
/** 本体界面：左侧导航树，右侧显示区。 */
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { staticBackend } from '@/api/static'
import { bump, enterSegment, loadMeta, nav, openObject, select } from '@/composables/useNav'
import NavPanel from '@/components/NavPanel.vue'
import Overview from '@/views/Overview.vue'
import OpSections from '@/views/OpSections.vue'
import AssetPanel from '@/views/AssetPanel.vue'
import GenericProfile from '@/views/GenericProfile.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

const keyword = ref('')
const hits = ref<Any[]>([])
const ready = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    await loadMeta()
    select({ type: 'workshop', id: 'WS-105' }, 'WS-105')
    ready.value = true
  } catch (e) {
    error.value = `连接后端失败：${(e as Error).message}。请先启动后端（python3 -m backend.main，端口 8710）。`
  }
})

let timer: number | undefined
function onSearch(): void {
  window.clearTimeout(timer)
  timer = window.setTimeout(async () => {
    hits.value = keyword.value.trim() ? (await api.search(keyword.value.trim())).items : []
  }, 200)
}
function go(h: Any): void {
  hits.value = []
  keyword.value = ''
  if (h.kind === 'op') enterSegment(h.segmentId, { type: 'op', id: h.opId, opId: h.opId })
  else if (h.kind === 'phenomenon') enterSegment(h.segmentId, { type: 'section:cond', id: h.opId, opId: h.opId })
  else {
    enterSegment(h.segmentId, { type: 'object', id: h.id, opId: h.opId })
    openObject(h.id, h.opId)
  }
}
async function reset(): Promise<void> {
  if (!confirm('把现象、根因关系、计算组态恢复为种子数据？所有在线编辑都会丢失。')) return
  await api.resetStore()
  bump()
}
const SECTION_KINDS = ['drawing', 'section:devices', 'section:calc', 'section:cond', 'section:docs', 'calc']
const kind = (): string => nav.selection.type
</script>

<template>
  <div class="h-full flex flex-col">
    <header class="flex items-center gap-4 px-4 h-12 border-b border-line bg-ink-panel2 shrink-0">
      <div class="font-semibold tracking-wide"><span class="text-brand">◆</span> 6APA 本体 <span class="text-fg-mute text-xs font-normal">v2 · 105 车间</span></div>
      <div class="relative w-[360px]">
        <input v-model="keyword" class="inp w-full !py-1.5" placeholder="搜索工序 / 设备组 / 设备 / 位号 / 现象" @input="onSearch" @keydown.esc="hits = []" />
        <div v-if="hits.length" class="absolute z-40 mt-1 w-full panel max-h-[420px] overflow-auto shadow-xl">
          <div v-for="(h, i) in hits" :key="i" class="tree-row !py-1.5" @click="go(h)">
            <span class="pill pill-plain">{{ ({ op: '工序', group: '设备组', equipment: '设备', tag: '位号', phenomenon: '现象' } as Record<string, string>)[h.kind] }}</span>
            <span class="truncate flex-1">{{ h.label }}</span>
            <span class="text-[11px] text-fg-mute truncate max-w-[140px]">{{ h.hint }}</span>
          </div>
        </div>
      </div>
      <span class="flex-1" />
      <span v-if="staticBackend" class="pill pill-info" title="离线单文件版：数据为导出时的快照，现象与根因关系的编辑保存在本浏览器">
        单文件版 · 数据快照 {{ staticBackend.info.generatedAt }}
      </span>
      <span class="sim-tag" title="试算用的测点数据由内置模拟器生成">试算数据为模拟数据</span>
      <button class="ctl" title="现象 / 根因关系 / 计算组态恢复为种子数据" @click="reset">恢复种子数据</button>
    </header>

    <div v-if="error" class="empty m-6">{{ error }}</div>
    <div v-else-if="ready" class="flex-1 grid grid-cols-[320px_1fr] min-h-0">
      <NavPanel />
      <main class="min-h-0 overflow-hidden bg-ink">
        <Overview v-if="kind() === 'workshop' || kind() === 'none'" kind="workshop" />
        <Overview v-else-if="kind() === 'segment'" kind="segment" :id="nav.selection.id" />
        <Overview v-else-if="kind() === 'op'" kind="op" :id="nav.selection.id" />
        <OpSections v-else-if="SECTION_KINDS.includes(kind())" :kind="kind()" :op-id="nav.selection.opId!"
                    :calc-id="kind() === 'calc' ? nav.selection.id : undefined" />
        <AssetPanel v-else-if="kind() === 'object'" :key="`${nav.selection.id}|${nav.selection.opId}`"
                    :object-id="nav.selection.id!" :op-id="nav.selection.opId" :initial-tab="nav.selection.tab" />
        <GenericProfile v-else-if="kind() === 'domain-object'" :object-id="nav.selection.id!" />
        <div v-else-if="kind() === 'domain-pending'" class="empty m-6">「{{ nav.selection.label }}」待建：暂无数据源</div>
      </main>
    </div>
  </div>
</template>
