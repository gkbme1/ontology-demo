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
              <thead><tr><th class="w-[84px]">类别</th><th>参数</th><th class="w-[110px]">类型 · 单位</th><th>值 / 数据关联（DCS 位号）</th></tr></thead>
              <tbody>
                <tr v-for="(a, i) in params" :key="i" class="!cursor-default">
                  <td><span class="pill" :class="GROUP_PILL[a.group] ?? 'pill-plain'">{{ a.group }}</span></td>
                  <td>
                    <div class="font-medium">{{ a.name }}</div>
                    <div v-if="a.description" class="text-[11px] text-fg-mute">{{ a.description }}</div>
                    <div v-if="a.inheritedFrom" class="text-[11px] text-fg-mute">继承自设备组 {{ a.inheritedFrom }}</div>
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

          <!-- 参数约束 -->
          <div v-else-if="tab === 'constraints'" class="space-y-4">
            <div>
              <div class="sec-title">工艺限值（LL / L / 正常区间 / H / HH）</div>
              <div v-if="!data.operating.length" class="empty">暂无工艺限值</div>
              <table v-else class="tbl">
                <thead><tr><th>编号</th><th>适用参数</th><th>工况</th><th>LL / L / 正常 / H / HH</th><th>单位</th><th>状态</th><th>依据</th></tr></thead>
                <tbody>
                  <tr v-for="c in data.operating" :key="c.id" class="!cursor-default">
                    <td class="font-mono">{{ c.id }}</td><td>{{ c.appliesTo }}</td><td class="text-fg-dim">{{ c.operatingMode }}</td>
                    <td class="font-mono text-xs whitespace-nowrap">{{ c.hasValues ? fmtBand(c) : '待现场提供' }}</td><td>{{ c.unit }}</td>
                    <td><span class="pill pill-warn">{{ c.status }}</span></td><td class="text-[11px] text-fg-mute max-w-[380px]">{{ c.basis }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="data.safety.length">
              <div class="sec-title">安全约束</div>
              <ul class="text-xs space-y-1"><li v-for="(s, i) in data.safety" :key="i">{{ s.text ?? s }}</li></ul>
            </div>
            <div>
              <div class="sec-title">结构约束检查</div>
              <table class="tbl"><tbody>
                <tr v-for="s in data.structure" :key="s.text" class="!cursor-default">
                  <td><span class="pill" :class="s.satisfied ? 'pill-ok' : 'pill-err'">{{ s.satisfied ? '满足' : '不满足' }}</span></td>
                  <td>{{ s.text }}</td><td class="text-fg-dim">{{ s.detail }}</td>
                </tr>
              </tbody></table>
            </div>
          </div>

          <!-- 拓扑关系 -->
          <div v-else-if="tab === 'topology'">
            <table class="tbl">
              <thead><tr><th>层</th><th>类别</th><th>方向</th><th>关系</th><th>对象</th><th>说明</th><th>来源</th></tr></thead>
              <tbody>
                <tr v-for="(r, i) in data.items" :key="i" class="!cursor-default">
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
            <div class="text-xs text-fg-mute mb-2">现象 = 当前情况的描述 + 判定规则；设备组上定义的现象对组内每台设备生效（标「继承自设备组」）。点一行查看它由什么导致。</div>
            <PhenomenaPanel :items="data.items" :anchor-options="anchorOptions" :op-id="opId ?? head.opId" @changed="loadTab" />
          </div>

          <!-- 根因影响关系 -->
          <CausalPanel v-else-if="tab === 'causal'" :links="data.links" :graph="data.graph" :op-id="opId ?? head.opId" @changed="loadTab" />

          <!-- 工艺影响关系 -->
          <div v-else-if="tab === 'influence'">
            <div class="text-xs text-fg-mute mb-2">{{ data.note }}</div>
            <div v-if="!data.items.length" class="empty">暂无工艺影响关系</div>
            <table v-else class="tbl">
              <thead><tr><th>影响方</th><th>关系</th><th>被影响方</th><th>机理</th><th>测点</th><th>来源</th></tr></thead>
              <tbody>
                <tr v-for="(r, i) in data.items" :key="i" class="!cursor-default">
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
            <CalcPanel :items="data.items" :op-id="opId ?? head.opId" :target-id="head.kind === 'equipment' ? objectId : undefined" />
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
  </div>
</template>
