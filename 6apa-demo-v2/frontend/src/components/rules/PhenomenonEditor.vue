<script setup lang="ts">
/** 新增 / 编辑现象：基本信息 + 挂载对象 + 判定规则（条件树）+ 保存前试算。 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '@/api/client'
import { nav } from '@/composables/useNav'
import Modal from '../Modal.vue'
import RuleEditor from './RuleEditor.vue'
import EvalResult from './EvalResult.vue'
import { newGroup } from './ruleText'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

const props = defineProps<{
  phenomenon?: Any // 编辑时传入
  anchorOptions: { id: string; name: string; kind: string }[]
  opId?: string
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved', p: Any): void }>()

const p = props.phenomenon
const form = reactive<Any>({
  name: p?.name ?? '',
  category: p?.category ?? '工艺',
  severity: p?.severity ?? '警告',
  status: p?.status ?? '草案·待工艺确认',
  description: p?.description ?? '',
  note: p?.note ?? '',
  anchorId: p?.anchor?.id ?? props.anchorOptions[0]?.id ?? '',
  hasRule: p ? !!p.rule : true,
  rule: p?.rule ? JSON.parse(JSON.stringify(p.rule)) : newGroup('AND')
})
// 条件挂在根上时包一层组，编辑器总以组为根
if (form.rule.type !== 'group') form.rule = { type: 'group', op: 'AND', children: [form.rule] }

const params = ref<Any[]>([])
const limits = ref<Any[]>([])
const calcs = ref<Any[]>([])
const error = ref('')
const saving = ref(false)
const evalResult = ref<Any>(null)
const evaluating = ref(false)

const anchors = computed(() => {
  const list = [...props.anchorOptions]
  if (p?.anchor && !list.some((a) => a.id === p.anchor.id)) list.unshift(p.anchor)
  return list
})
const anchor = computed(() => anchors.value.find((a) => a.id === form.anchorId))

async function loadParams(): Promise<void> {
  if (!form.anchorId) return
  params.value = (await api.objectParameters(form.anchorId)).items
}
onMounted(async () => {
  const [l, c] = await Promise.all([api.limits(), api.calculations()])
  limits.value = l.items
  calcs.value = c.items
  await loadParams()
})
watch(() => form.anchorId, loadParams)

function body(): Any {
  return {
    name: form.name, category: form.category, severity: form.severity, status: form.status,
    description: form.description, note: form.note,
    anchor: anchor.value ? { kind: anchor.value.kind, id: anchor.value.id, name: anchor.value.name } : null,
    rule: form.hasRule ? simplify(form.rule) : null
  }
}
// 只有一个条件的根组存成条件本身
function simplify(rule: Any): Any {
  return rule.type === 'group' && rule.children.length === 1 && rule.children[0].type === 'condition' ? rule.children[0] : rule
}

async function tryRun(): Promise<void> {
  error.value = ''
  evaluating.value = true
  try {
    evalResult.value = await api.evaluateRule({ anchorId: form.anchorId, rule: simplify(form.rule), hours: 24, opId: props.opId })
  } catch (e) {
    error.value = String((e as Error).message)
  } finally {
    evaluating.value = false
  }
}

async function save(): Promise<void> {
  error.value = ''
  saving.value = true
  try {
    const saved = p ? await api.updatePhenomenon(p.id, body()) : await api.createPhenomenon(body())
    emit('saved', saved)
  } catch (e) {
    error.value = String((e as Error).message)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Modal :title="p ? `编辑现象 · ${p.id}` : '新增现象'" wide @close="emit('close')">
    <template #actions>
      <button class="btn" :disabled="evaluating || !form.hasRule" @click="tryRun">{{ evaluating ? '试算中…' : '试算（模拟数据）' }}</button>
      <button class="btn btn-primary" :disabled="saving" @click="save">保存</button>
    </template>
    <datalist id="v2-param-list">
      <option v-for="x in params" :key="x.name" :value="x.name">{{ x.kind }} · {{ x.tags.join(' ') || '无测点' }}</option>
    </datalist>
    <div class="grid grid-cols-[90px_1fr_90px_1fr] gap-x-3 gap-y-2 items-center text-xs">
      <label class="text-fg-mute">现象名称</label>
      <input v-model="form.name" class="inp" placeholder="如 水解罐pH偏高" />
      <label class="text-fg-mute">挂载对象</label>
      <select v-model="form.anchorId" class="inp">
        <option v-for="a in anchors" :key="a.id" :value="a.id">{{ a.kind === 'group' ? '［设备组］' : '' }}{{ a.name }}</option>
      </select>
      <label class="text-fg-mute">类别</label>
      <select v-model="form.category" class="inp">
        <option v-for="c in nav.meta?.phenomenonCategories ?? []" :key="c">{{ c }}</option>
      </select>
      <label class="text-fg-mute">严重程度</label>
      <select v-model="form.severity" class="inp">
        <option>提示</option><option>警告</option><option>严重</option>
      </select>
      <label class="text-fg-mute">状态</label>
      <select v-model="form.status" class="inp">
        <option v-for="s in nav.meta?.statuses ?? []" :key="s">{{ s }}</option>
      </select>
      <span />
      <span class="text-fg-mute">设备组上的现象对组内每台设备分别判定</span>
      <label class="text-fg-mute">描述</label>
      <textarea v-model="form.description" rows="2" class="inp col-span-3" />
      <label class="text-fg-mute">备注</label>
      <input v-model="form.note" class="inp col-span-3" placeholder="如：阈值为占位值，待现场提供" />
    </div>

    <div class="mt-4">
      <div class="flex items-center gap-3 mb-2">
        <div class="sec-title !mb-0">判定规则</div>
        <label class="text-xs flex items-center gap-1"><input v-model="form.hasRule" type="checkbox" /> 已定义判定规则</label>
        <span class="text-[11px] text-fg-mute">条件可按「与 / 或」任意嵌套；「本对象属性」按挂载对象（设备组时为组内每台）落到测点</span>
      </div>
      <RuleEditor v-if="form.hasRule" :rule="form.rule" :params="params" :limits="limits" :calcs="calcs" />
      <div v-else class="empty">未定义判定规则的现象只能作为根因关系里的节点，不能试算</div>
    </div>

    <div v-if="error" class="mt-3 text-err text-xs">{{ error }}</div>
    <div v-if="evalResult" class="mt-4">
      <div class="sec-title">试算结果</div>
      <EvalResult :result="evalResult" />
    </div>
  </Modal>
</template>
