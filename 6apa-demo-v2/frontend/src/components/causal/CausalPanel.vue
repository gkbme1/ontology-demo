<script setup lang="ts">
/**
 * 根因影响关系：一条记录 =「原因现象 导致 结果现象」，列表与关系图谱两种方式展示。
 * 选中某个结果现象（列表里点结果、图谱里点节点）弹窗查看它由什么导致。
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { bump } from '@/composables/useNav'
import CausalGraph from './CausalGraph.vue'
import CausePopup from './CausePopup.vue'
import LinkEditor from './LinkEditor.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ links: Any[]; graph: Any; opId?: string }>()
const emit = defineEmits<{ (e: 'changed'): void }>()

const view = ref<'list' | 'graph'>('list')
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
      <button class="ctl" :class="{ 'ctl-on': view === 'list' }" @click="view = 'list'">列表</button>
      <button class="ctl" :class="{ 'ctl-on': view === 'graph' }" @click="view = 'graph'">关系图谱</button>
      <template v-if="view === 'list'">
        <input v-model="kw" class="inp w-52 ml-2" placeholder="筛选原因 / 结果" />
        <label class="text-xs flex items-center gap-1 text-fg-dim"><input v-model="groupByEffect" type="checkbox" /> 按结果现象分组</label>
      </template>
      <span class="text-xs text-fg-mute">{{ links.length }} 条导致关系</span>
      <span class="flex-1" />
      <button class="btn btn-primary" @click="creating = true">+ 新增导致关系</button>
    </div>

    <CausalGraph v-if="view === 'graph'" :graph="graph" :height="460" @pick="(id: string) => (popup = id)" />

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
                <td class="w-[32%]"><span class="text-brand">{{ l.causeName }}</span><div class="text-[11px] text-fg-mute">{{ l.causeAnchor }}</div></td>
                <td class="text-fg-dim">{{ l.mechanism }}<div class="text-[11px] text-fg-mute">{{ l.basis }}</div></td>
                <td class="whitespace-nowrap"><span class="pill pill-plain">{{ l.confidence }}</span> <span class="pill" :class="l.status === '已确认' ? 'pill-ok' : 'pill-warn'">{{ l.status === '已确认' ? '已确认' : '草案' }}</span></td>
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
        <thead><tr><th>编号</th><th>原因现象</th><th></th><th>结果现象</th><th>机理 / 依据</th><th>置信度</th><th></th></tr></thead>
        <tbody>
          <tr v-for="l in rows" :key="l.id" @click="popup = l.effect">
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
