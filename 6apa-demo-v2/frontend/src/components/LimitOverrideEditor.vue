<script setup lang="ts">
/** 在设备上覆盖继承来的工艺限值（需求 SW-045）：显示设备组（模板）值以便对比，空着的字段沿用模板。 */
import { ref } from 'vue'
import { api } from '@/api/client'
import Modal from './Modal.vue'
import { LIMIT_TEXT } from './rules/ruleText'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ objectId: string; objectName: string; limit: Any }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()
const values = ref<Record<string, Any>>({ ...(props.limit.override?.values ?? {}) })
const note = ref(props.limit.override?.note ?? '')
const error = ref('')
async function save(): Promise<void> {
  error.value = ''
  try {
    await api.overrideLimit(props.objectId, props.limit.id, { values: values.value, note: note.value })
    emit('saved')
  } catch (e) {
    error.value = String((e as Error).message)
  }
}
</script>

<template>
  <Modal :title="`在「${objectName}」上${limit.inherited ? '覆盖' : '修改'}限值 · ${limit.id} ${limit.appliesTo}`" @close="emit('close')">
    <template #actions><button class="btn btn-primary" @click="save">保存{{ limit.inherited ? '覆盖' : '修改' }}</button></template>
    <div class="space-y-3 text-sm">
      <div class="text-xs text-fg-mute">{{ limit.inherited ? '限值继承自设备组；只填需要改的字段，空着的沿用设备组的值。本台的判定规则引用该限值时按覆盖值判定。'
        : '修改本对象的限值：只填需要改的字段，空着的沿用原值；判定规则引用该限值时按修改后的值，可「撤销」恢复原值。' }}</div>
      <table class="tbl">
        <thead><tr><th>字段</th><th>{{ limit.inherited ? '设备组（模板）' : '原值' }}</th><th>{{ limit.inherited ? '本台覆盖值' : '修改为' }}（{{ limit.unit }}）</th></tr></thead>
        <tbody>
          <tr v-for="(t, k) in LIMIT_TEXT" :key="k" class="!cursor-default">
            <td>{{ t }}</td>
            <td class="font-mono">{{ limit.limitValues?.[k] ?? '—' }}</td>
            <td><input v-model="values[k]" type="number" step="any" class="inp !w-32" :placeholder="String(limit.limitValues?.[k] ?? '')" /></td>
          </tr>
        </tbody>
      </table>
      <label class="block text-xs text-fg-dim">{{ limit.inherited ? '覆盖原因' : '修改原因' }} <input v-model="note" class="inp w-full mt-1" placeholder="如：该罐容积不同，液位高限按现场" /></label>
      <div v-if="error" class="text-err text-xs">{{ error }}</div>
    </div>
  </Modal>
</template>
