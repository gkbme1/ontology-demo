<script setup lang="ts">
/**
 * 对象本体档案：类与层级 / 属性（数据关联直接体现在属性里）/ 能力挂载 / 约束 / 规则 / 类间关系 / 属性间关系。
 * 全部数据来自 /api/ontology/asset-profile/{id}，组件不内置任何设备、点位或关系。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { AssetProfile, LimitCheckResult, ProfileAttribute } from '@/api/types'
import ClassRelationHub from './ClassRelationHub.vue'

const props = defineProps<{ profile: AssetProfile }>()
const emit = defineEmits<{ open: [objectId: string] }>()

const KINDS = ['全部', '固有', '工艺属性', '测量', '状态', '控制'] as const
const kindFilter = ref<(typeof KINDS)[number]>('全部')
// 运行约束按当前值校验（本体约束校验接口，按需调用）
const checking = ref(false)
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
  kindFilter.value = '全部'
  showAllRules.value = false
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
  showAllRelations.value ? props.profile.relations.classRelations : props.profile.relations.classRelations.slice(0, 12)
)

const showAllRules = ref(false)
const specificRules = computed(() => props.profile.rules.filter((r) => r.matchedBy !== '通用层规则（未限定工段）'))
const genericRules = computed(() => props.profile.rules.filter((r) => r.matchedBy === '通用层规则（未限定工段）'))
const ruleRows = computed(() => {
  const all = [...specificRules.value, ...genericRules.value]
  return showAllRules.value ? all : all.slice(0, 6)
})

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
  equipment: '设备实例', group: '类 · 标准设备组', entity: '工艺对象', area: '工段'
}
</script>

<template>
  <div class="space-y-4">
    <!-- 类与层级 -->
    <section class="panel">
      <div class="px-5 py-4 bg-gradient-to-r from-brand/[0.10] to-transparent">
        <div class="flex flex-wrap items-baseline gap-x-6 gap-y-1">
          <div class="text-[11px] text-fg-mute">类名</div>
          <h2 class="m-0 text-[19px] font-semibold tracking-tight">{{ profile.name }}</h2>
          <span class="pill" :class="profile.header.nature && profile.header.nature !== '实例' ? 'pill-warn' : 'pill-info'">{{
            profile.kind === 'equipment' && profile.header.nature && profile.header.nature !== '实例' ? profile.header.nature : KIND_TITLE[profile.kind] }}</span>
          <span v-for="b in profile.header.badges" :key="b" class="pill pill-plain">{{ b }}</span>
        </div>
        <dl class="mt-3 grid gap-x-8 gap-y-1.5 text-[12.5px]" style="grid-template-columns: repeat(auto-fit, minmax(260px, 1fr))">
          <div class="flex gap-2"><dt class="text-fg-mute w-12 shrink-0">父类</dt>
            <dd class="m-0 text-fg-dim">{{ profile.header.classPath.join(' → ') }}</dd></div>
          <div class="flex gap-2"><dt class="text-fg-mute w-12 shrink-0">编码</dt>
            <dd class="m-0 font-mono text-[12px] break-all">{{ profile.header.code || '—' }}</dd></div>
          <div class="flex gap-2"><dt class="text-fg-mute w-12 shrink-0">工段</dt>
            <dd class="m-0">{{ profile.header.area || '—' }}<span v-if="profile.header.station" class="text-fg-mute"> · 控制站 {{ profile.header.station }}</span></dd></div>
          <div class="flex gap-2"><dt class="text-fg-mute w-12 shrink-0">来源</dt>
            <dd class="m-0 text-fg-dim">
              {{ profile.header.source?.file ?? '—' }}<span v-if="profile.header.source?.sheet"> · {{ profile.header.source.sheet }}</span><span v-if="profile.header.source?.row"> · 第 {{ profile.header.source.row }} 行</span>
            </dd></div>
        </dl>
        <div v-if="profile.header.aliases?.length" class="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]">
          <span class="text-fg-mute">点表来源写法</span>
          <span
            v-for="al in profile.header.aliases" :key="al.id" class="pill pill-plain"
            :title="`${al.mergeKind} · ${al.rule ?? ''}\n${al.basis ?? ''}\n${al.owlSubject}`"
          >{{ al.name }}<span class="text-fg-mute">{{ al.station }}站 · {{ al.mergeKind }} · {{ al.tagCount }}点</span></span>
          <span class="text-fg-mute text-[11px]">依据 6APA_设备归并.xlsx</span>
        </div>
        <div v-if="profile.kind === 'equipment' && profile.header.nature && profile.header.nature !== '实例'" class="mt-2 text-[12px] text-warn">
          这不是一台设备：{{ profile.header.nature === '组公共点位' ? '设备组拆回实例后，剩下没有台号、整组共用的点挂在这里。'
            : profile.header.nature === '合集·未拆分' ? '点表把同组几台设备的点写在一个名字下，按台号拆不开，暂作合集。'
            : '点表中按位置兜底归类的点（公用测量管线 / 其他工艺单元 / 管网阀门系统）。' }}
        </div>
        <div v-if="profile.splitFrom" class="mt-2 text-[12px] text-warn">
          点表中的「{{ profile.splitFrom.name }}」是本组 {{ profile.splitFrom.instanceIds.length }} 台设备的合集，已按台号拆回下面的实例。
        </div>
        <div v-if="profile.focusTag" class="mt-2 text-[12px] text-warn">由位号 {{ profile.focusTag }} 定位到本设备，属性表中已高亮。</div>
      </div>
    </section>

    <div class="grid gap-4 2xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <!-- 左列：属性 / 能力 / 约束 / 规则 -->
      <div class="space-y-4 min-w-0">
        <section class="panel">
          <div class="panel-head">
            <h3>属性</h3>
            <span class="text-fg-mute text-[11.5px]">数据关联直接体现在属性里</span>
            <div class="ml-auto flex flex-wrap gap-1">
              <button
                v-for="k in KINDS" :key="k" class="ctl !py-0.5 !px-2"
                :class="{ 'ctl-on': kindFilter === k }"
                :disabled="k !== '全部' && !kindCounts[k]"
                @click="kindFilter = k"
              >{{ k }}<span class="font-mono text-fg-mute">{{ k === '全部' ? profile.attributes.length : (kindCounts[k] ?? 0) }}</span></button>
            </div>
          </div>
          <div class="max-h-[520px] overflow-auto">
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
        </section>

        <section class="panel">
          <div class="panel-head">
            <h3>能力挂载</h3>
            <span class="text-fg-mute text-[11.5px]">能力由外部系统实现；本体登记能力描述、调用契约，并在本对象上绑定参数</span>
            <span class="ml-auto font-mono text-fg-mute text-[11px]">6APA_能力.xlsx</span>
          </div>
          <div v-if="!profile.capabilities.length" class="empty">能力登记表中没有适用于本对象的能力</div>
          <div v-for="c in profile.capabilities" :key="c.id" class="px-4 py-3 border-b border-line-soft last:border-0">
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
        </section>

        <div class="grid gap-4 xl:grid-cols-2">
          <section class="panel border-info/40">
            <div class="panel-head"><h3>约束</h3><span class="text-fg-mute text-[11.5px]">属于本体</span></div>
            <div class="panel-body space-y-3 text-[12.5px]">
              <div v-if="profile.constraints.structure.length">
                <div class="text-fg-mute text-[11px] mb-1">结构约束（加载器校验）</div>
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
                  </div>
                </div>
              </div>
              <div v-if="profile.constraints.safety.length">
                <div class="text-fg-mute text-[11px] mb-1">安全约束（报警联锁）</div>
                <div v-for="s in profile.constraints.safety" :key="s.text" class="py-0.5">{{ s.text }}<span class="text-fg-mute"> · {{ s.mechanism }}</span></div>
              </div>
            </div>
          </section>

          <section class="panel border-equip/40">
            <div class="panel-head"><h3>规则</h3><span class="text-fg-mute text-[11.5px]">在推理引擎中定义与执行</span>
              <span class="ml-auto font-mono text-fg-mute text-[11px]">{{ specificRules.length }} 专属/同工段 · {{ genericRules.length }} 通用层</span></div>
            <div class="panel-body text-[12.5px]">
              <div v-if="!profile.rules.length" class="text-fg-mute">暂无适用规则</div>
              <div v-for="r in ruleRows" :key="r.id" class="py-1.5 border-b border-line-soft last:border-0">
                <div class="flex items-center gap-1.5">
                  <span class="font-mono text-equip">{{ r.id }}</span>
                  <span class="truncate">{{ r.name }}</span>
                  <span v-if="r.draft" class="pill pill-warn">草案</span>
                  <span class="ml-auto text-fg-mute text-[11px] shrink-0">{{ r.matchedBy }}</span>
                </div>
                <div v-if="r.condition" class="text-fg-dim text-[12px]">{{ r.condition }} <span class="text-fg-mute">→</span> {{ r.conclusion }}</div>
              </div>
              <button v-if="profile.rules.length > 6" class="ctl mt-2" @click="showAllRules = !showAllRules">
                {{ showAllRules ? '收起' : `展开全部 ${profile.rules.length} 条` }}
              </button>
            </div>
          </section>
        </div>
      </div>

      <!-- 右列：类间关系 / 属性间关系 / 实例 -->
      <div class="space-y-4 min-w-0">
        <section class="panel">
          <div class="panel-head"><h3>类间关系</h3><span class="text-fg-mute text-[11.5px]">拓扑、所属、部件、控制、报警联锁</span>
            <span class="ml-auto font-mono text-fg-mute text-[11px]">{{ profile.relations.classRelations.length }} 条</span></div>
          <div class="panel-body">
            <ClassRelationHub
              v-if="profile.relations.classRelations.length"
              :name="profile.name" :class-name="profile.header.className"
              :relations="profile.relations.classRelations"
              @open="emit('open', $event)"
            />
            <div v-else class="empty">本体中没有登记该对象的类间关系</div>
            <table v-if="profile.relations.classRelations.length" class="tbl mt-3">
              <thead><tr><th class="w-[72px]">关系</th><th>对象</th><th>说明</th></tr></thead>
              <tbody>
                <tr v-for="r in relationRows" :key="r.role + r.target + r.predicate" @click="r.targetId && emit('open', r.targetId)">
                  <td class="text-fg-dim whitespace-nowrap">{{ r.role }}</td>
                  <td :class="r.targetId ? 'text-fg hover:text-brand' : 'text-fg-dim'">{{ r.target }}
                    <div class="text-fg-mute text-[11px]">{{ r.predicate }}<span v-if="r.targetType"> · {{ r.targetType }}</span></div></td>
                  <td class="text-fg-dim text-[12px]">{{ r.mechanism || '—' }}</td>
                </tr>
              </tbody>
            </table>
            <button v-if="profile.relations.classRelations.length > 12" class="ctl mt-2" @click="showAllRelations = !showAllRelations">
              {{ showAllRelations ? '收起' : `展开全部 ${profile.relations.classRelations.length} 条` }}
            </button>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><h3>属性间关系</h3><span class="text-fg-mute text-[11.5px]">因果 / 影响 / 质量关系，按计算、传递、关联归类</span></div>
          <div class="panel-body text-[12.5px] max-h-[360px] overflow-y-auto">
            <div v-if="!profile.relations.attributeRelations.length" class="text-fg-mute">本体中没有登记涉及该对象属性的因果关系</div>
            <div v-for="(list, kind) in attrRelGroups" :key="kind" class="mb-2">
              <div class="font-semibold mb-0.5" :class="ATTR_REL_STYLE[kind] ?? 'text-fg'">{{ kind }}</div>
              <div v-for="r in list" :key="r.from + r.to + r.predicate" class="py-0.5 pl-3">
                {{ r.from }} <span class="text-fg-mute">→{{ r.predicate }}→</span> {{ r.to }}
                <div v-if="r.mechanism" class="text-fg-mute text-[11.5px]">{{ r.mechanism }}</div>
              </div>
            </div>
          </div>
        </section>

        <section v-if="profile.instances?.length" class="panel">
          <div class="panel-head"><h3>类的实例</h3><span class="ml-auto font-mono text-fg-mute text-[11px]">{{ profile.instances.filter((i) => !i.nature || i.nature === '实例').length }} 台实例<template v-if="profile.instances.some((i) => i.nature && i.nature !== '实例')"> + 公共点位/合集</template></span></div>
          <div class="panel-body flex flex-wrap gap-1.5">
            <button v-for="i in profile.instances" :key="i.id" class="ctl" :class="i.nature && i.nature !== '实例' ? 'italic border-dashed' : ''" @click="emit('open', i.id)">
              {{ i.name }}<span class="text-fg-mute font-mono text-[10.5px]">{{ i.tagCount }}点<template v-if="i.nature && i.nature !== '实例'"> · {{ i.nature }}</template></span>
            </button>
          </div>
        </section>

        <section class="panel bg-ink-panel2/60">
          <div class="panel-body text-[12px] text-fg-dim leading-relaxed">
            <span class="font-semibold text-fg">定义要点：</span>类描述"是什么、能挂什么"。属性带出数据关联（DCS 位号）；
            约束属于本体；业务规则在推理引擎中定义与执行；能力与动作的实现在本体之外，本体只提供挂载点。
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
