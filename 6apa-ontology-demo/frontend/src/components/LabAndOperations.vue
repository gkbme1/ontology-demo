<script setup lang="ts">
/**
 * 「批次」页签下半部分：化验结果（LIMS + 人工录入）与操作记录（DCS 操作日志）。
 * 人工录入经本体校验化验项目后写入 LIMS（化验员只录一遍，调查与台账共用）。
 */
import { reactive, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { LabResultsPayload, OperationsPayload } from '@/api/types'

const props = defineProps<{ objectId: string; days: number }>()

const labs = ref<LabResultsPayload | null>(null)
const ops = ref<OperationsPayload | null>(null)
const labError = ref<string | null>(null)
const opsError = ref<string | null>(null)
const entryOpen = ref(false)
const saving = ref(false)
const saveMsg = ref<string | null>(null)
const saveError = ref<string | null>(null)

function nowText() {
  return new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 16).replace('T', ' ')
}
const form = reactive({ itemCode: 'PH', value: '', sampleTime: nowText(), enteredBy: '', note: '' })

async function load() {
  const end = Date.now()
  const q = { startTime: end - props.days * 86_400_000, endTime: end }
  labError.value = opsError.value = null
  try {
    labs.value = await api.labResults(props.objectId, q)
  } catch (e) {
    labs.value = null
    labError.value = (e as Error).message
  }
  try {
    ops.value = await api.operations(props.objectId, q)
  } catch (e) {
    ops.value = null
    opsError.value = (e as Error).message
  }
}
watch(() => [props.objectId, props.days], load, { immediate: true })

