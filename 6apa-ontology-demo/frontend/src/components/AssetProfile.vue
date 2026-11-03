<script setup lang="ts">
/**
 * 对象本体档案：头部是类与层级，下面按页签分为 属性 / 关系 / 能力 / 约束 / 规则 / 处置
 *（定义了工艺阶段的设备实例另有 批次，设备组 / 类另有 实例）。
 * 全部数据来自 /api/ontology/asset-profile/{id}，组件不内置任何设备、点位或关系。
 * 当前页签记在地址栏 ?tab=，切换对象时保持不变。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { AssetProfile, LimitCheckResult, ProfileAttribute } from '@/api/types'
import ClassRelationHub from './ClassRelationHub.vue'
import ProcedureCardView from './ProcedureCardView.vue'
import BatchPanel from './BatchPanel.vue'
import LimitVersions from './LimitVersions.vue'

const props = defineProps<{ profile: AssetProfile }>()
const emit = defineEmits<{ open: [objectId: string] }>()

// ---------------------------------------------------------------- 页签
type TabKey = '属性' | '关系' | '能力' | '约束' | '规则' | '处置' | '批次' | '实例'
const route = useRoute()
const router = useRouter()
const tabs = computed(() => {
  const p = props.profile
  const list: { key: TabKey; count: number; hint: string }[] = [
    { key: '属性', count: p.attributes.length, hint: '固有属性、工艺属性与测量 / 状态 / 控制参数；数据关联（DCS 位号）直接体现在属性里' },
    { key: '关系', count: p.relations.classRelations.length + p.relations.attributeRelations.length,
      hint: p.kind === 'class' ? '类间关系：这一类设备通常与哪些类、物料相连（由组间关系归纳的模式）'
        : p.kind === 'group' ? '设备组层面的关系（组间）与归属；落到具体设备的连接见各实例'
          : p.kind === 'equipment' ? '本台设备的归属与实例间关系；由组间关系推导的标出连接方式，所属设备组的关系作背景另列'
            : '对象的关系与属性间关系（计算 / 传递 / 关联）' },
    { key: '能力', count: p.capabilities.length, hint: '能力由外部系统实现；本体登记能力描述与调用契约，并在本对象上绑定参数（6APA_能力.xlsx）' },
    { key: '约束', count: p.constraints.structure.length + p.constraints.operating.length + p.constraints.safety.length,
      hint: '约束属于本体：结构约束（加载器校验）、运行约束（工艺限值，可按当前值校验）、安全约束（报警联锁）' },
    { key: '规则', count: p.rules.length, hint: '适用于本对象的推理规则；规则在推理引擎中定义与执行（6APA_规则.xlsx）' },
    { key: '处置', count: p.procedures?.length ?? 0,
      hint: '报警处置卡：触发、可能原因与验证方法、处置步骤、禁止操作；规程里的位号与对象已对应到本体（6APA_处置规程.xlsx）' },
  ]
  if (p.process?.batchSupported) {
    list.push({ key: '批次', count: p.process.stages.length,
      hint: '运行上下文：罐批次、工艺阶段、换酶后批次数、班次（经本体代调 EBR / MOM）；阶段定义见 6APA_工序与阶段.xlsx，计数为阶段数' })
  }
  if (p.instances?.length) {
    list.push({ key: '实例', count: p.instances.length, hint: p.kind === 'class'
      ? '属于本类的设备组与设备实例（实例取各设备组的主体实例）'
      : '本设备组的成员：设备实例，以及整组共用的公共点位 / 未拆分合集' })
  }
  return list
})
const tab = computed<TabKey>(() => {
  const want = route.query.tab as TabKey | undefined
  return tabs.value.some((t) => t.key === want) ? (want as TabKey) : '属性'
})
const activeTab = computed(() => tabs.value.find((t) => t.key === tab.value)!)
function setTab(key: TabKey) {
  router.replace({ query: { ...route.query, tab: key === '属性' ? undefined : key } })
}
// 头部默认只显示一行要点，来源与点表写法收进「来源与说明」
const headerOpen = ref(false)
const hasHeaderMore = computed(() => !!props.profile.header.source || !!props.profile.header.aliases?.length)
const notice = computed(() => {
  const p = props.profile
  if (p.kind === 'equipment' && p.header.nature && p.header.nature !== '实例') {
    return '这不是一台设备：' + (p.header.nature === '组公共点位' ? '设备组拆回实例后，剩下没有台号、整组共用的点挂在这里。'
      : p.header.nature === '合集·未拆分' ? '点表把同组几台设备的点写在一个名字下，按台号拆不开，暂作合集。'
        : '点表中按位置兜底归类的点（公用测量管线 / 其他工艺单元 / 管网阀门系统）。')
  }
  if (p.splitFrom) return `点表中的「${p.splitFrom.name}」是本组 ${p.splitFrom.instanceIds.length} 台设备的合集，已按台号拆回实例（见「实例」页签）。`
  if (p.focusTag) return `由位号 ${p.focusTag} 定位到本设备，属性表中已高亮。`
  return ''
})

// ---------------------------------------------------------------- 关系页：类间 + 属性间统一成一张表，可多选筛选
interface RelRow {
  key: string; layer: string; cat: string; label: string; linkMode?: string; linkStatus?: string
  from: string; fromId?: string | null; predicate: string; to: string; toId?: string | null
  mechanism: string; via?: string | null; kind?: string
}
const CAT_OF: Record<string, string> = {
  空间层级: '结构', 设备分类: '结构', 结构关系: '结构', 物理拓扑关系: '物理拓扑', 工段衔接: '物理拓扑',
  控制关系: '控制', 报警联锁关系: '报警联锁', 影响关系: '影响', 因果关系: '影响', 质量关系: '质量'
}
const CAT_ORDER = ['结构', '物理拓扑', '控制', '影响', '质量', '报警联锁']
const CAT_STYLE: Record<string, string> = {
  结构: 'text-info', 物理拓扑: 'text-ok', 控制: 'text-equip', 影响: 'text-prop', 质量: 'text-tagc', 报警联锁: 'text-err'
}
const relRows = computed<RelRow[]>(() => {
  const p = props.profile
  const toRow = (r: (typeof p.relations.classRelations)[number], i: number, prefix: string, layer?: string): RelRow => {
    const out = r.direction !== 'in'
    return {
      key: `${prefix}${i}`, layer: layer ?? r.layer ?? '类间', cat: CAT_OF[r.category ?? ''] ?? '结构', label: r.role,
      from: r.from ?? (out ? p.name : r.target), fromId: out ? null : r.targetId,
      predicate: r.predicate ?? r.role, to: r.to ?? (out ? r.target : p.name), toId: out ? r.targetId : null,
      mechanism: r.mechanism, linkMode: r.linkMode, linkStatus: r.linkStatus
    }
  }
  const rows: RelRow[] = p.relations.classRelations.map((r, i) => toRow(r, i, 'c'))
  ;(p.relations.groupRelations ?? []).forEach((r, i) => rows.push(toRow(r, i, 'g', '所属组')))
  p.relations.attributeRelations.forEach((r, i) => rows.push({
    key: `a${i}`, layer: '属性间', cat: CAT_OF[r.category ?? ''] ?? '影响', label: r.kind,
    from: r.from, fromId: r.fromId, predicate: r.predicate, to: r.to, toId: r.toId, mechanism: r.mechanism, via: r.via, kind: r.kind
  }))
  return rows
})
// 关系分层：归属 / 类间 / 组间 / 实例间 / 对象间 / 工段间 / 属性间；所属设备组的关系只作背景，默认不选
const LAYER_ORDER = ['归属', '类间', '组间', '实例间', '对象间', '工段间', '属性间', '所属组']
const LAYER_LABEL: Record<string, string> = {
  归属: '归属', 类间: '类间关系', 组间: '组间关系', 实例间: '实例间关系', 对象间: '对象间关系', 工段间: '工段间',
  属性间: '属性间关系', 所属组: '所属设备组的关系（背景）'
}
const relLayers = ref<Set<string>>(new Set(LAYER_ORDER.filter((l) => l !== '所属组')))
const layersPresent = computed(() => LAYER_ORDER.filter((l) => relRows.value.some((r) => r.layer === l)))
const relCats = ref<Set<string>>(new Set(CAT_ORDER))
const relKeyword = ref('')
function toggled(set: Set<string>, key: string) {
  const next = new Set(set)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  return next
}
function toggleLayer(key: string) { relLayers.value = toggled(relLayers.value, key) }
function toggleCat(key: string) { relCats.value = toggled(relCats.value, key) }
function onlyCat(key: string) { relCats.value = new Set([key]) }
function allCats() { relCats.value = new Set(CAT_ORDER) }
const catCounts = computed(() => {
  const c: Record<string, number> = {}
  for (const r of relRows.value) if (relLayers.value.has(r.layer)) c[r.cat] = (c[r.cat] ?? 0) + 1
  return c
})
const layerCounts = computed(() => {
  const c: Record<string, number> = {}
  for (const r of relRows.value) c[r.layer] = (c[r.layer] ?? 0) + 1
  return c
})
const filteredRel = computed(() => {
  const kw = relKeyword.value.trim()
  return relRows.value.filter((r) => relLayers.value.has(r.layer) && relCats.value.has(r.cat)
    && (!kw || [r.from, r.to, r.predicate, r.mechanism, r.via ?? ''].some((t) => t?.includes(kw))))
})
const hubRelations = computed(() => props.profile.relations.classRelations.filter(
  (r) => relLayers.value.has(r.layer ?? '类间') && relCats.value.has(CAT_OF[r.category ?? ''] ?? '结构')))
function openGraph() {
  if (props.profile.graphEntityId) router.push(`/graph/${props.profile.graphEntityId}`)
}

// 处置页：左侧卡片列表，右侧选中卡片
const procId = ref<string | null>(null)
const currentProc = computed(() => {
  const list = props.profile.procedures ?? []
  return list.find((c) => c.id === procId.value) ?? list[0] ?? null
})

const structureIssues = computed(() => props.profile.constraints.structure.filter((c) => !c.satisfied).length)

const RULE_FILTERS = ['全部', '专属 / 同工段', '通用层'] as const
const ruleFilter = ref<(typeof RULE_FILTERS)[number]>('全部')

const KINDS = ['全部', '固有', '工艺属性', '测量', '状态', '控制'] as const
const kindFilter = ref<(typeof KINDS)[number]>('全部')
// 运行约束按当前值校验（本体约束校验接口，按需调用）
const checking = ref(false)
// 展开限值版本（在线修改限值 = 追加版本）
const openLimit = ref<string | null>(null)
const checkResult = ref<LimitCheckResult | null>(null)
const checkError = ref<string | null>(null)
async function runCheck() {
  checking.value = true
  checkError.value = null
  try {
    checkResult.value = await api.limitCheck(props.profile.objectId)
  } catch (e) {
    checkError.value = (e as Error).message
  } finally {
    checking.value = false
  }
}
const CHECK_LABEL: Record<string, string> = { NORMAL: '正常', UNKNOWN: '无法判断' }
function statusLabel(key: string) {
  const hit = checkResult.value?.results?.find((r) => r.status === key)
  return hit?.statusLabel ?? CHECK_LABEL[key] ?? key
}

watch(() => props.profile.objectId, () => {
  checkResult.value = null
  checkError.value = null
  procId.value = null
  openLimit.value = null
  kindFilter.value = '全部'
  ruleFilter.value = '全部'
  showAllRelations.value = false
})

const kindCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const a of props.profile.attributes) counts[a.kind] = (counts[a.kind] ?? 0) + 1
  return counts
})
const attributes = computed(() =>
  kindFilter.value === '全部' ? props.profile.attributes : props.profile.attributes.filter((a) => a.kind === kindFilter.value)
)

const KIND_STYLE: Record<string, string> = {
  固有: 'text-fg-dim', 工艺属性: 'text-prop', 测量: 'text-info', 状态: 'text-warn', 控制: 'text-equip'
}

function valueCell(a: ProfileAttribute) {
  if (a.value !== undefined && a.value !== null && a.value !== '') return String(a.value)
  return ''
}

const STATUS_PILL: Record<string, string> = {
  可调用: 'pill-ok', 提供方待登记: 'pill-mute',
  已挂载: 'pill-ok', 具备挂载点: 'pill-info', 未挂载: 'pill-mute'
}

const ATTR_REL_STYLE: Record<string, string> = {
  计算: 'text-ok', 传递: 'text-equip', 关联: 'text-info'
}

const showAllRelations = ref(false)
const relationRows = computed(() =>
  showAllRelations.value ? props.profile.relations.classRelations : props.profile.relations.classRelations.slice(0, 20)
)

const specificRules = computed(() => props.profile.rules.filter((r) => r.matchedBy !== '通用层规则（未限定工段）'))
const genericRules = computed(() => props.profile.rules.filter((r) => r.matchedBy === '通用层规则（未限定工段）'))
const ruleRows = computed(() =>
  ruleFilter.value === '专属 / 同工段' ? specificRules.value
    : ruleFilter.value === '通用层' ? genericRules.value
      : [...specificRules.value, ...genericRules.value]
)

const attrRelGroups = computed(() => {
  const groups: Record<string, typeof props.profile.relations.attributeRelations> = {}
  for (const r of props.profile.relations.attributeRelations) (groups[r.kind] ??= []).push(r)
  return groups
})

function alarmText(alarm: Record<string, number>) {
  const label: Record<string, string> = { lowLow: 'LL', low: 'L', high: 'H', highHigh: 'HH' }
  return Object.entries(alarm).map(([k, v]) => `${label[k] ?? k} ${v}`).join(' · ') || '—'
}

const KIND_TITLE: Record<string, string> = {
  equipment: '设备实例', group: '设备组', entity: '工艺对象', area: '工段', class: '类 · 设备类型'
}
</script>

<template>
  <div class="space-y-4">
    <!-- 类与层级（紧凑） -->
    <section class="panel">
      <div class="px-4 py-2.5 bg-gradient-to-r from-brand/[0.10] to-transparent">
        <div class="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <h2 class="m-0 text-[17px] font-semibold tracking-tight">{{ profile.name }}</h2>
          <span class="pill" :class="profile.header.nature && profile.header.nature !== '实例' ? 'pill-warn' : 'pill-info'">{{
            profile.kind === 'equipment' && profile.header.nature && profile.header.nature !== '实例' ? profile.header.nature : KIND_TITLE[profile.kind] }}</span>
          <span v-for="b in profile.header.badges" :key="b" class="pill pill-plain">{{ b }}</span>
          <button v-if="hasHeaderMore" class="ml-auto text-[11.5px] text-fg-mute hover:text-fg" @click="headerOpen = !headerOpen">
            {{ headerOpen ? '收起' : '来源与说明' }} {{ headerOpen ? '▴' : '▾' }}</button>
        </div>
        <div class="mt-1 flex flex-wrap gap-x-5 gap-y-0.5 text-[12px] text-fg-dim">
          <span><span class="text-fg-mute">父类 </span>{{ profile.header.classPath.join(' → ') }}</span>
          <span v-if="profile.header.code"><span class="text-fg-mute">编码 </span><span class="font-mono text-[11.5px] text-fg">{{ profile.header.code }}</span></span>
          <span><span class="text-fg-mute">工段 </span><span class="text-fg">{{ profile.header.area || '—' }}</span><template v-if="profile.header.station"> · 站 {{ profile.header.station }}</template></span>
        </div>
        <div v-if="notice" class="mt-1 text-[12px] text-warn">{{ notice }}</div>
        <div v-if="headerOpen" class="mt-1.5 pt-1.5 border-t border-line-soft space-y-1 text-[12px]">
          <div class="text-fg-dim"><span class="text-fg-mute">来源 </span>{{ profile.header.source?.file ?? '—' }}<span v-if="profile.header.source?.sheet"> · {{ profile.header.source.sheet }}</span><span v-if="profile.header.source?.row"> · 第 {{ profile.header.source.row }} 行</span></div>
          <div v-if="profile.header.aliases?.length" class="flex flex-wrap items-center gap-1.5">
            <span class="text-fg-mute">点表来源写法</span>
            <span
              v-for="al in profile.header.aliases" :key="al.id" class="pill pill-plain"
              :title="`${al.mergeKind} · ${al.rule ?? ''}\n${al.basis ?? ''}\n${al.owlSubject}`"
            >{{ al.name }}<span class="text-fg-mute">{{ al.station }}站 · {{ al.mergeKind }} · {{ al.tagCount }}点</span></span>
            <span class="text-fg-mute text-[11px]">依据 6APA_设备归并.xlsx</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 页签 -->
    <section class="panel">
      <div class="flex items-end gap-1 px-3 pt-2 border-b border-line bg-ink-panel2/70 overflow-x-auto">
        <button
          v-for="t in tabs" :key="t.key"
          class="px-4 py-2 -mb-px text-[13px] whitespace-nowrap border-b-2 transition-colors"
          :class="tab === t.key ? 'border-brand text-fg font-semibold' : 'border-transparent text-fg-dim hover:text-fg'"
          @click="setTab(t.key)"
        >{{ t.key }}<span class="ml-1.5 font-mono text-[11px] text-fg-mute">{{ t.count }}</span><span
          v-if="t.key === '约束' && structureIssues" class="ml-1 text-warn text-[11px]">!{{ structureIssues }}</span></button>
      </div>
      <div class="px-4 py-2 text-[11.5px] text-fg-mute border-b border-line-soft">{{ activeTab.hint }}</div>

      <!-- 属性 -->
      <div v-if="tab === '属性'">
        <div class="flex flex-wrap gap-1 px-4 py-2">
          <button
            v-for="k in KINDS" :key="k" class="ctl !py-0.5 !px-2"
            :class="{ 'ctl-on': kindFilter === k }"
            :disabled="k !== '全部' && !kindCounts[k]"
            @click="kindFilter = k"
          >{{ k }}<span class="font-mono text-fg-mute">{{ k === '全部' ? profile.attributes.length : (kindCounts[k] ?? 0) }}</span></button>
        </div>
        <div class="overflow-x-auto">
            <table class="tbl">
              <thead><tr><th class="w-[84px]">类别</th><th>属性</th><th class="w-[132px]">类型 · 单位</th><th>值 / 数据关联</th></tr></thead>
              <tbody>
                <tr v-for="a in attributes" :key="a.kind + a.name + (a.parameterId ?? '')" class="!cursor-default">
                  <td class="font-medium whitespace-nowrap" :class="KIND_STYLE[a.kind]">{{ a.kind }}</td>
                  <td>
                    <span
                      :class="a.entityId ? 'cursor-pointer hover:text-brand' : ''"
                      @click="a.entityId && emit('open', a.entityId)"
                    >{{ a.name }}</span>
                    <div v-if="a.inheritedFrom" class="text-fg-mute text-[11px]">继承自设备组 {{ a.inheritedFrom }}</div>
                    <div v-if="a.matchStatus && !a.dataLinks?.length" class="text-fg-mute text-[11px]">{{ a.matchStatus }}</div>
                  </td>
                  <td class="text-fg-dim font-mono text-[11.5px]">{{ a.valueType || '—' }}</td>
                  <td>
                    <span
                      v-if="valueCell(a)"
                      :class="a.refId ? 'cursor-pointer text-fg hover:text-brand' : 'text-fg'"
                      @click="a.refId && emit('open', a.refId)"
                    >{{ valueCell(a) }}</span>
                    <span v-if="a.note" class="ml-1 text-fg-mute text-[11px]">（{{ a.note }}）</span>
                    <div v-if="a.dataLinks?.length" class="flex flex-wrap gap-1">
                      <span
                        v-for="l in a.dataLinks.slice(0, 5)" :key="l.tagId"
                        class="pill font-mono"
                        :class="profile.focusTag === l.tag ? 'pill-warn' : 'pill-info'"
                        :title="`${l.desc ?? ''}${l.unit ? ' · ' + l.unit : ''}${l.blockType ? ' · ' + l.blockType : ''}${l.station ? ' · 站' + l.station : ''}`"
                      >→ {{ l.tag }}<span v-if="l.unit" class="text-fg-mute">{{ l.unit }}</span></span>
                      <span v-if="(a.dataLinkTotal ?? 0) > 5" class="pill pill-plain">+{{ (a.dataLinkTotal ?? 0) - 5 }}</span>
                    </div>
                    <span v-else-if="!valueCell(a) && a.kind !== '固有' && !a.note" class="text-fg-mute text-[11.5px]">无现场测点</span>
                  </td>
                </tr>
              </tbody>
            </table>
        </div>
      </div>

      <!-- 关系 -->
      <div v-else-if="tab === '关系'" class="p-4 space-y-3">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-2 text-[12px]">
          <span class="text-fg-mute">层面</span>
          <div class="flex gap-1">
            <button v-for="l in layersPresent" :key="l" class="ctl !py-0.5 !px-2" :class="{ 'ctl-on': relLayers.has(l) }" @click="toggleLayer(l)">
              {{ LAYER_LABEL[l] ?? l }}<span class="font-mono text-fg-mute">{{ layerCounts[l] ?? 0 }}</span></button>
          </div>
          <span class="text-fg-mute ml-2">类别</span>
          <div class="flex flex-wrap gap-1">
            <button
              v-for="c in CAT_ORDER" :key="c" class="ctl !py-0.5 !px-2" :class="{ 'ctl-on': relCats.has(c) }"
              :disabled="!catCounts[c]" :title="'单击切换，双击只看这一类'"
              @click="toggleCat(c)" @dblclick="onlyCat(c)"
            ><span :class="CAT_STYLE[c]">●</span>{{ c }}<span class="font-mono text-fg-mute">{{ catCounts[c] ?? 0 }}</span></button>
            <button class="ctl !py-0.5 !px-2" @click="allCats">全选</button>
          </div>
          <input v-model="relKeyword" type="search" placeholder="筛选对象 / 关系 / 机理…"
                 class="ml-auto w-[200px] px-2 py-1 rounded-md border border-line bg-ink-panel2 text-[12px] text-fg placeholder:text-fg-mute focus:outline-none focus:border-brand" />
          <button v-if="profile.graphEntityId" class="ctl !py-0.5 !px-2" @click="openGraph">在关系图谱中展开 ↗</button>
        </div>

        <div class="grid gap-4" :class="hubRelations.length ? 'xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]' : ''">
          <div v-if="hubRelations.length">
            <div class="text-fg-mute text-[11px] mb-1">关系示意 · {{ hubRelations.length }} 条</div>
            <ClassRelationHub
              :name="profile.name" :class-name="profile.header.className"
              :relations="hubRelations"
              @open="emit('open', $event)"
            />
          </div>
          <div class="min-w-0">
            <div class="text-fg-mute text-[11px] mb-1">关系明细 · {{ filteredRel.length }} 条（点击对象可跳转）</div>
            <div class="max-h-[560px] overflow-y-auto border border-line-soft rounded">
              <table class="tbl">
                <thead class="sticky top-0 z-10"><tr><th class="w-[78px]">类别</th><th>关系</th><th>说明</th></tr></thead>
                <tbody>
                  <tr v-for="r in filteredRel" :key="r.key" class="!cursor-default">
                    <td class="whitespace-nowrap">
                      <span :class="CAT_STYLE[r.cat]">●</span> {{ r.cat }}
                      <div class="text-fg-mute text-[11px]">{{ r.layer }} · {{ r.label }}</div>
                    </td>
                    <td>
                      <span :class="r.fromId ? 'cursor-pointer text-fg hover:text-brand' : 'text-fg'" @click="r.fromId && emit('open', r.fromId)">{{ r.from }}</span>
                      <span class="text-fg-mute mx-1">—{{ r.predicate }}→</span>
                      <span :class="r.toId ? 'cursor-pointer text-fg hover:text-brand' : 'text-fg'" @click="r.toId && emit('open', r.toId)">{{ r.to }}</span>
                      <div v-if="r.via" class="text-fg-mute text-[11px]">经本对象属性「{{ r.via }}」</div>
                      <div v-if="r.linkMode" class="mt-0.5 flex flex-wrap gap-1">
                        <span class="pill pill-plain !text-[10px]">{{ r.linkMode }}</span>
                        <span class="pill !text-[10px]" :class="r.linkStatus === '推导' ? 'pill-info' : 'pill-warn'">{{ r.linkStatus }}</span>
                      </div>
                    </td>
                    <td class="text-fg-dim text-[12px]">{{ r.mechanism || '—' }}</td>
                  </tr>
                  <tr v-if="!filteredRel.length"><td colspan="3" class="text-fg-mute text-center py-4">当前筛选下没有关系</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- 能力 -->
      <div v-else-if="tab === '能力'" class="grid xl:grid-cols-2 xl:divide-x divide-line-soft">
          <div v-if="!profile.capabilities.length" class="empty">能力登记表中没有适用于本对象的能力</div>
          <div v-for="c in profile.capabilities" :key="c.id" class="px-4 py-3 border-b border-line-soft">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-semibold text-[13px]">{{ c.name }}</span>
              <span class="pill pill-plain">{{ c.type }}</span>
              <span class="pill" :class="STATUS_PILL[c.status] ?? 'pill-plain'">{{ c.status }}</span>
              <span class="ml-auto font-mono text-fg-mute text-[11px]">{{ c.id }}</span>
            </div>
            <div class="text-fg-dim text-[12px] mt-0.5">{{ c.description }}</div>
            <dl class="mt-2 grid gap-x-4 gap-y-1 text-[12px]" style="grid-template-columns: 72px minmax(0, 1fr)">
              <dt class="text-fg-mute">提供方</dt><dd class="m-0">{{ c.provider || '—' }}</dd>
              <dt class="text-fg-mute">调用</dt>
              <dd class="m-0">
                <span class="text-fg-dim">{{ c.protocol || '待定' }}</span>
                <span v-if="c.endpoint" class="ml-1.5 font-mono text-[11.5px] break-all">{{ c.endpoint }}</span>
                <span v-else class="ml-1.5 text-fg-mute">提供方接口待登记</span>
              </dd>
              <template v-if="c.gateway">
                <dt class="text-fg-mute">本体代调</dt>
                <dd class="m-0"><span class="font-mono text-[11.5px] break-all">{{ c.gateway }}</span>
                  <span class="text-fg-mute text-[11px]">（本体解析参数后转调提供方）</span></dd>
              </template>
              <dt class="text-fg-mute">输出</dt><dd class="m-0 text-fg-dim">{{ c.output || '—' }}</dd>
              <template v-if="c.preconditions">
                <dt class="text-fg-mute">前置条件</dt><dd class="m-0 text-warn">{{ c.preconditions }}</dd>
              </template>
            </dl>
            <table v-if="c.parameters.length" class="tbl mt-2">
              <thead><tr><th class="w-[96px]">参数</th><th class="w-[72px]">类型</th><th>本对象上的绑定</th></tr></thead>
              <tbody>
                <tr v-for="prm in c.parameters" :key="prm.name" class="!cursor-default">
                  <td class="font-mono text-[11.5px]">{{ prm.name }}<span v-if="prm.required" class="text-err">*</span>
                    <div v-if="prm.description" class="font-sans text-fg-mute text-[11px]">{{ prm.description }}</div></td>
                  <td class="font-mono text-[11px] text-fg-dim">{{ prm.type }}</td>
                  <td>
                    <div class="text-[12px]" :class="prm.bound.bound === null ? 'text-fg-mute' : 'text-fg'">{{ prm.bound.text }}</div>
                    <div v-if="prm.bound.values.length && prm.binding !== '本对象ID'" class="flex flex-wrap gap-1 mt-0.5">
                      <span v-for="v in prm.bound.values" :key="v" class="pill pill-info font-mono">{{ v }}</span>
                      <span v-if="prm.bound.total > prm.bound.values.length" class="pill pill-plain">+{{ prm.bound.total - prm.bound.values.length }}</span>
                    </div>
                    <div class="font-mono text-[10.5px] text-fg-mute mt-0.5">绑定规则：{{ prm.binding }}</div>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="c.note" class="text-fg-mute text-[11px] mt-1">{{ c.note }}</div>
          </div>
      </div>

      <!-- 约束 -->
      <div v-else-if="tab === '约束'" class="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1fr)] text-[12.5px]">
        <div>
          <div class="text-fg-mute text-[11px] mb-1">结构约束（加载器校验）</div>
          <div v-if="!profile.constraints.structure.length" class="text-fg-mute">无</div>
          <div v-for="c in profile.constraints.structure" :key="c.text" class="flex gap-2 py-0.5">
            <span :class="c.satisfied ? 'text-ok' : 'text-warn'">{{ c.satisfied ? '✓' : '!' }}</span>
            <span>{{ c.text }}<span class="text-fg-mute"> · {{ c.detail }}</span></span>
          </div>
        </div>
        <div>
                <div class="flex items-center gap-2 mb-1">
                  <span class="text-fg-mute text-[11px]">运行约束（工艺限值）</span>
                  <button
                    v-if="profile.constraints.check?.available" class="ctl !py-0.5 !px-2 ml-auto"
                    :disabled="checking" @click="runCheck"
                  >{{ checking ? '校验中…' : '按当前值校验' }}</button>
                  <span v-else-if="profile.constraints.check" class="ml-auto text-fg-mute text-[11px]">{{ profile.constraints.check.reason }}</span>
                </div>
                <div v-if="checkError" class="text-err text-[12px] mb-1">{{ checkError }}</div>
                <div v-if="checkResult" class="mb-2 px-2 py-1.5 rounded border border-line-soft bg-ink-panel2/60">
                  <div class="flex flex-wrap gap-1.5 items-center text-[12px]">
                    <span class="text-fg-dim">校验 {{ checkResult.checked ?? 0 }} 个测点</span>
                    <span v-for="(n, k) in checkResult.summary ?? {}" :key="k" class="pill" :class="String(k) === 'NORMAL' ? 'pill-ok' : String(k) === 'UNKNOWN' ? 'pill-mute' : 'pill-warn'">{{ statusLabel(String(k)) }} {{ n }}</span>
                    <span v-if="checkResult.dataSource?.simulated" class="pill pill-mute">模拟数据</span>
                  </div>
                  <div v-for="r in (checkResult.results ?? []).filter((x) => x.status !== 'NORMAL' && x.status !== 'UNKNOWN').slice(0, 6)" :key="r.limitId + r.tagName" class="text-[11.5px] mt-0.5">
                    <span class="font-mono">{{ r.tagName }}</span> {{ r.value ?? '—' }} {{ r.unit ?? '' }}
                    <span class="text-warn">· {{ r.statusLabel }}</span><span class="text-fg-mute"> · {{ r.limitId }}</span>
                  </div>
                  <div v-if="checkResult.notice" class="text-fg-mute text-[11px] mt-0.5">{{ checkResult.notice }}</div>
                </div>
                <div v-if="!profile.constraints.operating.length" class="text-fg-mute">本体中暂无适用的工艺限值</div>
                <div v-for="l in profile.constraints.operating" :key="l.id" class="py-1 border-b border-line-soft last:border-0">
                  <div class="flex flex-wrap items-center gap-1.5">
                    <span class="font-mono text-brand">{{ l.id }}</span>
                    <span>{{ l.appliesTo }}</span>
                    <span class="pill" :class="l.status === '已确认' ? 'pill-ok' : l.hasValues ? 'pill-warn' : 'pill-mute'">{{ l.status }}</span>
                  </div>
                  <div class="text-fg-dim text-[12px]">
                    <template v-if="l.hasValues">正常 {{ l.normal ?? '—' }} {{ l.unit }} · {{ alarmText(l.alarm) }}</template>
                    <template v-else>数值待现场提供</template>
                    <span v-if="l.operatingMode" class="text-fg-mute"> · {{ l.operatingMode }}</span>
                    <button class="ml-2 text-[11px] text-info hover:underline" @click="openLimit = openLimit === l.id ? null : l.id">
                      版本 {{ l.versionCount ?? 1 }}<template v-if="l.conditional"> · 含条件版本</template> {{ openLimit === l.id ? '▴' : '▾' }}
                    </button>
                  </div>
                </div>
        </div>
        <div>
          <div class="text-fg-mute text-[11px] mb-1">安全约束（报警联锁）</div>
          <div v-if="!profile.constraints.safety.length" class="text-fg-mute">本体中没有登记涉及本对象的报警联锁</div>
          <div v-for="s in profile.constraints.safety" :key="s.text" class="py-0.5">{{ s.text }}<span class="text-fg-mute"> · {{ s.mechanism }}</span></div>
        </div>
        <div v-if="openLimit" class="lg:col-span-3">
          <div class="text-fg-mute text-[11px]">限值 <span class="font-mono text-brand">{{ openLimit }}</span> 的版本（在线修改 = 追加版本，判断历史数据按当时生效的版本）</div>
          <LimitVersions :limit-id="openLimit" :unit-name="profile.kind === 'equipment' ? profile.name : null" />
        </div>
      </div>

      <!-- 规则 -->
      <div v-else-if="tab === '规则'">
        <div class="flex flex-wrap items-center gap-1 px-4 py-2">
          <button v-for="f in RULE_FILTERS" :key="f" class="ctl !py-0.5 !px-2" :class="{ 'ctl-on': ruleFilter === f }" @click="ruleFilter = f">
            {{ f }}<span class="font-mono text-fg-mute">{{ f === '全部' ? profile.rules.length : f === '通用层' ? genericRules.length : specificRules.length }}</span>
          </button>
        </div>
        <div v-if="!profile.rules.length" class="empty">暂无适用规则</div>
        <table v-else class="tbl">
          <thead><tr><th class="w-[96px]">规则</th><th>名称</th><th>条件 → 结论</th><th class="w-[72px]">程度</th><th class="w-[150px]">适用依据</th></tr></thead>
          <tbody>
            <tr v-for="r in ruleRows" :key="r.id" class="!cursor-default">
              <td class="font-mono text-equip whitespace-nowrap">{{ r.id }} <span v-if="r.draft" class="pill pill-warn">草案</span></td>
              <td>{{ r.name }}</td>
              <td class="text-fg-dim text-[12px]">{{ r.condition || '—' }} <span class="text-fg-mute">→</span> {{ r.conclusion || '—' }}</td>
              <td class="text-fg-dim">{{ r.severity || '—' }}</td>
              <td class="text-fg-mute text-[11.5px]">{{ r.matchedBy }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 处置 -->
      <div v-else-if="tab === '处置'">
        <div v-if="!profile.procedures?.length" class="empty">处置规程中没有与本对象相关的处置卡</div>
        <div v-else class="grid lg:grid-cols-[260px_minmax(0,1fr)] lg:divide-x divide-line-soft">
          <div class="py-2 max-h-[720px] overflow-y-auto">
            <button
              v-for="c in profile.procedures" :key="c.id"
              class="block w-full text-left px-4 py-2 border-l-2 hover:bg-ink-panel2"
              :class="currentProc?.id === c.id ? 'bg-brand/[0.13] border-brand' : 'border-transparent'"
              @click="procId = c.id"
            >
              <div class="flex items-center gap-1.5">
                <span class="font-mono text-[11px] text-equip">{{ c.id }}</span>
                <span class="ml-auto pill !text-[10px]" :class="c.relation === '触发' ? 'pill-info' : 'pill-plain'">{{ c.relation }}</span>
              </div>
              <div class="text-[12.5px] text-fg">{{ c.name }}</div>
              <div class="text-[11px] text-fg-mute">{{ c.trigger.level }} {{ c.trigger.setpoint }} · 原因 {{ c.summary.causeCount }} · 步骤 {{ c.summary.stepCount }}</div>
            </button>
          </div>
          <div class="p-4 min-w-0">
            <ProcedureCardView v-if="currentProc" :card="currentProc" @open="emit('open', $event)" />
          </div>
        </div>
      </div>

      <!-- 批次（运行上下文） -->
      <BatchPanel v-else-if="tab === '批次' && profile.process" :object-id="profile.objectId" :process="profile.process" />

      <!-- 实例（设备组） -->
      <div v-else-if="tab === '实例' && profile.instances" class="p-4">
        <div class="text-fg-mute text-[11px] mb-2">
          <template v-if="profile.instances.some((i) => i.nature === '设备组')">{{ profile.instances.filter((i) => i.nature === '设备组').length }} 个设备组、</template>{{ profile.instances.filter((i) => !i.nature || i.nature === '实例').length }} 台实例<template v-if="profile.instances.some((i) => i.nature && !['实例', '设备组'].includes(i.nature))"> + 公共点位 / 合集</template>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <button v-for="i in profile.instances" :key="i.id" class="ctl" :class="i.nature && !['实例', '设备组'].includes(i.nature) ? 'italic border-dashed' : ''" @click="emit('open', i.id)">
            {{ i.name }}<span class="text-fg-mute font-mono text-[10.5px]">{{ i.tagCount }}点<template v-if="i.nature && i.nature !== '实例'"> · {{ i.nature }}</template></span>
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
