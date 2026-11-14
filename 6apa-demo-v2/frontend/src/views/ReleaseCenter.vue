<script setup lang="ts">
/**
 * 发布与导出（需求 SW-060 发布、SW-061 对比与回滚、SW-067 Excel 导出、SW-069 TTL 导出、SW-079 操作留痕）。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { staticBackend } from '@/api/static'
import { bump, nav, select } from '@/composables/useNav'
import { classlibState } from '@/composables/useClassLibBinding'
import ClassLibUpgrade from '@/components/ClassLibUpgrade.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const tab = ref<'publish' | 'compare' | 'export' | 'audit' | 'know' | 'classlib'>('publish')
watch(() => classlibState.openTab, (t) => { if (t) { tab.value = t as 'classlib'; classlibState.openTab = '' } }, { immediate: true })
const rel = ref<Any>({ items: [], current: null })
const preview = ref<Any>(null)
const check = ref<Any>(null)
const note = ref('')
const busy = ref(false)
const msg = ref('')
const err = ref('')

// 知识沉淀审核（需求 SW-075：运行态提交的知识进入工程态候选审核队列）
const know = ref<Any>(null)
const comments = ref<Record<string, string>>({})
async function loadKnow(): Promise<void> { try { know.value = await api.knowledge() } catch { know.value = null } }
async function review(k: Any, decision: string): Promise<void> {
  err.value = ''; msg.value = ''
  try {
    const r = await api.reviewKnowledge(k.id, { decision, comment: comments.value[k.id] ?? '' })
    msg.value = `${k.id} ${r.status}${r.review?.result ? '：' + r.review.result : ''}`
    bump()
  } catch (e) { err.value = String((e as Error).message) }
}
async function load(): Promise<void> {
  loadKnow()
  rel.value = await api.releases()
  if (staticBackend) return
  preview.value = (await api.releasePreview()).stats
}
watch(() => nav.version, load, { immediate: true })
async function runCheck(): Promise<void> { check.value = null; check.value = await api.validation() }
watch(tab, (t) => { if (t === 'publish' && !check.value && !staticBackend) runCheck(); if (t === 'audit') loadAudit() }, { immediate: true })

async function publish(): Promise<void> {
  err.value = ''; msg.value = ''; busy.value = true
  try {
    const r = await api.publishRelease({ note: note.value })
    msg.value = `已发布 ${r.version}`
    note.value = ''
    bump()
  } catch (e) { err.value = String((e as Error).message) } finally { busy.value = false }
}
async function rollback(v: Any): Promise<void> {
  const sync = confirm(`把 ${v.version} 重新发布为当前版本（生成新版本号）。\n\n同时把工程态的编辑数据也回退到 ${v.version} 吗？\n「确定」= 同步回退；「取消」= 只回滚发布版本，工程态编辑数据保持不变。`)
  busy.value = true
  try {
    const r = await api.rollbackRelease(v.version, { syncDraft: sync })
    msg.value = `已回滚：${r.version}（来自 ${v.version}${sync ? '，工程态已同步回退' : ''}）`
    bump()
  } catch (e) { err.value = String((e as Error).message) } finally { busy.value = false }
}

// 对比
const cmpA = ref('')
const cmpB = ref('current')
const cmp = ref<Any>(null)
const openRow = ref<Record<string, boolean>>({})
const versionOptions = computed(() => [{ v: 'current', label: '工程态当前（未发布）' }, ...rel.value.items.map((x: Any) => ({ v: x.version, label: `${x.version} · ${x.time}` }))])
async function compare(a?: string, b?: string): Promise<void> {
  if (a) cmpA.value = a
  if (b) cmpB.value = b
  tab.value = 'compare'
  if (!cmpA.value) cmpA.value = rel.value.items[0]?.version ?? ''
  if (!cmpA.value) return
  cmp.value = null
  try { cmp.value = await api.compareReleases(cmpA.value, cmpB.value) } catch (e) { err.value = String((e as Error).message) }
}

// 导出
const space = ref<Any>(null)
const seg = ref('')
const exportInfo = ref<Any>(null)
api.navSpace().then((r) => (space.value = r))
const segments = computed(() => (space.value?.items?.[0]?.children ?? []).filter((c: Any) => c.kind === 'segment'))
async function download(kind: 'excel' | 'ttl'): Promise<void> {
  err.value = ''; busy.value = true
  try {
    const r = await api.download(`/export/${kind}`, { seg: seg.value || undefined })
    exportInfo.value = { kind, ...r.info, file: r.filename }
    bump()
  } catch (e) { err.value = String((e as Error).message) } finally { busy.value = false }
}

// 操作日志
const audit = ref<Any>(null)
const auditOp = ref('')
const auditKw = ref('')
async function loadAudit(): Promise<void> { audit.value = await api.audit({ op: auditOp.value, keyword: auditKw.value }) }
watch([auditOp, auditKw], loadAudit)
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-line bg-ink-panel shrink-0">
      <h2 class="text-[16px] font-semibold">发布与导出</h2>
      <span class="pill pill-info">当前发布版本：{{ rel.current ? `${rel.current.version} · ${rel.current.time}` : '未发布' }}</span>
      <span class="flex-1" />
      <button v-for="[k, l] in [['publish', '版本发布'], ['compare', '版本对比'], ['know', `知识审核${know?.pending ? ' ' + know.pending : ''}`], ['classlib', '类库版本'], ['export', '导出'], ['audit', '操作日志']]" :key="k"
              class="asset-tab !py-0.5" :class="{ 'asset-tab-on': tab === k }" @click="tab = k as Any">{{ l }}</button>
    </div>
    <div class="flex-1 overflow-auto px-4 py-3 space-y-3 min-h-0 text-sm">
      <ClassLibUpgrade v-if="tab === 'classlib'" />
      <div v-if="staticBackend && tab !== 'classlib'" class="empty">单文件版只能查看已导出的版本信息；发布、回滚、导出请在完整版中操作。</div>
      <div v-if="msg" class="text-ok text-xs">{{ msg }}</div>
      <div v-if="err" class="text-err text-xs">{{ err }}</div>

      <!-- 版本发布 -->
      <template v-if="tab === 'publish'">
        <div v-if="!staticBackend" class="grid grid-cols-[1fr_1fr] gap-3">
          <div class="card">
            <div class="sec-title">发布前检查</div>
            <div v-if="!check" class="text-fg-mute text-xs">正在全量校验…</div>
            <template v-else>
              <div class="text-[15px] font-semibold" :class="check.publishable ? 'text-ok' : 'text-err'">
                {{ check.publishable ? '可以发布' : `有 ${check.blocking} 个阻止发布的错误` }}
              </div>
              <div class="text-xs text-fg-dim mt-1">错误 {{ check.counts['错误'] }}（其中草案上 {{ check.counts['错误'] - check.blocking }} 个，不阻止发布）· 警告 {{ check.counts['警告'] }} · 提示 {{ check.counts['提示'] }}</div>
              <button class="ctl mt-2" @click="select({ type: 'global:check' }, 'global:check')">查看校验明细 ↗</button>
            </template>
          </div>
          <div class="card">
            <div class="sec-title">本次发布内容（只有「生效」的现象、导致关系、计算组态进入发布版本）</div>
            <table v-if="preview" class="w-full text-xs">
              <tr v-for="(s, k) in preview" :key="k" class="border-b border-line-soft"><td class="py-1">{{ s.label }}</td>
                <td class="py-1 tabular-nums">{{ ['phenomena', 'links', 'calculations'].includes(String(k)) ? `生效 ${s.published} / 共 ${s.total}` : `${s.total} 条` }}</td></tr>
            </table>
            <div class="text-[11px] text-fg-mute mt-1">草案可在「工况与根因」等列表中勾选后批量设为生效。</div>
          </div>
        </div>
        <div v-if="!staticBackend" class="flex items-center gap-2">
          <input v-model="note" class="inp flex-1" placeholder="发布说明（如：水解工段现象与根因工艺确认后首次发布）" />
          <button class="btn btn-primary" :disabled="busy || !check?.publishable" @click="publish">发布新版本</button>
        </div>
        <table class="tbl">
          <thead><tr><th class="w-16">版本</th><th class="w-40">发布时间</th><th class="w-20">发布人</th><th>发布说明</th><th>发布内容（生效 / 总数）</th><th class="w-48"></th></tr></thead>
          <tbody>
            <tr v-for="(v, i) in rel.items" :key="v.version" class="!cursor-default">
              <td class="font-mono font-medium">{{ v.version }}<span v-if="i === 0" class="pill pill-ok ml-1">当前</span></td>
              <td class="text-xs tabular-nums">{{ v.time }}</td><td class="text-xs">{{ v.user }}</td>
              <td>{{ v.note }}<div v-if="v.rollbackOf" class="text-[11px] text-warn">回滚自 {{ v.rollbackOf }}</div></td>
              <td class="text-xs text-fg-dim">现象 {{ v.stats.phenomena.published }}/{{ v.stats.phenomena.total }} · 导致关系 {{ v.stats.links.published }}/{{ v.stats.links.total }} · 计算组态 {{ v.stats.calculations.published }}/{{ v.stats.calculations.total }}</td>
              <td class="whitespace-nowrap">
                <button v-if="v.previous" class="ctl" @click="compare(v.previous, v.version)">对比上一版</button>
                <button class="ctl ml-1" @click="compare(v.version, 'current')">对比工程态</button>
                <button v-if="i > 0 && !staticBackend" class="ctl ml-1" :disabled="busy" @click="rollback(v)">回滚</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!rel.items.length" class="empty">还没有发布过版本</div>
      </template>

      <!-- 知识审核 -->
      <template v-if="tab === 'know'">
        <div class="text-xs text-fg-mute">运行态提交的知识沉淀（智能体 / 业务应用）。采纳后：新的根因关系 → 新增导致关系（草案）；置信度修正 → 修改该关系置信度；其他类型记录采纳，由工程人员按建议修改。经发布后生效。</div>
        <table class="tbl"><thead><tr><th class="w-20">编号</th><th class="w-28">类型</th><th>建议内容</th><th class="w-32">提交方</th><th class="w-24">状态</th><th class="w-[300px]">审核</th></tr></thead><tbody>
          <tr v-for="k in know?.items ?? []" :key="k.id" class="!cursor-default"><td class="font-mono text-xs">{{ k.id }}</td><td class="text-xs">{{ k.type }}</td>
            <td>{{ k.content }}<div v-if="k.basis" class="text-[11px] text-fg-mute">依据：{{ k.basis }}</div></td>
            <td class="text-xs">{{ k.submitter }}<div class="text-fg-mute">{{ k.submittedAt }}</div></td>
            <td><span class="pill" :class="k.status === '已采纳' ? 'pill-ok' : k.status === '已驳回' ? 'pill-mute' : 'pill-warn'">{{ k.status }}</span></td>
            <td>
              <template v-if="k.status === '待审核' && !staticBackend">
                <input v-model="comments[k.id]" class="inp w-full mb-1" placeholder="审核意见" />
                <button class="ctl" @click="review(k, '采纳')">采纳</button><button class="ctl ml-1" @click="review(k, '驳回')">驳回</button>
              </template>
              <div v-else class="text-xs text-fg-dim">{{ k.review?.reviewer }} {{ k.review?.at }}<div>{{ k.review?.comment }}</div><div>{{ k.review?.result }}</div></div>
            </td></tr>
        </tbody></table>
        <div v-if="!(know?.items ?? []).length" class="empty">审核队列为空（在「运行态 · 知识沉淀提交」模拟提交）</div>
      </template>

      <!-- 版本对比 -->
      <template v-else-if="tab === 'compare'">
        <div class="flex items-center gap-2">
          <span class="text-xs text-fg-mute">从</span>
          <select v-model="cmpA" class="inp w-64"><option v-for="o in versionOptions.slice(1)" :key="o.v" :value="o.v">{{ o.label }}</option></select>
          <span class="text-xs text-fg-mute">到</span>
          <select v-model="cmpB" class="inp w-64"><option v-for="o in versionOptions" :key="o.v" :value="o.v">{{ o.label }}</option></select>
          <button class="btn btn-primary" :disabled="!rel.items.length || !!staticBackend" @click="compare()">对比</button>
        </div>
        <div v-if="!rel.items.length" class="empty">还没有发布过版本</div>
        <template v-if="cmp">
          <div class="text-xs text-fg-dim">{{ cmp.from }} → {{ cmp.to === 'current' ? '工程态当前' : cmp.to }}：共 {{ cmp.total }} 处变化</div>
          <div v-for="g in cmp.groups" :key="g.kind" class="card">
            <div class="sec-title">{{ g.label }} <span class="text-fg-mute font-normal">新增 {{ g.added.length }} · 修改 {{ g.modified.length }} · 删除 {{ g.removed.length }}</span></div>
            <div v-for="x in g.added" :key="'a' + x.id" class="text-xs py-0.5"><span class="pill pill-ok">新增</span> {{ x.name }} <span class="text-fg-mute">{{ x.id }}</span></div>
            <div v-for="x in g.removed" :key="'r' + x.id" class="text-xs py-0.5"><span class="pill pill-err">删除</span> {{ x.name }} <span class="text-fg-mute">{{ x.id }}</span></div>
            <div v-for="x in g.modified" :key="'m' + x.id" class="text-xs py-0.5">
              <span class="pill pill-warn cursor-pointer" @click="openRow[g.kind + x.id] = !openRow[g.kind + x.id]">修改 {{ openRow[g.kind + x.id] ? '▾' : '▸' }}</span> {{ x.name }} <span class="text-fg-mute">{{ x.id }} · {{ x.changes.map((c: Any) => c.field).join('、') }}</span>
              <div v-if="openRow[g.kind + x.id]" class="ml-12 mt-1 space-y-0.5">
                <div v-for="c in x.changes" :key="c.field" class="truncate max-w-[900px]" :title="`${c.before} → ${c.after}`"><span class="text-fg-mute">{{ c.field }}：</span>{{ c.before ?? '—' }} → {{ c.after ?? '—' }}</div>
              </div>
            </div>
            <div v-if="!g.added.length && !g.removed.length && !g.modified.length" class="text-xs text-fg-mute">无变化</div>
          </div>
        </template>
      </template>

      <!-- 导出 -->
      <template v-else-if="tab === 'export'">
        <div class="card space-y-2">
          <div class="flex items-center gap-2">
            <span class="text-xs text-fg-mute">导出范围</span>
            <select v-model="seg" class="inp w-48"><option value="">全车间</option><option v-for="s in segments" :key="s.id" :value="s.id">{{ s.label }}</option></select>
            <button class="btn btn-primary" :disabled="busy || !!staticBackend" @click="download('excel')">导出 Excel</button>
            <button class="btn btn-primary" :disabled="busy || !!staticBackend" @click="download('ttl')">导出 TTL</button>
            <span v-if="busy" class="text-xs text-fg-mute">导出中…</span>
          </div>
          <div class="text-[11px] text-fg-mute leading-relaxed">
            Excel：空间层级、设备组、设备、参数、位号映射、工艺限值、现象（规则文本 + JSON）、导致关系、计算组态、处置规程与步骤、人工关系、继承覆盖，
            每张表一个工作表，对象引用列同时给出 ID 和名称。<br />
            TTL（RDF 1.1 Turtle）：类 → owl:Class（设备类型为 onto:Equipment 的子类），实例 → 具名个体，关系类型 → owl:ObjectProperty（包含为传递属性），
            名称为 rdfs:label @zh，带置信度的导致关系对象化为 onto:CausalLink；URI = 命名空间前缀 + 类型 + 对象 ID（前缀为占位，待组态）。导出后自动做语法自检。
          </div>
        </div>
        <div v-if="exportInfo" class="card text-xs">
          <div class="sec-title">最近导出：{{ exportInfo.file }}</div>
          <template v-if="exportInfo.kind === 'ttl'">
            节点 {{ exportInfo.nodes }} · 关系 {{ exportInfo.edges }} · 导致关系 {{ exportInfo.causalLinks }} · 类 {{ exportInfo.classes }} · 三元组 {{ exportInfo.triples ?? '—' }}
            <div :class="String(exportInfo.syntax).startsWith('通过') ? 'text-ok' : 'text-warn'">语法自检：{{ exportInfo.syntax }}</div>
          </template>
          <div v-else>{{ Object.entries(exportInfo.counts ?? {}).map(([k, v]) => `${k} ${v}`).join(' · ') }}</div>
        </div>
      </template>

      <!-- 操作日志 -->
      <template v-else-if="tab === 'audit'">
        <div class="flex items-center gap-2">
          <select v-model="auditOp" class="inp w-40"><option value="">全部操作</option><option v-for="o in audit?.ops ?? []" :key="o">{{ o }}</option></select>
          <input v-model="auditKw" class="inp w-60" placeholder="筛选对象 / 说明" />
          <span class="text-xs text-fg-mute">共 {{ audit?.total ?? 0 }} 条</span>
        </div>
        <table class="tbl">
          <thead><tr><th class="w-40">时间</th><th class="w-20">操作人</th><th class="w-28">操作</th><th class="w-24">类型</th><th>对象 / 说明</th><th>变更字段</th></tr></thead>
          <tbody>
            <tr v-for="e in audit?.items ?? []" :key="e.id" class="!cursor-default">
              <td class="text-xs tabular-nums">{{ e.time }}</td><td class="text-xs">{{ e.user }}</td>
              <td><span class="pill pill-plain">{{ e.op }}</span></td><td class="text-xs text-fg-dim">{{ e.kind }}</td>
              <td class="text-xs">{{ e.name }}<div v-if="e.note" class="text-fg-mute">{{ e.note }}</div></td>
              <td class="text-xs"><div v-for="d in e.changes.slice(0, 3)" :key="d.field" class="truncate max-w-[420px]" :title="`${d.before} → ${d.after}`"><span class="text-fg-mute">{{ d.field }}：</span>{{ d.before ?? '—' }} → {{ d.after ?? '—' }}</div></td>
            </tr>
          </tbody>
        </table>
        <div v-if="staticBackend" class="text-xs text-fg-mute">单文件版不记录操作日志</div>
      </template>
    </div>
  </div>
</template>