async function submit() {
  saving.value = true
  saveError.value = saveMsg.value = null
  try {
    const res = await api.submitLabResult(props.objectId, {
      itemCode: form.itemCode, value: Number(form.value), sampleTime: form.sampleTime.trim() || undefined,
      enteredBy: form.enteredBy.trim(), note: form.note.trim()
    })
    saveMsg.value = `已录入 ${res.created.sampleNo}（批次 ${res.created.batchNo ?? '—'}）。${res.note}`
    form.value = ''
    entryOpen.value = false
    await load()
  } catch (e) {
    saveError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

function fmt(ms: number) {
  const d = new Date(ms + 8 * 3600_000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`
}
</script>

<template>
  <div class="grid gap-4 xl:grid-cols-2">
    <!-- 化验 -->
    <div class="min-w-0">
      <div class="flex flex-wrap items-center gap-2 mb-1">
        <span class="text-fg font-semibold">化验结果</span>
        <span v-if="labs" class="text-fg-mute text-[11px]">{{ labs.total }} 条 · 来源 {{ labs.dataSource.sourceTypeLabel }}</span>
        <span v-if="labs?.dataSource.simulated" class="pill pill-warn !text-[10px]">模拟</span>
        <button class="ctl !py-0.5 !px-2 ml-auto" @click="entryOpen = !entryOpen">{{ entryOpen ? '收起' : '人工录入' }}</button>
      </div>
      <div v-if="entryOpen" class="mb-2 grid gap-2 sm:grid-cols-2 rounded border border-line-soft bg-ink-panel2/50 p-2 text-[11.5px]">
        <label class="flex items-center gap-1.5">项目
          <select v-model="form.itemCode" class="ctl !py-0.5">
            <option v-for="i in labs?.labItems ?? []" :key="i.code" :value="i.code">{{ i.name }}（{{ i.code }}）</option>
          </select>
        </label>
        <label class="flex items-center gap-1.5">结果 <input v-model="form.value" class="ctl !py-0.5 w-24 font-mono" /></label>
        <label class="flex items-center gap-1.5">取样时间 <input v-model="form.sampleTime" class="ctl !py-0.5 flex-1 font-mono" /></label>
        <label class="flex items-center gap-1.5">录入人 <input v-model="form.enteredBy" class="ctl !py-0.5 flex-1" /></label>
        <label class="flex items-center gap-1.5 sm:col-span-2">备注 <input v-model="form.note" class="ctl !py-0.5 flex-1" /></label>
        <div class="sm:col-span-2 flex items-center gap-2">
          <button class="ctl !py-0.5 !px-3 border-brand text-fg" :disabled="saving" @click="submit">{{ saving ? '提交中…' : '提交' }}</button>
          <span class="text-fg-mute">按取样时间对应到批次与阶段；化验员只录一遍，调查与台账共用。</span>
        </div>
        <div v-if="saveError" class="sm:col-span-2 text-err">{{ saveError }}</div>
      </div>
      <div v-if="saveMsg" class="text-ok text-[11.5px] mb-1">{{ saveMsg }}</div>
      <div v-if="labError" class="empty text-err">{{ labError }}</div>
      <div v-else-if="!labs?.items.length" class="empty">查询范围内没有化验结果</div>
      <div v-else class="max-h-[320px] overflow-y-auto">
        <table class="tbl !text-[11.5px]">
          <thead><tr><th>取样</th><th>批次</th><th>项目</th><th>结果</th><th>阶段</th><th>来源</th></tr></thead>
          <tbody>
            <tr v-for="r in [...labs.items].reverse()" :key="r.sampleNo">
              <td class="font-mono whitespace-nowrap">{{ fmt(r.sampleTime) }}</td>
              <td class="font-mono text-equip whitespace-nowrap">{{ r.batchNo ?? '—' }}</td>
              <td class="whitespace-nowrap">{{ r.itemName }}<span v-if="r.property" class="text-fg-mute"> → {{ r.property }}</span></td>
              <td class="font-mono">{{ r.value }} {{ r.unitOfMeasure }}</td>
              <td class="text-fg-dim">{{ r.stage }}</td>
              <td class="text-fg-dim">{{ r.source }}<template v-if="r.enteredBy">（{{ r.enteredBy }}）</template></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 操作记录 -->
    <div class="min-w-0">
      <div class="flex flex-wrap items-center gap-2 mb-1">
        <span class="text-fg font-semibold">操作记录</span>
        <span v-if="ops" class="text-fg-mute text-[11px]">{{ ops.total }} 条 · 来源 {{ ops.dataSource.sourceTypeLabel }}</span>
        <span v-if="ops?.dataSource.simulated" class="pill pill-warn !text-[10px]">模拟</span>
      </div>
      <div v-if="opsError" class="empty text-err">{{ opsError }}</div>
      <div v-else-if="!ops?.items.length" class="empty">查询范围内没有操作记录</div>
      <div v-else class="max-h-[320px] overflow-y-auto">
        <table class="tbl !text-[11.5px]">
          <thead><tr><th>时间</th><th>批次</th><th>操作</th><th>旧 → 新</th><th>班次</th><th>操作站</th></tr></thead>
          <tbody>
            <tr v-for="o in [...ops.items].reverse()" :key="o.time + o.tag + o.newValue">
              <td class="font-mono whitespace-nowrap">{{ fmt(o.time) }}</td>
              <td class="font-mono text-equip whitespace-nowrap">{{ o.batchNo ?? '—' }}</td>
              <td>
                <span class="pill !text-[10px]" :class="o.kind === '设定值修改' ? 'pill-warn' : 'pill-plain'">{{ o.kind }}</span>
                {{ o.param }} <span class="font-mono text-fg-mute">{{ o.tag }}</span>
                <span v-if="o.properties.length" class="text-fg-mute"> → {{ o.properties.join('、') }}</span>
              </td>
              <td class="font-mono whitespace-nowrap">{{ o.oldValue }} → {{ o.newValue }}</td>
              <td class="text-fg-dim whitespace-nowrap">{{ o.shift?.split(' ').slice(1).join(' ') ?? '—' }}</td>
              <td class="text-fg-dim">{{ o.station }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
