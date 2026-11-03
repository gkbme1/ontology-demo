<script setup lang="ts">
/**
 * 一条工艺限值的版本：V0（6APA_工艺限值.xlsx）+ 后续版本（6APA_限值版本.xlsx）。
 * 在线修改 = 追加一个版本（POST /process-limits/{id}/versions），必须写修改人与原因，旧版本保留；
 * Agent 判断历史数据时按当时生效的版本。
 */
import { computed, reactive, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { LimitVersion, LimitVersionInput, LimitVersionsPayload } from '@/api/types'

const props = defineProps<{ limitId: string; unitName?: string | null }>()
const emit = defineEmits<{ changed: [] }>()

const data = ref<LimitVersionsPayload | null>(null)
const error = ref<string | null>(null)
const editing = ref(false)
const saving = ref(false)
const saveError = ref<string | null>(null)
const saved = ref<string | null>(null)

function nowText() {
  const d = new Date(Date.now() + 8 * 3600_000)
  return d.toISOString().slice(0, 19).replace('T', ' ')
}

const form = reactive({
  sourceType: '人工设定',
  normalLow: '', normalHigh: '', low: '', high: '', lowLow: '', highHigh: '',
  optimum: '', delta: '',
  onlyThisUnit: false, enzymeMin: '', enzymeMax: '',
  effectiveFrom: nowText(), editor: '', reason: ''
})

async function load() {
  error.value = null
  try {
    data.value = await api.limitVersions(props.limitId)
  } catch (e) {
    error.value = (e as Error).message
  }
}
watch(() => props.limitId, load, { immediate: true })

function startEdit() {
  const base = data.value?.items[data.value.items.length - 1]
  form.normalLow = base?.normalLow?.toString() ?? ''
  form.normalHigh = base?.normalHigh?.toString() ?? ''
  form.low = form.high = form.lowLow = form.highHigh = ''
  form.effectiveFrom = nowText()
  saveError.value = null
  saved.value = null
  editing.value = true
}

function num(v: string): number | null {
  const t = v.trim()
  return t === '' ? null : Number(t)
}

async function submit() {
  saving.value = true
  saveError.value = null
  const body: LimitVersionInput = {
    editor: form.editor.trim(), reason: form.reason.trim(), sourceType: form.sourceType,
    effectiveFrom: form.effectiveFrom.trim(),
    enzymeMin: num(form.enzymeMin), enzymeMax: num(form.enzymeMax),
    unit: form.onlyThisUnit && props.unitName ? props.unitName : ''
  }
  if (form.sourceType === '模型最优值±差值') {
    body.optimum = num(form.optimum)
    body.delta = num(form.delta)
  } else {
    Object.assign(body, {
      normalLow: num(form.normalLow), normalHigh: num(form.normalHigh), low: num(form.low), high: num(form.high),
      lowLow: num(form.lowLow), highHigh: num(form.highHigh)
    })
  }
  try {
    const res = await api.addLimitVersion(props.limitId, body)
    saved.value = `已追加 ${res.created.id}。${res.note}`
    editing.value = false
    await load()
    emit('changed')
  } catch (e) {
    saveError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

function band(v: LimitVersion, lo: 'normalLow' | 'low' | 'lowLow', hi: 'normalHigh' | 'high' | 'highHigh') {
  if (v[lo] === null && v[hi] === null) return '—'
  return `${v[lo] ?? ''}~${v[hi] ?? ''}`
}
const rows = computed(() => [...(data.value?.items ?? [])].reverse())
</script>

<template>
  <div class="mt-1.5 rounded border border-line-soft bg-ink-panel2/50 p-2 text-[11.5px]">
    <div v-if="error" class="text-err">{{ error }}</div>
    <template v-else-if="data">
      <div class="overflow-x-auto"><table class="tbl !text-[11.5px]">
        <thead>
          <tr><th>版本</th><th>适用条件</th><th>正常</th><th>L~H</th><th>LL~HH</th><th>来源</th><th>生效</th><th>修改人 / 原因</th></tr>
        </thead>
        <tbody>
          <tr v-for="v in rows" :key="v.id">
            <td class="font-mono whitespace-nowrap" :class="v.base ? 'text-fg-mute' : 'text-brand'">{{ v.id }}</td>
            <td class="whitespace-nowrap">{{ v.conditionText }}</td>
            <td class="font-mono whitespace-nowrap">{{ band(v, 'normalLow', 'normalHigh') }}<span v-if="v.optimum !== null" class="text-fg-mute"> ({{ v.optimum }}±{{ v.delta }})</span></td>
            <td class="font-mono whitespace-nowrap text-fg-dim">{{ band(v, 'low', 'high') }}</td>
            <td class="font-mono whitespace-nowrap text-fg-dim">{{ band(v, 'lowLow', 'highHigh') }}</td>
            <td class="whitespace-nowrap">{{ v.sourceType }}</td>
            <td class="whitespace-nowrap text-fg-dim">{{ v.effectiveFromText ?? '自始' }}<template v-if="v.effectiveToText"> ~ {{ v.effectiveToText }}</template></td>
            <td class="text-fg-dim">{{ v.editor ? v.editor + '：' : '' }}{{ v.reason }} <span class="pill pill-plain !text-[10px]">{{ v.status }}</span></td>
          </tr>
        </tbody>
      </table></div>
      <div class="text-fg-mute mt-1">{{ data.matchRule }}</div>
      <div v-if="saved" class="text-ok mt-1">{{ saved }}</div>

      <div v-if="!editing" class="mt-1.5"><button class="ctl !py-0.5 !px-2" @click="startEdit">修改限值（追加版本）</button></div>
      <div v-else class="mt-2 grid gap-2 sm:grid-cols-2">
        <label class="flex items-center gap-1.5">来源
          <select v-model="form.sourceType" class="ctl !py-0.5">
            <option>人工设定</option><option>模型最优值±差值</option><option>规程</option>
          </select>
        </label>
        <label class="flex items-center gap-1.5">生效时间 <input v-model="form.effectiveFrom" class="ctl !py-0.5 flex-1 font-mono" /></label>
        <template v-if="form.sourceType === '模型最优值±差值'">
          <label class="flex items-center gap-1.5">最优值 <input v-model="form.optimum" class="ctl !py-0.5 w-20 font-mono" /></label>
          <label class="flex items-center gap-1.5">差值 ± <input v-model="form.delta" class="ctl !py-0.5 w-20 font-mono" /></label>
        </template>
        <template v-else>
          <label class="flex items-center gap-1.5">正常区间 <input v-model="form.normalLow" class="ctl !py-0.5 w-16 font-mono" /> ~ <input v-model="form.normalHigh" class="ctl !py-0.5 w-16 font-mono" /></label>
          <label class="flex items-center gap-1.5">L / H <input v-model="form.low" placeholder="沿用" class="ctl !py-0.5 w-16 font-mono" /> / <input v-model="form.high" placeholder="沿用" class="ctl !py-0.5 w-16 font-mono" /></label>
          <label class="flex items-center gap-1.5">LL / HH <input v-model="form.lowLow" placeholder="沿用" class="ctl !py-0.5 w-16 font-mono" /> / <input v-model="form.highHigh" placeholder="沿用" class="ctl !py-0.5 w-16 font-mono" /></label>
        </template>
        <label class="flex items-center gap-1.5">换酶后批次 <input v-model="form.enzymeMin" placeholder="不限" class="ctl !py-0.5 w-16 font-mono" /> ~ <input v-model="form.enzymeMax" placeholder="不限" class="ctl !py-0.5 w-16 font-mono" /></label>
        <label v-if="unitName" class="flex items-center gap-1.5"><input v-model="form.onlyThisUnit" type="checkbox" /> 只适用于 {{ unitName }}</label>
        <label class="flex items-center gap-1.5">修改人 <input v-model="form.editor" class="ctl !py-0.5 flex-1" /></label>
        <label class="flex items-center gap-1.5 sm:col-span-2">修改原因 <input v-model="form.reason" class="ctl !py-0.5 flex-1" /></label>
        <div class="sm:col-span-2 flex items-center gap-2">
          <button class="ctl !py-0.5 !px-3 border-brand text-fg" :disabled="saving" @click="submit">{{ saving ? '提交中…' : '提交' }}</button>
          <button class="ctl !py-0.5 !px-3" @click="editing = false">取消</button>
          <span class="text-fg-mute">留空的档位沿用基础版本；旧版本不会被改动。</span>
        </div>
        <div v-if="saveError" class="sm:col-span-2 text-err">{{ saveError }}</div>
      </div>
    </template>
    <div v-else class="text-fg-mute">加载中…</div>
  </div>
</template>
