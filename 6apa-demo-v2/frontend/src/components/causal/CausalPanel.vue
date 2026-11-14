<script setup lang="ts">
/**
 * 根因影响关系：一条记录 =「原因现象 导致 结果现象」，列表与关系图谱两种方式展示。
 * 选中某个结果现象（列表里点结果、图谱里点节点）弹窗查看它由什么导致。
 */
import StatusPill from '@/components/StatusPill.vue'
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { bump } from '@/composables/useNav'
import CausalGraph from './CausalGraph.vue'
import CausePopup from './CausePopup.vue'
import LinkEditor from './LinkEditor.vue'
import InheritBox from '../InheritBox.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ links: Any[]; graph: Any; opId?: string; showInherit?: boolean }>()
const emit = defineEmits<{ (e: 'changed'): void }>()

const view = ref<'blocks' | 'graph' | 'list'>('blocks')
const kw = ref('')
const popup = ref('')
const editing = ref<Any | null>(null)
const creating = ref(false)
const allPhen = ref<Any[]>([])
const groupByEffect = ref(true)

onMounted(async () => {
  allPhen.value = (await api.phenomena({})).items
})

const rows = computed(() => props.links.filter((l) => !kw.value || l.causeName.includes(kw.value) || l.effectName.includes(kw.value)))
const grouped = computed(() => {
  const m: Record<string, Any[]> = {}
  for (const l of rows.value) (m[l.effect] ??= []).push(l)
  return Object.entries(m).map(([effect, ls]) => ({ effect, name: ls[0].effectName, anchor: ls[0].effectAnchor, links: ls }))
    .sort((a, b) => b.links.length - a.links.length)
})

// 全局图谱默认不画孤立现象（如未被导致关系引用的工况现象）
const showIsolated = ref(false)
const linkedIds = computed(() => new Set((props.graph?.links ?? []).flatMap((l: Any) => [l.cause, l.effect])))
const isolatedCount = computed(() => (props.graph?.nodes ?? []).filter((n: Any) => !linkedIds.value.has(n.id)).length)
const globalGraph = computed(() => showIsolated.value || !props.graph ? props.graph
  : { ...props.graph, nodes: props.graph.nodes.filter((n: Any) => linkedIds.value.has(n.id)) })

// 某个结果现象的子图：结果 + 直接原因
const nodeById = computed<Record<string, Any>>(() => Object.fromEntries((props.graph?.nodes ?? []).map((n: Any) => [n.id, n])))
function subGraph(g: Any): Any {
  const ids = new Set<string>([g.effect, ...g.links.map((l: Any) => l.cause)])
  return { nodes: [...ids].map((id) => nodeById.value[id]).filter(Boolean).map((n: Any) => ({ ...n, focus: n.id === g.effect })),
           links: g.links }
}

async function remove(l: Any): Promise<void> {
  if (!confirm(`删除「${l.causeName} → ${l.effectName}」？`)) return
  await api.deleteLink(l.id)
  changed()
}
function changed(): void {
  editing.value = null
  creating.value = false
  bump()
  emit('changed')
}
</script>

