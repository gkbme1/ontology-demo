<script setup lang="ts">
/** 元模型（需求 SW-001，图 4-5）：元类列表 + 元类定义（编码、名称、说明、图谱样式）、可用属性集、对象详情可用页签、可参与的关系类型。 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { act, canEdit, lib } from '@/composables/useClassLib'
import DevForm from './DevForm.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const items = ref<Any[]>([])
const usage = ref<Record<string, number>>({})
const rels = ref<Any[]>([])
const sel = ref('')
const form = ref<Any>(null)
async function load(): Promise<void> {
  const r = await api.clSection('metaclasses')
  items.value = r.items
  usage.value = r.usage
  rels.value = (await api.clSection('relationTypes')).items
  if (!sel.value) sel.value = 'MC_EQUIP'
  pick(sel.value)
}
load()
function pick(code: string): void {
  sel.value = code
  const m = items.value.find((x) => x.code === code)
  form.value = m ? JSON.parse(JSON.stringify({ ...m, style: m.style ?? { color: '#64748b', shape: '圆形' } })) : null
}
const preset = computed(() => items.value.filter((x) => x.preset).length)
function addMeta(): void {
  form.value = { code: 'MC_X_', name: '', desc: '', preset: false, style: { color: '#0ea5e9', shape: '圆形' }, attrs: [], tabs: [], relations: [], _new: true }
  sel.value = ''
}
async function save(): Promise<void> {
  const f = form.value
  const r = await act(() => api.clSectionSave('metaclasses', f._new ? f.code : sel.value, f), `已保存元类「${f.name}」`)
  if (r) { sel.value = r.code; await load() }
}
async function remove(): Promise<void> {
  if (!confirm(`删除扩展元类「${form.value.name}」？`)) return
  if (await act(() => api.clSectionDelete('metaclasses', sel.value), '已删除')) { sel.value = ''; await load() }
}
const TABS = computed(() => lib.summary?.enums?.tabs ?? [])
watch(() => lib.summary?.current?.version, load)
</script>

<template>
  <div class="flex items-center gap-3 mb-3">
    <h2 class="text-[18px] font-semibold">元模型</h2>
    <span class="text-xs text-fg-mute">定义本体中允许存在的对象种类（元类）及其可用属性、页签和关系</span>
    <span class="flex-1" />
    <button class="btn btn-primary" :disabled="!canEdit()" @click="addMeta">+ 扩展元类</button>
  </div>
  <div class="grid grid-cols-[400px_1fr] gap-4">
    <div class="card self-start">
      <div class="sec-title">元类列表 <span class="text-fg-mute font-normal">{{ preset }} 预置 · {{ items.length - preset }} 扩展</span></div>
      <table class="tbl"><thead><tr><th>元类</th><th>编码</th><th>类</th><th>类型</th></tr></thead><tbody>
        <tr v-for="m in items" :key="m.code" :class="{ '!bg-brand/10': sel === m.code }" @click="pick(m.code)">
          <td class="font-medium"><i class="inline-block w-2.5 h-2.5 rounded-sm mr-1.5 align-middle" :style="{ background: m.style?.color }" />{{ m.name }}</td>
          <td class="font-mono text-xs">{{ m.code }}</td><td class="tabular-nums text-xs">{{ usage[m.code] ?? 0 }}</td>
          <td><span class="pill" :class="m.preset ? 'pill-plain' : 'pill-info'">{{ m.preset ? '预置' : '扩展' }}</span></td>
        </tr>
      </tbody></table>
    </div>
    <div v-if="form" class="space-y-4">
      <div class="card">
        <div class="flex items-center gap-2 mb-3">
          <div class="sec-title !mb-0">元类定义：{{ form.name || '（新元类）' }}</div>
          <span class="pill pill-plain">{{ form.preset ? '预置 · 不可删除' : '扩展 · 无类引用时可删除' }}</span>
          <span class="flex-1" />
          <button v-if="!form.preset && !form._new" class="btn btn-danger" :disabled="!canEdit()" @click="remove">删除</button>
          <button class="btn btn-primary" :disabled="!canEdit()" @click="save">保存</button>
        </div>
        <DevForm :model="form" :disabled="!canEdit()" :fields="[
          { key: 'code', label: '元类编码', type: 'code', readonly: !form._new },
          { key: 'name', label: '名称' }, { key: 'desc', label: '说明' }]" />
        <div class="grid grid-cols-[96px_1fr] gap-x-4 items-center mt-2 text-sm">
          <span class="text-xs text-fg-mute text-right">图谱样式</span>
          <div class="flex items-center gap-2">
            <input v-model="form.style.color" type="color" class="w-8 h-7 rounded border border-line" :disabled="!canEdit()" />
            <select v-model="form.style.shape" class="inp w-32" :disabled="!canEdit()"><option v-for="s in ['圆形', '圆角矩形', '矩形', '菱形', '三角', '小圆', '小矩形']" :key="s">{{ s }}</option></select>
            <span class="text-xs text-fg-mute">{{ form.style.shape }} · {{ form.style.color }}</span>
          </div>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4">
        <div class="card">
          <div class="flex items-center mb-2"><div class="sec-title !mb-0 flex-1">可用属性集</div>
            <button class="ctl" :disabled="!canEdit()" @click="form.attrs.push({ code: '', name: '', dtype: '文本', required: false })">+ 属性</button></div>
          <table class="tbl"><thead><tr><th>编码</th><th>属性</th><th>类型</th><th>必填</th><th></th></tr></thead><tbody>
            <tr v-for="(a, i) in form.attrs" :key="i" class="!cursor-default">
              <td><input v-model="a.code" class="inp w-24 font-mono" :disabled="!canEdit()" /></td>
              <td><input v-model="a.name" class="inp w-full" :disabled="!canEdit()" /></td>
              <td><select v-model="a.dtype" class="inp w-24" :disabled="!canEdit()"><option v-for="t in lib.summary?.enums?.dtypes ?? []" :key="t">{{ t }}</option></select></td>
              <td><input v-model="a.required" type="checkbox" :disabled="!canEdit()" /></td>
              <td><button class="ctl !px-1.5" :disabled="!canEdit()" @click="form.attrs.splice(i, 1)">×</button></td>
            </tr>
          </tbody></table>
          <div class="text-[11px] text-fg-mute mt-1">元类属性为该元类全部类共有；类可在此基础上扩展</div>
        </div>
        <div class="card">
          <div class="sec-title">对象详情可用页签</div>
          <div class="flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
            <label v-for="t in TABS" :key="t" class="inline-flex items-center gap-1.5"><input v-model="form.tabs" type="checkbox" :value="t" :disabled="!canEdit()" />{{ t }}</label>
          </div>
          <div class="sec-title mt-4">可参与的关系类型</div>
          <div class="flex flex-wrap gap-1.5">
            <button v-for="r in rels" :key="r.code" class="ctl !py-0.5" :class="{ 'ctl-on': form.relations.includes(r.code) }" :disabled="!canEdit()"
                    @click="form.relations.includes(r.code) ? form.relations.splice(form.relations.indexOf(r.code), 1) : form.relations.push(r.code)">{{ r.name }}</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
