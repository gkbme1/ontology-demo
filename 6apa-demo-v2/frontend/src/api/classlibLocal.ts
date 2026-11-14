/**
 * 单文件版的开发态类库：与后端 backend/v2/classlib.py 及 routes.py 的 /classlib/* 接口同一套规则，在浏览器里运行。
 *
 * - 类库数据（种子）随页面内嵌，编辑保存在本浏览器 localStorage（「恢复种子数据」清除）；
 * - 依赖本体实例的数据（类的实例、实例数、点表位号、现象预览用的「参数 → 测点」）在导出时预先算好；
 * - 内置算法的试算在这里重写了一遍（与 backend/v2/algorithms.py 一致）。
 */
import { ApiError, type Query } from './client'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

export interface ClassLibBundle {
  data: Any
  instanceCounts: Record<string, { instances: number }>
  instances: Record<string, Any[]>
  preview: Record<string, { name: string; tags: Record<string, string[]> }[]>
  tags: Record<string, [string, string, string, string]>
  mapSamples: Record<string, string[]>
}

const STORE_KEY = 'v2-static-classlib'
const PARTS: Record<string, string> = { attrs: '属性', params: '参数模板', constraints: '约束模板', phenomena: '现象 / 工况模板',
  causes: '根因模板', influences: '工艺影响模板' }
const SECTIONS: Record<string, string> = { metaclasses: '元类', hierarchyTypes: '层级类型', hierarchyTemplates: '层级模板',
  relationTypes: '关系类型', mappingRules: '映射规则', capabilities: '能力' }
const CONTENT_KEYS = ['metaclasses', 'hierarchyTypes', 'hierarchyTemplates', 'classes', 'relationTypes', 'mappingRules', 'capabilities']
const ENUMS = {
  dtypes: ['文本', '整数', '实数', '布尔', '日期', '枚举', '对象引用', '列表'],
  paramCats: ['测量值', '设定值', '阀位', '控制指令', '状态', '计算值', '设计值'],
  consTypes: ['工艺限值', '安全限值', '设备限值', '质量限值'],
  consSources: ['模板默认值', '取 XBase 报警限', '逻辑约束'],
  statuses: ['草案', '生效', '停用'],
  tabs: ['图纸位置与外观', '参数', '参数约束', '拓扑关系', '现象/工况定义', '根因影响关系', '工艺影响关系', '计算组态', '处置规程']
}
const SEED_REF = '@seed'

