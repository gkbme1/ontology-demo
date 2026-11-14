<script setup lang="ts">
/** 现象列表：判定规则、角色（原因 / 结果次数）、试算、编辑、删除、新增。 */
import StatusPill from '@/components/StatusPill.vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { bump } from '@/composables/useNav'
import Modal from '../Modal.vue'
import RuleView from '../rules/RuleView.vue'
import EvalResult from '../rules/EvalResult.vue'
import PhenomenonEditor from '../rules/PhenomenonEditor.vue'
import CausePopup from './CausePopup.vue'
import InheritBox from '../InheritBox.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{
  items: Any[]
  anchorOptions: { id: string; name: string; kind: string }[]
  opId?: string
  showInherit?: boolean
  focusId?: string
}>()
const emit = defineEmits<{ (e: 'changed'): void }>()

const kw = ref('')
const onlyRule = ref(false)
const editing = ref<Any | null>(null)
const creating = ref(false)
const popup = ref('')
const evalFor = ref<Any>(null)
const evalResult = ref<Any>(null)
const allPhen = ref<Any[]>([])
const calcNames = ref<Record<string, string>>({})

onMounted(async () => {
  const [p, c] = await Promise.all([api.phenomena({}), api.calculations()])
  allPhen.value = p.items
  calcNames.value = Object.fromEntries(c.items.map((x: Any) => [x.id, x.name]))
})

// 从参数约束跳过来时：高亮并滚动到该现象
const flash = ref('')
watch(() => [props.focusId, props.items], async () => {
  if (!props.focusId) return
  kw.value = ''
  onlyRule.value = false
  flash.value = props.focusId
  await nextTick()
  document.getElementById(`phen-row-${props.focusId}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}, { immediate: true })

const rows = computed(() => props.items.filter((p) =>
  (!kw.value || p.name.includes(kw.value) || (p.anchor?.name ?? '').includes(kw.value)) && (!onlyRule.value || p.hasRule)))

async function runEval(p: Any): Promise<void> {
  evalFor.value = p
  evalResult.value = null
  try {
    evalResult.value = await api.evaluate(p.id, { hours: 24, opId: props.opId })
  } catch (e) {
    evalResult.value = { error: String((e as Error).message) }
  }
}
async function remove(p: Any): Promise<void> {
  const n = p.roles.asCause + p.roles.asEffect
  if (!confirm(`删除现象「${p.name}」？${n ? `相关的 ${n} 条导致关系也会一并删除。` : ''}`)) return
  await api.deletePhenomenon(p.id)
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
      <input v-model="kw" class="inp w-56" placeholder="筛选现象 / 挂载对象" />
      <label class="text-xs flex items-center gap-1 text-fg-dim"><input v-model="onlyRule" type="checkbox" /> 只看已定义判定规则</label>
      <span class="text-xs text-fg-mute">{{ rows.length }} 个</span>
      <span class="flex-1" />
      <button class="btn btn-primary" :disabled="!anchorOptions.length" @click="creating = true">+ 新增现象</button>
    </div>
    <div v-if="!rows.length" class="empty">暂无现象定义</div>
    <table v-else class="tbl">
      <thead><tr><th v-if="showInherit" class="w-16 !text-center">来源</th><th>现象</th><th>挂载对象</th><th>判定规则</th><th>角色</th><th>状态</th><th></th></tr></thead>
      <tbody>
        <tr v-for="p in rows" :id="`phen-row-${p.id}`" :key="p.id" :class="{ '!bg-brand/15 outline outline-2 outline-brand/60': flash === p.id }" @click="popup = p.id">
          <td v-if="showInherit" @click.stop><InheritBox :checked="p.inherited" :from="p.inheritedFrom" /></td>
          <td class="min-w-[150px]">
            <div class="font-medium text-fg">{{ p.name }} <span v-if="p.category === '工况'" class="pill pill-info">工况</span></div>
            <div class="text-[11px] text-fg-mute">{{ p.id }} · {{ p.category }} · {{ p.severity }}</div>
          </td>
          <td class="text-fg-dim">
            {{ p.anchor?.name }}
          </td>
          <td class="max-w-[420px]"><RuleView :rule="p.rule" :calc-names="calcNames" /></td>
          <td class="whitespace-nowrap text-xs">
            <span class="pill pill-plain" title="作为原因">因 {{ p.roles.asCause }}</span>
            <span class="pill pill-plain ml-1" title="作为结果">果 {{ p.roles.asEffect }}</span>
          </td>
          <td><StatusPill :status="p.status" /></td>
          <td class="whitespace-nowrap" @click.stop>
            <button class="ctl" :disabled="!p.hasRule" :class="{ 'opacity-40': !p.hasRule }" @click="p.hasRule && runEval(p)">试算</button>
            <button class="ctl ml-1" @click="editing = p">编辑</button>
            <button class="ctl ml-1" @click="remove(p)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>

    <PhenomenonEditor v-if="creating" :anchor-options="anchorOptions" :op-id="opId" @close="creating = false" @saved="changed" />
    <PhenomenonEditor v-if="editing" :phenomenon="editing" :anchor-options="anchorOptions" :op-id="opId" @close="editing = null" @saved="changed" />
    <CausePopup v-if="popup" :phenomenon-id="popup" :phenomena="allPhen" :op-id="opId" @close="popup = ''; emit('changed')" />
    <Modal v-if="evalFor" :title="`试算 · ${evalFor.name}`" wide @close="evalFor = null">
      <div v-if="!evalResult" class="text-fg-mute">试算中…</div>
      <div v-else-if="evalResult.error" class="text-err">{{ evalResult.error }}</div>
      <EvalResult v-else :result="evalResult" />
    </Modal>
  </div>
</template>
