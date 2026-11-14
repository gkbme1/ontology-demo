<script setup lang="ts">
/**
 * 运行态（需求 4.9）：运行服务状态（SW-076）、现象与工况状态评估及原因链（SW-073）、绑定状态（SW-076）、知识沉淀提交（SW-075）。
 * 只读：修改须在工程态进行并发布。数据为模拟数据。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { staticBackend } from '@/api/static'
import { nav, openInEngineering } from '@/composables/useNav'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const SECTIONS = [['status', '运行服务状态'], ['eval', '现象 / 工况状态'], ['bind', '绑定状态'], ['know', '知识沉淀提交']] as const
const section = ref<string>('status')
const st = ref<Any>(null)
const err = ref('')
const space = ref<Any>(null)
const segments = computed(() => (space.value?.items?.[0]?.children ?? []).filter((c: Any) => c.kind === 'segment'))
api.navSpace().then((r) => (space.value = r))

async function loadStatus(): Promise<void> { try { st.value = await api.runtimeStatus() } catch (e) { err.value = String((e as Error).message) } }
watch(() => nav.version, loadStatus, { immediate: true })

// 现象评估
const scope = ref<'effective' | 'all'>('effective')
const seg = ref('SEG-04')
const ev = ref<Any>(null)
const evBusy = ref(false)
const stateFilter = ref('')
const causes = ref<Any>(null)
async function evaluate(): Promise<void> {
  err.value = ''; evBusy.value = true; causes.value = null
  try { ev.value = await api.runtimeEvaluate({ scope: scope.value, seg: scope.value === 'all' ? seg.value : undefined }) }
  catch (e) { err.value = String((e as Error).message) } finally { evBusy.value = false }
}
const evRows = computed(() => (ev.value?.items ?? []).filter((i: Any) => !stateFilter.value || i.state === stateFilter.value))
async function showCauses(i: Any): Promise<void> {
  causes.value = { loading: true, name: i.name, target: i.targetName }
  try { causes.value = { ...(await api.runtimeCauses(i.id, i.targetId)), target: i.targetName } } catch (e) { causes.value = { error: String((e as Error).message) } }
}
const STATE_PILL: Record<string, string> = { 发生: 'pill-err', 未发生: 'pill-ok', 未知: 'pill-mute' }

// 绑定状态
const bind = ref<Any>(null)
watch(section, async (s) => {
  if (s === 'bind' && !bind.value) { try { bind.value = await api.runtimeBindings() } catch (e) { err.value = String((e as Error).message) } }
  if (s === 'know') loadKnow()
})

// 知识沉淀
const know = ref<Any>(null)
const phen = ref<Any[]>([])
const links = ref<Any[]>([])
const kform = ref<Any>({ type: '新的根因关系', content: '', basis: '', submitter: '工艺调查智能体（演示）', cause: '', effect: '', linkId: '', confidence: '中' })
const kmsg = ref('')
async function loadKnow(): Promise<void> {
  know.value = await api.knowledge()
  if (!phen.value.length && !staticBackend) {
    phen.value = (await api.phenomena({})).items
    links.value = (await api.links({})).items
  }
}
async function submit(): Promise<void> {
  kmsg.value = ''; err.value = ''
  const f = kform.value
  const payload = f.type === '新的根因关系' ? { cause: f.cause, effect: f.effect, confidence: '低' } : f.type === '关系置信度修正' ? { linkId: f.linkId, confidence: f.confidence } : {}
  const objectIds = [f.cause, f.effect, f.linkId].filter(Boolean)
  try {
    const r = await api.submitKnowledge({ type: f.type, content: f.content, basis: f.basis, submitter: f.submitter, payload, objectIds })
    kmsg.value = `已提交 ${r.id}，进入工程态「发布与导出 · 知识审核」队列`
    f.content = ''; f.basis = ''
    await loadKnow()
  } catch (e) { err.value = String((e as Error).message) }
}
</script>

<template>
  <div class="h-full grid grid-cols-[240px_1fr] min-h-0">
    <aside class="border-r border-line bg-ink-panel p-3 space-y-1">
      <div class="text-xs text-fg-mute mb-2">运行态 · 只读（修改须在工程态进行并发布）</div>
      <button v-for="[k, l] in SECTIONS" :key="k" class="tree-row w-full !py-1.5" :class="{ 'tree-row-on': section === k }" @click="section = k">{{ l }}</button>
      <div class="pt-3 text-[11px] text-fg-mute leading-relaxed">
        运行服务加载：<b class="text-fg-dim">{{ st?.version ? `${st.version.version}（${st.version.time}）` : '工程态当前（未发布，演示）' }}</b><br />
        数据来源：<span class="sim-tag">模拟数据</span>
      </div>
    </aside>
    <main class="min-h-0 overflow-auto px-5 py-4 text-sm space-y-3">
      <div v-if="err" class="empty">{{ err }}</div>

      <template v-if="section === 'status'">
        <h2 class="text-[16px] font-semibold">运行服务状态</h2>
        <div v-if="st" class="grid grid-cols-4 gap-3">
          <div class="card"><div class="text-xs text-fg-mute">当前加载版本</div><div class="text-[18px] font-semibold">{{ st.version?.version ?? '未发布' }}</div>
            <div class="text-[11px] text-fg-mute">{{ st.version ? `发布于 ${st.version.time}` : st.versionNote }}</div></div>
          <div class="card"><div class="text-xs text-fg-mute">对象 / 关系</div><div class="text-[18px] font-semibold tabular-nums">{{ st.objectTotal }} / {{ st.relationTotal }}</div>
            <div class="text-[11px] text-fg-mute">加载时间 {{ st.loadedAt }}</div></div>
          <div class="card"><div class="text-xs text-fg-mute">现象（生效 / 有规则 / 总数）</div><div class="text-[18px] font-semibold tabular-nums">{{ st.phenomena.effective }} / {{ st.phenomena.withRule }} / {{ st.phenomena.total }}</div>
            <div class="text-[11px] text-fg-mute">只评估发布版本中生效的现象</div></div>
          <div class="card"><div class="text-xs text-fg-mute">内存占用（峰值）</div><div class="text-[18px] font-semibold tabular-nums">{{ st.memoryMB }} MB</div>
            <div class="text-[11px] text-fg-mute">后端进程</div></div>
        </div>
        <div v-if="st" class="grid grid-cols-2 gap-3">
          <div class="card text-xs space-y-1">
            <div class="sec-title">外部连接与引擎</div>
            <div>XBase：<span class="pill pill-warn">{{ st.xbase.state }}</span> {{ st.xbase.note }}</div>
            <div>计算 / 规则引擎：{{ st.engine.tasks }} 个计算任务（{{ Object.entries(st.engine.byMode).map(([k, v]) => `${k} ${v}`).join('、') }}）· {{ st.engine.note }}</div>
            <div>对外接口：<a class="text-brand" href="/docs" target="_blank">OpenAPI 说明（/docs）</a> · {{ st.api.note }}</div>
          </div>
          <div class="card text-xs">
            <div class="sec-title">对象数量</div>
            <div class="flex flex-wrap gap-1.5"><span v-for="(n, k) in st.objects" :key="k" class="pill pill-plain">{{ k }} {{ n }}</span></div>
            <div class="sec-title mt-2">关系数量</div>
            <div class="flex flex-wrap gap-1.5"><span v-for="(n, k) in st.relations" :key="k" class="pill pill-plain">{{ k }} {{ n }}</span></div>
          </div>
        </div>
      </template>

      <template v-else-if="section === 'eval'">
        <h2 class="text-[16px] font-semibold">现象 / 工况状态评估</h2>
        <div class="flex flex-wrap items-center gap-2">
          <button class="ctl" :class="{ 'ctl-on': scope === 'effective' }" @click="scope = 'effective'">发布版本中生效的现象</button>
          <button class="ctl" :class="{ 'ctl-on': scope === 'all' }" @click="scope = 'all'">全部（含草案，演示）</button>
          <select v-if="scope === 'all'" v-model="seg" class="inp w-40"><option v-for="s in segments" :key="s.id" :value="s.id">{{ s.label }}</option></select>
          <button class="btn btn-primary" :disabled="evBusy || !!staticBackend" @click="evaluate">{{ evBusy ? '评估中…' : '评估当前状态' }}</button>
          <span class="sim-tag">模拟数据</span>
          <span v-if="staticBackend" class="text-xs text-fg-mute">单文件版不支持在线评估</span>
        </div>
        <template v-if="ev">
          <div class="flex items-center gap-2 text-xs">
            <span class="text-fg-mute">{{ ev.label }} · {{ ev.at }} · 用时 {{ ev.seconds }} 秒</span>
            <button v-for="(n, s) in (ev.counts as Record<string, number>)" :key="s" class="ctl !py-0" :class="{ 'ctl-on': stateFilter === s }" @click="stateFilter = stateFilter === s ? '' : String(s)">{{ s }} {{ n }}</button>
          </div>
          <div v-if="!ev.items.length" class="empty">{{ scope === 'effective' ? '发布版本中没有生效且有判定规则的现象：先在工程态把现象设为生效并发布，或切到「全部（含草案，演示）」' : '范围内没有带判定规则的现象' }}</div>
          <div class="grid gap-3" :class="causes ? 'grid-cols-[1.2fr_1fr]' : ''">
            <table v-if="ev.items.length" class="tbl">
              <thead><tr><th class="w-20">状态</th><th>现象 / 工况</th><th>对象</th><th>本次发生起</th><th></th></tr></thead>
              <tbody>
                <tr v-for="(i, k) in evRows" :key="k" class="!cursor-default">
                  <td><span class="pill" :class="STATE_PILL[i.state]">{{ i.state }}</span></td>
                  <td>{{ i.name }}<div class="text-[11px] text-fg-mute">{{ i.id }} · {{ i.category }} · {{ i.severity }}</div><div v-if="i.reason" class="text-[11px] text-warn truncate max-w-[360px]">{{ i.reason }}</div></td>
                  <td>{{ i.targetName }}</td><td class="text-xs tabular-nums">{{ i.since ?? '—' }}</td>
                  <td class="whitespace-nowrap"><button v-if="i.state === '发生'" class="ctl" @click="showCauses(i)">可能原因</button></td>
                </tr>
              </tbody>
            </table>
            <div v-if="causes" class="card text-xs space-y-2 self-start">
              <div class="flex items-center"><div class="sec-title !mb-0 flex-1">「{{ causes.name }}」@{{ causes.target }} 的可能原因链</div><button class="ctl !py-0" @click="causes = null">×</button></div>
              <div v-if="causes.loading" class="text-fg-mute">查询中…</div>
              <div v-else-if="causes.error" class="text-err">{{ causes.error }}</div>
              <template v-else>
                <div v-if="!causes.causes.length" class="text-fg-mute">本体中还没有登记导致它的现象</div>
                <div v-for="c in causes.causes" :key="c.id" class="flex items-start gap-2 py-1 border-b border-line-soft" :style="{ paddingLeft: `${(c.level - 1) * 14}px` }">
                  <span class="pill" :class="STATE_PILL[c.state]">{{ c.state }}</span>
                  <div class="flex-1">{{ c.name }} <span class="text-fg-mute">→ {{ c.to.join('、') }}（置信度 {{ c.confidence.join('/') }}）</span>
                    <div class="text-[11px] text-fg-mute">{{ c.anchor }}<span v-if="c.reason"> · {{ c.reason }}</span></div></div>
                </div>
                <div class="text-[11px] text-fg-mute">按根因影响关系逐层向上，最多 3 层；状态为同一对象上的当前评估（模拟数据）</div>
              </template>
            </div>
          </div>
        </template>
      </template>

      <template v-else-if="section === 'bind'">
        <h2 class="text-[16px] font-semibold">参数—位号绑定状态</h2>
        <div v-if="!bind" class="text-fg-mute">统计中（逐台设备汇总，首次约十几秒）…</div>
        <template v-else>
          <div class="grid grid-cols-4 gap-3">
            <div v-for="(n, k) in (bind.counts as Record<string, number>)" :key="k" class="card"><div class="text-xs text-fg-mute">{{ k }}</div>
              <div class="text-[20px] font-semibold tabular-nums" :class="k === '失效' && n ? 'text-err' : k === '待确认' ? 'text-warn' : ''">{{ n }}</div></div>
          </div>
          <table class="tbl"><thead><tr><th>工艺段</th><th>已绑定</th><th>待确认</th><th>未绑定</th><th>失效</th></tr></thead><tbody>
            <tr v-for="(c, s) in bind.bySegment" :key="s" class="!cursor-default"><td>{{ s }}</td><td>{{ c['已绑定'] }}</td><td>{{ c['待确认'] }}</td><td>{{ c['未绑定'] }}</td><td>{{ c['失效'] }}</td></tr>
          </tbody></table>
          <div class="card"><div class="sec-title">失效绑定（位号不在位号目录中）</div>
            <div v-if="!bind.invalid.length" class="text-xs text-fg-mute">无</div>
            <div v-for="(x, i) in bind.invalid" :key="i" class="text-xs py-0.5">{{ x.objectName }} · {{ x.parameter }} <span class="text-fg-mute">{{ x.note }}</span></div>
          </div>
          <div class="text-[11px] text-fg-mute">{{ bind.note }} · 统计时间 {{ bind.at }}</div>
        </template>
      </template>

      <template v-else-if="section === 'know'">
        <h2 class="text-[16px] font-semibold">知识沉淀提交</h2>
        <div class="text-xs text-fg-mute">智能体或业务应用通过接口 <span class="font-mono">POST /api/v2/knowledge</span> 提交新知识，进入工程态候选审核队列，审核通过后经发布生效。下面模拟一次提交。</div>
        <div v-if="!staticBackend" class="card grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 items-center">
          <span class="text-xs text-fg-mute">知识类型</span>
          <select v-model="kform.type" class="inp w-56"><option v-for="t in know?.types ?? []" :key="t">{{ t }}</option></select>
          <template v-if="kform.type === '新的根因关系'">
            <span class="text-xs text-fg-mute">原因现象</span>
            <select v-model="kform.cause" class="inp"><option value="">选择</option><option v-for="p in phen" :key="p.id" :value="p.id">{{ p.name }}（{{ p.anchor?.name }}）</option></select>
            <span class="text-xs text-fg-mute">结果现象</span>
            <select v-model="kform.effect" class="inp"><option value="">选择</option><option v-for="p in phen" :key="p.id" :value="p.id">{{ p.name }}（{{ p.anchor?.name }}）</option></select>
          </template>
          <template v-if="kform.type === '关系置信度修正'">
            <span class="text-xs text-fg-mute">导致关系</span>
            <select v-model="kform.linkId" class="inp"><option value="">选择</option><option v-for="l in links" :key="l.id" :value="l.id">{{ l.causeName }} → {{ l.effectName }}（{{ l.confidence }}）</option></select>
            <span class="text-xs text-fg-mute">建议置信度</span>
            <select v-model="kform.confidence" class="inp w-24"><option>高</option><option>中</option><option>低</option></select>
          </template>
          <span class="text-xs text-fg-mute">建议内容</span><textarea v-model="kform.content" class="inp" rows="2" placeholder="如：C 罐 pH 电极 1 持续漂移时，pH双支偏差大会先于水解罐pH偏高出现" />
          <span class="text-xs text-fg-mute">依据</span><input v-model="kform.basis" class="inp" placeholder="数据、事件、分析过程，如 调查记录编号" />
          <span class="text-xs text-fg-mute">提交方</span><input v-model="kform.submitter" class="inp w-72" />
          <span /><div class="flex items-center gap-2"><button class="btn btn-primary" @click="submit">提交</button><span class="text-xs text-ok">{{ kmsg }}</span></div>
        </div>
        <table class="tbl"><thead><tr><th class="w-20">编号</th><th class="w-28">类型</th><th>内容</th><th class="w-32">提交方</th><th class="w-24">审核状态</th><th>审核意见 / 结果</th></tr></thead><tbody>
          <tr v-for="k in know?.items ?? []" :key="k.id" class="!cursor-default"><td class="font-mono text-xs">{{ k.id }}</td><td class="text-xs">{{ k.type }}</td>
            <td>{{ k.content }}<div v-if="k.basis" class="text-[11px] text-fg-mute">依据：{{ k.basis }}</div></td><td class="text-xs">{{ k.submitter }}<div class="text-fg-mute">{{ k.submittedAt }}</div></td>
            <td><span class="pill" :class="k.status === '已采纳' ? 'pill-ok' : k.status === '已驳回' ? 'pill-mute' : 'pill-warn'">{{ k.status }}</span></td>
            <td class="text-xs text-fg-dim">{{ k.review?.comment }}<div v-if="k.review?.result">{{ k.review.result }}</div></td></tr>
        </tbody></table>
        <div v-if="!(know?.items ?? []).length" class="text-xs text-fg-mute">还没有提交记录</div>
      </template>
    </main>
  </div>
</template>
