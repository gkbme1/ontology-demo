<script setup lang="ts">
/**
 * 工程态：在对象上新增 / 修改参数或属性（需求 SW-042）：名称、类别、类型 · 单位、值、说明、关联 DCS 位号。
 * 修改已有参数时只记改动（可撤销）；位号不在点表中时绑定状态为「失效」。
 */
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import Modal from './Modal.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ objectId: string; objectName: string; item?: Any; categories?: Record<string, string[]> }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()

const CATS = props.categories ?? { 属性: ['基本信息', '设计参数'], 参数: ['测量值', '设定值', '阀位', '控制指令', '状态', '计算值'] }
const it = props.item
const form = ref({
  name: it?.name ?? '',
  category: it?.category ?? '测量值',
  valueType: it?.valueType ?? '',
  value: it?.value ?? '',
  description: it?.description ?? '',
  tags: (it?.links ?? []).filter((l: Any) => l.own !== false).map((l: Any) => l.tag).join(', ')
})
const isAttr = computed(() => CATS['属性'].includes(form.value.category))
const error = ref('')
async function save(): Promise<void> {
  error.value = ''
  const f = form.value
  const body: Any = { name: f.name, category: f.category, valueType: f.valueType, description: f.description }
  if (isAttr.value) body.value = f.value === '' ? null : f.value
  else body.tags = f.tags
  try {
    if (it) await api.objEditUpdate(props.objectId, 'parameters', it.editKey ?? it.name, body)
    else await api.objEditAdd(props.objectId, 'parameters', body)
    emit('saved')
  } catch (e) {
    error.value = String((e as Error).message)
  }
}
</script>

<template>
  <Modal :title="it ? `修改参数 · ${it.name}（${objectName}）` : `在「${objectName}」上新增参数 / 属性`" @close="emit('close')">
    <template #actions><button class="btn btn-primary" @click="save">保存</button></template>
    <div class="grid grid-cols-[96px_1fr] gap-x-3 gap-y-2.5 items-center text-sm">
      <span class="text-xs text-fg-mute text-right">名称</span>
      <input v-model="form.name" class="inp" placeholder="如：夹套出口温度" />
      <span class="text-xs text-fg-mute text-right">类别</span>
      <select v-model="form.category" class="inp">
        <optgroup v-for="(list, g) in CATS" :key="g" :label="String(g)">
          <option v-for="c in list" :key="c" :value="c">{{ g }} · {{ c }}</option>
        </optgroup>
      </select>
      <span class="text-xs text-fg-mute text-right">类型 · 单位</span>
      <input v-model="form.valueType" class="inp" placeholder="如：float · ℃、文本、m³" />
      <template v-if="isAttr">
        <span class="text-xs text-fg-mute text-right">值</span>
        <input v-model="form.value" class="inp" placeholder="静态属性的值，如 S30408、12.5" />
      </template>
      <template v-else>
        <span class="text-xs text-fg-mute text-right">DCS 位号</span>
        <div>
          <input v-model="form.tags" class="inp w-full font-mono" placeholder="多个用逗号分隔，如 TI_1301C, TI_1301C2" />
          <div class="text-[11px] text-fg-mute mt-1">手动绑定后绑定状态为「已绑定（人工绑定）」；位号不在点表中显示「失效」。</div>
        </div>
      </template>
      <span class="text-xs text-fg-mute text-right">说明</span>
      <input v-model="form.description" class="inp" placeholder="可选" />
    </div>
    <div v-if="it && !it.userParam" class="text-[11px] text-fg-mute mt-3">修改的是本对象上的这一条{{ it.inherited ? `（继承自 ${it.inheritedFrom}，只改本对象）` : '' }}；可在列表里「撤销修改」恢复原值。</div>
    <div v-if="error" class="text-err text-xs mt-2">{{ error }}</div>
  </Modal>
</template>
