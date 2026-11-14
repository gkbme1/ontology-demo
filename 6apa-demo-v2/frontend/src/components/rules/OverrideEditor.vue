<script setup lang="ts">
/**
 * 在设备上覆盖继承自设备组的现象（需求 SW-026 / 046）：只改各条件的阈值与持续时长，规则结构保持与设备组一致；
 * 保存后本台按覆盖后的规则判定，设备组上的定义不变，可随时「恢复继承」。
 */
import { ref } from 'vue'
import { api } from '@/api/client'
import Modal from '../Modal.vue'
import { LIMIT_TEXT, OP_TEXT, conditionText, subjectText } from './ruleText'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ objectId: string; objectName: string; phenomenon: Any }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()

const rule = ref<Any>(JSON.parse(JSON.stringify(props.phenomenon.override?.rule ?? props.phenomenon.rule)))
const note = ref(props.phenomenon.override?.note ?? '')
const error = ref('')
const leaves: Any[] = []
const template: Any[] = []
function walk(r: Any, out: Any[]): void {
  if (!r) return
  if (r.type === 'group') r.children.forEach((c: Any) => walk(c, out))
  else out.push(r)
}
walk(rule.value, leaves)
walk(props.phenomenon.templateRule ?? props.phenomenon.rule, template)

async function save(): Promise<void> {
  error.value = ''
  try {
    for (const c of leaves) {
      if (c.threshold?.kind === 'value') c.threshold.value = Number(c.threshold.value)
      c.durationSec = Math.max(0, Number(c.durationMin ?? (c.durationSec ?? 0) / 60) * 60)
      delete c.durationMin
    }
    await api.overridePhenomenon(props.objectId, props.phenomenon.id, { rule: rule.value, note: note.value })
    emit('saved')
  } catch (e) {
    error.value = String((e as Error).message)
  }
}
</script>

<template>
  <Modal :title="`在「${objectName}」上覆盖 · ${phenomenon.name}`" wide @close="emit('close')">
    <template #actions><button class="btn btn-primary" @click="save">保存覆盖</button></template>
    <div class="space-y-3 text-sm">
      <div class="text-xs text-fg-mute">
        现象定义在设备组「{{ phenomenon.anchor?.name }}」上，组内每台分别判定。这里只改本台的阈值与持续时长（规则结构不变）；
        设备组上的定义不受影响，可随时「恢复继承」。
      </div>
      <table class="tbl">
        <thead><tr><th>条件</th><th class="w-[300px]">阈值（本台）</th><th class="w-[120px]">持续（分钟）</th><th>设备组模板</th></tr></thead>
        <tbody>
          <tr v-for="(c, i) in leaves" :key="i" class="!cursor-default">
            <td>{{ subjectText(c.subject) }} <span class="text-fg-mute">{{ OP_TEXT[c.operator] }}</span></td>
            <td>
              <span v-if="c.operator === 'change'" class="text-fg-mute">由 {{ c.from }} 变为 {{ c.to }}（不可覆盖）</span>
              <div v-else class="flex items-center gap-1">
                <select v-model="c.threshold.kind" class="inp !w-24" @change="c.threshold.kind === 'value' && c.threshold.value === undefined && (c.threshold.value = 0)">
                  <option value="limit">工艺限值</option><option value="value">数值</option>
                </select>
                <template v-if="c.threshold.kind === 'limit'">
                  <span class="font-mono text-xs">{{ c.threshold.limitId }}</span>
                  <select v-model="c.threshold.field" class="inp !w-28"><option v-for="(t, k) in LIMIT_TEXT" :key="k" :value="k">{{ t }}</option></select>
                </template>
                <input v-else v-model="c.threshold.value" type="number" step="any" class="inp !w-28" />
              </div>
            </td>
            <td><input :value="(c.durationMin ?? (c.durationSec ?? 0) / 60)" type="number" min="0" step="any" class="inp !w-20" @input="c.durationMin = ($event.target as HTMLInputElement).value" /></td>
            <td class="text-xs text-fg-mute">{{ template[i] ? conditionText(template[i]) : '' }}</td>
          </tr>
        </tbody>
      </table>
      <label class="block text-xs text-fg-dim">覆盖原因 <input v-model="note" class="inp w-full mt-1" placeholder="如：C 罐 pH 电极偏差大，本台阈值放宽，待工艺确认" /></label>
      <div v-if="error" class="text-err text-xs">{{ error }}</div>
    </div>
  </Modal>
</template>
