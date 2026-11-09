<script setup lang="ts">
/**
 * 全局（跨设备 / 跨工艺）：计算组态、算法库、工况与根因、文档提取。
 * 不挂在某道画面下；顶部按 单元 / 画面 筛选范围（从画面页跳过来时带上该画面）。
 */
import { computed, ref, watch } from 'vue'
import { marked } from 'marked'
import { api } from '@/api/client'
import { nav, select } from '@/composables/useNav'
import CalcPanel from '@/components/CalcPanel.vue'
import PhenomenaPanel from '@/components/causal/PhenomenaPanel.vue'
import CausalPanel from '@/components/causal/CausalPanel.vue'
import Modal from '@/components/Modal.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ kind: string; opId?: string }>()

const SECTIONS: { key: string; label: string }[] = [
  { key: 'global:calc', label: '计算组态' }, { key: 'global:algo', label: '算法库' },
  { key: 'global:cond', label: '工况与根因' }, { key: 'global:docs', label: '文档提取' }
]
const space = ref<Any>(null)
const segTrees = ref<Record<string, Any>>({})
const seg = ref('')
const op = ref(props.opId ?? '')
const calcs = ref<Any[]>([])
const algos = ref<Any>(null)
const cond = ref<Any>(null)
const docs = ref<Any>(null)
const docView = ref<Any>(null)
const condTab = ref<'phenomena' | 'causal'>('phenomena')
const onlyCross = ref(false)

const segments = computed(() => (space.value?.items?.[0]?.children ?? []).filter((c: Any) => c.kind === 'segment'))
const opOptions = computed(() => {
  const out: Any[] = []
  for (const s of segments.value) if (!seg.value || seg.value === s.id) for (const o of segTrees.value[s.id]?.items ?? []) out.push({ ...o, seg: s.id })
  return out
})

async function ensureTree(): Promise<void> {
  if (!space.value) space.value = await api.navSpace()
  for (const s of segments.value) if (!segTrees.value[s.id]) segTrees.value[s.id] = await api.navSegment(s.id)
  if (op.value && !seg.value) seg.value = opOptions.value.find((o: Any) => o.opId === op.value)?.seg ?? ''
}
async function load(): Promise<void> {
  await ensureTree()
  const q = { seg: op.value ? undefined : seg.value || undefined, op: op.value || undefined }
  if (props.kind === 'global:calc') calcs.value = (await api.scopeCalculations(q)).items
  if (props.kind === 'global:algo') algos.value = await api.algorithms()
  if (props.kind === 'global:cond') cond.value = await api.scopeConditions(q)
  if (props.kind === 'global:docs') docs.value = await api.scopeDocuments(q)
}
watch(() => [props.kind, nav.version], load, { immediate: true })
watch(() => props.opId, (v) => { if (v) { op.value = v; load() } })
watch([seg, op], load)
function onSeg(): void { op.value = '' }

const scopeText = computed(() => op.value ? opOptions.value.find((o: Any) => o.opId === op.value)?.label
  : seg.value ? segments.value.find((s: Any) => s.id === seg.value)?.label : '全装置')
