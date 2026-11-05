<script setup lang="ts">
/** 新增 / 编辑一条根因影响关系：原因现象 → 结果现象。 */
import { computed, reactive, ref } from 'vue'
import { api } from '@/api/client'
import { nav } from '@/composables/useNav'
import Modal from '../Modal.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ link?: Any; phenomena: Any[]; presetEffect?: string; presetCause?: string }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved', l: Any): void }>()

const form = reactive<Any>({
  cause: props.link?.cause ?? props.presetCause ?? '',
  effect: props.link?.effect ?? props.presetEffect ?? '',
  mechanism: props.link?.mechanism ?? '',
  basis: props.link?.basis ?? '',
  confidence: props.link?.confidence ?? '中',
  status: props.link?.status ?? '草案·待工艺确认'
})
const kw = ref('')
const error = ref('')
const options = computed(() =>
  props.phenomena.filter((p) => !kw.value || p.name.includes(kw.value) || (p.anchor?.name ?? '').includes(kw.value))
)
function label(p: Any): string {
  return `${p.name} · ${p.anchor?.name ?? ''}${p.rule ? '' : '（规则待定义）'}`
}

async function save(): Promise<void> {
  error.value = ''
  try {
    const saved = props.link ? await api.updateLink(props.link.id, form) : await api.createLink(form)
    emit('saved', saved)
  } catch (e) {
    error.value = String((e as Error).message)
  }
}
</script>

<template>
  <Modal :title="link ? `编辑导致关系 · ${link.id}` : '新增导致关系'" @close="emit('close')">
    <template #actions><button class="btn btn-primary" @click="save">保存</button></template>
    <div class="space-y-3 text-xs">
      <input v-model="kw" class="inp w-full" placeholder="按现象名称或挂载对象筛选下拉选项" />
      <div class="grid grid-cols-[1fr_auto_1fr] gap-2 items-center">
        <select v-model="form.cause" class="inp" size="8">
          <option v-for="p in options" :key="p.id" :value="p.id">{{ label(p) }}</option>
        </select>
        <div class="text-brand text-center font-semibold">导致 →</div>
        <select v-model="form.effect" class="inp" size="8">
          <option v-for="p in options" :key="p.id" :value="p.id">{{ label(p) }}</option>
        </select>
      </div>
      <div class="text-fg-mute">左：原因现象；右：结果现象。一个现象可以同时是别的关系里的原因和结果。</div>
      <div class="grid grid-cols-[80px_1fr] gap-2 items-center">
        <label class="text-fg-mute">机理说明</label><textarea v-model="form.mechanism" rows="2" class="inp" />
        <label class="text-fg-mute">依据</label><input v-model="form.basis" class="inp" placeholder="规程 / 规则编号、调研记录等" />
        <label class="text-fg-mute">置信度</label>
        <select v-model="form.confidence" class="inp w-28"><option v-for="c in nav.meta?.confidence ?? []" :key="c">{{ c }}</option></select>
        <label class="text-fg-mute">状态</label>
        <select v-model="form.status" class="inp w-44"><option v-for="s in nav.meta?.statuses ?? []" :key="s">{{ s }}</option></select>
      </div>
      <div v-if="error" class="text-err">{{ error }}</div>
    </div>
  </Modal>
</template>
