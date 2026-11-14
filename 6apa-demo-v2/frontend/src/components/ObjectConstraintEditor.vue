<script setup lang="ts">
/** 工程态：在对象上新增 / 修改人工约束（需求 SW-043）：适用参数、工况、单位、六个限值、依据。新增的约束为「草案·待工艺确认」。 */
import { ref } from 'vue'
import { api } from '@/api/client'
import Modal from './Modal.vue'
import { LIMIT_TEXT } from './rules/ruleText'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ objectId: string; objectName: string; item?: Any; params?: string[] }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()

const it = props.item
const form = ref({
  appliesTo: it?.appliesTo ?? '',
  operatingMode: it?.operatingMode ?? '',
  unit: it?.unit ?? '',
  note: it?.note ?? '',
  values: { ...(it?.limitValues ?? {}) } as Record<string, Any>
})
const error = ref('')
async function save(): Promise<void> {
  error.value = ''
  const values: Record<string, Any> = {}
  for (const [k, v] of Object.entries(form.value.values)) if (v !== '' && v !== null && v !== undefined) values[k] = v
  const body = { ...form.value, values }
  try {
    if (it) await api.objEditUpdate(props.objectId, 'constraints', it.editKey, body)
    else await api.objEditAdd(props.objectId, 'constraints', body)
    emit('saved')
  } catch (e) {
    error.value = String((e as Error).message)
  }
}
</script>

<template>
  <Modal :title="it ? `修改约束 · ${it.id}（${objectName}）` : `在「${objectName}」上新增参数约束`" @close="emit('close')">
    <template #actions><button class="btn btn-primary" @click="save">保存</button></template>
    <div class="grid grid-cols-[96px_1fr_96px_1fr] gap-x-3 gap-y-2.5 items-center text-sm">
      <span class="text-xs text-fg-mute text-right">适用参数</span>
      <div><input v-model="form.appliesTo" class="inp w-full" list="cons-params" placeholder="选择或输入参数名" />
        <datalist id="cons-params"><option v-for="p in params ?? []" :key="p" :value="p" /></datalist></div>
      <span class="text-xs text-fg-mute text-right">单位</span>
      <input v-model="form.unit" class="inp" placeholder="如 ℃" />
      <span class="text-xs text-fg-mute text-right">适用工况</span>
      <input v-model="form.operatingMode" class="inp" placeholder="可选，如 反应期" />
      <span class="text-xs text-fg-mute text-right">依据</span>
      <input v-model="form.note" class="inp" placeholder="如：操作规程 3.2 节 / 工艺口头确认" />
    </div>
    <table class="tbl mt-3">
      <thead><tr><th v-for="(t, k) in LIMIT_TEXT" :key="k">{{ t }}</th></tr></thead>
      <tbody><tr class="!cursor-default">
        <td v-for="(t, k) in LIMIT_TEXT" :key="k"><input v-model="form.values[k]" type="number" step="any" class="inp !w-24" /></td>
      </tr></tbody>
    </table>
    <div class="text-[11px] text-fg-mute mt-2">可只填部分限值；要满足 低低 ≤ 低 ≤ 正常下 ≤ 正常上 ≤ 高 ≤ 高高。人工新增的约束状态为「草案·待工艺确认」。</div>
    <div v-if="error" class="text-err text-xs mt-2">{{ error }}</div>
  </Modal>
</template>
