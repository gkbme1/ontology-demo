/**
 * 单文件版（离线 HTML）的「后端」：接口应答来自页面里内嵌的数据快照，不需要启动服务。
 *
 * - 导航、图纸、页签、文档等只读数据：导出时预先生成的应答（按 路径?参数 查表）；
 * - 现象与根因影响关系：在浏览器里现算（列表、导致链、图谱、各页签），支持新增 / 编辑 / 删除，
 *   编辑结果存在浏览器 localStorage，「恢复种子数据」清除；
 * - 试算：只能给出导出时预先算好的结果（规则未改动时）；改过的规则需在完整版里试算。
 *
 * 数据由 backend/tools/export_static.py 生成。
 */
import { ApiError, type Query } from './client'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

interface Snapshot {
  info: Any
  get: Record<string, Any>
  base: {
    phenomena: Any[]
    links: Any[]
    anchorOps: Record<string, string[]>
    equipGroup: Record<string, string>
    limits: Record<string, Any>
    calcNames: Record<string, string>
    search: { index: Any[]; phenPy: Record<string, string>; opSegment: Record<string, string> }
    phenProcedures?: Record<string, Any[]>
  }
  evals: Record<string, Any>
  calcRuns: Record<string, Any>
}

const STORE_KEY = 'v2-static-store'
const OPS: Record<string, string> = { '>': '大于', '>=': '大于等于', '<': '小于', '<=': '小于等于', '=': '等于', '!=': '不等于', change: '由…变为…' }
const LIMIT_FIELDS: Record<string, string> = { lowLow: '低低限', low: '低限', normalLow: '正常下限', normalHigh: '正常上限', high: '高限', highHigh: '高高限' }
const AGG: Record<string, string> = { any: '任一测点', all: '全部测点', mean: '测点均值' }
const DRAFT = '草案·待工艺确认'
const LEGACY_STATUS: Record<string, string> = { 已确认: '生效' }
const KIND_ORDER = ['segment', 'op', 'group', 'equipment', 'tag', 'phenomenon', 'condition', 'parameter', 'stream', 'utility', 'quality']

/** 与后端 backend/v2/search.py 的 score() 一致。 */
function score(e: Any, kw: string): number {
  const low = kw.toLowerCase()
  const label: string = e.label
  const code: string = (e.code ?? '').toLowerCase()
  if (kw.toUpperCase() === label.toUpperCase() || kw.toUpperCase() === code.toUpperCase()) return 5
  if (e.kind === 'tag') return code.startsWith(low) ? 4 : kw.length >= 2 && label.includes(kw) ? 3 : 0
  if (label.includes(kw) || (low && code.includes(low)) || low === String(e.id).toLowerCase()) return 4
  if (/^[a-zA-Z]{2,}$/.test(kw)) {
    const py: string = e.py ?? ''
    if (py.startsWith(low)) return 2
    if (py.includes(low)) return 1
  }
  return 0
}

/** 导致关系所在的强连通分量（处在因果环路上的关系）。 */
function cyclicLinks(links: Any[]): Set<string> {
  const adj: Record<string, string[]> = {}
  for (const l of links) (adj[l.cause] ??= []).push(l.effect)
  const reach = (from: string, to: string): boolean => {
    const seen = new Set([from])
    const stack = [from]
    while (stack.length) {
      const cur = stack.pop()!
      for (const n of adj[cur] ?? []) {
        if (n === to) return true
        if (!seen.has(n)) { seen.add(n); stack.push(n) }
      }
    }
    return false
  }
  return new Set(links.filter((l) => reach(l.effect, l.cause)).map((l) => l.id))
}

function canon(v: Any): string {
  if (Array.isArray(v)) return `[${v.map(canon).join(',')}]`
  if (v && typeof v === 'object') return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(',')}}`
  return JSON.stringify(v ?? null)
}
function key(path: string, query?: Query): string {
  const parts = Object.entries(query ?? {}).filter(([, v]) => v !== undefined && v !== null && v !== '')
    .sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k}=${v}`)
  return parts.length ? `${path}?${parts.join('&')}` : path
}
function now(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v))
}

export class StaticBackend {
  private snap: Snapshot
  private phen: Record<string, Any> = {}
  private links: Record<string, Any> = {}
  private seedRules: Record<string, string> = {}

