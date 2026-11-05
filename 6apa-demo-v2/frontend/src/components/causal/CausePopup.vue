<script setup lang="ts">
/**
 * 现象详情弹窗：它由什么现象导致（逐层往上追溯），以及它会导致什么。
 * 图谱 + 按层列出的导致关系；可在这里直接给它补一条原因。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { bump } from '@/composables/useNav'
import Modal from '../Modal.vue'
import RuleView from '../rules/RuleView.vue'
import EvalResult from '../rules/EvalResult.vue'
import CausalGraph from './CausalGraph.vue'
import LinkEditor from './LinkEditor.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ phenomenonId: string; phenomena: Any[]; opId?: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const current = ref(props.phenomenonId)
const history = ref<string[]>([])
const detail = ref<Any>(null)
const chain = ref<Any>(null)
const direction = ref<'up' | 'down'>('up')
const evalResult = ref<Any>(null)
const evaluating = ref(false)
const adding = ref(false)
const calcNames = ref<Record<string, string>>({})

async function load(): Promise<void> {
  evalResult.value = null
  const [d, c] = await Promise.all([api.phenomenon(current.value), api.chain(current.value, direction.value)])
  detail.value = d
  chain.value = c
}
onMounted(async () => {
  const cs = await api.calculations()
  calcNames.value = Object.fromEntries(cs.items.map((c: Any) => [c.id, c.name]))
  await load()
})
watch([current, direction], load)

const byLevel = computed(() => {
  if (!chain.value) return []
  const levels: Record<number, Any[]> = {}
  for (const l of chain.value.links) {
    const far = direction.value === 'up' ? l.cause : l.effect
    const lv = chain.value.levels[far] ?? 1
    ;(levels[lv] ??= []).push(l)
  }
  return Object.entries(levels).sort((a, b) => Number(a[0]) - Number(b[0]))
    .map(([lv, links]) => ({ level: Number(lv), links: chain.value.graph.links.filter((g: Any) => links.some((x) => x.id === g.id)) }))
})

function go(id: string): void {
  if (id === current.value) return
  history.value.push(current.value)
  current.value = id
}
function back(): void {
  const prev = history.value.pop()
  if (prev) current.value = prev
}
async function evaluate(): Promise<void> {
  evaluating.value = true
  try { evalResult.value = await api.evaluate(current.value, { hours: 24, opId: props.opId }) } finally { evaluating.value = false }
}
async function onAdded(): Promise<void> {
  adding.value = false
  bump()
  await load()
}
</script>

<template>
  <Modal :title="detail ? `${detail.name}` : '现象'" wide @close="emit('close')">
    <template #actions>
      <button v-if="history.length" class="btn" @click="back">← 上一个</button>
      <button class="btn" :disabled="!detail?.hasRule || evaluating" @click="evaluate">{{ evaluating ? '试算中…' : '试算（模拟数据）' }}</button>
    </template>
    <div v-if="detail" class="space-y-4">
      <div class="grid grid-cols-[1fr_1fr] gap-4">
        <dl class="kv">
          <dt>编号</dt><dd class="font-mono">{{ detail.id }}</dd>
          <dt>挂载对象</dt><dd>{{ detail.anchor?.name }}<span class="text-fg-mute">（{{ detail.anchor?.kind === 'group' ? '设备组，组内每台分别判定' : '设备' }}）</span></dd>
          <dt>类别 / 严重</dt><dd>{{ detail.category }} · {{ detail.severity }}</dd>
          <dt>状态</dt><dd><span class="pill pill-warn">{{ detail.status }}</span></dd>
          <dt>来源</dt><dd>{{ detail.source?.kind }} {{ detail.source?.ref }}</dd>
          <dt>角色</dt><dd>作为原因 {{ detail.roles.asCause }} 次 · 作为结果 {{ detail.roles.asEffect }} 次</dd>
        </dl>
        <div>
          <div class="sec-title">判定规则</div>
          <RuleView :rule="detail.rule" :calc-names="calcNames" />
          <div v-if="detail.description" class="text-xs text-fg-dim mt-2">{{ detail.description }}</div>
          <div v-if="detail.note" class="text-xs text-warn mt-1">{{ detail.note }}</div>
        </div>
      </div>

      <div v-if="evalResult"><EvalResult :result="evalResult" /></div>

      <div class="flex items-center gap-2">
        <button class="ctl" :class="{ 'ctl-on': direction === 'up' }" @click="direction = 'up'">由什么导致（{{ detail.causes.length }} 条直接原因）</button>
        <button class="ctl" :class="{ 'ctl-on': direction === 'down' }" @click="direction = 'down'">会导致什么（{{ detail.effects.length }}）</button>
        <span class="flex-1" />
        <button class="btn" @click="adding = true">+ 补一条{{ direction === 'up' ? '原因' : '结果' }}</button>
      </div>
      <CausalGraph v-if="chain" :graph="chain.graph" :height="320" @pick="go" />
      <div v-if="chain && !chain.links.length" class="empty">{{ direction === 'up' ? '还没有登记导致它的现象' : '还没有登记它会导致的现象' }}</div>
      <div v-for="g in byLevel" :key="g.level">
        <div class="sec-title">{{ direction === 'up' ? `第 ${g.level} 层原因` : `第 ${g.level} 层结果` }}</div>
        <table class="tbl">
          <tbody>
            <tr v-for="l in g.links" :key="l.id" @click="go(direction === 'up' ? l.cause : l.effect)">
              <td class="w-[30%]"><span class="text-brand">{{ l.causeName }}</span><div class="text-[11px] text-fg-mute">{{ l.causeAnchor }}</div></td>
              <td class="w-6 text-fg-mute">→</td>
              <td class="w-[26%]">{{ l.effectName }}</td>
              <td class="text-fg-dim">{{ l.mechanism }}<div class="text-[11px] text-fg-mute">{{ l.basis }}</div></td>
              <td class="whitespace-nowrap"><span class="pill pill-plain">置信度 {{ l.confidence }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <LinkEditor
      v-if="adding"
      :phenomena="phenomena"
      :preset-effect="direction === 'up' ? current : undefined"
      :preset-cause="direction === 'down' ? current : undefined"
      @close="adding = false"
      @saved="onAdded"
    />
  </Modal>
</template>
