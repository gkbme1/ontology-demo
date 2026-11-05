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
const tags = computed(() => (data.value?.items ?? []).filter((t: Any) => !tagKw.value || `${t.tag}${t.description}${t.equipment}${t.parameter}`.includes(tagKw.value)))
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
      <!-- 头部 -->
      <div class="px-5 pt-4 pb-0 border-b border-line bg-ink-panel">
        <div class="text-[11px] text-fg-mute">
          <span v-for="(p, i) in head.path" :key="p.id">{{ p.name }}<span v-if="i < head.path.length - 1"> › </span></span>
          <span v-if="head.opIds.length > 1" class="ml-2 text-info">（成员分属 {{ head.opIds.length }} 道工序）</span>
        </div>
        <div class="flex items-center gap-3 mt-1">
          <h2 class="text-[18px] font-semibold">{{ head.name }}</h2>
          <span class="pill pill-info">{{ head.kind === 'group' ? '设备组' : '设备' }}</span>
          <span v-if="head.className" class="pill pill-plain">{{ head.className }}</span>
          <span v-for="b in head.badges" :key="b" class="pill pill-plain">{{ b }}</span>
        </div>
        <div class="flex gap-0.5 mt-3 overflow-x-auto">
          <button v-for="t in head.tabs" :key="t.key" class="tab-btn" :class="{ 'tab-on': tab === t.key }" @click="tab = t.key">
            {{ t.label }}<span v-if="counts[t.key]" class="ml-1 text-[10.5px] text-fg-mute">{{ counts[t.key] }}</span>
          </button>
        </div>
      </div>

      <!-- 页签内容 -->
      <div class="flex-1 overflow-auto p-5 min-h-0">
        <div v-if="loading && !data" class="text-fg-mute">加载中…</div>
        <template v-else-if="data">
          <!-- 图纸位置与外观 -->
          <div v-if="tab === 'drawing'" class="space-y-4">
            <div v-if="drawing" class="text-xs text-fg-mute">所在图纸：{{ drawing.name }}（流程画面 {{ drawing.screen }}）</div>
            <DrawingView v-if="drawing" :drawing="drawing" :highlight="data.highlight" @pick="pick" />
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

          <!-- 参数 -->
          <div v-else-if="tab === 'parameters'">
            <div class="text-xs text-fg-mute mb-2">{{ data.note }}</div>
            <table class="tbl">
              <thead><tr><th>参数</th><th>类型 / 单位</th><th>说明</th><th>数据关联（测点）</th><th>来源</th></tr></thead>
              <tbody>
                <tr v-for="a in data.items" :key="a.name" class="!cursor-default">
                  <td class="font-medium">{{ a.name }}</td>
                  <td class="text-fg-dim whitespace-nowrap">{{ a.valueType }}</td>
                  <td class="text-fg-dim">{{ a.description }}<div v-if="a.note" class="text-[11px] text-fg-mute">{{ a.note }}</div></td>
                  <td>
                    <span v-for="l in a.dataLinks" :key="l.tag" class="pill pill-plain mr-1 font-mono" :title="l.desc">{{ l.tag }}</span>
                    <span v-if="!a.dataLinks?.length" class="text-fg-mute text-xs">无测点（派生量或待补）</span>
                  </td>
                  <td class="text-[11px] text-fg-mute">{{ a.inheritedFrom ? `继承自 ${a.inheritedFrom}` : '' }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 仪表 -->
          <div v-else-if="tab === 'instruments'">
            <div class="flex items-center gap-2 mb-2">
              <input v-model="tagKw" class="inp w-60" placeholder="筛选位号 / 描述 / 设备 / 参数" />
              <span class="text-xs text-fg-mute">{{ tags.length }} / {{ data.total }} 个测点</span>
            </div>
            <table class="tbl">
              <thead><tr><th>位号</th><th>描述</th><th>设备</th><th>参数</th><th>类型</th><th>单位</th><th>块</th><th>站</th><th>限值</th></tr></thead>
              <tbody>
                <tr v-for="t in tags" :key="t.tag" class="!cursor-default">
                  <td class="font-mono text-brand">{{ t.tag }}</td><td>{{ t.description }}</td><td class="text-fg-dim">{{ t.equipment }}</td>
                  <td class="text-fg-dim">{{ t.parameter }}</td><td class="text-fg-dim whitespace-nowrap">{{ t.type }}</td><td>{{ t.unit }}</td>
                  <td class="text-fg-mute">{{ t.block }}</td><td class="text-fg-mute">{{ t.station }}</td><td class="font-mono text-xs">{{ t.limit ?? '' }}</td>
                </tr>
              </tbody>
            </table>
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
