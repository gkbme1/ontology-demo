<script setup lang="ts">
/** 映射规则（需求 SW-011，图 4-14）：位号解析 / 设备识别 / P&ID 图元 / 外部编码；规则定义 + 规则测试（样例、解析结果、匹配对象、置信度）。 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { staticBackend } from '@/api/static'
import { act, canEdit, lib } from '@/composables/useClassLib'
import DevForm from './DevForm.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const KINDS = ['位号解析', '设备识别', 'P&ID 图元', '外部编码']
const items = ref<Any[]>([])
const kind = ref('位号解析')
const sel = ref('MR-01')
const form = ref<Any>(null)
const test = ref<Any>(null)
const samples = ref('')
async function load(): Promise<void> { items.value = (await api.clSection('mappingRules')).items; pick(sel.value) }
load()
watch(() => lib.summary?.current?.version, load)
const list = computed(() => items.value.filter((r) => r.kind === kind.value).sort((a, b) => a.priority - b.priority))
function pick(code: string): void {
  sel.value = code
  const r = items.value.find((x) => x.code === code)
  form.value = r ? JSON.parse(JSON.stringify(r)) : null
  test.value = null
}
watch(kind, () => { const f = list.value[0]; if (f) pick(f.code) })
function newRule(): void {
  form.value = { code: `MR-NEW-${items.value.length + 1}`, kind: kind.value, name: '', priority: 50, pattern: '', segments: [], target: '参数', descMatch: '', locate: '', threshold: 0.9, status: '草案', confidence: '中', _new: true }
  sel.value = ''
}
async function save(): Promise<void> {
  const f = form.value
  if (await act(() => api.clSectionSave('mappingRules', f._new ? f.code : sel.value, f), `已保存规则「${f.name}」`)) { sel.value = f.code; await load() }
}
async function remove(): Promise<void> {
  if (!confirm(`删除规则「${form.value.name}」？`)) return
  if (await act(() => api.clSectionDelete('mappingRules', sel.value), '已删除')) { sel.value = list.value[0]?.code; await load() }
}
async function runTest(): Promise<void> {
  const s = samples.value.split(/[\s,，、]+/).filter(Boolean)
  try { test.value = await api.clMapTest({ code: sel.value, samples: s.length ? s : undefined }) } catch (e) { alert((e as Error).message) }
}
const funcMap = computed(() => Object.entries(lib.summary?.library?.funcMap ?? {}).map(([k, v]) => `${k}→${v}`).join(' · '))
const confPill = (c: Any) => (c == null ? 'pill-err' : c >= (form.value?.threshold ?? 0.9) ? 'pill-ok' : 'pill-warn')
</script>

<template>
  <div class="flex items-center gap-3 mb-3">
    <h2 class="text-[18px] font-semibold">映射规则</h2>
    <span class="text-xs text-fg-mute">把位号、P&amp;ID 图元、外部编码自动转换为本体实例和关系</span>
    <span class="flex-1" /><button class="btn btn-primary" :disabled="!canEdit()" @click="newRule">+ 新建规则</button>
  </div>
  <div class="flex gap-1.5 mb-3">
    <button v-for="k in KINDS" :key="k" class="asset-tab" :class="{ 'asset-tab-on': kind === k }" @click="kind = k">{{ k }}<span class="asset-tab-count">{{ items.filter((r) => r.kind === k).length }}</span></button>
  </div>
  <div class="grid grid-cols-[400px_1fr] gap-4">
    <div class="card self-start">
      <div class="sec-title">{{ kind }}规则</div>
      <table class="tbl"><thead><tr><th>优先级</th><th>规则名称</th><th>目标</th><th>状态</th></tr></thead><tbody>
        <tr v-for="r in list" :key="r.code" :class="{ '!bg-brand/10': sel === r.code }" @click="pick(r.code)">
          <td>{{ r.priority }}</td><td>{{ r.name }}<div class="font-mono text-[10.5px] text-fg-mute break-all">{{ r.pattern }}</div></td>
          <td class="text-xs">{{ r.target }}</td><td><span class="pill" :class="r.status === '生效' ? 'pill-ok' : 'pill-warn'">{{ r.status }}</span></td></tr>
      </tbody></table>
    </div>
    <div v-if="form" class="space-y-3">
      <div class="card">
        <div class="flex items-center mb-3"><div class="sec-title !mb-0 flex-1">规则定义：{{ form.name || '（新）' }}</div>
          <button v-if="!form._new" class="btn btn-danger mr-1" :disabled="!canEdit()" @click="remove">删除</button>
          <button class="btn btn-primary" :disabled="!canEdit()" @click="save">保存</button></div>
        <DevForm :model="form" :disabled="!canEdit()" :fields="[
          { key: 'name', label: '规则名称' }, { key: 'priority', label: '优先级', type: 'number', hint: '数字小的先匹配' },
          { key: 'pattern', label: '匹配表达式', type: 'code', placeholder: '正则表达式，分组对应分段' }, { key: 'segments', label: '分段含义', type: 'list', placeholder: '$1 区域号、$2 仪表功能字母…' },
          { key: 'target', label: '输出目标' }, { key: 'descMatch', label: '描述匹配' }, { key: 'locate', label: '设备定位' },
          { key: 'threshold', label: '自动接受阈值', type: 'number', hint: '置信度 ≥ 阈值可批量接受，其余进入审核队列' },
          { key: 'status', label: '状态', type: 'select', options: ['草案', '生效', '停用'] }]" />
        <div v-if="form.kind === '位号解析'" class="grid grid-cols-[96px_1fr] gap-x-4 mt-2 text-xs"><span class="text-fg-mute text-right">功能字母映射</span><span class="text-fg-dim">{{ funcMap }}</span></div>
      </div>
      <div class="card">
        <div class="flex items-center gap-2 mb-2"><div class="sec-title !mb-0">规则测试</div>
          <input v-model="samples" class="inp flex-1 font-mono" placeholder="样例（空 = 用默认样例），用空格 / 逗号分隔" />
          <button class="btn btn-primary" @click="runTest">执行测试</button></div>
        <div v-if="staticBackend" class="text-xs text-fg-mute">单文件版只能用默认样例测试</div>
        <template v-if="test">
          <table class="tbl"><thead><tr><th>样例</th><th>描述（点表）</th><th>解析结果</th><th>点表中的设备</th><th>置信度</th></tr></thead><tbody>
            <tr v-for="(r, i) in test.results" :key="i" class="!cursor-default">
              <td class="font-mono text-xs">{{ r.tag }}</td><td class="text-xs">{{ r.desc || '—' }}</td>
              <td class="text-xs"><template v-if="r.matched">{{ r.parsed.filter((p: Any) => p.value).map((p: Any) => `${p.label.replace(/^\$\d+ /, '')} ${p.value}${p.meaning ? '(' + p.meaning + ')' : ''}`).join(' · ') }}</template><span v-else class="text-fg-mute">未匹配</span></td>
              <td class="text-xs">{{ r.equipment || '—' }}<span v-if="r.variable" class="text-fg-mute"> · {{ r.variable }}</span></td>
              <td><span class="pill" :class="confPill(r.confidence)">{{ r.confidence ?? '—' }}</span></td></tr>
          </tbody></table>
          <div class="text-[11px] text-fg-mute mt-1">命中规则：{{ test.rule.name }}（优先级 {{ test.rule.priority }}）<template v-if="test.hits"> · 点表中命中 {{ test.hits }} / {{ test.total }} 个位号</template></div>
        </template>
      </div>
    </div>
  </div>
</template>
