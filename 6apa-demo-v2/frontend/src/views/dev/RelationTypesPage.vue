<script setup lang="ts">
/** 关系类型（需求 SW-010，图 4-13）：列表 + 编辑（编码、名称 / 反向、源 / 目标端约束、方向 / 基数、特性、图谱视角、TTL 谓词、附加属性、图谱样式）。 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { act, canEdit, lib } from '@/composables/useClassLib'
import DevForm from './DevForm.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const items = ref<Any[]>([])
const metas = ref<Any[]>([])
const sel = ref('REL_CAUSES')
const form = ref<Any>(null)
async function load(): Promise<void> {
  items.value = (await api.clSection('relationTypes')).items
  metas.value = (await api.clSection('metaclasses')).items
  pick(sel.value)
}
load()
watch(() => lib.summary?.current?.version, load)
function pick(code: string): void {
  sel.value = code
  const r = items.value.find((x) => x.code === code)
  form.value = r ? JSON.parse(JSON.stringify({ ...r, style: r.style ?? { line: '实线', color: '#6366f1' } })) : null
}
const metaNames = computed(() => metas.value.map((m) => m.name))
function newRel(): void {
  form.value = { code: 'REL_NEW', name: '', inverse: '', from: [], to: [], direction: '有向', cardinality: '多对多', transitive: false, symmetric: false, noCycle: false,
                 views: [], ttl: 'onto:', attrs: [], desc: '', preset: false, style: { line: '实线', color: '#6366f1' }, _new: true }
  sel.value = ''
}
const asList = (v: Any): string[] => (Array.isArray(v) ? v : String(v ?? '').split(/[、,，]/).map((s) => s.trim()).filter(Boolean))
async function save(): Promise<void> {
  const f = { ...form.value, from: asList(form.value.from), to: asList(form.value.to) }
  if (await act(() => api.clSectionSave('relationTypes', f._new ? f.code : sel.value, f), `已保存关系类型「${f.name}」`)) { sel.value = f.code; await load() }
}
async function remove(): Promise<void> {
  if (!confirm(`删除关系类型「${form.value.name}」？`)) return
  if (await act(() => api.clSectionDelete('relationTypes', sel.value), '已删除')) { sel.value = items.value[0]?.code; await load() }
}
</script>

<template>
  <div class="flex items-center gap-3 mb-3">
    <h2 class="text-[18px] font-semibold">关系类型</h2>
    <span class="text-xs text-fg-mute">所有关系都必须属于一个关系类型；关系类型决定图谱筛选、TTL 导出与一致性校验</span>
    <span class="flex-1" /><button class="btn btn-primary" :disabled="!canEdit()" @click="newRel">+ 新建关系类型</button>
  </div>
  <div class="grid grid-cols-[1.25fr_1fr] gap-4">
    <div class="card self-start">
      <div class="sec-title">关系类型列表</div>
      <table class="tbl"><thead><tr><th>名称 / 反向</th><th>源端</th><th>目标端</th><th>方向</th><th>特性</th><th>图谱视角</th></tr></thead><tbody>
        <tr v-for="r in items" :key="r.code" :class="{ '!bg-brand/10': sel === r.code }" @click="pick(r.code)">
          <td class="font-medium whitespace-nowrap">{{ r.name }}<span class="text-fg-mute font-normal"> / {{ r.inverse }}</span></td>
          <td class="text-xs">{{ asList(r.from).join('、') }}</td><td class="text-xs">{{ asList(r.to).join('、') }}</td><td class="text-xs">{{ r.direction }}</td>
          <td><span v-if="r.transitive" class="pill pill-plain">传递</span><span v-if="r.symmetric" class="pill pill-plain">对称</span><span v-if="r.attrs?.length" class="pill pill-info">带属性</span></td>
          <td class="text-xs">{{ (r.views ?? []).join(' · ') || '—' }}</td></tr>
      </tbody></table>
    </div>
    <div v-if="form" class="card self-start space-y-3">
      <div class="flex items-center gap-2"><div class="sec-title !mb-0 flex-1">编辑：{{ form.name || '（新）' }}</div>
        <span class="pill pill-plain">{{ form.preset ? '预置' : '自定义' }}</span>
        <button v-if="!form.preset && !form._new" class="btn btn-danger" :disabled="!canEdit()" @click="remove">删除</button>
        <button class="btn btn-primary" :disabled="!canEdit()" @click="save">保存</button></div>
      <DevForm :model="form" :disabled="!canEdit()" :fields="[
        { key: 'code', label: '编码', type: 'code', readonly: !form._new }, { key: 'name', label: '名称' }, { key: 'inverse', label: '反向名称' },
        { key: 'from', label: '源端约束', type: 'list', hint: `元类：${metaNames.join('、')}` }, { key: 'to', label: '目标端约束', type: 'list' },
        { key: 'direction', label: '方向', type: 'select', options: ['有向', '无向', '可配'] }, { key: 'cardinality', label: '基数', type: 'select', options: ['一对一', '一对多', '多对多'] },
        { key: 'transitive', label: '传递', type: 'bool' }, { key: 'symmetric', label: '对称', type: 'bool' }, { key: 'noCycle', label: '禁止环路', type: 'bool' },
        { key: 'views', label: '图谱视角', type: 'multi', options: ['工艺流程', '设备与参数', '现象因果'] }, { key: 'ttl', label: 'TTL 谓词', type: 'code' }, { key: 'desc', label: '说明' }]" />
      <div>
        <div class="flex items-center"><div class="sec-title !mb-0 flex-1">附加属性</div><button class="ctl" :disabled="!canEdit()" @click="form.attrs.push({ name: '', type: '文本', values: '' })">+ 属性</button></div>
        <table class="tbl mt-1"><thead><tr><th>属性</th><th>类型</th><th>取值</th><th></th></tr></thead><tbody>
          <tr v-for="(a, i) in form.attrs" :key="i" class="!cursor-default">
            <td><input v-model="a.name" class="inp w-full" :disabled="!canEdit()" /></td><td><input v-model="a.type" class="inp w-full" :disabled="!canEdit()" /></td>
            <td><input v-model="a.values" class="inp w-full" :disabled="!canEdit()" /></td><td><button class="ctl !px-1.5" :disabled="!canEdit()" @click="form.attrs.splice(i, 1)">×</button></td></tr>
        </tbody></table>
      </div>
      <div>
        <div class="sec-title">图谱样式</div>
        <div class="flex items-center gap-3 text-xs">
          <select v-model="form.style.line" class="inp w-24" :disabled="!canEdit()"><option>实线</option><option>虚线</option></select>
          <input v-model="form.style.color" type="color" class="w-8 h-7 rounded border border-line" :disabled="!canEdit()" />
          <svg width="140" height="14"><line x1="2" y1="7" x2="128" y2="7" :stroke="form.style.color" stroke-width="2" :stroke-dasharray="form.style.line === '虚线' ? '6 4' : ''" /><path d="M128,2 L138,7 L128,12 z" :fill="form.style.color" /></svg>
          <template v-if="form.style.lowConfidence"><span class="text-fg-mute">低置信度</span>
            <svg width="140" height="14"><line x1="2" y1="7" x2="128" y2="7" :stroke="form.style.color" stroke-width="2" stroke-dasharray="6 4" /><path d="M128,2 L138,7 L128,12 z" :fill="form.style.color" /></svg></template>
        </div>
      </div>
    </div>
  </div>
</template>
