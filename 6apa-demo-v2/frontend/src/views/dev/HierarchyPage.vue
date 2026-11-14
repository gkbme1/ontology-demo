<script setup lang="ts">
/** 层级类型与层级模板（需求 SW-002，图 4-6）：模板列表、模板结构（层级顺序，可调整）、预览（取自已引用工程）、层级类型属性。 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { act, canEdit, lib } from '@/composables/useClassLib'
import DevForm from './DevForm.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const types = ref<Any[]>([])
const tpls = ref<Any[]>([])
const tplSel = ref('TPL_WORKSHOP')
const typeSel = ref('PROCESS')
const typeForm = ref<Any>(null)
const preview = ref<Any>(null)
async function load(): Promise<void> {
  types.value = (await api.clSection('hierarchyTypes')).items
  tpls.value = (await api.clSection('hierarchyTemplates')).items
  if (!preview.value) preview.value = await api.clHierPreview()
  pickType(typeSel.value)
}
load()
watch(() => lib.summary?.current?.version, load)
const tpl = computed(() => tpls.value.find((t) => t.code === tplSel.value))
const typeName = (c: string) => types.value.find((t) => t.code === c)?.name ?? ({ MC_EQGRP: '设备组', MC_EQUIP: '设备', MC_PARAM: '参数' } as Record<string, string>)[c] ?? c
function pickType(code: string): void {
  typeSel.value = code
  const t = types.value.find((x) => x.code === code)
  typeForm.value = t ? JSON.parse(JSON.stringify(t)) : null
}
const typeOptions = computed(() => [...types.value.map((t) => ({ value: t.code, label: t.name })), { value: 'MC_EQGRP', label: '设备组' }, { value: 'MC_EQUIP', label: '设备' }, { value: 'MC_PARAM', label: '参数' }])
async function saveType(): Promise<void> {
  const f = typeForm.value
  if (await act(() => api.clSectionSave('hierarchyTypes', f._new ? f.code : typeSel.value, f), `已保存层级类型「${f.name}」`)) { typeSel.value = f.code; await load() }
}
async function delType(): Promise<void> {
  if (!confirm(`删除层级类型「${typeForm.value.name}」？`)) return
  if (await act(() => api.clSectionDelete('hierarchyTypes', typeSel.value), '已删除')) { typeSel.value = ''; await load() }
}
function newType(): void { typeForm.value = { code: 'NEW_LEVEL', name: '', parents: [], children: [], drawing: false, card: false, ordered: false, maxDepth: 8, _new: true }; typeSel.value = '' }
async function saveTpl(t: Any): Promise<void> {
  if (await act(() => api.clSectionSave('hierarchyTemplates', t._new ? t.code : t.code, t), `已保存层级模板「${t.name}」`)) await load()
}
function move(i: number, d: number): void {
  const t = tpl.value
  const lv = [...t.levels]
  const j = i + d
  if (j < 0 || j >= lv.length) return
  ;[lv[i], lv[j]] = [lv[j], lv[i]]
  saveTpl({ ...t, levels: lv })
}
const addLevel = ref('')
function newTpl(): void {
  const name = prompt('新层级模板名称（如：深冷装置模板）', '')
  if (!name) return
  saveTpl({ code: 'TPL_' + Date.now().toString(36).toUpperCase(), name, levels: [], projects: [], kind: '空间层级', _new: true }).then(() => { tplSel.value = tpls.value[tpls.value.length - 1]?.code })
}
async function delTpl(): Promise<void> {
  if (!tpl.value || !confirm(`删除层级模板「${tpl.value.name}」？`)) return
  if (await act(() => api.clSectionDelete('hierarchyTemplates', tpl.value.code), '已删除')) { tplSel.value = tpls.value[0]?.code; await load() }
}
</script>

<template>
  <div class="flex items-center gap-3 mb-3">
    <h2 class="text-[18px] font-semibold">层级类型与层级模板</h2>
    <span class="text-xs text-fg-mute">不同工厂的空间层级深度和叫法不同，通过模板配置</span>
    <span class="flex-1" />
    <button class="btn" :disabled="!canEdit()" @click="newType">+ 新建层级类型</button>
    <button class="btn btn-primary" :disabled="!canEdit()" @click="newTpl">+ 新建层级模板</button>
  </div>
  <div class="grid grid-cols-[300px_1fr_360px] gap-4">
    <div class="card self-start">
      <div class="sec-title">层级模板</div>
      <table class="tbl"><thead><tr><th>模板</th><th>级数</th><th>引用工程</th></tr></thead><tbody>
        <tr v-for="t in tpls" :key="t.code" :class="{ '!bg-brand/10': tplSel === t.code }" @click="tplSel = t.code">
          <td class="font-medium">{{ t.name }}<div class="text-[11px] text-fg-mute font-normal">{{ t.levels.map(typeName).join('—') }}</div></td>
          <td>{{ t.levels.length }}</td><td>{{ (t.projects ?? []).length }}</td>
        </tr>
      </tbody></table>
    </div>
    <div v-if="tpl" class="card self-start space-y-3">
      <div class="flex items-center gap-2"><div class="sec-title !mb-0">模板结构：{{ tpl.name }}</div><span class="text-[11px] text-fg-mute">↑↓ 调整层级顺序</span>
        <span class="flex-1" /><button class="ctl" :disabled="!canEdit()" @click="delTpl">删除模板</button></div>
      <div v-for="(c, i) in tpl.levels" :key="c" class="flex items-center gap-2" :style="{ paddingLeft: `${i * 28}px` }">
        <button class="flex-1 max-w-[340px] text-left rounded-md border px-3 py-1.5" :class="typeSel === c ? 'border-brand bg-brand/5' : 'border-line bg-white'" @click="pickType(c)">
          <b>L{{ i + 1 }} {{ typeName(c) }}</b> <span class="text-fg-mute text-xs ml-1 font-mono">{{ c }}</span>
        </button>
        <span v-if="types.find((t) => t.code === c)?.card" class="pill pill-plain">首页卡片</span>
        <span v-if="types.find((t) => t.code === c)?.drawing" class="pill pill-ok">可绑定图纸</span>
        <span v-if="types.find((t) => t.code === c)?.ordered" class="pill pill-info">同级有序</span>
        <button class="ctl !px-1.5 !py-0" :disabled="!canEdit()" @click="move(i, -1)">↑</button>
        <button class="ctl !px-1.5 !py-0" :disabled="!canEdit()" @click="move(i, 1)">↓</button>
        <button class="ctl !px-1.5 !py-0" :disabled="!canEdit()" @click="saveTpl({ ...tpl, levels: tpl.levels.filter((x: string) => x !== c) })">×</button>
      </div>
      <div class="flex items-center gap-2">
        <select v-model="addLevel" class="inp w-48" :disabled="!canEdit()"><option value="">添加层级…</option><option v-for="t in types.filter((t) => !tpl.levels.includes(t.code))" :key="t.code" :value="t.code">{{ t.name }}</option></select>
        <button class="ctl" :disabled="!canEdit() || !addLevel" @click="saveTpl({ ...tpl, levels: [...tpl.levels, addLevel] }); addLevel = ''">添加</button>
        <span class="text-[11px] text-fg-mute">最大深度 8 级</span>
      </div>
      <div v-if="tpl.code === 'TPL_WORKSHOP' && preview">
        <div class="sec-title mt-2">预览（取自已引用工程）</div>
        <div class="text-xs text-fg-dim mb-1.5">{{ preview.path.join(' › ') }} ›</div>
        <div class="flex flex-wrap items-center gap-1.5">
          <template v-for="(s, i) in preview.subSteps" :key="s"><span class="rounded-full border border-line px-3 py-1 text-xs bg-white">{{ s }}</span><span v-if="i < preview.subSteps.length - 1" class="text-fg-mute">→</span></template>
        </div>
        <div class="text-[11px] text-fg-mute mt-2">节点数：车间 {{ preview.levels.WORKSHOP }} · 工艺段 {{ preview.levels.SECTION }} · 工序 {{ preview.levels.PROCESS }} · 子工序 {{ preview.levels.SUBPROC }}（写在图纸上）</div>
      </div>
      <div class="text-[11px] text-fg-mute">引用工程：{{ (tpl.projects ?? []).join('、') || '无' }} · 视角：{{ tpl.kind }}</div>
    </div>
    <div v-if="typeForm" class="card self-start">
      <div class="flex items-center mb-2"><div class="sec-title !mb-0 flex-1">层级类型属性：{{ typeForm.name || '（新）' }}</div>
        <button v-if="!typeForm._new" class="ctl mr-1" :disabled="!canEdit()" @click="delType">删除</button>
        <button class="btn btn-primary" :disabled="!canEdit()" @click="saveType">保存</button></div>
      <DevForm :model="typeForm" :disabled="!canEdit()" :fields="[
        { key: 'code', label: '编码', type: 'code', readonly: !typeForm._new }, { key: 'name', label: '名称' },
        { key: 'parents', label: '允许上级', type: 'multi', options: typeOptions },
        { key: 'children', label: '允许下级', type: 'multi', options: typeOptions },
        { key: 'drawing', label: '可绑定图纸', type: 'bool', hint: '是（P&ID / DCS 画面 / 示意图）' },
        { key: 'card', label: '首页卡片', type: 'bool' }, { key: 'ordered', label: '同级排序', type: 'bool', hint: '启用顺序关系（如子工序链）' },
        { key: 'maxDepth', label: '最大深度', type: 'number', hint: '系统上限 8 级' }]" />
      <div v-if="typeForm.note" class="text-[11px] text-fg-mute mt-2">{{ typeForm.note }}</div>
      <div class="text-[11px] text-fg-mute mt-2">资产分类、工艺参数目录等其他视角的层级也在此配置</div>
    </div>
  </div>
</template>
