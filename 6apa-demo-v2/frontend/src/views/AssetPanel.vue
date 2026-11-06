<script setup lang="ts">
/**
 * 设备 / 设备组信息：页签依次为 图纸位置与外观、参数、仪表、参数约束、拓扑关系、现象定义、
 * 根因影响关系、工艺影响关系、计算/指标、处置规程。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { nav, openObject } from '@/composables/useNav'
import DrawingView from '@/components/DrawingView.vue'
import CalcPanel from '@/components/CalcPanel.vue'
import ProcedureCard from '@/components/ProcedureCard.vue'
import InheritBox from '@/components/InheritBox.vue'
import CausePopup from '@/components/causal/CausePopup.vue'
import PhenomenaPanel from '@/components/causal/PhenomenaPanel.vue'
import CausalPanel from '@/components/causal/CausalPanel.vue'

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
async function loadTab(): Promise<void> {
  loading.value = true
  data.value = null
  try {
    data.value = await api.objectTab(props.objectId, tab.value, props.opId)
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
const paramGroup = ref('')
const openVer = ref<Record<string, boolean>>({})
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
  基本信息: 'pill-plain', 设计参数: 'pill-warn', 工艺属性: 'pill-ok', 测量: 'pill-info', 状态: 'pill-info', 控制: 'pill-info'
}
const params = computed(() => (data.value?.items ?? []).filter((a: Any) =>
  (!paramGroup.value || a.group === paramGroup.value) &&
  (!tagKw.value || `${a.name}${a.description}${a.links?.map((l: Any) => l.tag + l.desc).join('') ?? ''}`.toLowerCase().includes(tagKw.value.toLowerCase()))))
const counts = computed<Record<string, number>>(() => head.value?.counts ?? {})

function pick(id: string, kind: string, opId?: string): void {
  if (kind === 'equipment' || kind === 'group') openObject(id, opId ?? props.opId ?? head.value?.opId, 'drawing')
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
              <button v-for="g in data.groups" :key="g" class="ctl" :class="{ 'ctl-on': paramGroup === g }" @click="paramGroup = g">
                {{ g }} <span class="text-fg-mute">{{ data.counts[g] }}</span>
              </button>
              <input v-model="tagKw" class="inp w-56 ml-2" placeholder="筛选参数名 / 位号 / 描述" />
              <span class="flex-1" />
              <span class="text-[11px] text-fg-mute">{{ data.scope }} {{ data.tagTotal }} 个 DCS 测点<template v-if="data.designPending"> · 设计参数 {{ data.designPending }} 项待补充</template></span>
            </div>
            <table class="tbl">
              <thead><tr><th class="w-12 !text-center">继承</th><th class="w-[84px]">类别</th><th>参数</th><th class="w-[110px]">类型 · 单位</th><th>值 / 数据关联（DCS 位号）</th></tr></thead>
              <tbody>
                <tr v-for="(a, i) in params" :key="i" class="!cursor-default">
                  <td><InheritBox :checked="a.inherited" :from="a.inheritedFrom" /></td>
                  <td><span class="pill" :class="GROUP_PILL[a.group] ?? 'pill-plain'">{{ a.group }}</span></td>
                  <td>
                    <div class="font-medium">{{ a.name }}</div>
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
                    <span v-else-if="!a.note && ['工艺属性', '测量', '状态', '控制'].includes(a.group) && (a.value === undefined || a.value === null)" class="text-[11px] text-fg-mute">
                      无本台测点{{ a.groupLinkTotal ? `（设备组共 ${a.groupLinkTotal} 个）` : '（派生量或待补）' }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div class="text-[11px] text-fg-mute mt-2">
              设计参数来自 data/config/6APA_设备设计参数.xlsx（模板「{{ data.designTemplate ?? '无匹配模板' }}」），按设备档案 / 铭牌填写后重新导出即可显示；灰色位号表示测点在其他设备上（共用设备或组级属性）。
            </div>
          </div>

          <!-- 参数约束：工况与版本适用条件关联到「工况」现象 -->
          <div v-else-if="tab === 'constraints'" class="space-y-4">
            <div class="text-xs text-fg-mute">{{ data.note }}</div>
            <div v-if="!data.operating.length" class="empty">暂无工艺限值</div>
            <table v-else class="tbl">
              <thead><tr><th class="w-12 !text-center">继承</th><th>编号</th><th>适用参数</th><th>工况</th><th>LL / L / 正常 / H / HH</th><th>单位</th><th>版本</th><th>状态</th></tr></thead>
              <tbody>
                <template v-for="c in data.operating" :key="c.id">
                  <tr class="!cursor-default">
                    <td><InheritBox :checked="c.inherited" :from="c.inheritedFrom" /></td>
                    <td class="font-mono">{{ c.id }}</td>
                    <td>{{ c.appliesTo }}<div class="text-[11px] text-fg-mute max-w-[340px] truncate" :title="c.basis">{{ c.basis }}</div></td>
                    <td>
                      <button v-if="c.modePhenomenon" class="phen-link" :title="`工况现象：${c.modePhenomenon.name}（${c.modePhenomenon.anchor}）`" @click="gotoPhen(c.modePhenomenon.id)">
                        {{ c.operatingMode }}<span v-if="!c.modePhenomenon.hasRule" class="opacity-60">（规则待定义）</span>
                      </button>
                      <span v-else class="text-fg-dim">{{ c.operatingMode || '—' }}</span>
                    </td>
                    <td class="font-mono text-xs whitespace-nowrap">{{ c.hasValues ? fmtBand(c) : '待现场提供' }}</td>
                    <td>{{ c.unit }}</td>
                    <td>
                      <button class="ctl !py-0" @click="openVer[c.id] = !openVer[c.id]">{{ c.versions.length }} 个 {{ openVer[c.id] ? '▾' : '▸' }}</button>
                    </td>
                    <td><span class="pill pill-warn">{{ c.status }}</span></td>
                  </tr>
                  <tr v-if="openVer[c.id]" class="!cursor-default hover:!bg-transparent">
                    <td />
                    <td colspan="7" class="!pt-0">
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
          <div v-else-if="tab === 'topology'">
            <table class="tbl">
              <thead><tr><th class="w-12 !text-center">继承</th><th>层</th><th>类别</th><th>方向</th><th>关系</th><th>对象</th><th>说明</th><th>来源</th></tr></thead>
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
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 现象定义 -->
          <div v-else-if="tab === 'phenomena'">
            <div class="text-xs text-fg-mute mb-2">现象 = 当前情况的描述 + 判定规则；设备组上定义的现象对组内每台设备生效（「继承」列勾选）。类别为「工况」的现象被参数约束引用。点一行查看它由什么导致。</div>
            <PhenomenaPanel :items="data.items" :anchor-options="anchorOptions" :op-id="opId ?? head.opId" show-inherit :focus-id="focusPhen" @changed="loadTab" />
          </div>

          <!-- 根因影响关系 -->
          <CausalPanel v-else-if="tab === 'causal'" :links="data.links" :graph="data.graph" :op-id="opId ?? head.opId" show-inherit @changed="loadTab" />

          <!-- 工艺影响关系 -->
          <div v-else-if="tab === 'influence'">
            <div class="text-xs text-fg-mute mb-2">{{ data.note }}</div>
            <div v-if="!data.items.length" class="empty">暂无工艺影响关系</div>
            <table v-else class="tbl">
              <thead><tr><th class="w-12 !text-center">继承</th><th>影响方</th><th>关系</th><th>被影响方</th><th>机理</th><th>测点</th><th>来源</th></tr></thead>
              <tbody>
                <tr v-for="(r, i) in data.items" :key="i" class="!cursor-default">
                  <td><InheritBox :checked="r.inherited" :from="r.inheritedFrom" /></td>
                  <td>{{ r.from }}</td>
                  <td class="whitespace-nowrap" :class="r.predicate === '负向影响' ? 'text-warn' : 'text-ok'">{{ r.predicate }}</td>
                  <td>{{ r.to }}</td><td class="text-fg-dim">{{ r.mechanism }}</td>
                  <td class="text-fg-mute tabular-nums">{{ r.tagCount }}</td><td class="text-[11px] text-fg-mute">{{ r.source }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 计算/指标 -->
          <div v-else-if="tab === 'calc'" class="space-y-4">
            <CalcPanel :items="data.items" :op-id="opId ?? head.opId" :target-id="head.kind === 'equipment' ? objectId : undefined" show-inherit />
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
            <ProcedureCard v-for="(c, i) in data.items" :key="c.id" :card="c" :open="i === 0" />
          </div>
        </template>
      </div>
    </template>
    <CausePopup v-if="popupPhen" :phenomenon-id="popupPhen" :phenomena="allPhen" :op-id="opId ?? head?.opId" @close="popupPhen = ''" />
  </div>
</template>
