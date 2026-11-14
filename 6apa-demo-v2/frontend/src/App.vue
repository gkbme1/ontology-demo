<script setup lang="ts">
/** 本体界面：左侧导航树，右侧显示区。 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { staticBackend } from '@/api/static'
import { bump, enterSegment, goBack, loadMeta, nav, navHistory, openGlobalGraph, openObject, select } from '@/composables/useNav'
import NavPanel from '@/components/NavPanel.vue'
import Overview from '@/views/Overview.vue'
import OpSections from '@/views/OpSections.vue'
import AssetPanel from '@/views/AssetPanel.vue'
import GenericProfile from '@/views/GenericProfile.vue'
import GlobalGraph from '@/views/GlobalGraph.vue'
import GlobalSections from '@/views/GlobalSections.vue'
import ConsistencyCheck from '@/views/ConsistencyCheck.vue'
import ReleaseCenter from '@/views/ReleaseCenter.vue'
import DevStudio from '@/views/DevStudio.vue'
import RuntimeView from '@/views/RuntimeView.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

const keyword = ref('')
const STAGES = [['dev', '开发态'], ['eng', '工程态'], ['run', '运行态']] as const
function switchStage(k: 'dev' | 'eng' | 'run'): void { if (nav.stage !== k) nav.stage = k }
// 页头显示当前发布版本（需求 SW-077 第 5 条、SW-088 第 2 条）
const currentRelease = ref<Any>(null)
async function loadRelease(): Promise<void> { try { currentRelease.value = (await api.releases()).current } catch { currentRelease.value = null } }
watch(() => nav.version, loadRelease)
const hits = ref<Any[]>([])
const hitTotal = ref(0)
const searched = ref(false)
// 结果按类型分组（需求 SW-078）
const KIND_LABEL: Record<string, string> = {
  segment: '工艺段', op: '工序 / 画面', group: '设备组', equipment: '设备', tag: '位号', phenomenon: '现象', condition: '工况',
  parameter: '工艺参数', stream: '物料流股', utility: '公用介质', quality: '质量指标'
}
const grouped = computed(() => {
  const out: { kind: string; items: Any[] }[] = []
  for (const h of hits.value) {
    const last = out[out.length - 1]
    if (last?.kind === h.kind) last.items.push(h)
    else out.push({ kind: h.kind, items: [h] })
  }
  return out
})
const ready = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    await loadMeta()
    select({ type: 'workshop', id: 'WS-105' }, 'WS-105')
    ready.value = true
    loadRelease()
  } catch (e) {
    error.value = `连接后端失败：${(e as Error).message}。请先启动后端（python3 -m backend.main，端口 8710）。`
  }
})

let timer: number | undefined
function onSearch(): void {
  window.clearTimeout(timer)
  timer = window.setTimeout(async () => {
    const kw = keyword.value.trim()
    const r = kw ? await api.search(kw) : { items: [], total: 0 }
    hits.value = r.items
    hitTotal.value = r.total
    searched.value = !!kw
  }, 200)
}
function go(h: Any): void {
  hits.value = []
  searched.value = false
  keyword.value = ''
  nav.page = h.graph ? 'graph' : 'browse'
  if (h.graph) openGlobalGraph(h.id, 1)
  else if (h.kind === 'segment') enterSegment(h.segmentId)
  else if (h.kind === 'op') enterSegment(h.segmentId, { type: 'op', id: h.opId, opId: h.opId })
  else if (h.kind === 'phenomenon' || h.kind === 'condition') {
    // 打开现象挂载对象的「现象/工况定义」页签
    if (h.anchorId) { enterSegment(h.segmentId, { type: 'object', id: h.anchorId, opId: h.opId, tab: 'phenomena' }); openObject(h.anchorId, h.opId, 'phenomena') }
    else select({ type: 'global:cond', opId: h.opId }, 'global:cond')
  } else {
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
      <!-- 三态切换（需求 SW-088）：开发态（类库）/ 工程态（实例组态）/ 运行态（运行服务） -->
      <div class="flex rounded-md border border-line overflow-hidden text-xs font-medium">
        <button v-for="[k, l] in STAGES" :key="k" class="px-2.5 py-1.5 border-l border-line first:border-l-0"
                :class="nav.stage === k ? 'bg-fg text-white' : 'bg-white text-fg-dim hover:text-brand'" @click="switchStage(k)">{{ l }}</button>
      </div>
      <button class="ctl !px-2" :disabled="!navHistory.size" :class="{ 'opacity-40': !navHistory.size }" title="后退到上一个查看的位置" @click="goBack">← 后退</button>
      <div v-show="nav.stage === 'eng'" class="flex rounded-md border border-line overflow-hidden text-xs font-medium">
        <button class="px-3 py-1.5" :class="nav.page === 'browse' ? 'bg-brand text-white' : 'bg-white text-fg-dim hover:text-brand'" @click="nav.page = 'browse'">本体浏览</button>
        <button class="px-3 py-1.5 border-l border-line" :class="nav.page === 'graph' ? 'bg-brand text-white' : 'bg-white text-fg-dim hover:text-brand'" @click="nav.page = 'graph'">◎ 全局图谱</button>
      </div>
      <div v-show="nav.stage === 'eng'" class="relative w-[380px]">
        <input v-model="keyword" class="inp w-full !py-1.5" placeholder="搜索工艺段 / 工序 / 设备 / 位号 / 现象 / 参数（支持拼音首字母）"
               @input="onSearch" @keydown.esc="hits = []; searched = false" />
        <div v-if="searched" class="absolute z-40 mt-1 w-[520px] panel max-h-[480px] overflow-auto shadow-xl">
          <div v-if="!hits.length" class="px-3 py-2 text-xs text-fg-mute">没有匹配的对象</div>
          <div v-else class="px-3 pt-1.5 text-[11px] text-fg-mute">共 {{ hitTotal }} 条{{ hitTotal > hits.length ? `，每类显示前 12 条` : '' }} · 名称 / 编码 / 位号 / 拼音首字母匹配</div>
          <template v-for="g in grouped" :key="g.kind">
            <div class="px-3 pt-2 pb-0.5 text-[11px] font-semibold text-fg-dim">{{ KIND_LABEL[g.kind] ?? g.kind }}</div>
            <div v-for="(h, i) in g.items" :key="i" class="tree-row !py-1.5" @click="go(h)">
              <span class="truncate flex-1">{{ h.label }}</span>
              <span class="text-[11px] text-fg-mute truncate max-w-[220px]">{{ h.hint }}</span>
            </div>
          </template>
        </div>
      </div>
      <span class="flex-1" />
      <span v-if="staticBackend" class="pill pill-info" title="离线单文件版：数据为导出时的快照，现象与根因关系的编辑保存在本浏览器">
        单文件版 · 数据快照 {{ staticBackend.info.generatedAt }}
      </span>
      <button class="pill cursor-pointer" :class="currentRelease ? 'pill-ok' : 'pill-mute'" title="当前发布版本；点击打开「发布与导出」"
              @click="nav.page = 'browse'; select({ type: 'global:release' }, 'global:release')">
        {{ currentRelease ? `发布版本 ${currentRelease.version} · ${currentRelease.time.slice(5, 16)}` : '未发布' }}
      </button>
      <span class="sim-tag" title="试算用的测点数据由内置模拟器生成">试算数据为模拟数据</span>
      <button class="ctl" title="现象 / 根因关系 / 计算组态恢复为种子数据" @click="reset">恢复种子数据</button>
    </header>

    <div v-if="error" class="empty m-6">{{ error }}</div>
    <main v-else-if="ready && nav.stage === 'dev'" class="flex-1 min-h-0 bg-ink"><DevStudio /></main>
    <main v-else-if="ready && nav.stage === 'run'" class="flex-1 min-h-0 bg-ink"><RuntimeView /></main>
    <main v-else-if="ready && nav.page === 'graph'" class="flex-1 min-h-0 bg-ink"><GlobalGraph /></main>
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
        <ConsistencyCheck v-else-if="kind() === 'global:check'" />
        <ReleaseCenter v-else-if="kind() === 'global:release'" />
        <GlobalSections v-else-if="kind().startsWith('global:')" :kind="kind()" :op-id="nav.selection.opId" />
        <GenericProfile v-else-if="kind() === 'domain-object'" :object-id="nav.selection.id!" />
        <div v-else-if="kind() === 'domain-pending'" class="empty m-6">「{{ nav.selection.label }}」待建：暂无数据源</div>
      </main>
    </div>
  </div>
</template>
