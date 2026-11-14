<script setup lang="ts">
/** 能力与算法（需求 SW-012 / 013，图 4-15 / 4-16）：能力定义（适用类、引用算法、执行方式、输入 → 参数模板绑定、输出、运行态发现）；算法库（登记信息、输入输出、测试）。 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { act, canEdit, lib } from '@/composables/useClassLib'
import DevForm from './DevForm.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const tab = ref<'cap' | 'algo'>('cap')
const caps = ref<Any[]>([])
const classNames = ref<Record<string, string>>({})
const algos = ref<Any[]>([])
const sel = ref('')
const form = ref<Any>(null)
const aSel = ref('')
const testIn = ref('')
const testOut = ref<Any>(null)
async function load(): Promise<void> {
  const r = await api.clSection('capabilities')
  caps.value = r.items
  classNames.value = r.classNames
  algos.value = (await api.clAlgorithms()).items
  if (!sel.value) sel.value = caps.value.find((c) => c.algorithm)?.code ?? caps.value[0]?.code
  pick(sel.value)
  if (!aSel.value) pickAlgo(algos.value[0]?.id)
}
load()
watch(() => lib.summary?.current?.version, load)
function pick(code: string): void {
  sel.value = code
  const c = caps.value.find((x) => x.code === code)
  form.value = c ? JSON.parse(JSON.stringify(c)) : null
}
function newCap(): void {
  form.value = { code: 'CAP-NEW', name: '', classes: [], algorithm: '', version: '', mode: '同步', timeout: 10, desc: '', inputs: [], outputs: [], _new: true }
  sel.value = ''
}
watch(() => form.value?.algorithm, (aid, old) => {
  if (!form.value || !aid || aid === old || !form.value._new && old === undefined) return
  const a = algos.value.find((x) => x.id === aid)
  if (!a) return
  form.value.version = a.version
  if (!form.value.inputs.length) form.value.inputs = (a.inputs ?? []).map((i: Any) => ({ name: i.name, type: i.type, unit: i.unit ?? '', bind: i.default != null ? String(i.default) : '' }))
  if (!form.value.outputs.length) form.value.outputs = [{ name: a.output?.name ?? 'out', type: '实数', unit: a.output?.unit ?? '', write: '' }]
})
async function save(): Promise<void> {
  const f = form.value
  if (await act(() => api.clSectionSave('capabilities', f._new ? f.code : sel.value, f), `已保存能力「${f.name}」`)) { sel.value = f.code; await load() }
}
async function remove(): Promise<void> {
  if (!confirm(`删除能力「${form.value.name}」？挂载它的类会一并取消挂载。`)) return
  if (await act(() => api.clSectionDelete('capabilities', sel.value), '已删除')) { sel.value = ''; await load() }
}
const classOptions = computed(() => Object.entries(classNames.value).map(([id, n]) => ({ value: id, label: n })))
const algo = computed(() => algos.value.find((a) => a.id === aSel.value))
function pickAlgo(id: string): void {
  aSel.value = id
  const a = algos.value.find((x) => x.id === id)
  testOut.value = null
  if (!a) return
  const ex: Any = {}
  for (const i of a.inputs ?? []) ex[i.name] = i.type === '常量' ? (i.default ?? 1) : [1.0, 2.0, 3.5, 3.0, 2.5]
  testIn.value = JSON.stringify(ex)
}
async function runTest(): Promise<void> {
  try { testOut.value = await api.clAlgoTest(aSel.value, { inputs: JSON.parse(testIn.value) }) } catch (e) { testOut.value = { ok: false, error: String((e as Error).message) } }
}
const discovery = computed(() => {
  const f = form.value
  if (!f) return ''
  const bound = (f.inputs ?? []).filter((i: Any) => i.bind).length
  return `GET /api/v2/objects/{对象ID}/capabilities\n→ [{ id: "${f.code}", name: "${f.name}",\n    inputs: 已自动绑定 ${bound}/${(f.inputs ?? []).length}, mode: "${f.mode === '同步' ? 'sync' : 'async'}" }, …]`
})
</script>

<template>
  <div class="flex items-center gap-3 mb-3">
    <h2 class="text-[18px] font-semibold">能力与算法</h2><span class="flex-1" />
    <button class="btn" disabled title="本 Demo 算法由内置实现代替，不支持上传">上传算法包</button>
    <button v-if="tab === 'cap'" class="btn btn-primary" :disabled="!canEdit()" @click="newCap">+ 新建能力</button>
  </div>
  <div class="flex gap-1.5 mb-3">
    <button class="asset-tab" :class="{ 'asset-tab-on': tab === 'cap' }" @click="tab = 'cap'">能力定义<span class="asset-tab-count">{{ caps.length }}</span></button>
    <button class="asset-tab" :class="{ 'asset-tab-on': tab === 'algo' }" @click="tab = 'algo'">算法库<span class="asset-tab-count">{{ algos.length }}</span></button>
  </div>

  <div v-if="tab === 'cap'" class="grid grid-cols-[420px_1fr] gap-4">
    <div class="card self-start">
      <div class="sec-title">能力列表</div>
      <table class="tbl"><thead><tr><th>能力</th><th>适用类</th><th>算法</th><th>方式</th></tr></thead><tbody>
        <tr v-for="c in caps" :key="c.code" :class="{ '!bg-brand/10': sel === c.code }" @click="pick(c.code)">
          <td>{{ c.name }}<div class="font-mono text-[10.5px] text-fg-mute">{{ c.code }}</div></td>
          <td class="text-xs">{{ (c.classes ?? []).map((x: string) => classNames[x] ?? x).join('、') || '—' }}<div v-if="c.inheritedClasses?.length" class="text-fg-mute">+ 继承 {{ c.inheritedClasses.length }} 个子类</div></td>
          <td class="font-mono text-xs">{{ c.algorithm || '—' }}<span v-if="c.version"> v{{ c.version }}</span></td><td>{{ c.mode }}</td></tr>
      </tbody></table>
    </div>
    <div v-if="form" class="space-y-3">
      <div class="card">
        <div class="flex items-center mb-3"><div class="sec-title !mb-0 flex-1">能力定义：{{ form.name || '（新）' }}</div>
          <button v-if="!form._new" class="btn btn-danger mr-1" :disabled="!canEdit()" @click="remove">删除</button>
          <button class="btn btn-primary" :disabled="!canEdit()" @click="save">保存</button></div>
        <DevForm :model="form" :disabled="!canEdit()" :fields="[
          { key: 'code', label: '能力编码', type: 'code', readonly: !form._new }, { key: 'name', label: '名称' },
          { key: 'classes', label: '适用类', type: 'multi', options: classOptions, hint: '即类的挂载：在这里勾选与在类库「能力」页签勾选是同一份数据；子类自动继承' },
          { key: 'algorithm', label: '引用算法', type: 'select', options: [{ value: '', label: '（无，数据类能力）' }, ...algos.map((a) => ({ value: a.id, label: `${a.name}（${a.id}）` }))] },
          { key: 'version', label: '算法版本' }, { key: 'mode', label: '执行方式', type: 'select', options: ['同步', '异步'] },
          { key: 'timeout', label: '超时（秒）', type: 'number' }, { key: 'desc', label: '说明' }]" />
        <div v-if="form.inheritedClasses?.length" class="text-xs mt-2 pl-[104px]">
          <span class="text-fg-mute">因继承而具备（{{ form.inheritedClasses.length }} 个子类）：</span>
          <span v-for="x in form.inheritedClasses.slice(0, 12)" :key="x" class="pill pill-plain mr-1 mb-0.5">{{ classNames[x] ?? x }}</span>
          <span v-if="form.inheritedClasses.length > 12" class="text-fg-mute">等</span>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-3">
        <div class="card">
          <div class="flex items-center"><div class="sec-title !mb-0 flex-1">输入签名 → 参数模板绑定</div><button class="ctl" :disabled="!canEdit()" @click="form.inputs.push({ name: '', type: '时序', unit: '', bind: '' })">+</button></div>
          <table class="tbl mt-1"><thead><tr><th>算法输入</th><th>类型 / 单位</th><th>绑定参数模板</th><th></th></tr></thead><tbody>
            <tr v-for="(i, k) in form.inputs" :key="k" class="!cursor-default"><td><input v-model="i.name" class="inp w-24 font-mono" :disabled="!canEdit()" /></td>
              <td class="text-xs">{{ i.type }}{{ i.unit ? ' · ' + i.unit : '' }}</td><td><input v-model="i.bind" class="inp w-full" :disabled="!canEdit()" placeholder="参数模板名 / 常量" /></td>
              <td><button class="ctl !px-1.5" :disabled="!canEdit()" @click="form.inputs.splice(k, 1)">×</button></td></tr>
          </tbody></table>
        </div>
        <div class="card">
          <div class="sec-title">输出签名</div>
          <table class="tbl"><thead><tr><th>算法输出</th><th>类型 / 单位</th><th>写入</th></tr></thead><tbody>
            <tr v-for="(o, k) in form.outputs" :key="k" class="!cursor-default"><td class="font-mono">{{ o.name }}</td><td class="text-xs">{{ o.type }}{{ o.unit ? ' · ' + o.unit : '' }}</td>
              <td><input v-model="o.write" class="inp w-full" :disabled="!canEdit()" placeholder="计算值参数模板" /></td></tr>
          </tbody></table>
          <div class="sec-title mt-3">运行态发现（智能体视角）</div>
          <pre class="text-[11px] bg-ink-panel2 rounded p-2 whitespace-pre-wrap">{{ discovery }}</pre>
        </div>
      </div>
    </div>
  </div>

  <div v-else class="grid grid-cols-[480px_1fr] gap-4">
    <div class="card self-start">
      <div class="sec-title">算法列表</div>
      <table class="tbl"><thead><tr><th>算法标识</th><th>名称</th><th>版本</th><th>实现</th><th>引用</th></tr></thead><tbody>
        <tr v-for="a in algos" :key="a.id" :class="{ '!bg-brand/10': aSel === a.id }" @click="pickAlgo(a.id)">
          <td class="font-mono text-xs">{{ a.id }}</td><td>{{ a.name }}</td><td>v{{ a.version }}</td><td class="text-xs">{{ a.invoke?.protocol }}</td>
          <td class="tabular-nums">{{ a.usedByCaps.length + a.usedByCalcs.length }}</td></tr>
      </tbody></table>
    </div>
    <div v-if="algo" class="space-y-3">
      <div class="card">
        <div class="sec-title">算法登记：{{ algo.id }} v{{ algo.version }}</div>
        <dl class="kv text-sm">
          <dt>实现方式</dt><dd>{{ algo.impl }}</dd><dt>入口</dt><dd class="font-mono text-xs">{{ algo.invoke?.protocol }} {{ algo.invoke?.method }} {{ algo.invoke?.endpoint }}</dd>
          <dt>说明</dt><dd class="text-xs text-fg-dim">{{ algo.description }}</dd>
          <dt>被引用</dt><dd><span v-for="c in algo.usedByCaps" :key="c" class="pill pill-info mr-1">能力 {{ c }}</span><span v-if="algo.usedByCalcs.length" class="pill pill-info">计算组态 ×{{ algo.usedByCalcs.length }}</span></dd>
        </dl>
        <table class="tbl mt-2"><thead><tr><th>方向</th><th>名称</th><th>类型</th><th>单位</th><th>必填</th><th>默认</th></tr></thead><tbody>
          <tr v-for="i in algo.inputs" :key="i.name" class="!cursor-default"><td>输入</td><td class="font-mono">{{ i.name }} <span class="font-sans text-fg-mute">{{ i.label }}</span></td><td>{{ i.type }}</td><td>{{ i.unit }}</td><td>{{ i.required ? '是' : '否' }}</td><td>{{ i.default ?? '' }}</td></tr>
          <tr class="!cursor-default"><td>输出</td><td class="font-mono">{{ algo.output?.name }} <span class="font-sans text-fg-mute">{{ algo.output?.label }}</span></td><td>时序</td><td>{{ algo.output?.unit }}</td><td></td><td></td></tr>
        </tbody></table>
        <div class="text-[11px] text-fg-mute mt-1">登记来自 data/config/6APA_算法库.json；多版本与上传算法包在正式产品中实现</div>
      </div>
      <div class="card">
        <div class="flex items-center mb-2"><div class="sec-title !mb-0 flex-1">测试</div><button class="btn btn-primary" @click="runTest">运行</button></div>
        <div class="grid grid-cols-2 gap-3">
          <div><div class="text-xs text-fg-mute mb-1">输入（JSON，时序为数组）</div><textarea v-model="testIn" class="inp w-full font-mono text-xs" rows="5" /></div>
          <div><div class="text-xs text-fg-mute mb-1">输出 <span v-if="testOut" class="pill" :class="testOut.ok ? 'pill-ok' : 'pill-err'">{{ testOut.ok ? `成功 · ${testOut.ms} ms` : '失败' }}</span></div>
            <pre class="text-[11px] bg-ink-panel2 rounded p-2 min-h-[90px] whitespace-pre-wrap">{{ testOut ? (testOut.ok ? JSON.stringify(testOut.output) + '\n' + (testOut.log ?? []).join('\n') : testOut.error) : '' }}</pre></div>
        </div>
      </div>
    </div>
  </div>
</template>