const links = computed(() => (cond.value?.links ?? []).filter((l: Any) => !onlyCross.value || l.crossDevice))
async function openDoc(id: string): Promise<void> { docView.value = await api.document(id) }
const docHtml = computed(() => (docView.value ? (marked.parse(docView.value.content) as string) : ''))
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-line bg-ink-panel shrink-0">
      <h2 class="text-[16px] font-semibold whitespace-nowrap">{{ SECTIONS.find((s) => s.key === kind)?.label }}</h2>
      <span class="pill pill-info">全局 · 跨设备 / 跨工艺</span>
      <template v-if="kind !== 'global:algo'">
        <span class="text-xs text-fg-mute ml-2">范围</span>
        <select v-model="seg" class="inp" @change="onSeg"><option value="">全装置</option><option v-for="s in segments" :key="s.id" :value="s.id">{{ s.label }}</option></select>
        <select v-model="op" class="inp"><option value="">全部画面</option><option v-for="o in opOptions" :key="o.opId" :value="o.opId">{{ o.label }}</option></select>
      </template>
      <span class="flex-1" />
      <button v-for="s in SECTIONS" :key="s.key" class="asset-tab !py-0.5" :class="{ 'asset-tab-on': kind === s.key }"
              @click="select({ type: s.key as Any, opId: op || undefined }, s.key)">{{ s.label }}</button>
    </div>

    <div class="flex-1 overflow-auto px-4 pb-4 space-y-3 min-h-0">
      <div class="h-0" />

      <!-- 计算组态 -->
      <template v-if="kind === 'global:calc'">
        <div class="text-xs text-fg-mute">
          {{ scopeText }}：{{ calcs.length }} 条计算组态。计算组态只引用算法库里的算法，并把算法的每个参数绑定到本体（本对象参数 / 设备组全部成员的参数 / 位号 / 常量）；
          作用范围是单元、输入取设备组全部成员的，属于跨设备 / 跨工艺统计。
        </div>
        <CalcPanel :items="calcs" :op-id="op || undefined" />
      </template>

      <!-- 算法库 -->
      <template v-if="kind === 'global:algo' && algos">
        <div class="text-xs text-fg-mute">{{ algos.note }}</div>
        <div v-for="a in algos.items" :key="a.id" class="card space-y-2">
          <div class="flex items-center gap-2">
            <span class="text-brand font-mono">ƒ</span><span class="font-semibold">{{ a.name }}</span>
            <span class="text-[11px] text-fg-mute font-mono">{{ a.id }} · v{{ a.version }}</span>
            <span class="pill pill-plain">{{ a.category }}</span><span class="pill pill-warn">{{ a.status }}</span>
            <span class="flex-1" />
            <span class="font-mono text-[11px] text-fg-dim">{{ a.invoke.protocol }} {{ a.invoke.method }} {{ a.invoke.endpoint }}</span>
          </div>
          <div class="text-xs text-fg-dim">{{ a.description }}</div>
          <table class="tbl">
            <thead><tr><th>输入参数</th><th>说明</th><th>类型</th><th>单位</th><th>必填</th><th>默认</th></tr></thead>
            <tbody>
              <tr v-for="i in a.inputs" :key="i.name" class="!cursor-default">
                <td><span class="font-mono text-xs">{{ i.name }}</span> {{ i.label }}</td><td class="text-fg-dim">{{ i.desc }}</td>
                <td>{{ i.type }}{{ i.multi ? '（可多个）' : '' }}</td><td>{{ i.unit }}</td><td>{{ i.required ? '是' : '否' }}</td><td>{{ i.default ?? '' }}</td>
              </tr>
            </tbody>
          </table>
          <div class="text-xs"><span class="text-fg-mute">输出：</span><span class="font-mono">{{ a.output.name }}</span> {{ a.output.label }}（{{ a.output.unit }}）
            <span class="text-fg-mute ml-3">提供方：</span>{{ a.provider }}</div>
          <div class="text-xs"><span class="text-fg-mute">被引用：</span>
            <span v-for="u in a.usedBy" :key="u.id" class="pill pill-plain mr-1">{{ u.name }} · {{ u.anchor }}</span>
            <span v-if="!a.usedBy.length" class="text-fg-mute">暂无计算组态引用</span>
          </div>
        </div>
      </template>

      <!-- 工况与根因 -->
      <template v-if="kind === 'global:cond' && cond">
        <div class="flex items-center gap-0.5 border-b border-line">
          <button class="tab-btn" :class="{ 'tab-on': condTab === 'phenomena' }" @click="condTab = 'phenomena'">现象/工况定义 <span class="text-fg-mute text-[10.5px]">{{ cond.phenomena.length }}</span></button>
          <button class="tab-btn" :class="{ 'tab-on': condTab === 'causal' }" @click="condTab = 'causal'">根因影响关系 <span class="text-fg-mute text-[10.5px]">{{ cond.links.length }}</span></button>
          <span class="flex-1" />
          <span class="text-xs text-fg-mute">{{ scopeText }} · 跨设备的导致关系 {{ cond.crossCount }} 条</span>
          <label v-if="condTab === 'causal'" class="text-xs flex items-center gap-1 text-fg-dim ml-3"><input v-model="onlyCross" type="checkbox" /> 只看跨设备</label>
        </div>
        <PhenomenaPanel v-if="condTab === 'phenomena'" :items="cond.phenomena" :anchor-options="cond.anchors" :op-id="op || undefined" @changed="load" />
        <CausalPanel v-else :links="links" :graph="{ ...cond.graph, links: links }" :op-id="op || undefined" @changed="load" />
      </template>

      <!-- 文档提取 -->
      <template v-if="kind === 'global:docs' && docs">
        <div class="sec-title">规程类文档（{{ scopeText }}）</div>
        <div v-if="!docs.documents.length" class="empty">范围内暂无登记的规程文档</div>
        <div v-for="d in docs.documents" :key="d.id" class="card space-y-2">
          <div class="flex items-center gap-2">
            <span class="font-mono text-xs text-fg-mute">{{ d.id }}</span><span class="font-semibold">{{ d.title }}</span>
            <span class="pill pill-plain">{{ d.type }}</span><span class="pill pill-warn">{{ d.status }}</span>
            <span class="text-xs text-fg-mute">适用工段 {{ d.areaCodes.join('、') }}</span>
            <span class="flex-1" /><button class="btn" @click="openDoc(d.id)">查看原文</button>
          </div>
          <div class="text-xs text-warn">{{ d.note }}</div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <div class="sec-title">提取出的处置卡（{{ d.extracted.procedures.length }}）</div>
              <table class="tbl"><tbody>
                <tr v-for="c in d.extracted.procedures" :key="c.id" class="!cursor-default">
                  <td class="font-mono text-xs">{{ c.id }}</td><td>{{ c.name }}</td><td class="text-fg-mute text-xs">原因 {{ c.causes }} · 步骤 {{ c.steps }}</td>
                </tr>
              </tbody></table>
            </div>
            <div>
              <div class="sec-title">据此整理的现象（{{ d.extracted.phenomena.length }}）</div>
              <div class="flex flex-wrap gap-1.5"><span v-for="p in d.extracted.phenomena" :key="p.id" class="pill pill-plain" :title="p.anchor">{{ p.name }}</span></div>
            </div>
          </div>
        </div>
        <div class="sec-title mt-4">数据源文档（{{ scopeText }}）</div>
        <table class="tbl">
          <thead><tr><th>文件</th><th>工作表</th><th>提取内容</th><th>数量</th><th>说明</th></tr></thead>
          <tbody><tr v-for="s in docs.sources" :key="s.file" class="!cursor-default">
            <td class="font-mono text-xs">{{ s.file }}</td><td class="text-fg-dim">{{ s.sheet }}</td><td>{{ s.what }}</td><td class="tabular-nums">{{ s.count }}</td><td class="text-fg-mute text-xs">{{ s.detail }}</td>
          </tr></tbody>
        </table>
      </template>
    </div>

    <Modal v-if="docView" :title="docView.title" wide @close="docView = null">
      <div class="md text-[13px] leading-relaxed" v-html="docHtml" />
    </Modal>
  </div>
</template>

<style scoped>
.md :deep(h1) { font-size: 18px; font-weight: 600; margin: 8px 0; }
.md :deep(h2) { font-size: 15px; font-weight: 600; margin: 16px 0 6px; color: #0e8fa3; }
.md :deep(h3) { font-size: 13.5px; font-weight: 600; margin: 12px 0 4px; }
.md :deep(p), .md :deep(li) { color: #334155; margin: 4px 0; }
.md :deep(ul), .md :deep(ol) { padding-left: 20px; list-style: disc; }
.md :deep(table) { border-collapse: collapse; margin: 6px 0; font-size: 12px; }
.md :deep(th), .md :deep(td) { border: 1px solid #d6dde7; padding: 3px 6px; }
.md :deep(blockquote) { border-left: 3px solid #d6dde7; padding-left: 8px; color: #64748b; }
</style>
