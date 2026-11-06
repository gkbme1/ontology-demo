<script setup lang="ts">
/** 工序图纸与工序下 4 个节点：装置、计算组态、工况与根因、文档提取。 */
import { computed, ref, watch } from 'vue'
import { marked } from 'marked'
import { api } from '@/api/client'
import { nav, openObject, select } from '@/composables/useNav'
import DrawingView from '@/components/DrawingView.vue'
import CalcPanel from '@/components/CalcPanel.vue'
import PhenomenaPanel from '@/components/causal/PhenomenaPanel.vue'
import CausalPanel from '@/components/causal/CausalPanel.vue'
import Modal from '@/components/Modal.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ kind: string; opId: string; calcId?: string }>()

const op = ref<Any>(null)
const drawing = ref<Any>(null)
const cond = ref<Any>(null)
const calcs = ref<Any[]>([])
const docs = ref<Any>(null)
const docView = ref<Any>(null)
const condTab = ref<'phenomena' | 'causal'>('phenomena')

async function load(): Promise<void> {
  op.value = await api.op(props.opId)
  if (props.kind === 'drawing' || props.kind === 'section:devices') drawing.value = await api.opDrawing(props.opId)
  if (props.kind === 'section:cond') cond.value = await api.opConditions(props.opId)
  if (props.kind === 'section:calc' || props.kind === 'calc') calcs.value = (await api.opCalculations(props.opId)).items
  if (props.kind === 'section:docs') docs.value = await api.opDocuments(props.opId)
}
watch(() => [props.kind, props.opId, nav.version], load, { immediate: true })

// 新增现象时的挂载对象候选：本工序的设备组 + 设备
const anchorOptions = computed(() => {
  const d = drawing.value
  const out: Any[] = []
  for (const n of d?.nodes ?? []) {
    if (n.kind === 'group') out.push({ id: n.id, name: n.name, kind: 'group' })
    for (const m of n.members) out.push({ id: m.id, name: m.name, kind: 'equipment' })
  }
  return out
})
watch(() => props.kind, async (k) => {
  if (k === 'section:cond' && !drawing.value) drawing.value = await api.opDrawing(props.opId)
}, { immediate: true })

function pick(id: string, _kind?: string, opId?: string): void {
  openObject(id, opId ?? props.opId)
}
async function openDoc(id: string): Promise<void> {
  docView.value = await api.document(id)
}
const docHtml = computed(() => (docView.value ? marked.parse(docView.value.content) as string : ''))
const title = computed(() => ({
  drawing: '图纸', 'section:devices': '装置', 'section:calc': '计算组态', calc: '计算组态',
  'section:cond': '工况与根因', 'section:docs': '文档提取'
} as Record<string, string>)[props.kind] ?? '')
</script>