// 不在模块加载时继承 ApiError：client.ts → static.ts → 本文件 有循环引用
const err = (msg: string): ApiError => new ApiError(400, msg)
const notFound = (x: string): ApiError => new ApiError(404, `未找到：${x}`)

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v))
}
function canon(v: Any): string {
  if (Array.isArray(v)) return `[${v.map(canon).join(',')}]`
  if (v && typeof v === 'object') return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(',')}}`
  return JSON.stringify(v ?? null)
}
function now(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
function short(v: Any): string {
  const s = v && typeof v === 'object' ? JSON.stringify(v) : v === undefined || v === null ? 'None' : String(v)
  return s.length <= 40 ? s : s.slice(0, 38) + '…'
}
function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}
/** Python re.match：只从开头匹配。 */
function pyRegex(pattern: string): RegExp {
  try {
    return new RegExp(`^(?:${pattern})`)
  } catch (e) {
    throw err(`匹配表达式不合法：${(e as Error).message}`)
  }
}
function* conditions(rule: Any): Generator<Any> {
  if (!rule) return
  if (rule.type === 'group') for (const c of rule.children ?? []) yield* conditions(c)
  else yield rule
}
const splitList = (s: Any): string[] => String(s ?? '').split(/[|/、,，\s]+/).map((x) => x.trim()).filter(Boolean)

export class ClassLibLocal {
  private b: ClassLibBundle
  private stamp: string
  private seedContent: Any
  private algoBase: Any[]
  private ruleText: (r: Any) => string
  private hierPreview: Any
  data: Any

  constructor(bundle: ClassLibBundle, stamp: string, algorithms: Any[], hierPreview: Any, ruleText: (r: Any) => string) {
    this.b = bundle
    this.stamp = stamp
    this.algoBase = algorithms
    this.hierPreview = hierPreview
    this.ruleText = ruleText
    this.seedContent = Object.fromEntries(CONTENT_KEYS.map((k) => [k, bundle.data[k]]))
    this.load()
  }

  // ------------------------------------------------------------ 持久化
  private load(): void {
    let saved: Any = null
    try { saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null') } catch { saved = null }
    this.data = saved?.stamp === this.stamp ? saved.data : clone(this.b.data)
    for (const v of this.data.versions) {
      if (v.snapshot === SEED_REF) v.snapshot = this.seedContent
      else if (v.status === '已发布' && !v.snapshot) v.snapshot = this.seedContent
    }
  }
  reset(): void {
    try { localStorage.removeItem(STORE_KEY) } catch { /* ignore */ }
    this.load()
  }
  private save(): void {
    const data = { ...this.data, versions: this.data.versions.map((v: Any) => (v.snapshot === this.seedContent ? { ...v, snapshot: SEED_REF } : v)) }
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({ stamp: this.stamp, data }))
    } catch {
      console.warn('浏览器存储空间不足：类库修改只在本次打开内有效')
    }
  }

  // ------------------------------------------------------------ 版本
  private get current(): Any {
    return this.data.versions[this.data.versions.length - 1]
  }
  private editable(): void {
    const v = this.current.version
    if (this.current.status !== '编辑中') throw err(`类库 ${v} 已发布，只读；请先「基于 ${v} 新建版本」再修改`)
  }
  private content(): Any {
    return Object.fromEntries(CONTENT_KEYS.map((k) => [k, this.data[k]]))
  }
  private strip(v: Any): Any {
    const { snapshot: _s, ...rest } = v
    return rest
  }
  summary(): Any {
    const d = this.data
    return {
      library: d.library, current: this.strip(this.current), versions: [...d.versions].reverse().map((x: Any) => this.strip(x)),
      counts: { metaclasses: d.metaclasses.length, classes: d.classes.length, relationTypes: d.relationTypes.length,
                mappingRules: d.mappingRules.length, capabilities: d.capabilities.length, hierarchyTypes: d.hierarchyTypes.length,
                hierarchyTemplates: d.hierarchyTemplates.length },
      enums: ENUMS
    }
  }
  private publish(note: string): Any {
    this.editable()
    const v = this.current
    Object.assign(v, { status: '已发布', publishedAt: now(), note: note || v.note || '', snapshot: clone(this.content()) })
    this.save()
    return this.strip(v)
  }
  private newVersion(base?: string): Any {
    if (this.current.status === '编辑中') throw err(`${this.current.version} 仍在编辑中，发布后才能新建版本`)
    const bv = this.data.versions.find((x: Any) => x.version === (base || this.current.version))
    if (!bv?.snapshot) throw err(`版本 ${base} 不存在或没有快照`)
    const m = String(this.current.version).match(/^v(\d+)\.(\d+)/)
    const nv = m ? `v${m[1]}.${Number(m[2]) + 1}` : `${this.current.version}+1`
    for (const [k, val] of Object.entries(clone(bv.snapshot))) this.data[k] = val
    this.data.versions.push({ version: nv, status: '编辑中', createdAt: now(), base: bv.version, note: '' })
    this.save()
    return { version: nv, base: bv.version }
  }
  private versionContent(version: string): Any {
    if (version === 'current') return this.content()
    const v = this.data.versions.find((x: Any) => x.version === version)
    if (!v) throw notFound(version)
    return v.snapshot ?? this.content()
  }
  private diff(a: string, b: string): Any {
    const flatten = (c: Any): Map<string, [string, string, string, Any]> => {
      const out = new Map<string, [string, string, string, Any]>()
      for (const [sec, label] of Object.entries(SECTIONS)) for (const x of c[sec] ?? []) out.set(`${label}\u0000${x.code}`, [label, x.code, x.name || x.code, x])
      for (const cls of c.classes ?? []) {
        const base: Any = {}
        for (const [k, v] of Object.entries(cls)) if (!(k in PARTS) && !['caps', 'updatedAt', 'createdAt'].includes(k)) base[k] = v  // 时间戳不算变更
        out.set(`类\u0000${cls.id}`, ['类', cls.id, cls.name, { ...base, caps: cls.caps }])
        for (const [part, label] of Object.entries(PARTS)) {
          for (const x of cls[part] ?? []) out.set(`${label}\u0000${cls.id}/${x.code}`, [label, `${cls.id}/${x.code}`, `${cls.name} › ${x.name || x.code}`, x])
        }
      }
      return out
    }
    const A = flatten(this.versionContent(a))
    const B = flatten(this.versionContent(b))
    const rows: Any[] = []
    for (const [k, [type, id, name, x]] of B) {
      const prev = A.get(k)
      if (!prev) rows.push({ change: '新增', type, id, name, detail: '' })
      else if (canon(prev[3]) !== canon(x)) {
        const fields = [...new Set([...Object.keys(prev[3]), ...Object.keys(x)])].sort(cmp).filter((f) => canon(prev[3][f]) !== canon(x[f]))
        rows.push({ change: '修改', type, id, name, detail: fields.slice(0, 3).map((f) => `${f}：${short(prev[3][f])} → ${short(x[f])}`).join('；') })
      }
    }
    for (const [k, [type, id, name]] of A) if (!B.has(k)) rows.push({ change: '删除', type, id, name, detail: '' })
    const order: Record<string, number> = { 新增: 0, 修改: 1, 删除: 2 }
    rows.sort((r, s) => order[r.change] - order[s.change] || cmp(r.type, s.type) || cmp(r.id, s.id))
    const counts = Object.fromEntries(Object.keys(order).map((c) => [c, rows.filter((r) => r.change === c).length]))
    return { from: a, to: b, rows, counts }
  }

  // ------------------------------------------------------------ 通用小节
  private section(sec: string): Any[] {
    if (!(sec in SECTIONS)) throw notFound(sec)
    return this.data[sec]
  }
  private upsert(sec: string, code: string, body: Any): Any {
    this.editable()
    const items = this.section(sec)
    body = { ...body, code: String(body.code || code).trim() }
    if (!body.code || !String(body.name ?? '').trim()) throw err('编码和名称不能为空')
    const old = items.find((x) => x.code === code)
    if (body.code !== code && items.some((x) => x.code === body.code)) throw err(`编码已存在：${body.code}`)
    if ((sec === 'metaclasses' || sec === 'relationTypes') && old?.preset) body.preset = true
    if (sec === 'mappingRules' && body.pattern) pyRegex(body.pattern)
    if (old) items[items.indexOf(old)] = { ...old, ...body }
    else items.push({ preset: false, ...body })
    this.save()
    return items.find((x) => x.code === body.code)
  }
  private remove(sec: string, code: string): Any {
    this.editable()
    const items = this.section(sec)
    const old = items.find((x) => x.code === code)
    if (!old) throw notFound(code)
    if (old.preset && (sec === 'metaclasses' || sec === 'relationTypes')) throw err(`预置${SECTIONS[sec]}不可删除`)
    if (sec === 'metaclasses') {
      const refs = this.data.classes.filter((c: Any) => c.metaclass === code).map((c: Any) => c.name)
      if (refs.length) throw err(`有类引用该元类，不能删除：${refs.slice(0, 5).join('、')}`)
    }
    if (sec === 'hierarchyTypes') {
      const refs = this.data.hierarchyTemplates.filter((t: Any) => (t.levels ?? []).includes(code)).map((t: Any) => t.name)
      if (refs.length) throw err(`层级模板引用了该层级类型：${refs.join('、')}`)
    }
    if (sec === 'capabilities') for (const c of this.data.classes) if (c.caps?.includes(code)) c.caps = c.caps.filter((x: string) => x !== code)
    items.splice(items.indexOf(old), 1)
    this.save()
    return old
  }

  // ------------------------------------------------------------ 类
  private cls(cid: string): Any {
    const c = this.data.classes.find((x: Any) => x.id === cid)
    if (!c) throw notFound(cid)
    return c
  }
  private chain(cid: string): Any[] {
    const out: Any[] = []
    const seen = new Set<string>()
    let c: Any = this.cls(cid)
    while (c && !seen.has(c.id)) {
      seen.add(c.id)
      out.unshift(c)
      c = c.parent ? this.cls(c.parent) : null
    }
    return out
  }
  private effective(cid: string, part: string): Any[] {
    const merged = new Map<string, Any>()
    for (const c of this.chain(cid)) {
      const own = c.id === cid
      for (const x of c[part] ?? []) {
        const prev = merged.get(x.code)
        const src = own && !prev ? '本类' : prev && own ? `覆盖：${prev._srcName}` : `继承：${c.name}`
        merged.set(x.code, { ...x, _src: src, _srcName: c.name, _own: own })
      }
    }
    return [...merged.values()]
  }
  private instancesOf(c: Any): Any[] {
    return c.abstract ? [] : this.b.instances[c.id] ?? []
  }
  private instanceCounts(): Record<string, { instances: number }> {
    const out: Record<string, { instances: number }> = {}
    for (const c of this.data.classes) {
      const n = this.b.instanceCounts[c.id]
      if (n && (!c.abstract || (c.parent == null && c.metaclass !== 'MC_EQUIP'))) out[c.id] = n
    }
    return out
  }
  private tree(): Any[] {
    const counts = this.instanceCounts()
    const kids = new Map<string | null, Any[]>()
    for (const c of this.data.classes) {
      const k = c.parent ?? null
      if (!kids.has(k)) kids.set(k, [])
      kids.get(k)!.push(c)
    }
    const order = (a: Any, b: Any) => (a.order ?? 99) - (b.order ?? 99)
    const node = (c: Any): Any => {
      const ch = [...(kids.get(c.id) ?? [])].sort(order).map(node)
      return { id: c.id, name: c.name, code: c.code, abstract: c.abstract, status: c.status, metaclass: c.metaclass, children: ch,
               instances: (counts[c.id]?.instances ?? 0) + ch.reduce((s: number, k: Any) => s + k.instances, 0) }
    }
    return [...(kids.get(null) ?? [])].sort(order).map(node)
  }
  private classView(cid: string): Any {
    const c = this.cls(cid)
    const chain = this.chain(cid)
    const parts = Object.fromEntries(Object.keys(PARTS).map((p) => [p, this.effective(cid, p)]))
    const own = new Set<string>(c.caps ?? [])
    const inherited = new Set<string>(chain.slice(0, -1).flatMap((k) => k.caps ?? []))
    const caps = this.data.capabilities.filter((x: Any) => own.has(x.code) || inherited.has(x.code))
      .map((x: Any) => ({ ...x, _src: own.has(x.code) ? '本类' : '继承' }))
    const meta = this.data.metaclasses.find((m: Any) => m.code === c.metaclass) ?? {}
    const prev = [...this.data.versions].reverse().find((v: Any) => v.status === '已发布')?.version ?? null
    let changes = 0
    if (prev && prev !== this.current.version) changes = this.diff(prev, 'current').rows.filter((r: Any) => r.id === cid || r.id.startsWith(cid + '/')).length
    const base: Any = {}
    for (const [k, v] of Object.entries(c)) if (!(k in PARTS)) base[k] = v
    return {
      ...clone(base), path: chain.map((x) => ({ id: x.id, name: x.name, abstract: x.abstract })),
      metaclassName: meta.name, tabsEffective: c.tabs?.length ? c.tabs : meta.tabs ?? [],
      parts, caps, instances: this.instancesOf(c),
      summary: Object.fromEntries(Object.entries(parts).map(([p, v]) => [p, { own: v.filter((x: Any) => x._own).length, inherited: v.filter((x: Any) => !x._own).length }])),
      version: { current: this.current.version, status: this.current.status, since: prev, changes, updatedAt: c.updatedAt }
    }
  }
  private upsertClass(cid: string | null, body: Any): Any {
    this.editable()
    const name = String(body.name ?? '').trim()
    const code = String(body.code ?? '').trim()
    if (!name || !code) throw err('类编码和类名称不能为空')
    if (this.data.classes.some((c: Any) => c.code === code && c.id !== cid)) throw err(`类编码已存在：${code}`)
    const parent = body.parent || null
    if (parent) {
      this.cls(parent)
      if (cid && this.chain(parent).some((c) => c.id === cid)) throw err('父类不能是本类或本类的子类（单继承、不能成环）')
    }
    if (!this.data.metaclasses.some((m: Any) => m.code === body.metaclass)) throw err('所属元类不存在')
    const fields = ['code', 'name', 'metaclass', 'parent', 'abstract', 'status', 'icon', 'desc', 'tabs']
    let c: Any
    if (cid) {
      c = this.cls(cid)
      for (const k of fields) if (k in body) c[k] = body[k]
      c.parent = parent
    } else {
      let id = 'cls-' + code.replace(/[^A-Za-z0-9-]/g, '').toLowerCase()
      if (this.data.classes.some((x: Any) => x.id === id)) id += `-${this.data.classes.length}`
      c = { id, ...Object.fromEntries(fields.map((k) => [k, body[k] ?? null])), parent, status: body.status || '草案',
            attrs: [], params: [], constraints: [], phenomena: [], causes: [], influences: [], caps: [], createdAt: now() }
      this.data.classes.push(c)
    }
    c.updatedAt = now()
    this.save()
    return clone(c)
  }
  private deleteClass(cid: string): Any {
    this.editable()
    const c = this.cls(cid)
    const kids = this.data.classes.filter((x: Any) => x.parent === cid).map((x: Any) => x.name)
    if (kids.length) throw err(`存在子类，不能删除：${kids.slice(0, 6).join('、')}`)
    const n = this.instancesOf(c).reduce((s: number, i: Any) => s + i.members + 1, 0)
    if (n) throw err(`存在 ${n} 个实例，不能删除`)
    this.data.classes.splice(this.data.classes.indexOf(c), 1)
    this.save()
    return { deleted: cid }
  }
  private upsertItem(cid: string, part: string, code: string, body: Any): Any {
    this.editable()
    if (!(part in PARTS)) throw notFound(part)
    const c = this.cls(cid)
    const items: Any[] = (c[part] ??= [])
    body = Object.fromEntries(Object.entries(body).filter(([k]) => !k.startsWith('_')))
    body.code = String(body.code || code).trim()
    if (!body.code) throw err('编码不能为空')
    if (['attrs', 'params', 'phenomena'].includes(part) && !String(body.name ?? '').trim()) throw err('名称不能为空')
    if (part === 'attrs') {
      const inh = this.effective(cid, 'attrs').find((x) => x.code === body.code && !x._own)
      if (inh && body.dtype && body.dtype !== inh.dtype) throw err(`属性 ${body.code} 继承自「${inh._srcName}」，子类不可修改数据类型（${inh.dtype}）`)
    }
    if (part === 'constraints') {
      const raw = ['ll', 'l', 'nl', 'nh', 'h', 'hh'].map((k) => body[k]).filter((v) => v !== undefined && v !== null && v !== '')
      const vals = raw.map(Number)
      if (vals.some((v) => isNaN(v))) throw err('限值要填数字')
      if (vals.some((v, i) => i > 0 && v < vals[i - 1])) throw err('限值要满足 低低 ≤ 低 ≤ 正常下 ≤ 正常上 ≤ 高 ≤ 高高')
      if (body.source === '逻辑约束' && !String(body.expr ?? '').trim()) throw err('逻辑约束要填写表达式，如 P_OUT > P_IN')
    }
    if (part === 'causes') {
      const names = new Set(this.effective(cid, 'phenomena').map((p) => p.name))
      if (body.cause === body.effect) throw err('原因和结果不能是同一个现象模板')
      if (!names.has(body.effect) && !names.has(body.cause)) throw err('原因或结果至少有一个是本类（含继承）的现象模板')
    }
    const old = items.find((x) => x.code === code)
    if (old) {
      if (body.code !== code && items.some((x) => x.code === body.code)) throw err(`编码已存在：${body.code}`)
      items[items.indexOf(old)] = body
    } else {
      if (items.some((x) => x.code === body.code)) throw err(`编码已存在：${body.code}`)
      items.push(body)
    }
    c.updatedAt = now()
    this.save()
    return clone(body)
  }
  private deleteItem(cid: string, part: string, code: string): Any {
    this.editable()
    const c = this.cls(cid)
    const old = (c[part] ?? []).find((x: Any) => x.code === code)
    if (!old) {
      const inh = this.effective(cid, part).find((x) => x.code === code)
      throw err(inh ? `「${code}」继承自「${inh._srcName}」，请在父类中删除，或在本类覆盖` : `未找到 ${code}`)
    }
    c[part].splice(c[part].indexOf(old), 1)
    this.save()
    return { deleted: code }
  }
  private setCaps(cid: string, caps: string[]): Any {
    this.editable()
    const known = new Set(this.data.capabilities.map((x: Any) => x.code))
    const bad = caps.filter((x) => !known.has(x))
    if (bad.length) throw err(`能力不存在：${bad.join('、')}`)
    this.cls(cid).caps = caps
    this.save()
    return { caps }
  }

  // ------------------------------------------------------------ 试验
  private tag(name: string): Any {
    const t = this.b.tags[String(name).toUpperCase()] ?? this.b.tags[name]
    return t ? { name: t[0], desc: t[1], equipment: t[2], variable: t[3] } : null
  }
  private paramTest(cid: string, code: string, body: Any): Any {
    const tpl = this.effective(cid, 'params').find((x) => x.code === code)
    if (!tpl) throw notFound(code)
    const raw = String(body.tag ?? '').trim()
    const t = this.tag(raw)
    const tag = t?.name ?? raw
    const desc: string = body.desc || t?.desc || ''
    const rule = tpl.tagRule ?? {}
    const funcs = splitList(rule.funcs).map((f) => f.toUpperCase())
    const kws = splitList(rule.keywords)
    const prefix = (tag.match(/^[A-Za-z]+/)?.[0] ?? '').toUpperCase()
    const fOk = funcs.length > 0 && funcs.includes(prefix)
    const kHit = kws.filter((k) => desc.includes(k))
    const conf = Math.round(((fOk ? 0.55 : 0) + (kHit.length ? 0.4 : 0) + (fOk && kHit.length === kws.length ? 0.04 : 0)) * 100) / 100
    const dims = (tpl.dims ?? []).map((d: Any) => ({ name: d.name, value: (d.values ?? []).find((v: string) => v && desc.includes(v)) ?? null }))
    return { tag, desc, prefix, funcOk: fOk, keywords: kHit, keywordsAll: kws, funcs, dims, confidence: conf, matched: conf >= 0.55,
             template: tpl.name, equipment: t?.equipment ?? null }
  }
  private phenPreview(cid: string, code: string): Any {
    const tpl = this.effective(cid, 'phenomena').find((x) => x.code === code)
    if (!tpl) throw notFound(code)
    const inst = this.instancesOf(this.cls(cid))
    if (!inst.length) return { instance: null, lines: [], note: '本类暂无实例' }
    const conds = [...conditions(tpl.rule)]
    const names = conds.filter((c) => c.subject?.kind === 'parameter').map((c) => c.subject.name ?? '')
    const members = this.b.preview[cid] ?? []
    const member = members.find((m) => names.some((n) => m.tags[n]?.length)) ?? members[0] ?? { name: inst[0].name, tags: {} }
    const lines = conds.map((c) => c.subject?.kind === 'parameter'
      ? { text: this.ruleText(c), tags: member.tags[c.subject.name ?? ''] ?? ['（本台未落到测点）'] }
      : { text: this.ruleText(c), tags: [] })
    return { instance: inst[0].name, member: member.name, lines, ruleText: tpl.rule ? this.ruleText(tpl.rule) : '（判定规则待定义）' }
  }
  private mappingTest(body: Any): Any {
    const rule = this.data.mappingRules.find((r: Any) => r.code === body.code)
    if (!rule) throw notFound(String(body.code))
    const raw: string[] = body.samples?.length ? body.samples : this.b.mapSamples[rule.kind] ?? []
    const samples = raw.map((s) => {
      const t = this.tag(s)
      return { tag: t?.name ?? s, desc: t?.desc ?? '', equipment: t?.equipment ?? '', variable: t?.variable ?? '' }
    })
    const rx = pyRegex(rule.pattern || '^$')
    const funcMap: Record<string, string> = this.data.library?.funcMap ?? {}
    const segs: string[] = rule.segments ?? []
    const results = samples.map((s) => {
      const m = rx.exec(s.tag)
      if (!m) return { ...s, matched: false, parsed: [], confidence: null }
      const parsed = m.slice(1).map((g, i) => {
        const label = i < segs.length ? segs[i] : `$${i + 1}`
        return { label, value: g ?? null, meaning: label.includes('功能') ? funcMap[g ?? ''] ?? '' : '' }
      })
      const conf = 0.6 + (parsed.some((p) => p.meaning) ? 0.2 : 0) + (s.equipment ? 0.15 : 0)
      return { ...s, matched: true, parsed, confidence: Math.round(Math.min(conf, 0.98) * 100) / 100 }
    })
    const names = Object.keys(this.b.tags)
    const hits = rule.pattern && rule.kind === '位号解析' ? names.filter((n) => rx.test(n)).length : 0
    return { rule, results, hits, total: names.length }
  }
  private algorithms(): Any {
    const caps = this.data.capabilities
    return { items: this.algoBase.map((a) => ({ ...a, usedByCaps: caps.filter((c: Any) => c.algorithm === a.id).map((c: Any) => c.code) })) }
  }
  private algoTest(aid: string, body: Any): Any {
    const algo = this.algoBase.find((a) => a.id === aid)
    if (!algo) throw notFound(aid)
    const args: Any = {}
    const log: string[] = []
    for (const inp of algo.inputs ?? []) {
      let v = (body.inputs ?? {})[inp.name]
      if (v === undefined || v === null) {
        if (inp.default !== undefined && inp.default !== null) v = inp.default
        else if (inp.required) throw err(`缺少输入 ${inp.name}（${inp.label}）`)
        else continue
      }
      args[inp.name] = v
      log.push(`输入 ${inp.name} = ${JSON.stringify(v)}`)
    }
    const t0 = performance.now()
    let values: number[] = []
    let ok = true
    let error = ''
    try {
      values = runAlgorithm(aid, args, Number(body.stepMin) || 1).slice(0, 200).map((x) => Math.round(x * 1e4) / 1e4)
      if (values.some((x) => isNaN(x))) throw new Error('输入数据不是数字')
    } catch (e) {
      ok = false
      error = (e as Error).message
      values = []
    }
    return { ok, error, output: { [algo.output?.name || 'out']: values }, ms: Math.round(performance.now() - t0),
             log: [...log, '运行环境：单文件版浏览器内置实现（与完整版内置实现一致）'] }
  }

  // ------------------------------------------------------------ 工程绑定的类库版本（与 classlib.binding / upgrade_impact 一致）
  private binding(): Any {
    const vs = this.data.versions
    const bound = this.data.library?.boundVersion ?? vs.find((v: Any) => v.status === '已发布')?.version ?? vs[0].version
    const idx = Math.max(0, vs.findIndex((v: Any) => v.version === bound))
    const ed = vs.find((v: Any) => v.status === '编辑中')
    return { project: '105车间', library: this.data.library.name, bound: this.strip(vs[idx]),
             newer: vs.slice(idx + 1).filter((v: Any) => v.status === '已发布').map((v: Any) => this.strip(v)),
             published: vs.filter((v: Any) => v.status === '已发布').map((v: Any) => this.strip(v)), editing: ed ? this.strip(ed) : null }
  }
  private upgradeImpact(to: string): Any {
    const b = this.binding()
    const frm = b.bound.version
    if (to === frm) throw err('目标版本就是工程当前使用的版本')
    const target = this.data.versions.find((v: Any) => v.version === to)
    if (!target || target.status !== '已发布') throw err('只能切换到已发布的类库版本')
    const d = this.diff(frm, to)
    const classes: Record<string, Any> = {}
    for (const c of [...this.versionContent(to).classes, ...this.versionContent(frm).classes]) classes[c.id] = c
    const kids: Record<string, string[]> = {}
    for (const c of Object.values(classes)) if (c.parent) (kids[c.parent] ??= []).push(c.id)
    const insts = (cid: string): Any[] => {
      const out: Any[] = []
      const stack = [cid]
      while (stack.length) {
        const x = stack.pop()!
        if (classes[x]) out.push(...this.instancesOf(classes[x]))
        stack.push(...(kids[x] ?? []))
      }
      return out
    }
    const partLabels = new Set(Object.values(PARTS))
    const conflictTypes = new Set(['约束模板', '现象 / 工况模板', '根因模板'])
    const groups: Record<string, Any[]> = { auto: [], conflict: [], manual: [] }
    const affected = new Set<string>()
    for (const r of d.rows) {
      const cid = r.type === '类' ? r.id : partLabels.has(r.type) ? r.id.split('/')[0] : null
      const inst = cid ? insts(cid) : []
      const row: Any = { ...r, className: cid ? classes[cid]?.name ?? null : null,
        instances: inst.slice(0, 6).map((i) => ({ id: i.id, name: i.name, members: i.members })),
        instanceCount: inst.length, memberCount: inst.reduce((s, i) => s + i.members, 0), options: [] }
      let g = 'auto'
      if (!cid) row.reason = '全局定义变化（元模型 / 层级 / 关系类型 / 映射规则 / 能力），不直接改动实例数据'
      else if (!inst.length) row.reason = '该类在本工程没有实例，不影响现有数据'
      else if (r.change === '新增') row.reason = '新增项，本工程该类的实例将获得此项'
      else if (r.change === '删除') { g = 'manual'; row.reason = '类库删除了该项，本工程实例仍在使用'; row.options = ['保留为本工程自有', '一并删除'] }
      else if (r.type === '属性' && String(r.detail ?? '').includes('dtype')) { g = 'manual'; row.reason = '属性数据类型变化，已有实例值需人工转换'; row.options = ['人工确认后转换', '暂不升级此项'] }
      else if (conflictTypes.has(r.type)) { g = 'conflict'; row.reason = '工程态可能已在设备组 / 设备上覆盖或调整，需选择保留哪一边'; row.options = ['保留工程值', '采用类库值'] }
      else row.reason = '实例未单独覆盖时直接同步'
      if (g !== 'auto' || cid) for (const i of inst) affected.add(i.id)
      groups[g].push(row)
    }
    return { project: b.project, from: frm, to, groups, counts: Object.fromEntries(Object.entries(groups).map(([k, v]) => [k, v.length])),
             affectedGroups: affected.size, diffCounts: d.counts }
  }

  private importPkg(body: Any): Any {
    this.editable()
    const pkg = body.package ?? {}
    if (pkg.format !== '6apa-classlib/1') throw err('不是本系统导出的类库包')
    const strategy = body.strategy || 'skip'
    const stats = { added: 0, merged: 0, skipped: 0 }
    const merge = (list: Any[], incoming: Any[], k: string) => {
      for (const x of incoming ?? []) {
        const i = list.findIndex((y) => y[k] === x[k])
        if (i < 0) { list.push(x); stats.added++ } else if (strategy === 'merge') { list[i] = x; stats.merged++ } else stats.skipped++
      }
    }
    for (const sec of Object.keys(SECTIONS)) merge(this.data[sec], pkg[sec], 'code')
    merge(this.data.classes, pkg.classes, 'id')
    this.save()
    return { ...stats, strategy }
  }
  exportPkg(): { filename: string; text: string } {
    const pkg = { format: '6apa-classlib/1', library: this.data.library, version: this.current.version,
                  exportedAt: new Date().toISOString().slice(0, 19), ...this.content() }
    return { filename: `类库包_${this.current.version}.json`, text: JSON.stringify(pkg, null, 1) }
  }

  // ------------------------------------------------------------ 路由（与 routes.py 的 /classlib/* 一致）
  handle(method: string, path: string, body: Any, q: Query): Any {
    let m: RegExpMatchArray | null
    const dec = decodeURIComponent
    if (path === '/classlib' && method === 'GET') return clone(this.summary())
    if (path === '/classlib/tree') return { items: this.tree() }
    if (path === '/classlib/class' && method === 'POST') return this.upsertClass(null, body ?? {})
    if ((m = path.match(/^\/classlib\/class\/([^/]+)$/))) {
      if (method === 'GET') return this.classView(m[1])
      if (method === 'PUT') return this.upsertClass(m[1], body ?? {})
      if (method === 'DELETE') return this.deleteClass(m[1])
    }
    if ((m = path.match(/^\/classlib\/class\/([^/]+)\/caps$/)) && method === 'PUT') return this.setCaps(m[1], (body?.caps ?? []).map(String))
    if ((m = path.match(/^\/classlib\/class\/([^/]+)\/params\/([^/]+)\/test$/))) return this.paramTest(m[1], dec(m[2]), body ?? {})
    if ((m = path.match(/^\/classlib\/class\/([^/]+)\/phenomena\/([^/]+)\/preview$/))) return this.phenPreview(m[1], dec(m[2]))
    if ((m = path.match(/^\/classlib\/class\/([^/]+)\/([^/]+)\/([^/]+)$/))) {
      if (method === 'PUT') return this.upsertItem(m[1], m[2], dec(m[3]), body ?? {})
      if (method === 'DELETE') return this.deleteItem(m[1], m[2], dec(m[3]))
    }
    if ((m = path.match(/^\/classlib\/section\/([^/]+)$/))) {
      const items = clone(this.section(m[1]))
      const out: Any = { items }
      if (m[1] === 'metaclasses') out.usage = Object.fromEntries(items.map((x: Any) => [x.code, this.data.classes.filter((c: Any) => c.metaclass === x.code).length]))
      if (m[1] === 'capabilities') out.classNames = Object.fromEntries(this.data.classes.map((c: Any) => [c.id, c.name]))
      return out
    }
    if ((m = path.match(/^\/classlib\/section\/([^/]+)\/([^/]+)$/))) {
      if (method === 'PUT') return clone(this.upsert(m[1], dec(m[2]), body ?? {}))
      if (method === 'DELETE') { this.remove(m[1], dec(m[2])); return { deleted: dec(m[2]) } }
    }
    if (path === '/classlib/hierarchy-preview') return clone(this.hierPreview)
    if (path === '/classlib/mapping-test') return this.mappingTest(body ?? {})
    if (path === '/classlib/algorithms') return this.algorithms()
    if ((m = path.match(/^\/classlib\/algorithms\/([^/]+)\/test$/))) return this.algoTest(dec(m[1]), body ?? {})
    if (path === '/classlib/publish') return this.publish(String(body?.note ?? ''))
    if (path === '/classlib/versions' && method === 'POST') return this.newVersion(body?.base)
    if (path === '/classlib/diff') return this.diff(String(q.a ?? ''), String(q.b ?? 'current'))
    if (path === '/classlib/binding') return this.binding()
    if (path === '/classlib/upgrade-impact') return this.upgradeImpact(String(q.to ?? ''))
    if (path === '/classlib/import') return this.importPkg(body ?? {})
    throw new ApiError(404, `未找到接口：${method} ${path}`)
  }
}

// ------------------------------------------------------------------ 内置算法（与 backend/v2/algorithms.py 一致）
type Vec = number[]
const toMat = (v: Any): Vec[] => (Array.isArray(v) && Array.isArray(v[0]) ? v : [Array.isArray(v) ? v : [v]]).map((r: Any[]) => r.map(Number))
const colwise = (mat: Vec[], f: (col: number[]) => number): Vec => mat[0].map((_, j) => f(mat.map((r) => r[j])))
const windowOf = (args: Any, step: number): number => Math.max(1, Math.round(Number(args.windowMin || 10) / step))
function rollingSum(x: Vec, w: number): Vec {
  const c = [0]
  for (const v of x) c.push(c[c.length - 1] + v)
  return x.map((_, i) => c[i + 1] - c[Math.max(0, i + 1 - w)])
}
function dropsPerStep(values: Vec, deadband: number): Vec {
  const out = new Array(values.length).fill(0)
  let anchor = values[0]
  for (let i = 1; i < values.length; i++) {
    const v = values[i]
    if (v < anchor - deadband) { out[i] = anchor - v; anchor = v } else if (v > anchor + deadband) anchor = v
  }
  return out
}
function runAlgorithm(aid: string, args: Any, step: number): Vec {
  switch (aid) {
    case 'ALG-LEVEL-CONSUMPTION': {
      const mat = toMat(args.level)
      const w = windowOf(args, step)
      const total = new Array(mat[0].length).fill(0)
      for (const row of mat) {
        const span = Math.max(...row) - Math.min(...row)
        const db = span > 0 ? span * Number(args.deadbandRatio || 0.01) : 0
        rollingSum(dropsPerStep(row, db), w).forEach((v, i) => (total[i] += v))
      }
      return total.map((v) => v / (w * step))
    }
    case 'ALG-RATE': {
      const row = colwise(toMat(args.series), (c) => c.reduce((s, v) => s + v, 0) / c.length)
      const w = windowOf(args, step)
      return row.map((v, i) => (v - (i - w >= 0 ? row[i - w] : row[0])) / (w * step))
    }
    case 'ALG-ABS-DIFF': {
      const a = toMat(args.a)[0]
      const b = toMat(args.b)[0]
      if (a.length !== b.length) throw new Error(`两组数据长度不一致（${a.length} / ${b.length}）`)
      return a.map((v, i) => Math.abs(v - b[i]))
    }
    case 'ALG-MEAN': return colwise(toMat(args.series), (c) => c.reduce((s, v) => s + v, 0) / c.length)
    case 'ALG-RANGE': return colwise(toMat(args.series), (c) => Math.max(...c) - Math.min(...c))
    case 'ALG-SUM': return colwise(toMat(args.series), (c) => c.reduce((s, v) => s + v, 0))
    default: throw new Error(`算法 ${aid} 没有内置实现`)
  }
}