<template>
  <div class="space-y-2">
    <div class="flex items-center gap-2">
      <button class="ctl" :class="{ 'ctl-on': view === 'blocks' }" @click="view = 'blocks'">分组图谱</button>
      <button class="ctl" :class="{ 'ctl-on': view === 'graph' }" @click="view = 'graph'">全局图谱</button>
      <button class="ctl" :class="{ 'ctl-on': view === 'list' }" @click="view = 'list'">列表</button>
      <template v-if="view !== 'graph'">
        <input v-model="kw" class="inp w-52 ml-2" placeholder="筛选原因 / 结果" />
        <label v-if="view === 'list'" class="text-xs flex items-center gap-1 text-fg-dim"><input v-model="groupByEffect" type="checkbox" /> 按结果现象分组</label>
      </template>
      <label v-if="view === 'graph'" class="text-xs flex items-center gap-1 text-fg-dim ml-2">
        <input v-model="showIsolated" type="checkbox" /> 显示没有导致关系的现象（{{ isolatedCount }}）
      </label>
      <span class="text-xs text-fg-mute">{{ links.length }} 条导致关系</span>
      <span class="flex-1" />
      <button class="btn btn-primary" @click="creating = true">+ 新增导致关系</button>
    </div>

    <CausalGraph v-if="view === 'graph'" :graph="globalGraph" height="calc(100vh - 290px)" @pick="(id: string) => (popup = id)" />

    <!-- 分组图谱：一个结果现象一块，左侧是导致它的现象 -->
    <template v-else-if="view === 'blocks'">
      <div class="flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-fg-mute">
        <span>每块 = 一个结果现象及导致它的现象（左 → 右）· 虚线框 = 判定规则待定义 · 虚线边 = 低置信度 · 单击节点查看导致链</span>
      </div>
      <div v-if="!grouped.length" class="empty">暂无根因影响关系</div>
      <div class="grid gap-3" style="grid-template-columns: repeat(auto-fill, minmax(560px, 1fr))">
        <div v-for="g in grouped" :key="g.effect" class="card !p-0 overflow-hidden">
          <div class="flex items-center gap-2 px-3 py-2 bg-ink-panel2 border-b border-line-soft">
            <button class="font-medium text-fg hover:text-brand truncate" @click="popup = g.effect">{{ g.name }}</button>
            <span class="text-[11px] text-fg-mute truncate">{{ g.anchor }}</span>
            <span class="flex-1" />
            <span v-if="showInherit && g.links.every((l: Any) => l.inherited)" class="pill pill-plain" title="这组导致关系继承自设备组">继承</span>
            <span class="text-[11px] text-fg-mute whitespace-nowrap">由 {{ g.links.length }} 个现象导致</span>
            <button class="ctl" @click="popup = g.effect">导致链</button>
          </div>
          <div class="px-2 py-2 bg-[#fbfcfe]">
            <CausalGraph :graph="subGraph(g)" compact @pick="(id: string) => (popup = id)" />
          </div>
        </div>
      </div>
    </template>

    <template v-else>
      <div v-if="!rows.length" class="empty">暂无根因影响关系</div>
      <template v-else-if="groupByEffect">
        <div v-for="g in grouped" :key="g.effect" class="card !p-0 overflow-hidden">
          <div class="flex items-center gap-2 px-3 py-2 bg-ink-panel2 border-b border-line-soft">
            <button class="font-medium text-fg hover:text-brand" @click="popup = g.effect">{{ g.name }}</button>
            <span class="text-[11px] text-fg-mute">{{ g.anchor }}</span>
            <span class="flex-1" />
            <span class="text-[11px] text-fg-mute">由 {{ g.links.length }} 个现象导致</span>
            <button class="ctl" @click="popup = g.effect">查看导致链</button>
          </div>
          <table class="tbl">
            <tbody>
              <tr v-for="l in g.links" :key="l.id" @click="popup = l.cause">
                <td v-if="showInherit" class="w-12" @click.stop><InheritBox :checked="l.inherited" :from="l.inheritedFrom" /></td>
                <td class="w-[32%]"><span class="text-brand">{{ l.causeName }}</span><div class="text-[11px] text-fg-mute">{{ l.causeAnchor }}</div></td>
                <td class="text-fg-dim">{{ l.mechanism }}<div class="text-[11px] text-fg-mute">{{ l.basis }}</div></td>
                <td class="whitespace-nowrap"><span class="pill pill-plain">{{ l.confidence }}</span> <StatusPill :status="l.status" /> <span v-if="l.inCycle" class="pill pill-err" title="这条关系处在因果环路上">环路</span></td>
                <td class="whitespace-nowrap" @click.stop>
                  <button class="ctl" @click="editing = l">编辑</button>
                  <button class="ctl ml-1" @click="remove(l)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <table v-else class="tbl">
        <thead><tr><th v-if="showInherit" class="w-16 !text-center">来源</th><th>编号</th><th>原因现象</th><th></th><th>结果现象</th><th>机理 / 依据</th><th>置信度</th><th></th></tr></thead>
        <tbody>
          <tr v-for="l in rows" :key="l.id" @click="popup = l.effect">
            <td v-if="showInherit" @click.stop><InheritBox :checked="l.inherited" :from="l.inheritedFrom" /></td>
            <td class="font-mono text-[11px] text-fg-mute">{{ l.id }}</td>
            <td>{{ l.causeName }}<div class="text-[11px] text-fg-mute">{{ l.causeAnchor }}</div></td>
            <td class="text-brand">导致</td>
            <td>{{ l.effectName }}<div class="text-[11px] text-fg-mute">{{ l.effectAnchor }}</div></td>
            <td class="text-fg-dim">{{ l.mechanism }}<div class="text-[11px] text-fg-mute">{{ l.basis }}</div></td>
            <td>{{ l.confidence }}</td>
            <td class="whitespace-nowrap" @click.stop>
              <button class="ctl" @click="editing = l">编辑</button>
              <button class="ctl ml-1" @click="remove(l)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <LinkEditor v-if="creating" :phenomena="allPhen" @close="creating = false" @saved="changed" />
    <LinkEditor v-if="editing" :link="editing" :phenomena="allPhen" @close="editing = null" @saved="changed" />
    <CausePopup v-if="popup" :phenomenon-id="popup" :phenomena="allPhen" :op-id="opId" @close="popup = ''; emit('changed')" />
  </div>
</template>