  constructor(snap: Snapshot) {
    this.snap = snap
    for (const p of snap.base.phenomena) this.seedRules[p.id] = `${p.anchor?.id}|${canon(p.rule)}`
    this.load()
  }

  get info(): Any {
    return this.snap.info
  }

  // ------------------------------------------------------------ 持久化
  private load(): void {
    let saved: Any = null
    try { saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null') } catch { saved = null }
    const src = saved?.generatedAt === this.snap.info.generatedAt ? saved : null
    this.phen = Object.fromEntries((src?.phenomena ?? clone(this.snap.base.phenomena)).map((p: Any) => [p.id, p]))
    this.links = Object.fromEntries((src?.links ?? clone(this.snap.base.links)).map((l: Any) => [l.id, l]))
    for (const x of [...Object.values(this.phen), ...Object.values(this.links)]) x.status = LEGACY_STATUS[x.status] ?? x.status
  }
  private save(): void {
    this.cyc = null
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        generatedAt: this.snap.info.generatedAt, phenomena: Object.values(this.phen), links: Object.values(this.links)
      }))
    } catch { /* 隐私模式等无法保存时只在本次打开内生效 */ }
  }

  // ------------------------------------------------------------ 规则文本
  private dur(sec: Any): string {
    const n = Number(sec || 0)
    if (!n) return ''
    return n % 60 === 0 ? ` 持续 ${n / 60} 分钟` : ` 持续 ${n} 秒`
  }
  private subject(s: Any): string {
    if (s?.kind === 'parameter') return `本对象.${s.name || '?'}`
    if (s?.kind === 'tag') return `位号 ${s.tag || '?'}`
    if (s?.kind === 'calc') return `计算 ${this.snap.base.calcNames[s.calcId] ?? s.calcId ?? '?'}`
    if (s?.kind === 'context') return `上下文.${s.name || '?'}`
    return '?'
  }
  private threshold(t: Any): string {
    if (t?.kind === 'limit') {
      const v = this.snap.base.limits[t.limitId]?.[t.field]
      return `${t.limitId || '?'} ${LIMIT_FIELDS[t.field] ?? t.field ?? '?'}${v !== undefined && v !== null ? `（${v}）` : ''}`
    }
    return t?.value === undefined || t?.value === null ? '?' : String(t.value)
  }
  ruleText(rule: Any, top = true): string {
    if (!rule) return '（判定规则待定义）'
    if (rule.type === 'group') {
      const parts = (rule.children ?? []).map((c: Any) => this.ruleText(c, false))
      if (!parts.length) return '（空条件组）'
      const joined = parts.join(rule.op === 'AND' ? ' 且 ' : ' 或 ')
      return top || parts.length === 1 ? joined : `（${joined}）`
    }
    const agg = rule.subject?.kind === 'parameter' && rule.aggregate && rule.aggregate !== 'any' ? `[${AGG[rule.aggregate]}]` : ''
    const s = this.subject(rule.subject) + agg
    if (rule.operator === 'change') return `${s} 由 ${rule.from} 变为 ${rule.to}${this.dur(rule.durationSec)}`
    return `${s} ${OPS[rule.operator] ?? rule.operator} ${this.threshold(rule.threshold)}${this.dur(rule.durationSec)}`
  }

  // ------------------------------------------------------------ 视图
  private ops(p: Any): string[] {
    return this.snap.base.anchorOps[p.anchor?.id ?? ''] ?? []
  }
  private roles(pid: string): Any {
    const ls = Object.values(this.links)
    return { asCause: ls.filter((l) => l.cause === pid).length, asEffect: ls.filter((l) => l.effect === pid).length }
  }
  private view(p: Any, origin = ''): Any {
    const inherited = origin === '继承自设备组'
    return { ...p, ruleText: this.ruleText(p.rule), hasRule: !!p.rule, roles: this.roles(p.id), opIds: this.ops(p), origin,
             inherited, inheritedFrom: inherited ? `设备组 ${p.anchor?.name ?? ''}` : null }
  }
  private cyc: Set<string> | null = null
  private linkView(l: Any): Any {
    const c = this.phen[l.cause] ?? {}
    const e = this.phen[l.effect] ?? {}
    this.cyc ??= cyclicLinks(Object.values(this.links))
    return { ...l, inCycle: this.cyc.has(l.id), causeName: c.name ?? l.cause, effectName: e.name ?? l.effect,
             causeAnchor: c.anchor?.name ?? '', effectAnchor: e.anchor?.name ?? '' }
  }
  private graph(scope: Set<string>, links: Any[], focus?: Set<string>): Any {
    const ids = new Set(scope)
    for (const l of links) { ids.add(l.cause); ids.add(l.effect) }
    const nodes = [...ids].filter((id) => this.phen[id]).map((id) => {
      const p = this.phen[id]
      const r = this.roles(id)
      return { id, name: p.name, category: p.category || '工艺', anchor: p.anchor?.name ?? '', hasRule: !!p.rule,
               asCause: r.asCause, asEffect: r.asEffect, inScope: scope.has(id), focus: !!focus?.has(id) }
    })
    return { nodes, links: links.map((l) => this.linkView(l)) }
  }
  private forObject(objectId: string): [Any, string][] {
    const gid = this.snap.base.equipGroup[objectId]
    const out: [Any, string][] = []
    for (const p of Object.values(this.phen)) {
      if (p.anchor?.id === objectId) out.push([p, '本对象'])
      else if (gid && p.anchor?.id === gid) out.push([p, '继承自设备组'])
    }
    return out
  }
  private touching(ids: Set<string>): Any[] {
    return Object.values(this.links).filter((l) => ids.has(l.cause) || ids.has(l.effect))
  }
  private chain(pid: string, direction: string, depth = 6): Any {
    if (!this.phen[pid]) throw new ApiError(404, `未找到：${pid}`)
    const levels: Record<string, number> = { [pid]: 0 }
    const edges: Any[] = []
    const queue = [pid]
    while (queue.length) {
      const cur = queue.shift()!
      if (levels[cur] >= depth) continue
      for (const l of Object.values(this.links)) {
        if ((direction === 'up' ? l.effect : l.cause) !== cur) continue
        const other = direction === 'up' ? l.cause : l.effect
        edges.push(l)
        if (levels[other] === undefined) { levels[other] = levels[cur] + 1; queue.push(other) }
      }
    }
    const graph = this.graph(new Set(Object.keys(levels)), edges, new Set([pid]))
    for (const n of graph.nodes) n.level = levels[n.id] ?? 0
    return { root: pid, direction, levels, links: edges, graph }
  }

  // ------------------------------------------------------------ 增删改
  private nextId(prefix: string, existing: Record<string, Any>): string {
    const nums = Object.keys(existing).filter((k) => k.startsWith(prefix)).map((k) => Number(k.slice(prefix.length))).filter((n) => !isNaN(n))
    return `${prefix}${String((nums.length ? Math.max(...nums) : 0) + 1).padStart(4, '0')}`
  }
  private cleanPhen(body: Any, current?: Any): Any {
    const d = { ...(current ? clone(current) : {}) }
    for (const k of ['name', 'category', 'description', 'severity', 'status', 'anchor', 'rule', 'note']) if (k in body) d[k] = body[k]
    if (!String(d.name ?? '').trim()) throw new ApiError(400, '现象名称不能为空')
    if (!d.anchor?.id) throw new ApiError(400, '现象必须挂在一个本体对象上')
    const check = (r: Any): void => {
      if (!r) return
      if (r.type === 'group') {
        if (!r.children?.length) throw new ApiError(400, '条件组至少要有一个条件')
        r.children.forEach(check)
      } else if (r.subject?.kind === 'parameter' && !r.subject.name) throw new ApiError(400, '条件的属性名不能为空')
      else if (r.subject?.kind === 'tag' && !r.subject.tag) throw new ApiError(400, '条件的位号不能为空')
      else if (r.threshold?.kind === 'limit' && !r.threshold.limitId) throw new ApiError(400, '引用限值时要选择限值编号')
    }
    check(d.rule)
    d.status ??= DRAFT
    return d
  }
  private cleanLink(body: Any, current?: Any, ownId?: string): Any {
    const d = { ...(current ? clone(current) : {}) }
    for (const k of ['cause', 'effect', 'mechanism', 'basis', 'confidence', 'status', 'note']) if (k in body) d[k] = body[k]
    if (!this.phen[d.cause]) throw new ApiError(400, `原因现象不存在：${d.cause || '未选择'}`)
    if (!this.phen[d.effect]) throw new ApiError(400, `结果现象不存在：${d.effect || '未选择'}`)
    if (d.cause === d.effect) throw new ApiError(400, '原因和结果不能是同一个现象')
    const dup = Object.values(this.links).find((l) => l.id !== ownId && l.cause === d.cause && l.effect === d.effect)
    if (dup) throw new ApiError(400, `这条导致关系已存在：${dup.id}`)
    d.status ??= DRAFT
    d.confidence ??= '中'
    return d
  }

  // ------------------------------------------------------------ 试算（预先算好的）
  private evalFor(pid: string, opId?: string): Any {
    const ev = this.snap.evals
    const hit = ev[`${pid}|${opId ?? ''}`] ?? ev[`${pid}|`] ?? Object.entries(ev).find(([k]) => k.startsWith(`${pid}|`))?.[1]
    if (!hit) throw new ApiError(400, '单文件版没有这条规则的试算结果，请在完整版中试算')
    return hit
  }

  // ------------------------------------------------------------ 路由
  async handle(method: string, path: string, body: Any, query?: Query): Promise<Any> {
    const q = query ?? {}
    let m: RegExpMatchArray | null
    // 现象
    if (path === '/phenomena' && method === 'GET') {
      const items = Object.values(this.phen).filter((p) =>
        (!q.anchor || p.anchor?.id === q.anchor) && (!q.op || this.ops(p).includes(String(q.op))) && (!q.keyword || p.name.includes(String(q.keyword))))
      return { items: items.map((p) => this.view(p)), total: items.length }
    }
    if (path === '/phenomena' && method === 'POST') {
      const d = this.cleanPhen(body)
      d.id = this.nextId('PH-U-', this.phen)
      d.source = { kind: '人工新增', ref: '演示用户（单文件版）' }
      d.createdAt = d.updatedAt = now()
      this.phen[d.id] = d
      this.save()
      return this.view(d)
    }
    if ((m = path.match(/^\/phenomena\/([^/]+)\/chain$/))) return this.chain(m[1], String(q.direction ?? 'up'))
    if ((m = path.match(/^\/phenomena\/([^/]+)\/evaluate$/))) {
      const p = this.phen[m[1]]
      if (!p) throw new ApiError(404, m[1])
      if (!p.rule) throw new ApiError(400, '该现象还没有判定规则，无法试算')
      if (this.seedRules[p.id] !== `${p.anchor?.id}|${canon(p.rule)}`) throw new ApiError(400, '规则已修改：单文件版只能展示导出时算好的试算结果，改过的规则请在完整版中试算')
      return this.evalFor(p.id, body?.opId)
    }
    if ((m = path.match(/^\/phenomena\/([^/]+)$/))) {
      const id = m[1]
      if (!this.phen[id]) throw new ApiError(404, `未找到：${id}`)
      if (method === 'GET') {
        return { ...this.view(this.phen[id]), procedures: this.snap.base.phenProcedures?.[id] ?? [],
                 causes: Object.values(this.links).filter((l) => l.effect === id).map((l) => this.linkView(l)),
                 effects: Object.values(this.links).filter((l) => l.cause === id).map((l) => this.linkView(l)) }
      }
      if (method === 'PUT') {
        const d = this.cleanPhen(body, this.phen[id])
        d.updatedAt = now()
        this.phen[id] = d
        this.save()
        return this.view(d)
      }
      if (method === 'DELETE') {
        const removed = Object.values(this.links).filter((l) => l.cause === id || l.effect === id).map((l) => l.id)
        removed.forEach((lid) => delete this.links[lid])
        delete this.phen[id]
        this.save()
        return { deleted: id, removedLinks: removed }
      }
    }
    if (path === '/rules/evaluate') {
      const sig = `${body?.anchorId}|${canon(body?.rule)}`
      const pid = Object.keys(this.seedRules).find((k) => this.seedRules[k] === sig)
      if (!pid) throw new ApiError(400, '单文件版只能展示导出时算好的试算结果；新写或改过的规则请在完整版中试算')
      return this.evalFor(pid, body?.opId)
    }
    // 根因影响关系
    if (path === '/causal-links' && method === 'GET') {
      let ls = Object.values(this.links)
      if (q.phenomenon) ls = ls.filter((l) => l.cause === q.phenomenon || l.effect === q.phenomenon)
      if (q.op) {
        const ids = new Set(Object.values(this.phen).filter((p) => this.ops(p).includes(String(q.op))).map((p) => p.id))
        ls = ls.filter((l) => ids.has(l.cause) || ids.has(l.effect))
      }
      return { items: ls.map((l) => this.linkView(l)), total: ls.length }
    }
    if (path === '/causal-links' && method === 'POST') {
      const d = this.cleanLink(body)
      d.id = this.nextId('CL-U-', this.links)
      d.source = { kind: '人工新增', ref: '演示用户（单文件版）' }
      d.createdAt = d.updatedAt = now()
      this.links[d.id] = d
      this.save()
      const v = this.linkView(d)
      if (v.inCycle) v.warnings = [`形成因果环路：${v.causeName} → ${v.effectName} → … → ${v.causeName}（请确认是否为正反馈 / 控制回路，否则检查关系方向）`]
      return v
    }
    if ((m = path.match(/^\/causal-links\/([^/]+)$/))) {
      const id = m[1]
      if (!this.links[id]) throw new ApiError(404, `未找到：${id}`)
      if (method === 'PUT') {
        const d = this.cleanLink(body, this.links[id], id)
        d.updatedAt = now()
        this.links[id] = d
        this.save()
        return this.linkView(d)
      }
      if (method === 'DELETE') {
        delete this.links[id]
        this.save()
        return { deleted: id }
      }
    }
    // 依赖现象 / 关系的视图
    if (path === '/scope/conditions') {
      // 全局工况与根因：范围（工序 / 工艺段 / 全车间）内的现象与导致关系，跨装置的标出
      const opSeg = this.snap.base.search.opSegment
      const inScope = (p: Any) => this.ops(p).some((o) => (q.op ? o === q.op : q.seg ? opSeg[o] === q.seg : true))
      const phen = Object.values(this.phen).filter(inScope)
      const ids = new Set(phen.map((p) => p.id))
      const links = this.touching(ids)
      const pre = this.snap.get[key('/scope/conditions', { seg: q.seg, op: q.op })] ?? this.snap.get['/scope/conditions'] ?? {}
      const views = links.map((l) => ({ ...this.linkView(l), crossDevice: this.phen[l.cause]?.anchor?.id !== this.phen[l.effect]?.anchor?.id }))
      return { phenomena: phen.map((p) => this.view(p)), links: views, graph: this.graph(ids, links),
               anchors: pre.anchors ?? [], crossCount: views.filter((v) => v.crossDevice).length }
    }
    if ((m = path.match(/^\/ops\/([^/]+)\/conditions$/))) {
      const phen = Object.values(this.phen).filter((p) => this.ops(p).includes(m![1]))
      const ids = new Set(phen.map((p) => p.id))
      const links = this.touching(ids)
      return { phenomena: phen.map((p) => this.view(p)), links: links.map((l) => this.linkView(l)), graph: this.graph(ids, links) }
    }
    if ((m = path.match(/^\/objects\/([^/]+)\/tabs\/phenomena$/))) {
      return { items: this.forObject(m[1]).map(([p, o]) => this.view(p, o)) }
    }
    if ((m = path.match(/^\/objects\/([^/]+)\/tabs\/causal$/))) {
      const pairs = this.forObject(m[1])
      const own = new Set(pairs.map(([p]) => p.id))
      const mine = new Set(pairs.filter(([, o]) => o === '本对象').map(([p]) => p.id))
      const gname = pairs.find(([, o]) => o !== '本对象')?.[0]?.anchor?.name ?? ''
      const links = this.touching(own)
      return {
        links: links.map((l) => {
          const inherited = !mine.has(l.cause) && !mine.has(l.effect)
          return { ...this.linkView(l), inherited, inheritedFrom: inherited ? `设备组 ${gname}` : null }
        }),
        graph: this.graph(own, links)
      }
    }
    if (path === '/search') return this.search(String(q.keyword ?? ''))
    if (path === '/global-graph') {
      // 导致关系用浏览器里（可能已编辑过）的当前数据
      const g = clone(this.snap.get['/global-graph'])
      const ids = new Set(g.nodes.map((n: Any) => n.id))
      g.edges = g.edges.filter((e: Any) => e.type !== '导致').concat(
        Object.values(this.links).filter((l) => ids.has(l.cause) && ids.has(l.effect))
          .map((l) => ({ s: l.cause, t: l.effect, type: '导致', label: '导致', mechanism: l.mechanism ?? '', confidence: l.confidence })))
      return g
    }
    if ((m = path.match(/^\/calculations\/([^/]+)\/run$/))) {
      const r = this.snap.calcRuns
      const hit = r[`${m[1]}|${body?.opId ?? ''}|${body?.targetId ?? ''}`] ?? r[`${m[1]}|${body?.opId ?? ''}|`] ??
        Object.entries(r).find(([k]) => k.startsWith(`${m![1]}|`))?.[1]
      if (!hit) throw new ApiError(400, '单文件版没有这条计算组态的试算结果')
      return hit
    }
    if (path === '/admin/reset-store') {
      try { localStorage.removeItem(STORE_KEY) } catch { /* ignore */ }
      this.load()
      return { status: 'ok' }
    }
    if (method !== 'GET') throw new ApiError(400, '单文件版不支持该操作，请在完整版中使用')

    // 预先生成的只读应答
    const g = this.snap.get
    const hit = g[key(path, q)] ?? g[path]
    if (hit === undefined) throw new ApiError(404, `单文件版未包含该数据：${path}`)
    const out = clone(hit)
    // 单文件版不支持继承覆盖、人工关系的编辑（需要后端保存），隐藏这些按钮
    if (/^\/objects\/[^/]+\/tabs\/(topology|influence|constraints|procedures|calc)$/.test(path)) { out.canEdit = false; out.canOverride = false }
    const om = path.match(/^\/objects\/([^/]+)$/)
    if (om && out.counts) {
      const own = new Set(this.forObject(om[1]).map(([p]) => p.id))
      out.counts.phenomena = own.size
      out.counts.causal = this.touching(own).length
    }
    if (path.match(/^\/(ops|segments)\/[^/]+$/)) this.patchCounts(out)
    return out
  }

  private patchCounts(out: Any): void {
    const count = (op: string) => Object.values(this.phen).filter((p) => this.ops(p).includes(op)).length
    if (out.id?.startsWith?.('OP-')) out.phenomenonCount = count(out.id)
    for (const o of out.ops ?? []) o.phenomenonCount = count(o.id)
  }

  private search(kw: string): Any {
    kw = kw.trim()
    if (!kw) return { items: [], total: 0 }
    const s = this.snap.base.search
    const items: Any[] = []
    for (const e of s.index) { const sc = score(e, kw); if (sc) items.push({ ...e, score: sc }) }
    for (const p of Object.values(this.phen)) {
      const ops = this.ops(p)
      if (!ops.length) continue
      const e = { kind: p.category === '工况' ? 'condition' : 'phenomenon', id: p.id, label: p.name, hint: p.anchor?.name ?? '',
                  py: s.phenPy[p.id] ?? '', segmentId: s.opSegment[ops[0]], opId: ops[0], anchorId: p.anchor?.id }
      const sc = score(e, kw)
      if (sc) items.push({ ...e, score: sc })
    }
    items.sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) || b.score - a.score)
    const per: Record<string, number> = {}
    const shown: Any[] = []
    for (const e of items) {
      per[e.kind] = (per[e.kind] ?? 0) + 1
      if (per[e.kind] <= 12) { const { py: _py, score: _sc, ...rest } = e; shown.push(rest) }
    }
    return { items: shown.slice(0, 80), total: items.length, counts: per }
  }
}

export let staticBackend: StaticBackend | null = null

/** 页面里有内嵌数据时进入单文件模式（base64 + gzip 的 JSON）。 */
export async function initStatic(): Promise<boolean> {
  const el = document.getElementById('v2-data')
  if (!el) return false
  const bin = Uint8Array.from(atob((el.textContent ?? '').trim()), (c) => c.charCodeAt(0))
  const stream = new Blob([bin]).stream().pipeThrough(new DecompressionStream('gzip'))
  const text = await new Response(stream).text()
  staticBackend = new StaticBackend(JSON.parse(text))
  el.remove()
  return true
}
