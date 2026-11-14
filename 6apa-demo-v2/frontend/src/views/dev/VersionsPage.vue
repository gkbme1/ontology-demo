<script setup lang="ts">
/** 类库版本（需求 SW-014，图 4-17）：版本列表、版本对比（新增 / 修改 / 删除）、基于已发布版本新建版本、导入类库包。升级影响分析（同步到工程态）不做。 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { act, canEdit, lib } from '@/composables/useClassLib'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const a = ref('')
const b = ref('current')
const diff = ref<Any>(null)
const versions = computed(() => lib.summary?.versions ?? [])
async function compare(): Promise<void> {
  if (!a.value) a.value = versions.value.find((v: Any) => v.status === '已发布')?.version ?? ''
  if (!a.value) return
  try { diff.value = await api.clDiff(a.value, b.value) } catch (e) { alert((e as Error).message) }
}
watch(() => lib.summary?.current?.version, () => { diff.value = null; compare() }, { immediate: true })
const lastPublished = computed(() => versions.value.find((v: Any) => v.status === '已发布')?.version)
async function newVersion(): Promise<void> {
  await act(() => api.clNewVersion(lastPublished.value), `已基于 ${lastPublished.value} 新建版本`)
}
async function importPkg(ev: Event): Promise<void> {
  const f = (ev.target as HTMLInputElement).files?.[0]
  if (!f) return
  const pkg = JSON.parse(await f.text())
  const merge = confirm(`导入类库包 ${pkg.version ?? ''}：同编码的对象\n「确定」= 覆盖（合并）；「取消」= 跳过`)
  const r = await act(() => api.clImport({ package: pkg, strategy: merge ? 'merge' : 'skip' }), '已导入类库包')
  if (r) alert(`新增 ${r.added}，合并 ${r.merged}，跳过 ${r.skipped}`)
  ;(ev.target as HTMLInputElement).value = ''
}
const PILL: Record<string, string> = { 新增: 'pill-ok', 修改: 'pill-info', 删除: 'pill-err' }
const ST: Record<string, string> = { 编辑中: 'pill-warn', 已发布: 'pill-ok', 已归档: 'pill-mute' }
</script>

<template>
  <div class="flex items-center gap-3 mb-3">
    <h2 class="text-[18px] font-semibold">类库版本</h2>
    <span class="text-xs text-fg-mute">已发布版本只读；修改须基于新版本进行</span>
    <span class="flex-1" />
    <label class="btn cursor-pointer" :class="{ 'opacity-40 pointer-events-none': !canEdit() }">导入类库包<input type="file" accept=".json" class="hidden" @change="importPkg" /></label>
    <button class="btn btn-primary" :disabled="lib.summary?.current?.status === '编辑中'" @click="newVersion">基于 {{ lastPublished ?? '—' }} 新建版本</button>
  </div>
  <div class="grid grid-cols-[340px_1fr] gap-4">
    <div class="card self-start">
      <div class="sec-title">版本列表</div>
      <table class="tbl"><thead><tr><th>版本</th><th>状态</th><th>说明</th></tr></thead><tbody>
        <tr v-for="v in versions" :key="v.version" :class="{ '!bg-brand/10': a === v.version }" @click="a = v.version; b = 'current'; compare()">
          <td class="font-medium">{{ v.version }}<div class="text-[11px] text-fg-mute font-normal">{{ v.publishedAt ? `${v.publishedAt} 发布` : `${v.createdAt} 起编辑` }}</div></td>
          <td><span class="pill" :class="ST[v.status]">{{ v.status }}</span></td><td class="text-xs text-fg-dim">{{ v.note || (v.base ? `基于 ${v.base}` : '') }}</td></tr>
      </tbody></table>
    </div>
    <div class="space-y-3">
      <div class="card">
        <div class="flex items-center gap-2 mb-2">
          <div class="sec-title !mb-0">版本对比</div>
          <select v-model="a" class="inp w-28"><option v-for="v in versions" :key="v.version" :value="v.version">{{ v.version }}</option></select>→
          <select v-model="b" class="inp w-40"><option value="current">当前（{{ lib.summary?.current?.version }}）</option><option v-for="v in versions" :key="v.version" :value="v.version">{{ v.version }}</option></select>
          <button class="btn" @click="compare">对比</button>
          <span v-if="diff" class="text-xs text-fg-mute">新增 {{ diff.counts['新增'] }} · 修改 {{ diff.counts['修改'] }} · 删除 {{ diff.counts['删除'] }}</span>
        </div>
        <div v-if="diff && !diff.rows.length" class="text-xs text-fg-mute">两个版本没有差异（在「编辑中」的版本里修改类库后再对比）</div>
        <table v-else-if="diff" class="tbl"><thead><tr><th class="w-16">变更</th><th class="w-28">对象类型</th><th>对象</th><th>内容</th></tr></thead><tbody>
          <tr v-for="(r, i) in diff.rows" :key="i" class="!cursor-default"><td><span class="pill" :class="PILL[r.change]">{{ r.change }}</span></td>
            <td class="text-xs">{{ r.type }}</td><td>{{ r.name }}</td><td class="text-xs text-fg-dim">{{ r.detail }}</td></tr>
        </tbody></table>
      </div>
      <div class="card text-xs text-fg-mute">
        <div class="sec-title">升级影响分析</div>
        类库发布新版本后分析对本体实例的影响（自动同步 / 冲突 / 需人工处理）——开发态修改触发工程态更新本 Demo 不做（已确认）。
      </div>
    </div>
  </div>
</template>
