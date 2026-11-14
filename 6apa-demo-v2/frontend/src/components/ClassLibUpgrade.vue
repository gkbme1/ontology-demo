<script setup lang="ts">
/**
 * 工程态 · 类库版本：本工程使用的类库版本、可升级版本、升级影响分析（需求图 4-17）。
 * 类库发布只是升版，不会自动更新工程；工程在这里手动切换。本 Demo「确认切换」只做二次提示，不改工程数据。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { classlibState, loadBinding } from '@/composables/useClassLibBinding'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const b = computed(() => classlibState.binding)
const targets = computed<Any[]>(() => (b.value?.published ?? []).filter((v: Any) => v.version !== b.value?.bound?.version).reverse())
const to = ref('')
const impact = ref<Any>(null)
const err = ref('')
const msg = ref('')
const choice = ref<Record<string, string>>({})
const loading = ref(false)

loadBinding()
watch(targets, (t) => { if (!to.value || !t.some((v: Any) => v.version === to.value)) to.value = b.value?.newer?.slice(-1)[0]?.version ?? t[0]?.version ?? '' }, { immediate: true })
watch(to, async (v) => {
  impact.value = null
  err.value = ''
  msg.value = ''
  choice.value = {}
  if (!v) return
  loading.value = true
  try {
    impact.value = await api.clUpgradeImpact(v)
    for (const g of ['conflict', 'manual']) for (const r of impact.value.groups[g]) choice.value[`${r.type}|${r.id}`] = r.options[0]
  } catch (e) { err.value = String((e as Error).message) } finally { loading.value = false }
}, { immediate: true })

const GROUPS: [string, string, string][] = [
  ['auto', '可自动同步', 'pill-ok'], ['conflict', '冲突', 'pill-warn'], ['manual', '需人工处理', 'pill-err']
]
const PILL: Record<string, string> = { 新增: 'pill-ok', 修改: 'pill-info', 删除: 'pill-err' }
const isNewer = computed(() => (b.value?.newer ?? []).some((v: Any) => v.version === to.value))

function confirmSwitch(): void {
  const i = impact.value
  if (!i) return
  const verb = isNewer.value ? '升级' : '切换'
  const ok = window.confirm(
    `确认将「${i.project}」使用的类库从 ${i.from} ${verb}到 ${i.to}？\n\n` +
    `· 可自动同步 ${i.counts.auto} 项\n· 冲突 ${i.counts.conflict} 项（按所选方式处理）\n· 需人工处理 ${i.counts.manual} 项\n` +
    `· 涉及设备组 ${i.affectedGroups} 个\n\n切换后的改动进入工程态草案，在「版本发布」中发布后才生效。`)
  if (!ok) return
  window.alert(`演示：本 Demo 不实际执行切换，工程仍使用类库 ${i.from}，工程数据未改动。`)
  msg.value = `已确认${verb}到 ${i.to}（演示，未实际执行，工程仍使用 ${i.from}）`
}
</script>

<template>
  <div class="space-y-3">
    <div class="card">
      <div class="sec-title">本工程使用的类库</div>
      <div v-if="!b" class="text-fg-mute text-xs">加载中…</div>
      <div v-else class="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <div><span class="text-fg-mute">工程</span> <b>{{ b.project }}</b></div>
        <div><span class="text-fg-mute">类库</span> {{ b.library }}</div>
        <div><span class="text-fg-mute">当前版本</span> <span class="pill pill-info">{{ b.bound.version }}</span>
          <span class="text-xs text-fg-mute"> · {{ b.bound.publishedAt }} 发布 · {{ b.bound.note }}</span></div>
        <div v-if="b.newer.length"><span class="pill pill-warn">有新版本 {{ b.newer.map((v: Any) => v.version).join('、') }} 可升级</span></div>
        <div v-else class="text-xs text-fg-mute">已是开发态最新的已发布版本<span v-if="b.editing">（{{ b.editing.version }} 仍在开发态编辑中，发布后可在这里升级）</span></div>
      </div>
      <div class="text-[11px] text-fg-mute mt-2 leading-5">
        类库发布只是升版，不会自动更新工程。工程需要新版本时在这里切换：先看升级影响 → 处理冲突与人工项 → 确认切换（改动进入工程态草案）→ 在「版本发布」中发布后生效。
        <b>本 Demo 确认切换后不改动工程数据。</b>
      </div>
    </div>

    <div class="card space-y-3">
      <div class="flex flex-wrap items-center gap-2">
        <div class="sec-title !mb-0">切换类库版本</div>
        <span class="pill pill-info">{{ b?.bound?.version }}</span><span>→</span>
        <select v-model="to" class="ctl" :disabled="!targets.length">
          <option v-for="v in targets" :key="v.version" :value="v.version">{{ v.version }} · {{ v.publishedAt }} 发布{{ v.note ? ' · ' + v.note : '' }}</option>
        </select>
        <span v-if="!targets.length" class="text-xs text-fg-mute">开发态还没有其他已发布版本（在开发态「发布类库」后这里可选）</span>
        <span class="flex-1" />
        <button class="btn btn-primary" :disabled="!impact" @click="confirmSwitch">确认切换到 {{ to || '—' }}</button>
      </div>
      <div v-if="msg" class="text-ok text-xs">{{ msg }}</div>
      <div v-if="err" class="text-err text-xs">{{ err }}</div>
      <div v-if="loading" class="text-xs text-fg-mute">正在分析升级影响…</div>
      <template v-if="impact">
        <div class="flex flex-wrap items-center gap-2 text-xs">
          <span class="text-fg-mute">升级影响分析（{{ impact.from }} → {{ impact.to }}）：</span>
          <span v-for="[k, l, c] in GROUPS" :key="k" class="pill" :class="c">{{ l }} {{ impact.counts[k] }}</span>
          <span class="text-fg-mute">· 涉及设备组 {{ impact.affectedGroups }} 个 · 差异：新增 {{ impact.diffCounts['新增'] }} / 修改 {{ impact.diffCounts['修改'] }} / 删除 {{ impact.diffCounts['删除'] }}</span>
        </div>
        <div v-if="!impact.counts.auto && !impact.counts.conflict && !impact.counts.manual" class="empty">两个版本没有差异，切换不影响工程。</div>
        <template v-for="[k, l, c] in GROUPS" :key="k">
          <div v-if="impact.groups[k].length">
            <div class="flex items-center gap-2 mb-1"><span class="pill" :class="c">{{ l }}</span><span class="text-xs text-fg-mute">{{ impact.groups[k].length }} 项</span></div>
            <table class="tbl">
              <thead><tr><th class="w-14">变更</th><th class="w-28">对象类型</th><th>对象</th><th>内容</th><th class="w-56">影响实例</th><th class="w-60">{{ k === 'auto' ? '说明' : '处理方式' }}</th></tr></thead>
              <tbody>
                <tr v-for="r in impact.groups[k]" :key="r.type + r.id" class="!cursor-default">
                  <td><span class="pill" :class="PILL[r.change]">{{ r.change }}</span></td>
                  <td class="text-xs">{{ r.type }}</td>
                  <td>{{ r.name }}</td>
                  <td class="text-xs text-fg-dim">{{ r.detail || '—' }}</td>
                  <td class="text-xs">
                    <template v-if="r.instanceCount">
                      <span v-for="i in r.instances" :key="i.id" class="pill pill-plain mr-1 mb-0.5">{{ i.name }}</span>
                      <div class="text-fg-mute">{{ r.instanceCount }} 个设备组 · {{ r.memberCount }} 台设备</div>
                    </template>
                    <span v-else class="text-fg-mute">{{ r.className ? '无实例' : '全局' }}</span>
                  </td>
                  <td class="text-xs">
                    <select v-if="r.options.length" v-model="choice[`${r.type}|${r.id}`]" class="ctl !py-0.5 mb-1">
                      <option v-for="o in r.options" :key="o" :value="o">{{ o }}</option>
                    </select>
                    <div class="text-fg-mute">{{ r.reason }}</div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>
