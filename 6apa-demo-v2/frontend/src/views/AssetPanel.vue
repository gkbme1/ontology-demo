<script setup lang="ts">
/**
 * 设备 / 设备组信息：页签依次为 图纸位置与外观、参数、仪表、参数约束、拓扑关系、现象定义、
 * 根因影响关系、工艺影响关系、计算/指标、处置规程。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { nav, openGlobalGraph, openObject } from '@/composables/useNav'
import DrawingView from '@/components/DrawingView.vue'
import CalcPanel from '@/components/CalcPanel.vue'
import ProcedureCard from '@/components/ProcedureCard.vue'
import InheritBox from '@/components/InheritBox.vue'
import TopologyGraph from '@/components/TopologyGraph.vue'
import InfluenceGraph from '@/components/InfluenceGraph.vue'
import CausePopup from '@/components/causal/CausePopup.vue'
import PhenomenaPanel from '@/components/causal/PhenomenaPanel.vue'
import CausalPanel from '@/components/causal/CausalPanel.vue'
import LimitOverrideEditor from '@/components/LimitOverrideEditor.vue'
import RelationEditor from '@/components/RelationEditor.vue'
import ObjectInfo from '@/components/ObjectInfo.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ objectId: string; opId?: string; initialTab?: string }>()

const head = ref<Any>(null)
const tab = ref(props.initialTab ?? 'drawing')
const data = ref<Any>(null)
const drawing = ref<Any>(null)
const loading = ref(false)
const error = ref('')
const tagKw = ref('')

async function loadHead(): Promise<void> {
  error.value = ''
  try {
    head.value = await api.object(props.objectId, props.opId)
  } catch (e) {
    error.value = String((e as Error).message)
  }
}
// 同一页签刷新（编辑、关弹窗后）时保留旧数据直到新数据到达，子面板不卸载，用户选的视图（图谱 / 列表）不丢
let loadedKey = ''
async function loadTab(): Promise<void> {
  const key = `${props.objectId}|${props.opId ?? ''}|${tab.value}`
  loading.value = true
  if (key !== loadedKey) data.value = null
  try {
    const res = await api.objectTab(props.objectId, tab.value, props.opId)
    if (key !== `${props.objectId}|${props.opId ?? ''}|${tab.value}`) return  // 期间切了页签
    data.value = res
    loadedKey = key
    if (tab.value === 'drawing' && data.value.opId) {
      if (drawing.value?.opId !== data.value.opId) drawing.value = await api.opDrawing(data.value.opId)
    }
  } catch (e) {
    error.value = String((e as Error).message)
  } finally {
    loading.value = false
  }
}
watch(() => [props.objectId, props.opId], async () => { await loadHead(); await loadTab() }, { immediate: true })
watch(() => props.initialTab, (t) => { if (t) tab.value = t })
watch(tab, loadTab)
watch(() => nav.version, () => { loadHead(); if (['phenomena', 'causal', 'calc'].includes(tab.value)) loadTab() })

// 新增现象时可挂在本对象，或（设备时）挂在它所属的设备组上
const anchorOptions = computed(() => {
  if (!head.value) return []
  const self = { id: props.objectId, name: head.value.name, kind: head.value.kind === 'group' ? 'group' : 'equipment' }
  const g = head.value.group
  return g ? [self, { id: g.id, name: g.name, kind: 'group' }] : [self]
})
// 计算组态的作用范围：本对象、所属设备组、所在工艺段（跨装置统计）
const calcAnchors = computed(() => {
  const seg = head.value?.path?.find((p: Any) => String(p.id).startsWith('SEG-'))
  return [...anchorOptions.value, ...(seg ? [{ id: seg.id, name: seg.name, kind: 'segment' }] : [])]
})
const paramGroup = ref('')
const openVer = ref<Record<string, boolean>>({})
const topoView = ref<'graph' | 'list'>('graph')
const inflView = ref<'graph' | 'list'>('graph')
const focusPhen = ref('')
const popupPhen = ref('')
const allPhen = ref<Any[]>([])

// 点「工况」/ 版本适用条件：跳到本对象的「现象定义」并高亮；本对象没有这条现象时弹窗查看
async function gotoPhen(id: string): Promise<void> {
  const list = await api.objectTab(props.objectId, 'phenomena', props.opId)
  if (list.items.some((p: Any) => p.id === id)) {
    focusPhen.value = id
    tab.value = 'phenomena'
  } else {
    if (!allPhen.value.length) allPhen.value = (await api.phenomena({})).items
    popupPhen.value = id
  }
}
watch(tab, (t) => { if (t !== 'phenomena') focusPhen.value = '' })
const GROUP_PILL: Record<string, string> = {
  基本信息: 'pill-plain', 设计参数: 'pill-warn', 测量值: 'pill-info', 设定值: 'pill-info', 阀位: 'pill-info', 控制指令: 'pill-info',
  状态: 'pill-info', 计算值: 'pill-ok'
}
const BIND_PILL: Record<string, string> = { 已绑定: 'pill-ok', 待确认: 'pill-warn', 未绑定: 'pill-mute', 失效: 'pill-err' }
const bindFilter = ref('')
const params = computed(() => (data.value?.items ?? []).filter((a: Any) =>
  (!paramGroup.value || a.category === paramGroup.value || (paramGroup.value === '属性' && a.section === '属性') || (paramGroup.value === '参数' && a.section === '参数')) &&
  (!bindFilter.value || a.binding === bindFilter.value) &&
  (!tagKw.value || `${a.name}${a.description}${a.links?.map((l: Any) => l.tag + l.desc).join('') ?? ''}`.toLowerCase().includes(tagKw.value.toLowerCase()))))
const counts = computed<Record<string, number>>(() => head.value?.counts ?? {})

function pick(id: string, kind: string, opId?: string): void {
  if (kind === 'equipment' || kind === 'group') openObject(id, opId ?? props.opId ?? head.value?.opId, 'drawing')
}
// 人工新增 / 删除拓扑与工艺影响关系（需求 SW-044 / 049）
const relEditing = ref<'' | 'topology' | 'influence'>('')
const showInfo = ref(false)
async function removeRelation(r: Any): Promise<void> {
  if (!confirm(`删除人工新增的关系「${r.from} —${r.predicate}→ ${r.to}」？`)) return
  try { await api.deleteRelation(r.relationId); await loadTab(); await loadHead() } catch (e) { alert((e as Error).message) }
}
async function relSaved(): Promise<void> { relEditing.value = ''; await loadTab(); await loadHead() }

// 设备上覆盖 / 禁用 / 恢复继承来的限值（需求 SW-045）
const limitEditing = ref<Any>(null)
async function limitDisable(c: Any): Promise<void> {
  if (!confirm(`在「${head.value.name}」上禁用继承的限值 ${c.id}（${c.appliesTo}）？本台引用该限值的判定规则将无法判定。`)) return
  try { await api.overrideLimit(props.objectId, c.id, { disabled: true }); await loadTab() } catch (e) { alert((e as Error).message) }
}
async function limitRestore(c: Any): Promise<void> {
  try { await api.restoreLimit(props.objectId, c.id); await loadTab() } catch (e) { alert((e as Error).message) }
}
function fmtBand(c: Any): string {
  const a = c.alarm ?? {}
  return [a.lowLow ?? '—', a.low ?? '—', c.normal ?? '—', a.high ?? '—', a.highHigh ?? '—'].join(' / ')
}
</script>

<template>
  <div class="flex flex-col h-full min-h-0">
    <div v-if="error" class="empty m-4">{{ error }}</div>
    <template v-if="head">
      <!-- 头部：一行对象信息 + 醒目的页签按钮 -->
      <div class="px-4 pt-2 pb-2 border-b border-line bg-ink-panel shrink-0">
        <div class="flex items-center gap-2 min-w-0">
          <h2 class="text-[16px] font-semibold whitespace-nowrap">{{ head.name }}</h2>
          <span class="pill pill-info">{{ head.kind === 'group' ? '设备组' : '设备' }}</span>
          <span v-if="head.className" class="pill pill-plain">{{ head.className }}</span>
          <span class="text-[11px] text-fg-mute truncate" :title="head.badges.join(' · ')">{{ head.badges.join(' · ') }}</span>
          <span class="flex-1" />
          <button class="ctl !py-0.5" title="ID、编码、类、状态、来源、所属位置、被引用、变更记录" @click="showInfo = true">ⓘ 基础信息 · 变更记录</button>
          <button class="ctl !py-0.5" title="在全局图谱中以本对象为中心查看 1 跳邻域（可再扩到 2 / 3 跳）" @click="openGlobalGraph(objectId, 1)">◎ 全局图谱定位</button>
          <span class="text-[11px] text-fg-mute whitespace-nowrap truncate max-w-[40%]">
            <span v-for="(p, i) in head.path" :key="p.id">{{ p.name }}<span v-if="i < head.path.length - 1"> › </span></span>
            <span v-if="head.opIds.length > 1" class="ml-1 text-info">（成员分属 {{ head.opIds.length }} 道工序）</span>
          </span>
        </div>
        <div class="flex flex-wrap gap-1.5 mt-2">
          <button v-for="t in head.tabs" :key="t.key" class="asset-tab" :class="{ 'asset-tab-on': tab === t.key }" @click="tab = t.key">
            {{ t.label }}<span v-if="counts[t.key]" class="asset-tab-count">{{ counts[t.key] }}</span>
          </button>
        </div>
      </div>

      <!-- 页签内容 -->
      <!-- 滚动容器不留上内边距：表头 sticky 贴顶，内容不会从表头上方透出 -->
      <div class="flex-1 overflow-auto px-4 pb-3 min-h-0">
        <div class="h-3" />
        <div v-if="loading && !data" class="text-fg-mute">加载中…</div>
        <template v-else-if="data">
          <!-- 图纸位置与外观 -->
          <div v-if="tab === 'drawing'" class="space-y-3">
            <DrawingView v-if="drawing" :drawing="drawing" :highlight="data.highlight" :caption="`所在图纸：${drawing.name}`" @pick="pick" />
            <div v-else class="empty">该对象不在导航树的工序内，没有图纸位置</div>
            <div class="grid grid-cols-2 gap-4">
              <div class="card">
                <div class="sec-title">外观与固有属性</div>
                <dl class="kv">
                  <template v-for="a in data.appearance" :key="a.name">
                    <dt>{{ a.name }}</dt><dd>{{ a.value }}<div v-if="a.note" class="text-[11px] text-fg-mute">{{ a.note }}</div></dd>
                  </template>
                </dl>
                <div class="text-[11px] text-fg-mute mt-2">{{ data.note }}</div>
              </div>
              <div v-if="data.members.length" class="card">
                <div class="sec-title">本工序内的成员（{{ data.members.length }}）</div>
                <div class="flex flex-wrap gap-1.5">
                  <button v-for="m in data.members" :key="m.id" class="ctl" @click="openObject(m.id, opId ?? head.opId)">{{ m.name }} <span class="text-fg-mute">{{ m.tagCount }}</span></button>
                </div>
              </div>
            </div>
          </div>

          <!-- 参数 · 仪表：分类筛选 + 一张表，DCS 位号直接列在行里 -->
          <div v-else-if="tab === 'parameters'">
            <div class="flex flex-wrap items-center gap-1.5 mb-2">
              <button class="ctl" :class="{ 'ctl-on': !paramGroup }" @click="paramGroup = ''">全部 <span class="text-fg-mute">{{ data.items.length }}</span></button>
              <span class="text-[11px] text-fg-mute ml-1">属性</span>
              <button v-for="g in data.attrGroups" :key="g" class="ctl" :class="{ 'ctl-on': paramGroup === g }" @click="paramGroup = g">
                {{ g }} <span class="text-fg-mute">{{ data.counts[g] }}</span>
              </button>
              <span class="text-[11px] text-fg-mute ml-1">参数</span>
              <button v-for="g in data.paramGroups" :key="g" class="ctl" :class="{ 'ctl-on': paramGroup === g }" @click="paramGroup = g">
                {{ g }} <span class="text-fg-mute">{{ data.counts[g] }}</span>
              </button>
              <span class="text-[11px] text-fg-mute ml-1">绑定</span>
              <template v-for="(n, b) in (data.bindingCounts as Record<string, number>)" :key="b">
                <button v-if="n" class="ctl" :class="{ 'ctl-on': bindFilter === b }" @click="bindFilter = bindFilter === b ? '' : String(b)">{{ b }} <span class="text-fg-mute">{{ n }}</span></button>
              </template>
              <input v-model="tagKw" class="inp w-56 ml-2" placeholder="筛选参数名 / 位号 / 描述" />
              <span class="flex-1" />
              <span class="text-[11px] text-fg-mute">{{ data.scope }} {{ data.tagTotal }} 个 DCS 测点<template v-if="data.designPending"> · 设计参数 {{ data.designPending }} 项待补充</template></span>
            </div>
            <table class="tbl">
              <thead><tr><th class="w-16 !text-center">来源</th><th class="w-[84px]">类别</th><th>参数 / 属性</th><th class="w-[110px]">类型 · 单位</th><th>值 / 数据关联（DCS 位号）</th><th class="w-[84px]">绑定</th></tr></thead>
              <tbody>
                <tr v-for="(a, i) in params" :key="i" class="!cursor-default">
                  <td><InheritBox :checked="a.inherited" :from="a.inheritedFrom" /></td>
                  <td><span class="pill" :class="GROUP_PILL[a.category] ?? 'pill-plain'">{{ a.category }}</span></td>
                  <td>
                    <div class="font-medium">{{ a.name }}<span v-if="a.semantic" class="pill pill-ok !py-0 ml-1" title="本体工艺属性（语义参数），由工业关系表定义">工艺属性</span></div>
                    <div v-if="a.description" class="text-[11px] text-fg-mute">{{ a.description }}</div>
                  </td>
                  <td class="text-fg-dim whitespace-nowrap">{{ a.valueType }}</td>
                  <td>
                    <span v-if="a.group === '设计参数' && a.pending" class="text-fg-mute italic">待补充</span>
                    <span v-else-if="a.value !== undefined && a.value !== null && a.value !== ''" class="font-medium">{{ a.value }}<span v-if="a.group === '设计参数' && a.valueType !== '文本'" class="text-fg-mute"> {{ a.valueType }}</span></span>
                    <span v-if="a.note" class="text-[11px] text-fg-mute ml-1">{{ a.note }}</span>
                    <div v-if="a.links.length" class="flex flex-wrap gap-1 mt-0.5">
                      <span v-for="l in a.links" :key="l.tag" class="pill font-mono"
                            :class="l.own ? 'pill-info' : 'pill-mute'"
                            :title="`${l.desc}${l.unit ? ' · ' + l.unit : ''}${l.limit ? ' · 限值 ' + l.limit : ''}${l.own ? '' : ' · 测点在 ' + l.equipment}`">
                        {{ l.tag }}<span v-if="l.unit" class="opacity-70">{{ l.unit }}</span><span v-if="!l.own" class="opacity-70">@{{ l.equipment }}</span>
                      </span>
                    </div>
                  </td>
                  <td>
                    <span v-if="a.binding" class="pill whitespace-nowrap cursor-help" :class="BIND_PILL[a.binding]" :title="a.bindingNote">{{ a.binding }}</span>
                    <span v-else class="text-fg-mute">—</span>
                    <div v-if="a.binding && a.binding !== '已绑定'" class="text-[10.5px] text-fg-mute leading-tight mt-0.5">{{ a.bindingNote }}</div>
                  </td>
                </tr>
              </tbody>
            </table>
            <div class="text-[11px] text-fg-mute mt-2">
              设计参数来自 data/config/6APA_设备设计参数.xlsx（模板「{{ data.designTemplate ?? '无匹配模板' }}」），按设备档案 / 铭牌填写后重新导出即可显示；灰色位号表示测点在其他设备上（共用设备或组级属性）。
              {{ data.note }}。绑定状态：已绑定 / 待确认（按名称推断或归属置信度低）/ 未绑定 / 失效（位号不在点表中）。
            </div>
          </div>

          <!-- 参数约束：工况与版本适用条件关联到「工况」现象 -->
          <div v-else-if="tab === 'constraints'" class="space-y-4">
            <div class="text-xs text-fg-mute">{{ data.note }}</div>
            <div v-if="!data.operating.length" class="empty">暂无工艺限值</div>
            <table v-else class="tbl">
              <thead><tr><th class="w-16 !text-center">来源</th><th>编号</th><th>适用参数</th><th>工况</th><th>LL / L / 正常 / H / HH</th><th>单位</th><th>版本</th><th>状态</th><th v-if="data.canOverride"></th></tr></thead>
              <tbody>
                <template v-for="c in data.operating" :key="c.id">
                  <tr class="!cursor-default" :class="{ 'opacity-50': c.inheritState === '已禁用' }">
                    <td><InheritBox :checked="c.inherited" :from="c.inheritedFrom" :state="c.inheritState" /></td>
                    <td class="font-mono">{{ c.id }}</td>
                    <td>{{ c.appliesTo }}<div class="text-[11px] text-fg-mute max-w-[340px] truncate" :title="c.basis">{{ c.basis }}</div></td>
                    <td>
                      <button v-if="c.modePhenomenon" class="phen-link" :title="`工况现象：${c.modePhenomenon.name}（${c.modePhenomenon.anchor}）`" @click="gotoPhen(c.modePhenomenon.id)">
                        {{ c.operatingMode }}<span v-if="!c.modePhenomenon.hasRule" class="opacity-60">（规则待定义）</span>
                      </button>
                      <span v-else class="text-fg-dim">{{ c.operatingMode || '—' }}</span>
                    </td>
                    <td class="font-mono text-xs whitespace-nowrap">
                      <template v-if="c.inheritState === '已禁用'">本台已禁用</template>
                      <template v-else>{{ c.hasValues ? fmtBand(c) : '待现场提供' }}</template>
                      <div v-if="c.template" class="text-[10.5px] text-fg-mute font-sans">设备组：{{ fmtBand(c.template) }}<span v-if="c.override?.note"> · {{ c.override.note }}</span></div>
                    </td>
                    <td>{{ c.unit }}</td>
                    <td>
                      <button class="ctl !py-0" @click="openVer[c.id] = !openVer[c.id]">{{ c.versions.length }} 个 {{ openVer[c.id] ? '▾' : '▸' }}</button>
                    </td>
                    <td><span class="pill pill-warn">{{ c.status }}</span></td>
                    <td v-if="data.canOverride" class="whitespace-nowrap">
                      <template v-if="c.inherited">
                        <button v-if="c.inheritState !== '已禁用'" class="ctl" title="只改本台的限值" @click="limitEditing = c">覆盖</button>
                        <button v-if="!c.inheritState" class="ctl ml-1" @click="limitDisable(c)">禁用</button>
                        <button v-else class="ctl ml-1" @click="limitRestore(c)">恢复继承</button>
                      </template>
                    </td>
                  </tr>
                  <tr v-if="openVer[c.id]" class="!cursor-default hover:!bg-transparent">
                    <td />
                    <td :colspan="data.canOverride ? 8 : 7" class="!pt-0">
                      <table class="w-full text-xs border border-line-soft rounded">
                        <thead><tr class="bg-ink-panel2 text-fg-mute">
                          <th class="text-left px-2 py-1 font-medium">版本</th><th class="text-left px-2 py-1 font-medium">适用条件</th>
                          <th class="text-left px-2 py-1 font-medium">正常</th><th class="text-left px-2 py-1 font-medium">L~H</th>
                          <th class="text-left px-2 py-1 font-medium">LL~HH</th><th class="text-left px-2 py-1 font-medium">来源</th>
                          <th class="text-left px-2 py-1 font-medium">生效</th><th class="text-left px-2 py-1 font-medium">修改人 / 原因</th>
                        </tr></thead>
                        <tbody>
                          <tr v-for="v in c.versions" :key="v.id" class="border-t border-line-soft">
                            <td class="px-2 py-1 font-mono" :class="v.base ? 'text-fg-mute' : 'text-brand'">{{ v.id }}</td>
                            <td class="px-2 py-1">
                              <button v-if="v.phenomenon" class="phen-link" :title="`工况现象：${v.phenomenon.name}`" @click="gotoPhen(v.phenomenon.id)">{{ v.phenomenon.name }}</button>
                              <span v-else>{{ v.conditionText }}</span>
                              <span v-if="v.conditionNote" class="text-fg-mute ml-1">{{ v.conditionNote }}</span>
                            </td>
                            <td class="px-2 py-1 font-mono">{{ v.normal }}</td><td class="px-2 py-1 font-mono">{{ v.lh }}</td>
                            <td class="px-2 py-1 font-mono">{{ v.llhh }}</td><td class="px-2 py-1">{{ v.sourceType }}</td>
                            <td class="px-2 py-1 whitespace-nowrap">{{ v.effective }}</td>
                            <td class="px-2 py-1 text-fg-dim">{{ v.editor }}{{ v.editor ? '：' : '' }}{{ v.reason }} <span class="pill pill-warn">{{ v.status }}</span></td>
                          </tr>
                        </tbody>
                      </table>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
            <div v-if="data.safety.length">
              <div class="sec-title">安全约束</div>
              <ul class="text-xs space-y-1"><li v-for="(s, i) in data.safety" :key="i">{{ s.text ?? s }}</li></ul>
            </div>
          </div>

          <!-- 拓扑关系 -->
          <div v-else-if="tab === 'topology'" class="space-y-2">
            <div class="flex items-center gap-2">
              <button class="ctl" :class="{ 'ctl-on': topoView === 'graph' }" @click="topoView = 'graph'">关系图谱</button>
              <button class="ctl" :class="{ 'ctl-on': topoView === 'list' }" @click="topoView = 'list'">列表</button>
              <span class="text-xs text-fg-mute">{{ data.items.length }} 条关系<template v-if="data.items.some((r: Any) => r.userRelation)">（人工新增 {{ data.items.filter((r: Any) => r.userRelation).length }} 条，列表中可删除）</template></span>
              <span class="flex-1" />
              <button v-if="data.canEdit" class="btn btn-primary" @click="relEditing = 'topology'">+ 新增关系</button>
            </div>
            <TopologyGraph v-if="topoView === 'graph'" :items="data.items" :center-name="head.name" :center-kind="head.kind"
                           @open="(id: string) => openObject(id, opId ?? head.opId)" />
            <table v-else class="tbl">
              <thead><tr><th class="w-16 !text-center">来源</th><th>层</th><th>类别</th><th>方向</th><th>关系</th><th>对象</th><th>说明</th><th>来源</th><th></th></tr></thead>
              <tbody>
                <tr v-for="(r, i) in data.items" :key="i" class="!cursor-default">
                  <td><InheritBox :checked="r.inherited" :from="r.inheritedFrom" /></td>
                  <td class="text-fg-mute text-xs whitespace-nowrap">{{ r.layer }}</td>
                  <td class="text-fg-dim whitespace-nowrap">{{ r.category }}</td>
                  <td class="whitespace-nowrap">{{ r.role ?? (r.direction === 'in' ? '上游' : '下游') }}</td>
                  <td class="text-brand whitespace-nowrap">{{ r.predicate }}</td>
                  <td>{{ r.target }}<div v-if="r.targetType" class="text-[11px] text-fg-mute">{{ r.targetType }}</div></td>
                  <td class="text-fg-dim">{{ r.mechanism }}</td>
                  <td class="text-[11px] text-fg-mute">{{ r.source }}</td>
                  <td><button v-if="r.userRelation && !r.inherited" class="ctl" @click="removeRelation(r)">删除</button></td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 现象定义 -->
          <div v-else-if="tab === 'phenomena'">
            <div class="text-xs text-fg-mute mb-2">现象 = 当前情况的描述 + 判定规则；设备组上定义的现象对组内每台设备生效（「来源」列标「设备组」）。类别为「工况」的现象被参数约束引用。点一行查看它由什么导致。</div>
            <PhenomenaPanel :items="data.items" :anchor-options="anchorOptions" :op-id="opId ?? head.opId" show-inherit :focus-id="focusPhen"
                            :object-id="objectId" :object-name="head.name" :can-override="data.canOverride" @changed="loadTab" />
          </div>

          <!-- 根因影响关系 -->
          <CausalPanel v-else-if="tab === 'causal'" :links="data.links" :graph="data.graph" :op-id="opId ?? head.opId" show-inherit @changed="loadTab" />

          <!-- 工艺影响关系 -->
          <div v-else-if="tab === 'influence'" class="space-y-2">
            <div class="flex items-center gap-2">
              <button class="ctl" :class="{ 'ctl-on': inflView === 'graph' }" @click="inflView = 'graph'">关系图谱</button>
              <button class="ctl" :class="{ 'ctl-on': inflView === 'list' }" @click="inflView = 'list'">列表</button>
              <span class="text-xs text-fg-mute">{{ data.items.length }} 条 · {{ data.note }}</span>
              <span class="flex-1" />
              <button v-if="data.canEdit && data.params?.length" class="btn btn-primary" @click="relEditing = 'influence'">+ 新增关系</button>
            </div>
            <div v-if="!data.items.length" class="empty">暂无工艺影响关系</div>
            <InfluenceGraph v-else-if="inflView === 'graph'" :items="data.items" :own="data.own" />
            <table v-else class="tbl">
              <thead><tr><th class="w-16 !text-center">来源</th><th>影响方</th><th>关系</th><th>被影响方</th><th>机理</th><th>测点</th><th>来源</th><th></th></tr></thead>
              <tbody>
                <tr v-for="(r, i) in data.items" :key="i" class="!cursor-default">
                  <td><InheritBox :checked="r.inherited" :from="r.inheritedFrom" /></td>
                  <td>{{ r.from }}</td>
                  <td class="whitespace-nowrap" :class="r.predicate === '负向影响' ? 'text-warn' : 'text-ok'">{{ r.predicate }}</td>
                  <td>{{ r.to }}</td><td class="text-fg-dim">{{ r.mechanism }}</td>
                  <td class="text-fg-mute tabular-nums">{{ r.tagCount }}</td><td class="text-[11px] text-fg-mute">{{ r.source }}</td>
                  <td><button v-if="r.userRelation" class="ctl" @click="removeRelation(r)">删除</button></td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 计算/指标 -->
          <div v-else-if="tab === 'calc'" class="space-y-4">
            <CalcPanel :items="data.items" :op-id="opId ?? head.opId" :target-id="head.kind === 'equipment' ? objectId : undefined" show-inherit
                       :can-edit="data.canEdit" :anchor-options="calcAnchors" @changed="loadTab" />
            <div v-if="data.derivedCandidates.length" class="card">
              <div class="sec-title">尚无测点、可做成计算组态的工艺属性</div>
              <div class="flex flex-wrap gap-1.5">
                <span v-for="d in data.derivedCandidates" :key="d.name" class="pill pill-mute" :title="d.description">{{ d.name }}</span>
              </div>
            </div>
            <div v-if="data.capabilities.length" class="card">
              <div class="sec-title">已登记的能力（原 Demo 能力登记表，本 Demo 不调用）</div>
              <table class="tbl"><tbody>
                <tr v-for="c in data.capabilities" :key="c.id" class="!cursor-default">
                  <td class="font-mono text-xs">{{ c.id }}</td><td>{{ c.name }}</td><td class="text-fg-dim">{{ c.description }}</td><td class="text-fg-mute text-xs">{{ c.provider }}</td>
                </tr>
              </tbody></table>
            </div>
          </div>

          <!-- 处置规程 -->
          <div v-else-if="tab === 'procedures'" class="space-y-3">
            <div v-if="!data.items.length" class="empty">暂无相关处置卡</div>
            <div class="text-xs text-fg-mute">处置卡按需求拆成三部分：报警现象、可能原因（原因现象 + 导致关系，进根因影响关系）、处置规程（步骤、检查项、执行边界）。原文来自 6APA_处置规程.xlsx，在线修改另存。</div>
            <ProcedureCard v-for="(c, i) in data.items" :key="c.id" :card="c" :open="i === 0" :can-edit="data.canEdit" :anchor-id="objectId"
                           @changed="(nc: Any) => { data.items.splice(data.items.findIndex((x: Any) => x.id === nc.id), 1, nc) }"
                           @phen="(id: string) => gotoPhen(id)" />
          </div>
        </template>
      </div>
    </template>
    <CausePopup v-if="popupPhen" :phenomenon-id="popupPhen" :phenomena="allPhen" :op-id="opId ?? head?.opId" @close="popupPhen = ''" />
    <ObjectInfo v-if="showInfo" :object-id="objectId" :op-id="opId ?? head?.opId" @close="showInfo = false" />
    <RelationEditor v-if="relEditing" :mode="relEditing" :self="{ id: objectId, name: head?.name ?? '' }" :params="data?.params"
                    @close="relEditing = ''" @saved="relSaved" />
    <LimitOverrideEditor v-if="limitEditing" :object-id="objectId" :object-name="head?.name ?? ''" :limit="limitEditing"
                         @close="limitEditing = null" @saved="limitEditing = null; loadTab()" />
  </div>
</template>