<template>
  <div class="h-full overflow-auto px-5 pb-5 space-y-4">
    <div v-if="op" class="flex items-center gap-3 pt-5">
      <div>
        <div class="text-[11px] text-fg-mute"><span v-for="(p, i) in op.path" :key="p.id">{{ p.name }} › </span>{{ title }}</div>
        <h2 class="text-[18px] font-semibold">{{ op.name }} · {{ title }}</h2>
      </div>
      <span class="flex-1" />
      <button v-for="k in ['drawing', 'section:devices', 'section:calc', 'section:cond', 'section:docs']" :key="k"
              class="ctl" :class="{ 'ctl-on': kind === k || (k === 'section:calc' && kind === 'calc') }"
              @click="select({ type: k as Any, id: opId, opId }, k === 'drawing' ? opId : `${opId}|${k.split(':')[1]}`)">
        {{ ({ drawing: '图纸', 'section:devices': '装置', 'section:calc': '计算组态', 'section:cond': '工况与根因', 'section:docs': '文档提取' } as Record<string, string>)[k] }}
      </button>
    </div>

    <!-- 图纸 -->
    <template v-if="kind === 'drawing' && drawing">
      <div class="text-xs text-fg-mute">单击图上的设备查看设备信息。{{ drawing.image ? '' : drawing.note }}</div>
      <DrawingView :drawing="drawing" @pick="pick" />
      <div v-if="drawing.internalStreams?.length" class="text-xs text-fg-mute">本工序内部物料：{{ drawing.internalStreams.join('、') }}</div>
    </template>

    <!-- 装置 -->
    <template v-if="kind === 'section:devices' && drawing">
      <div v-for="n in drawing.nodes" :key="n.id" class="card">
        <div class="flex items-center gap-2">
          <button v-if="n.kind === 'group'" class="font-semibold hover:text-brand" @click="pick(n.id)">▢ {{ n.name }}</button>
          <span v-else class="font-semibold text-fg-dim">{{ n.name }}</span>
          <span class="text-xs text-fg-mute">{{ n.type }} · {{ n.members.length }} 台</span>
        </div>
        <div class="flex flex-wrap gap-1.5 mt-2">
          <button v-for="m in n.members" :key="m.id" class="ctl" @click="pick(m.id)">{{ m.name }} <span class="text-fg-mute">{{ m.tagCount }}</span></button>
        </div>
      </div>
    </template>

    <!-- 计算组态 -->
    <CalcPanel v-if="kind === 'section:calc' || kind === 'calc'" :items="calcs" :op-id="opId" :focus-id="calcId" />

    <!-- 工况与根因 -->
    <template v-if="kind === 'section:cond' && cond">
      <div class="flex gap-0.5 border-b border-line">
        <button class="tab-btn" :class="{ 'tab-on': condTab === 'phenomena' }" @click="condTab = 'phenomena'">现象定义 <span class="text-fg-mute text-[10.5px]">{{ cond.phenomena.length }}</span></button>
        <button class="tab-btn" :class="{ 'tab-on': condTab === 'causal' }" @click="condTab = 'causal'">根因影响关系 <span class="text-fg-mute text-[10.5px]">{{ cond.links.length }}</span></button>
      </div>
      <PhenomenaPanel v-if="condTab === 'phenomena'" :items="cond.phenomena" :anchor-options="anchorOptions" :op-id="opId" @changed="load" />
      <CausalPanel v-else :links="cond.links" :graph="cond.graph" :op-id="opId" @changed="load" />
    </template>

    <!-- 文档提取 -->
    <template v-if="kind === 'section:docs' && docs">
      <div class="sec-title">规程类文档</div>
      <div v-if="!docs.documents.length" class="empty">本工序暂无登记的规程文档</div>
      <div v-for="d in docs.documents" :key="d.id" class="card space-y-2">
        <div class="flex items-center gap-2">
          <span class="font-mono text-xs text-fg-mute">{{ d.id }}</span><span class="font-semibold">{{ d.title }}</span>
          <span class="pill pill-plain">{{ d.type }}</span><span class="pill pill-warn">{{ d.status }}</span>
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
            <div class="sec-title">据此整理的现象（本工序，{{ d.extracted.phenomena.length }}）</div>
            <div class="flex flex-wrap gap-1.5">
              <span v-for="p in d.extracted.phenomena" :key="p.id" class="pill pill-plain" :title="p.anchor">{{ p.name }}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="sec-title mt-4">数据源文档</div>
      <table class="tbl">
        <thead><tr><th>文件</th><th>工作表</th><th>提取内容</th><th>数量</th><th>说明</th></tr></thead>
        <tbody><tr v-for="s in docs.sources" :key="s.file" class="!cursor-default">
          <td class="font-mono text-xs">{{ s.file }}</td><td class="text-fg-dim">{{ s.sheet }}</td><td>{{ s.what }}</td><td class="tabular-nums">{{ s.count }}</td><td class="text-fg-mute text-xs">{{ s.detail }}</td>
        </tr></tbody>
      </table>
    </template>

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
.md :deep(th), .md :deep(td) { border: 1px solid #c9d4e0; padding: 3px 6px; }
.md :deep(blockquote) { border-left: 3px solid #c9d4e0; padding-left: 8px; color: #4b5563; }
</style>
