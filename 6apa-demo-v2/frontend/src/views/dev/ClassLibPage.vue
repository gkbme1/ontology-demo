<script setup lang="ts">
/**
 * 类库（需求 SW-003～009、012、015，图 4-7～4-12）：左侧类树（新建类、搜索、实例数，斜体为抽象类），右侧类详情页签：
 * 基本信息、属性、参数模板、约束模板、现象/工况模板、根因模板、工艺影响模板、能力、实例。各模板逐行标出来源（本类 / 继承 / 覆盖）。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { openInEngineering } from '@/composables/useNav'
import { act, canEdit, lib } from '@/composables/useClassLib'
import DevForm from './DevForm.vue'
import ClassTreeNode from './ClassTreeNode.vue'
import TplRuleEditor from './TplRuleEditor.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const tree = ref<Any[]>([])
const open = ref<Record<string, boolean>>({ 'cls-equipment': true, 'cls-cat-fysb': true })
const kw = ref('')
const sel = ref(lib.focusClass || 'cls-type-gdhmfyg')
const cls = ref<Any>(null)
const tab = ref('base')
const metas = ref<Any[]>([])
const allCaps = ref<Any[]>([])

async function loadTree(): Promise<void> { tree.value = (await api.clTree()).items }
async function loadClass(): Promise<void> {
  if (!sel.value) { cls.value = null; return }
  try { cls.value = await api.clClass(sel.value) } catch { cls.value = null }
  baseForm.value = cls.value ? JSON.parse(JSON.stringify({ code: cls.value.code, name: cls.value.name, metaclass: cls.value.metaclass, parent: cls.value.parent ?? '',
    abstract: !!cls.value.abstract, status: cls.value.status, icon: cls.value.icon ?? '', desc: cls.value.desc ?? '', tabs: cls.value.tabs ?? null })) : null
  editing.value = null
}
async function init(): Promise<void> {
  await loadTree()
  metas.value = (await api.clSection('metaclasses')).items
  allCaps.value = (await api.clSection('capabilities')).items
  await loadClass()
}
init()
watch(sel, () => { tab.value = tab.value === 'inst' ? 'base' : tab.value; loadClass() })
watch(() => lib.summary?.current?.version, init)
async function refresh(): Promise<void> { await Promise.all([loadTree(), loadClass()]) }

function filterTree(nodes: Any[]): Any[] {
  if (!kw.value) return nodes
  return nodes.map((n) => ({ ...n, children: filterTree(n.children) }))
    .filter((n) => n.name.includes(kw.value) || n.code.toLowerCase().includes(kw.value.toLowerCase()) || n.children.length)
}
const shown = computed(() => filterTree(tree.value))
const flat = computed(() => { const out: Any[] = []; const walk = (ns: Any[], d: number) => ns.forEach((n) => { out.push({ ...n, d }); walk(n.children, d + 1) }); walk(tree.value, 0); return out })

// ---------------- 基本信息
const baseForm = ref<Any>(null)
const creating = ref(false)
function newClass(): void {
  creating.value = true
  baseForm.value = { code: 'CLS-', name: '', metaclass: cls.value?.metaclass ?? 'MC_EQUIP', parent: cls.value?.id ?? '', abstract: false, status: '草案', icon: '', desc: '', tabs: null }
  tab.value = 'base'
}
async function saveBase(): Promise<void> {
  const f = { ...baseForm.value, parent: baseForm.value.parent || null }
  const r = creating.value ? await act(() => api.clClassCreate(f), `已新建类「${f.name}」`) : await act(() => api.clClassUpdate(sel.value, f), '已保存类定义')
  if (r) { creating.value = false; sel.value = r.id; open.value[f.parent] = true; await refresh() }
}
async function delClass(): Promise<void> {
  if (!confirm(`删除类「${cls.value.name}」？存在子类或实例时不能删除。`)) return
  if (await act(() => api.clClassDelete(sel.value), '已删除类')) { sel.value = cls.value.parent ?? ''; await refresh() }
}
const TABS = computed(() => lib.summary?.enums?.tabs ?? [])
const tabsEff = computed<string[]>(() => baseForm.value?.tabs ?? cls.value?.tabsEffective ?? [])
function toggleTab(t: string): void {
  const cur = [...tabsEff.value]
  const i = cur.indexOf(t)
  if (i >= 0) cur.splice(i, 1)
  else cur.push(t)
  baseForm.value.tabs = cur
}

// ---------------- 通用：模板条目的编辑
const PART_FIELDS: Record<string, Any[]> = {
  attrs: [{ key: 'group', label: '分组' }, { key: 'code', label: '属性编码', type: 'code' }, { key: 'name', label: '名称' }, { key: 'dtype', label: '数据类型', type: 'select', options: [] },
    { key: 'unit', label: '单位' }, { key: 'required', label: '必填', type: 'bool' }, { key: 'default', label: '默认值' }, { key: 'enum', label: '枚举值', placeholder: '用 / 分隔' },
    { key: 'range', label: '取值范围', placeholder: '如 1~10' }, { key: 'desc', label: '说明' }],
  params: [{ key: 'code', label: '参数编码', type: 'code' }, { key: 'name', label: '名称' }, { key: 'category', label: '类别', type: 'select', options: [] },
    { key: 'quantity', label: '物理量' }, { key: 'unit', label: '单位' }, { key: 'dtype', label: '数据类型', type: 'select', options: [] },
    { key: 'repeatable', label: '可重复', type: 'bool', hint: '多实例参数（按位置维度展开）' }, { key: 'required', label: '必备参数', type: 'bool', hint: '实例未绑定位号时校验提示' }, { key: 'desc', label: '说明' }],
  constraints: [{ key: 'code', label: '约束编码', type: 'code' }, { key: 'param', label: '约束对象', hint: '参数模板名，可重复参数写 名称[*]' },
    { key: 'ctype', label: '约束类型', type: 'select', options: [] }, { key: 'source', label: '限值来源', type: 'select', options: [] },
    { key: 'll', label: '低低', type: 'number' }, { key: 'l', label: '低', type: 'number' }, { key: 'nl', label: '正常下限', type: 'number' }, { key: 'nh', label: '正常上限', type: 'number' },
    { key: 'h', label: '高', type: 'number' }, { key: 'hh', label: '高高', type: 'number' }, { key: 'unit', label: '单位' }, { key: 'expr', label: '逻辑表达式', placeholder: '如 P_OUT > P_IN' },
    { key: 'cond', label: '适用工况', hint: '引用工况模板，空 = 所有工况' }, { key: 'priority', label: '优先级', type: 'number' }, { key: 'override', label: '实例覆盖' }],
  influences: [{ key: 'code', label: '编码', type: 'code' }, { key: 'from', label: '来源参数' }, { key: 'to', label: '目标参数' },
    { key: 'direction', label: '影响方向', type: 'select', options: ['正相关', '负相关', '非单调'] }, { key: 'strength', label: '影响强度', type: 'select', options: ['强', '中', '弱'] },
    { key: 'lag', label: '典型时滞', placeholder: '如 10 分钟' }, { key: 'cond', label: '适用工况' }, { key: 'scope', label: '范围', type: 'select', options: ['类内', '跨类（按拓扑上下游路径限定）'] },
    { key: 'mechanism', label: '机理说明' }],
  causes: [{ key: 'code', label: '编码', type: 'code' }, { key: 'cause', label: '原因现象', type: 'select', options: [] }, { key: 'effect', label: '结果现象', type: 'select', options: [] },
    { key: 'path', label: '关系路径限定', placeholder: '跨类时填写，如：仪表风 供应→ 本对象；仅当两者存在供应关系时生成' },
    { key: 'mechanism', label: '机理说明', type: 'textarea' }, { key: 'confidence', label: '默认置信度', type: 'select', options: ['高', '中', '低'] },
    { key: 'evidence', label: '证据依据' }, { key: 'cond', label: '适用条件' }],
}
const fieldsFor = (part: string): Any[] => PART_FIELDS[part].map((f) => {
  const e = lib.summary?.enums ?? {}
  if (part === 'attrs' && f.key === 'dtype') return { ...f, options: e.dtypes }
  if (part === 'params' && f.key === 'category') return { ...f, options: e.paramCats }
  if (part === 'params' && f.key === 'dtype') return { ...f, options: e.dtypes }
  if (part === 'constraints' && f.key === 'ctype') return { ...f, options: e.consTypes }
  if (part === 'constraints' && f.key === 'source') return { ...f, options: e.consSources }
  if (part === 'causes' && (f.key === 'cause' || f.key === 'effect')) return { ...f, options: phenNames.value }
  return f
})
const phenNames = computed<string[]>(() => [...new Set([...(cls.value?.parts?.phenomena ?? []).map((p: Any) => p.name), ...(cls.value?.parts?.causes ?? []).flatMap((c: Any) => [c.cause, c.effect])])])
const editing = ref<{ part: string; code: string; item: Any; isNew: boolean } | null>(null)
function edit(part: string, x: Any): void { editing.value = { part, code: x.code, item: JSON.parse(JSON.stringify(x)), isNew: false } }
function add(part: string, extra: Any = {}): void {
  const n = (cls.value?.parts?.[part]?.length ?? 0) + 1
  const base: Record<string, Any> = {
    attrs: { code: 'new_attr', name: '', group: '设计', dtype: '文本', required: false },
    params: { code: 'P_NEW', name: '', category: '测量值', quantity: '', unit: '', dtype: '实数', repeatable: false, dims: [], tagRule: { funcs: '', keywords: '' }, required: false },
    constraints: { code: `CT-${n}`, param: '', ctype: '工艺限值', source: '模板默认值', unit: '', cond: '', priority: 1 },
    influences: { code: `IT-NEW-${n}`, from: '', to: '', direction: '正相关', strength: '中', lag: '', scope: '类内' },
    causes: { code: `CT-NEW-${n}`, cause: '', effect: '', confidence: '中', evidence: '', cond: '全部工况', path: '' },
    phenomena: { code: `PHT-NEW-${n}`, name: '', category: '设备', severity: '警告', desc: '', rule: { type: 'group', op: 'OR', children: [] } },
  }
  editing.value = { part, code: '', item: { ...base[part], ...extra }, isNew: true }
  if (part === 'phenomena') phenSel.value = ''
}
async function saveItem(): Promise<void> {
  const e = editing.value!
  const r = await act(() => api.clItem(sel.value, e.part, e.isNew ? e.item.code : e.code, e.item), '已保存')
  if (r) { await loadClass(); if (e.part === 'phenomena') pickPhen(r.code) }
}
async function delItem(part: string, x: Any): Promise<void> {
  if (!confirm(`删除「${x.name || x.code}」？`)) return
  if (await act(() => api.clItemDelete(sel.value, part, x.code), '已删除')) await loadClass()
}
const showInherited = ref(true)
const onlyRequired = ref(false)
const rows = (part: string): Any[] => (cls.value?.parts?.[part] ?? []).filter((x: Any) => (showInherited.value || x._own) && (part !== 'params' || !onlyRequired.value || x.required))
const SRC = (x: Any) => (x._own ? (x._src.startsWith('覆盖') ? 'pill-warn' : 'pill-info') : 'pill-plain')
const bandText = (c: Any) => c.source === '逻辑约束' ? c.expr : c.source === '取 XBase 报警限' ? '取 XBase 位号报警限 H / HH' : [c.ll, c.l, c.nl != null || c.nh != null ? `${c.nl ?? ''}~${c.nh ?? ''}` : null, c.h, c.hh].map((v) => (v ?? '—')).join(' / ')

// ---------------- 参数模板：位号匹配试验
const testTag = ref('TI_1301C')
const testRes = ref<Any>(null)
async function runTagTest(): Promise<void> {
  const code = editing.value?.part === 'params' ? editing.value.item.code : rows('params')[0]?.code
  if (!code) return
  try { testRes.value = await api.clParamTest(sel.value, code, { tag: testTag.value }) } catch (e) { alert((e as Error).message) }
}
const dimCount = computed(() => (editing.value?.item?.dims ?? []).reduce((n: number, d: Any) => n * Math.max(1, (d.values ?? []).length), 1))

// ---------------- 现象模板
const phenSel = ref('')
const preview = ref<Any>(null)
function pickPhen(code: string): void {
  phenSel.value = code
  const x = (cls.value?.parts?.phenomena ?? []).find((p: Any) => p.code === code)
  if (x) { edit('phenomena', x); if (!editing.value!.item.rule) editing.value!.item.rule = { type: 'group', op: 'OR', children: [] } }
  preview.value = null
  api.clPhenPreview(sel.value, code).then((r) => (preview.value = r)).catch(() => (preview.value = null))
}

// ---------------- 根因模板图（左：原因，右：结果）
const causeGraph = computed(() => {
  const cs = cls.value?.parts?.causes ?? []
  const effects = [...new Set(cs.map((c: Any) => c.effect))] as unknown as string[]
  const causes = [...new Set(cs.map((c: Any) => c.cause).filter((c: string) => !effects.includes(c)))] as unknown as string[]
  const mids = effects.filter((e) => cs.some((c: Any) => c.cause === e))
  const finals = effects.filter((e) => !mids.includes(e))
  const own = new Set((cls.value?.parts?.phenomena ?? []).map((p: Any) => p.name))
  const col = (names: string[], x: number) => names.map((n, i) => ({ n, x, y: 20 + i * 46, own: own.has(n) }))
  const nodes = [...col(causes, 10), ...col(mids, 250), ...col(finals, 490)]
  const pos = Object.fromEntries(nodes.map((p) => [p.n, p]))
  return { nodes, edges: cs.map((c: Any) => ({ a: pos[c.cause], b: pos[c.effect], low: c.confidence === '低', code: c.code })).filter((e: Any) => e.a && e.b),
           h: Math.max(causes.length, mids.length, finals.length) * 46 + 30 }
})
const capsChecked = computed(() => new Set<string>((cls.value?.caps ?? []).filter((c: Any) => c._src === "本类").map((c: Any) => String(c.code))))
async function toggleCap(code: string): Promise<void> {
  const s = new Set(capsChecked.value)
  if (s.has(code)) s.delete(code)
  else s.add(code)
  if (await act(() => api.clCaps(sel.value, [...s]), '已更新挂载能力')) await loadClass()
}
const CLS_TABS = [['base', '基本信息'], ['attrs', '属性'], ['params', '参数模板'], ['constraints', '约束模板'], ['phenomena', '现象/工况模板'],
  ['causes', '根因模板'], ['influences', '工艺影响模板'], ['caps', '能力'], ['inst', '实例']] as const
const cnt = (k: string) => (k === 'caps' ? cls.value?.caps?.length : k === 'inst' ? cls.value?.instances?.length : cls.value?.parts?.[k]?.length)
</script>

<template>
  <div class="grid grid-cols-[320px_1fr] gap-4 min-h-[calc(100vh-110px)]">
    <!-- 类树 -->
    <div class="card self-start sticky top-0 max-h-[calc(100vh-110px)] flex flex-col">
      <div class="flex items-center mb-2"><div class="sec-title !mb-0 flex-1">类树</div>
        <button class="btn btn-primary !py-1" :disabled="!canEdit()" @click="newClass">+ 新建类</button></div>
      <input v-model="kw" class="inp w-full mb-2" placeholder="搜索类名称 / 编码" />
      <div class="flex-1 overflow-auto -mx-1">
        <ClassTreeNode v-for="n in shown" :key="n.id" :node="n" :depth="0" :sel="sel" :open="open" :kw="kw"
                       @pick="(id: string) => { sel = id; creating = false }" @toggle="(id: string) => (open[id] = !open[id])" />
      </div>
      <div class="text-[11px] text-fg-mute mt-2">数字为实例数（含子类）；斜体为抽象类</div>
    </div>

    <!-- 类详情 -->
    <div v-if="creating && baseForm" class="card self-start">
      <div class="flex items-center mb-3"><div class="sec-title !mb-0 flex-1">新建类</div>
        <button class="btn mr-1" @click="creating = false; loadClass()">取消</button><button class="btn btn-primary" @click="saveBase">保存</button></div>
      <DevForm :model="baseForm" :fields="[
        { key: 'code', label: '类编码', type: 'code', hint: '全局唯一，如 CLS-EQ-CCLXJ' }, { key: 'name', label: '类名称' },
        { key: 'metaclass', label: '所属元类', type: 'select', options: metas.map((m) => ({ value: m.code, label: `${m.name}（${m.code}）` })) },
        { key: 'parent', label: '父类', type: 'select', options: [{ value: '', label: '（无，作为根类）' }, ...flat.map((n) => ({ value: n.id, label: '　'.repeat(n.d) + n.name }))] },
        { key: 'abstract', label: '抽象类', type: 'bool', hint: '是（只用于被继承，不能创建实例）' },
        { key: 'status', label: '状态', type: 'select', options: lib.summary?.enums?.statuses ?? [] }, { key: 'icon', label: '图标' }, { key: 'desc', label: '说明', type: 'textarea' }]" />
    </div>
    <div v-else-if="cls" class="space-y-3 min-w-0">
      <div class="flex flex-wrap items-center gap-2">
        <h2 class="text-[19px] font-semibold">{{ cls.name }}</h2>
        <span class="pill pill-info">{{ cls.metaclassName }}类</span>
        <span class="pill" :class="cls.status === '生效' ? 'pill-ok' : cls.status === '停用' ? 'pill-mute' : 'pill-warn'">{{ cls.status }}</span>
        <span v-if="cls.abstract" class="pill pill-mute">抽象类</span>
        <span class="text-xs text-fg-mute">{{ cls.path.map((p: Any) => p.name).join(' › ') }} ｜ 编码 {{ cls.code }} ｜ 实例 {{ cls.instances.reduce((n: number, i: Any) => n + i.members + 1, 0) }} 个</span>
      </div>
      <div class="flex flex-wrap gap-1.5">
        <button v-for="[k, l] in CLS_TABS" :key="k" class="asset-tab" :class="{ 'asset-tab-on': tab === k }" @click="tab = k; editing = null">
          {{ l }}<span v-if="cnt(k)" class="asset-tab-count">{{ cnt(k) }}</span>
        </button>
      </div>

      <!-- 基本信息 -->
      <template v-if="tab === 'base' && baseForm">
        <div class="grid grid-cols-[1.3fr_1fr] gap-3">
          <div class="card">
            <div class="flex items-center mb-3"><div class="sec-title !mb-0 flex-1">类定义</div>
              <button class="btn btn-danger mr-1" :disabled="!canEdit()" @click="delClass">删除类</button>
              <button class="btn btn-primary" :disabled="!canEdit()" @click="saveBase">保存</button></div>
            <DevForm :model="baseForm" :disabled="!canEdit()" :fields="[
              { key: 'code', label: '类编码', type: 'code' }, { key: 'name', label: '类名称' },
              { key: 'metaclass', label: '所属元类', type: 'select', options: metas.map((m) => ({ value: m.code, label: `${m.name}（${m.code}）` })) },
              { key: 'parent', label: '父类', type: 'select', options: [{ value: '', label: '（无，根类）' }, ...flat.filter((n) => n.id !== cls.id).map((n) => ({ value: n.id, label: '　'.repeat(n.d) + n.name + (n.abstract ? '（抽象）' : '') }))] },
              { key: 'abstract', label: '抽象类', type: 'bool', hint: '是（只用于被继承，不能创建实例）' },
              { key: 'status', label: '状态', type: 'select', options: lib.summary?.enums?.statuses ?? [] }, { key: 'icon', label: '图标' }, { key: 'desc', label: '说明', type: 'textarea' }]" />
          </div>
          <div class="card">
            <div class="sec-title">对象详情可见页签 <span class="font-normal text-fg-mute">继承自元类，可按类收窄</span></div>
            <div class="grid grid-cols-2 gap-1.5 text-xs">
              <label v-for="t in TABS" :key="t" class="inline-flex items-center gap-1.5"><input type="checkbox" :checked="tabsEff.includes(t)" :disabled="!canEdit()" @change="toggleTab(t)" />{{ t }}</label>
            </div>
            <div class="sec-title mt-4">继承汇总</div>
            <table class="tbl"><thead><tr><th>内容</th><th>本类</th><th>继承</th></tr></thead><tbody>
              <tr v-for="[k, l] in [['attrs', '属性'], ['params', '参数模板'], ['constraints', '约束模板'], ['phenomena', '现象/工况模板'], ['causes', '根因模板'], ['influences', '工艺影响模板']]" :key="k" class="!cursor-default">
                <td>{{ l }}</td><td class="tabular-nums">{{ cls.summary[k].own }}</td><td class="tabular-nums">{{ cls.summary[k].inherited }}</td></tr>
            </tbody></table>
          </div>
        </div>
        <div class="card text-xs text-fg-dim flex items-center gap-2">
          <div class="sec-title !mb-0 mr-2">版本信息</div>
          类库版本 {{ cls.version.current }}（{{ cls.version.status }}） · 最近修改 {{ cls.version.updatedAt }}
          <template v-if="cls.version.since"> · 本类自 {{ cls.version.since }} 以来 {{ cls.version.changes }} 处变更</template>
          <button class="ctl ml-2" @click="lib.page = 'ver'">查看差异</button>
        </div>
      </template>

      <!-- 属性 / 约束 / 工艺影响：表格 + 编辑面板 -->
      <template v-else-if="['attrs', 'constraints', 'influences'].includes(tab)">
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <div class="sec-title !mb-0 flex-1">{{ ({ attrs: '属性定义', constraints: '约束模板', influences: '工艺影响模板' } as Any)[tab] }}</div>
            <label class="text-xs inline-flex items-center gap-1"><input v-model="showInherited" type="checkbox" />显示继承</label>
            <button v-if="tab === 'constraints'" class="btn" :disabled="!canEdit()" @click="add('constraints', { source: '逻辑约束', expr: '' })">+ 逻辑约束</button>
            <button class="btn btn-primary" :disabled="!canEdit()" @click="add(tab)">{{ tab === 'attrs' ? '+ 新增属性' : tab === 'constraints' ? '+ 限值约束' : '+ 新增影响' }}</button>
          </div>
          <table v-if="tab === 'attrs'" class="tbl"><thead><tr><th>分组</th><th>属性编码</th><th>名称</th><th>数据类型</th><th>单位</th><th>必填</th><th>默认值 / 枚举 / 范围</th><th>来源</th></tr></thead><tbody>
            <tr v-for="x in rows('attrs')" :key="x.code" :class="{ '!bg-brand/10': editing?.code === x.code }" @click="edit('attrs', x)">
              <td>{{ x.group }}</td><td class="font-mono text-xs">{{ x.code }}</td><td>{{ x.name }}</td><td>{{ x.dtype }}</td><td>{{ x.unit }}</td><td>{{ x.required ? '是' : '否' }}</td>
              <td class="text-xs text-fg-dim">{{ [x.default && `默认 ${x.default}`, x.enum, x.range && `范围 ${x.range}`, x.desc].filter(Boolean).join(' · ') || '—' }}</td>
              <td><span class="pill" :class="SRC(x)">{{ x._src }}</span></td></tr>
          </tbody></table>
          <table v-else-if="tab === 'constraints'" class="tbl"><thead><tr><th>约束对象</th><th>约束类型</th><th>LL / L / 正常 / H / HH（或表达式）</th><th>单位</th><th>限值来源</th><th>适用工况</th><th>优先级</th><th>来源</th></tr></thead><tbody>
            <tr v-for="x in rows('constraints')" :key="x.code" :class="{ '!bg-brand/10': editing?.code === x.code }" @click="edit('constraints', x)">
              <td><span class="font-mono text-xs text-fg-mute">{{ x.code }}</span> {{ x.param }}</td><td>{{ x.ctype }}</td><td class="font-mono text-xs">{{ bandText(x) }}</td><td>{{ x.unit }}</td>
              <td><span class="pill" :class="x.source === '逻辑约束' ? 'pill-info' : x.source === '取 XBase 报警限' ? 'pill-warn' : 'pill-plain'">{{ x.source }}</span></td>
              <td>{{ x.cond || '全部工况' }}</td><td>{{ x.priority }}</td><td><span class="pill" :class="SRC(x)">{{ x._src }}</span></td></tr>
          </tbody></table>
          <table v-else class="tbl"><thead><tr><th>来源参数</th><th>方向</th><th>目标参数</th><th>强度</th><th>时滞</th><th>范围</th><th>机理</th><th>来源</th></tr></thead><tbody>
            <tr v-for="x in rows('influences')" :key="x.code" :class="{ '!bg-brand/10': editing?.code === x.code }" @click="edit('influences', x)">
              <td>{{ x.from }}</td><td :class="x.direction === '负相关' ? 'text-warn' : 'text-ok'">{{ x.direction }}</td><td>{{ x.to }}</td><td>{{ x.strength }}</td><td>{{ x.lag || '—' }}</td>
              <td class="text-xs">{{ x.scope }}</td><td class="text-xs text-fg-dim max-w-[300px]">{{ x.mechanism }}</td><td><span class="pill" :class="SRC(x)">{{ x._src }}</span></td></tr>
          </tbody></table>
        </div>
        <div v-if="editing && editing.part === tab" class="card">
          <div class="flex items-center mb-3"><div class="sec-title !mb-0 flex-1">{{ editing.isNew ? '新增' : '编辑' }}：{{ editing.item.name || editing.item.param || editing.item.code }}
            <span v-if="!editing.isNew && editing.item._src && !editing.item._own" class="font-normal text-fg-mute">（继承项：保存后在本类覆盖）</span></div>
            <button v-if="!editing.isNew" class="btn btn-danger mr-1" :disabled="!canEdit()" @click="delItem(tab, editing.item)">删除</button>
            <button class="btn mr-1" @click="editing = null">取消</button><button class="btn btn-primary" :disabled="!canEdit()" @click="saveItem">保存</button></div>
          <DevForm :model="editing.item" :fields="fieldsFor(tab)" :disabled="!canEdit()" :cols="2" />
        </div>
      </template>

      <!-- 参数模板 -->
      <template v-else-if="tab === 'params'">
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <div class="sec-title !mb-0 flex-1">参数模板 <span class="font-normal text-fg-mute">{{ cls.parts.params.length }} 项（本类 {{ cls.summary.params.own }} · 继承 {{ cls.summary.params.inherited }}）</span></div>
            <label class="text-xs inline-flex items-center gap-1"><input v-model="onlyRequired" type="checkbox" />只看必备参数</label>
            <button class="btn btn-primary" :disabled="!canEdit()" @click="add('params')">+ 新增参数模板</button>
          </div>
          <table class="tbl"><thead><tr><th>参数编码</th><th>名称</th><th>类别</th><th>物理量</th><th>单位</th><th>可重复 / 位置维度</th><th>位号匹配规则</th><th>必备</th><th>来源</th></tr></thead><tbody>
            <tr v-for="x in rows('params')" :key="x.code" :class="{ '!bg-brand/10': editing?.code === x.code }" @click="edit('params', x); testRes = null">
              <td class="font-mono text-xs">{{ x.code }}</td><td>{{ x.name }}<span v-if="x.semantic" class="pill pill-ok !py-0 ml-1">工艺属性</span></td><td>{{ x.category }}</td><td>{{ x.quantity }}</td><td>{{ x.unit }}</td>
              <td class="text-xs">{{ x.repeatable ? `是 · ${(x.dims ?? []).map((d: Any) => d.name).join('×') || '—'}` : '否' }}</td>
              <td class="font-mono text-xs">{{ x.tagRule?.funcs ? `${x.tagRule.funcs} + ` : '' }}{{ x.tagRule?.keywords ? `「${x.tagRule.keywords}」` : '' }}</td>
              <td>{{ x.required ? '是' : '否' }}</td><td><span class="pill" :class="SRC(x)">{{ x._src }}</span></td></tr>
          </tbody></table>
        </div>
        <div v-if="editing && editing.part === 'params'" class="card">
          <div class="flex items-center mb-3"><div class="sec-title !mb-0 flex-1">{{ editing.isNew ? '新增参数模板' : `编辑：${editing.item.name}` }}</div>
            <button v-if="!editing.isNew" class="btn btn-danger mr-1" :disabled="!canEdit()" @click="delItem('params', editing.item)">删除</button>
            <button class="btn mr-1" @click="editing = null">取消</button><button class="btn btn-primary" :disabled="!canEdit()" @click="saveItem">保存</button></div>
          <DevForm :model="editing.item" :fields="fieldsFor('params')" :disabled="!canEdit()" :cols="2" />
          <div class="grid grid-cols-[96px_1fr_96px_1fr] gap-x-4 gap-y-2 items-center text-sm mt-2">
            <span class="text-xs text-fg-mute text-right">功能字母</span><input v-model="editing.item.tagRule.funcs" class="inp font-mono" :disabled="!canEdit()" placeholder="如 TI|TE" />
            <span class="text-xs text-fg-mute text-right">描述关键字</span><input v-model="editing.item.tagRule.keywords" class="inp" :disabled="!canEdit()" placeholder="如 温度 | 轴承" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="card">
            <div class="sec-title">多实例参数：{{ editing?.part === 'params' ? editing.item.name : '（选中一个参数模板）' }} · 位置维度</div>
            <template v-if="editing?.part === 'params'">
              <div v-for="(d, i) in editing.item.dims" :key="i" class="flex items-center gap-2 mb-1.5">
                <input v-model="d.name" class="inp w-24" :disabled="!canEdit()" placeholder="维度名" />
                <input :value="(d.values ?? []).join('、')" class="inp flex-1" :disabled="!canEdit()" placeholder="取值，用「、」分隔，如 低压缸、高压缸"
                       @change="d.values = ($event.target as HTMLInputElement).value.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)" />
                <button class="ctl !px-1.5" :disabled="!canEdit()" @click="editing.item.dims.splice(i, 1)">×</button>
              </div>
              <button class="ctl" :disabled="!canEdit()" @click="editing.item.dims.push({ name: '', values: [] }); editing.item.repeatable = true">+ 维度</button>
              <div class="text-xs text-fg-dim mt-2">实例化：每台设备展开为 <b>{{ editing.item.repeatable ? dimCount : 1 }}</b> 个参数</div>
            </template>
          </div>
          <div class="card">
            <div class="sec-title">位号匹配试验</div>
            <div class="flex gap-2"><input v-model="testTag" class="inp flex-1 font-mono" placeholder="输入位号，如 TI_1301C" @keydown.enter="runTagTest" />
              <button class="btn btn-primary" @click="runTagTest">试验</button></div>
            <div v-if="testRes" class="text-xs mt-2 space-y-1">
              <div class="text-fg-dim">{{ testRes.tag }} · {{ testRes.desc || '（点表中无此位号描述）' }}<span v-if="testRes.equipment"> · {{ testRes.equipment }}</span></div>
              <div>→ {{ testRes.matched ? '匹配' : '不匹配' }} <b>{{ testRes.template }}</b>
                <span v-if="testRes.dims.some((d: Any) => d.value)">[{{ testRes.dims.map((d: Any) => d.value ?? '?').join(', ') }}]</span>
                <span class="pill ml-1" :class="testRes.matched ? 'pill-ok' : 'pill-mute'">置信度 {{ testRes.confidence }}</span></div>
              <div class="text-fg-mute">规则：功能字母 {{ testRes.funcs.join('|') || '—' }}{{ testRes.funcOk ? ' ✓' : ' ✗' }}（位号前缀 {{ testRes.prefix }}）· 关键字「{{ testRes.keywordsAll.join('|') }}」{{ testRes.keywords.length ? ' ✓' : ' ✗' }}</div>
            </div>
          </div>
        </div>
      </template>

      <!-- 现象 / 工况模板 -->
      <template v-else-if="tab === 'phenomena'">
        <div class="grid grid-cols-[1fr_1.2fr] gap-3">
          <div class="card self-start">
            <div class="flex items-center mb-2"><div class="sec-title !mb-0 flex-1">现象/工况模板</div><button class="btn btn-primary !py-1" :disabled="!canEdit()" @click="add('phenomena')">+ 新增</button></div>
            <table class="tbl"><thead><tr><th>编码</th><th>名称</th><th>类别</th><th>级别</th><th>来源</th></tr></thead><tbody>
              <tr v-for="x in rows('phenomena')" :key="x.code" :class="{ '!bg-brand/10': phenSel === x.code }" @click="pickPhen(x.code)">
                <td class="font-mono text-[11px] whitespace-nowrap">{{ x.code }}</td><td>{{ x.name }}</td>
                <td class="whitespace-nowrap"><span class="pill" :class="x.category === '工况' ? 'pill-info' : 'pill-plain'">{{ x.category }}</span></td><td class="whitespace-nowrap">{{ x.category === '工况' ? '—' : x.severity }}</td>
                <td><span class="pill" :class="SRC(x)">{{ x._own ? '本类' : '继承' }}</span></td></tr>
            </tbody></table>
          </div>
          <div v-if="editing?.part === 'phenomena'" class="card self-start space-y-3">
            <div class="flex items-center gap-2"><div class="sec-title !mb-0 flex-1">判定规则模板：{{ editing.item.name || '（新）' }}</div>
              <span class="pill pill-warn">{{ editing.item.severity }}</span>
              <button v-if="!editing.isNew" class="btn btn-danger" :disabled="!canEdit()" @click="delItem('phenomena', editing.item)">删除</button>
              <button class="btn btn-primary" :disabled="!canEdit()" @click="saveItem">保存</button></div>
            <DevForm :model="editing.item" :disabled="!canEdit()" :cols="2" :fields="[
              { key: 'code', label: '编码', type: 'code' }, { key: 'name', label: '名称' },
              { key: 'category', label: '类别', type: 'select', options: ['工况', '工艺', '设备', '仪表', '操作', '物料', '公用工程', '环境'] },
              { key: 'severity', label: '严重程度', type: 'select', options: ['提示', '警告', '严重'] }, { key: 'desc', label: '说明', wide: true }]" />
            <TplRuleEditor v-if="editing.item.rule" :rule="editing.item.rule" :params="cls.parts.params" :constraints="cls.parts.constraints" :disabled="!canEdit()" />
            <button v-else class="ctl" :disabled="!canEdit()" @click="editing.item.rule = { type: 'group', op: 'OR', children: [] }">定义判定规则</button>
            <div v-if="preview && !editing.isNew">
              <div class="sec-title">实例化预览：{{ preview.instance ?? '本类暂无实例' }}<span v-if="preview.member" class="font-normal text-fg-mute"> · 以「{{ preview.member }}」展开</span></div>
              <div v-for="(l, i) in preview.lines" :key="i" class="text-xs rounded border border-line-soft bg-ink-panel2 px-2 py-1 mb-1">{{ l.text }} <span class="text-fg-mute">→ {{ l.tags.join('、') }}</span></div>
              <div class="text-[11px] text-fg-mute">设备组 / 设备可禁用本模板或覆盖阈值、持续时间（工程态「现象/工况定义」页签）；预览按保存后的模板</div>
            </div>
          </div>
        </div>
      </template>

      <!-- 根因模板 -->
      <template v-else-if="tab === 'causes'">
        <div class="grid grid-cols-[1.4fr_1fr] gap-3">
          <div class="card self-start">
            <div class="flex items-center mb-2"><div class="sec-title !mb-0 flex-1">根因模板图 <span class="font-normal text-fg-mute">橙 = 本类现象模板 · 蓝 = 跨类 · 实线 = 高 / 中置信度 · 虚线 = 低</span></div>
              <button class="btn btn-primary !py-1" :disabled="!canEdit()" @click="add('causes')">+ 新增</button></div>
            <div class="overflow-auto max-h-[520px]">
              <svg :width="720" :height="causeGraph.h" class="block">
                <defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#64748b" /></marker></defs>
                <path v-for="(e, i) in causeGraph.edges" :key="i" :d="`M${e.a.x + 210},${e.a.y + 16} C${e.a.x + 230},${e.a.y + 16} ${e.b.x - 20},${e.b.y + 16} ${e.b.x},${e.b.y + 16}`"
                      fill="none" stroke="#64748b" :stroke-dasharray="e.low ? '5 4' : ''" stroke-width="1.2" marker-end="url(#ar)" class="cursor-pointer"
                      @click="edit('causes', cls.parts.causes.find((c: Any) => c.code === e.code))" />
                <g v-for="n in causeGraph.nodes" :key="n.n">
                  <rect :x="n.x" :y="n.y" width="210" height="32" rx="6" :fill="n.own ? '#fff7ed' : '#eff6ff'" :stroke="n.own ? '#fdba74' : '#93c5fd'" />
                  <text :x="n.x + 8" :y="n.y + 20" font-size="12" fill="#1f2937">{{ n.n.length > 15 ? n.n.slice(0, 15) + '…' : n.n }}</text>
                </g>
              </svg>
            </div>
          </div>
          <div v-if="editing?.part === 'causes'" class="card self-start">
            <div class="flex items-center mb-3"><div class="sec-title !mb-0 flex-1">根因模板：{{ editing.item.cause || '?' }} → {{ editing.item.effect || '?' }}</div>
              <button v-if="!editing.isNew" class="btn btn-danger mr-1" :disabled="!canEdit()" @click="delItem('causes', editing.item)">删除</button>
              <button class="btn btn-primary" :disabled="!canEdit()" @click="saveItem">保存</button></div>
            <DevForm :model="editing.item" :fields="fieldsFor('causes')" :disabled="!canEdit()" />
            <div class="mt-3 rounded border border-line-soft bg-ink-panel2 px-3 py-2 text-xs text-fg-dim">
              <b>实例化结果</b>：在已引用工程中按关系路径生成实例级根因关系，状态「待确认」，由工程人员确认后生效（开发态 → 工程态同步本 Demo 不做）。
            </div>
          </div>
          <div v-else class="card self-start text-xs text-fg-mute">点图中的连线或表中的一行查看 / 编辑根因模板</div>
        </div>
        <div class="card">
          <table class="tbl"><thead><tr><th>原因现象模板</th><th></th><th>结果现象模板</th><th>路径限定</th><th>置信度</th><th>来源</th></tr></thead><tbody>
            <tr v-for="x in rows('causes')" :key="x.code" :class="{ '!bg-brand/10': editing?.code === x.code }" @click="edit('causes', x)">
              <td>{{ x.cause }}</td><td class="text-brand whitespace-nowrap">导致 →</td><td>{{ x.effect }}</td><td class="text-xs text-info">{{ x.path || '类内' }}</td><td>{{ x.confidence }}</td>
              <td><span class="pill" :class="SRC(x)">{{ x._own ? '本类' : '继承' }}</span></td></tr>
          </tbody></table>
        </div>
      </template>

      <!-- 能力 -->
      <template v-else-if="tab === 'caps'">
        <div class="card">
          <div class="sec-title">挂载能力 <span class="font-normal text-fg-mute">类挂载能力后，该类的所有实例自动具备该能力；继承来的不可在本类取消</span></div>
          <table class="tbl"><thead><tr><th class="w-10"></th><th>能力</th><th>算法</th><th>方式</th><th>说明</th><th>来源</th></tr></thead><tbody>
            <tr v-for="c in allCaps" :key="c.code" class="!cursor-default">
              <td><input type="checkbox" :checked="cls.caps.some((x: Any) => x.code === c.code)" :disabled="!canEdit() || cls.caps.some((x: Any) => x.code === c.code && x._src === '继承')" @change="toggleCap(c.code)" /></td>
              <td>{{ c.name }}<div class="font-mono text-[11px] text-fg-mute">{{ c.code }}</div></td><td class="font-mono text-xs">{{ c.algorithm || '—' }}</td><td>{{ c.mode }}</td>
              <td class="text-xs text-fg-dim">{{ c.desc }}</td><td><span v-if="cls.caps.find((x: Any) => x.code === c.code)" class="pill" :class="cls.caps.find((x: Any) => x.code === c.code)._src === '本类' ? 'pill-info' : 'pill-plain'">{{ cls.caps.find((x: Any) => x.code === c.code)._src }}</span></td></tr>
          </tbody></table>
        </div>
      </template>

      <!-- 实例 -->
      <template v-else-if="tab === 'inst'">
        <div class="card">
          <div v-if="!cls.instances.length" class="text-xs text-fg-mute">{{ cls.abstract ? '抽象类没有直接实例；实例数见子类' : '暂无实例' }}</div>
          <table v-else class="tbl"><thead><tr><th>实例（设备组）</th><th>成员设备</th><th>导航</th><th></th></tr></thead><tbody>
            <tr v-for="x in cls.instances" :key="x.id" class="!cursor-default"><td>{{ x.name }}</td><td>{{ x.members }}</td><td class="text-xs">{{ x.inNav ? '在导航中' : '未纳入导航' }}</td>
              <td><button v-if="x.inNav" class="ctl" @click="openInEngineering(x.id, x.opId, x.segmentId)">在工程态打开 ↗</button></td></tr>
          </tbody></table>
        </div>
      </template>
    </div>
    <div v-else class="empty">左侧选择一个类</div>
  </div>
</template>
