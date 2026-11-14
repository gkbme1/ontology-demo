<script setup lang="ts">
/**
 * 一致性校验（需求 ONTO-SR-SW-059）：全量校验结果分 错误 / 警告 / 提示，按规则筛选，点一条跳到问题对象。
 * 错误阻止发布（发布功能后续实现）。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { staticBackend } from '@/api/static'
import { enterSegment, nav, openDrawing, openObject, select } from '@/composables/useNav'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const data = ref<Any>(null)
const loading = ref(false)
const error = ref('')
const level = ref('')
const rule = ref('')
const kw = ref('')

async function run(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.validation()
  } catch (e) {
    error.value = String((e as Error).message)
  } finally {
    loading.value = false
  }
}
watch(() => nav.version, run, { immediate: true })

const LEVEL_PILL: Record<string, string> = { 错误: 'pill-err', 警告: 'pill-warn', 提示: 'pill-plain' }
const items = computed(() => (data.value?.items ?? []).filter((i: Any) =>
  (!level.value || i.level === level.value) && (!rule.value || i.rule === rule.value) && (!kw.value || i.message.includes(kw.value))))
const rules = computed(() => Object.entries(data.value?.rules ?? {}) as [string, number][])

function go(i: Any): void {
  const t = i.target
  if (!t) return
  if (t.kind === 'object') { enterSegment(t.segmentId, { type: 'object', id: t.id, opId: t.opId, tab: t.tab }); openObject(t.id, t.opId, t.tab) }
  else if (t.kind === 'drawing') openDrawing(t.id, t.segmentId)
  else if (t.kind === 'global:calc') select({ type: 'global:calc' }, 'global:calc')
}
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-line bg-ink-panel shrink-0">
      <h2 class="text-[16px] font-semibold">一致性校验</h2>
      <span class="pill pill-info">全局 · 全量</span>
      <span v-if="data" class="text-xs text-fg-mute">校验时间 {{ data.checkedAt }}<template v-if="staticBackend">（单文件版为导出时的结果）</template></span>
      <span class="flex-1" />
      <button class="btn btn-primary" :disabled="loading" @click="run">{{ loading ? '校验中…' : '重新校验' }}</button>
    </div>
    <div class="flex-1 overflow-auto px-4 py-3 space-y-3 min-h-0">
      <div v-if="error" class="empty">{{ error }}</div>
      <div v-if="loading && !data" class="text-fg-mute">正在校验全部对象（首次约十几秒）…</div>
      <template v-if="data">
        <div class="grid grid-cols-4 gap-3">
          <div class="card cursor-pointer" :class="{ 'ring-2 ring-brand/40': level === '' }" @click="level = ''">
            <div class="text-xs text-fg-mute">发布前检查</div>
            <div class="text-[15px] font-semibold mt-1" :class="data.publishable ? 'text-ok' : 'text-err'">{{ data.publishable ? '无错误，可发布' : '有错误，不可发布' }}</div>
            <div class="text-[11px] text-fg-mute mt-1">现象 {{ data.scope.phenomena }} · 导致关系 {{ data.scope.links }} · 计算组态 {{ data.scope.calculations }} · 对象 {{ data.scope.objects }}</div>
          </div>
          <div v-for="lv in ['错误', '警告', '提示']" :key="lv" class="card cursor-pointer" :class="{ 'ring-2 ring-brand/40': level === lv }" @click="level = level === lv ? '' : lv">
            <div class="text-xs text-fg-mute">{{ lv }}</div>
            <div class="text-[22px] font-semibold tabular-nums" :class="lv === '错误' ? 'text-err' : lv === '警告' ? 'text-warn' : 'text-fg-dim'">{{ data.counts[lv] }}</div>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="text-xs text-fg-mute">规则</span>
          <button class="ctl" :class="{ 'ctl-on': !rule }" @click="rule = ''">全部</button>
          <button v-for="[r, n] in rules" :key="r" class="ctl" :class="{ 'ctl-on': rule === r }" @click="rule = rule === r ? '' : r">{{ r }} <span class="text-fg-mute">{{ n }}</span></button>
          <input v-model="kw" class="inp w-56 ml-2" placeholder="筛选说明文字" />
        </div>
        <table class="tbl">
          <thead><tr><th class="w-16">级别</th><th class="w-28">规则</th><th>说明</th><th class="w-44">问题对象</th></tr></thead>
          <tbody>
            <tr v-for="(i, k) in items" :key="k" :class="{ '!cursor-default': !i.target }" @click="go(i)">
              <td><span class="pill" :class="LEVEL_PILL[i.level]">{{ i.level }}</span></td>
              <td class="text-fg-dim">{{ i.rule }}</td>
              <td>{{ i.message }}</td>
              <td><span v-if="i.target" class="text-brand">{{ i.target.name }} ↗</span><span v-else class="text-fg-mute">—</span></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!items.length" class="empty">没有符合筛选的校验结果</div>
        <div class="text-[11px] text-fg-mute">{{ data.note }}</div>
      </template>
    </div>
  </div>
</template>
