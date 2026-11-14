/**
 * 单文件版的工程态对象编辑：backend/v2/object_edits.py + 限值覆盖（userdata.OverrideStore.set_limit）+ 人工关系（RelationStore）
 * 的浏览器版。编辑存在本浏览器 localStorage（「恢复种子数据」清除），合并到导出时的页签应答上。改后端合并逻辑时要同步改这里。
 */
import { ApiError, type Query } from './client'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

const STORE_KEY = 'v2-static-objedits'
const ATTR = ['基本信息', '设计参数']
const PARAM = ['测量值', '设定值', '阀位', '控制指令', '状态', '计算值']
const BINDING = ['已绑定', '待确认', '未绑定', '失效']
const LIMIT_FIELDS = ['lowLow', 'low', 'normalLow', 'normalHigh', 'high', 'highHigh']
const DRAFT = '草案·待工艺确认'
const KIND = { parameters: '参数', constraints: '参数约束', topology: '拓扑关系' } as Record<string, string>
const REL_TYPES: Record<string, { from: string[]; to: string[]; label: string }> = {
  物理拓扑: { from: ['equipment', 'group'], to: ['equipment', 'group'], label: '串联下游' },
  工艺流向: { from: ['stream', 'equipment', 'group'], to: ['stream', 'equipment', 'group'], label: '流入' },
  供应: { from: ['utility'], to: ['equipment', 'group'], label: '供给介质' }
}
const KIND_NAMES: Record<string, string> = { equipment: '设备', group: '设备组', stream: '物料流股', utility: '公用介质', parameter: '工艺参数', quality: '质量指标' }
const KIND_TYPE: Record<string, string> = { equipment: '生产设备', group: '生产设备', stream: '物料流股', utility: '公用介质' }

// 不在模块加载时调用 ApiError（client.ts → static.ts → 本文件 有循环引用）
const err = (msg: string, status = 400): ApiError => new ApiError(status, msg)
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v))
function now(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export interface EditDeps {
  stamp: string
  tagInfo: (name: string) => Any | null
  endpoints: Any[]              // [id, kind, name, hint, 拼音首字母]
  equipGroup: Record<string, string>
  objectName: (id: string) => string
  isObject: (id: string) => boolean
  tab: (id: string, tab: string) => Any | null   // 导出时的页签应答（未合并）
}

export class ObjEditsLocal {
  private d: EditDeps
  private s: { objects: Record<string, Any>; limits: Record<string, Any>; relations: Any[] } = { objects: {}, limits: {}, relations: [] }

  constructor(deps: EditDeps) {
    this.d = deps
    this.load()
  }
  private load(): void {
    let saved: Any = null
    try { saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null') } catch { saved = null }
    this.s = saved?.stamp === this.d.stamp ? saved.data : { objects: {}, limits: {}, relations: [] }
  }
  reset(): void {
    try { localStorage.removeItem(STORE_KEY) } catch { /* ignore */ }
    this.s = { objects: {}, limits: {}, relations: [] }
  }
  private save(): void {
    try { localStorage.setItem(STORE_KEY, JSON.stringify({ stamp: this.d.stamp, data: this.s })) } catch { /* 只在本次打开内生效 */ }
  }
  private get(oid: string, tab: string): Any {
    return this.s.objects[oid]?.[tab] ?? { added: [], modified: {}, removed: [] }
  }
  private slot(oid: string, tab: string): Any {
    if (!KIND[tab]) throw err(`不支持编辑的页签：${tab}`)
    if (!this.d.isObject(oid)) throw err(`未找到对象：${oid}`, 404)
    return ((this.s.objects[oid] ??= {})[tab] ??= { added: [], modified: {}, removed: [] })
  }

  // ------------------------------------------------------------ 校验（与 object_edits.clean_param / clean_constraint 一致）
  private cleanParam(body: Any): Any {
    const out: Any = {}
    for (const k of ['name', 'category', 'valueType', 'value', 'description', 'tags']) if (k in body) out[k] = body[k]
    if ('name' in out) { out.name = String(out.name ?? '').trim(); if (!out.name) throw err('参数名称不能为空') }
    if ('category' in out && ![...ATTR, ...PARAM].includes(out.category)) throw err(`类别只能是：${[...ATTR, ...PARAM].join('、')}`)
    if ('tags' in out) {
      const raw: string[] = Array.isArray(out.tags) ? out.tags : String(out.tags ?? '').replace(/[，、]/g, ',').split(',')
      out.tags = [...new Set(raw.map((t) => String(t).trim().toUpperCase()).filter(Boolean))]
    }
    return out
  }
  private cleanCons(body: Any): Any {
    const out: Any = {}
    for (const k of ['appliesTo', 'operatingMode', 'unit', 'values', 'note']) if (k in body) out[k] = body[k]
    if ('appliesTo' in out && !String(out.appliesTo ?? '').trim()) throw err('适用参数不能为空')
    if ('values' in out) out.values = this.cleanValues(out.values)
    return out
  }
  private cleanValues(raw: Any): Record<string, number> {
    const vals: Record<string, number> = {}
    for (const f of LIMIT_FIELDS) {
      const v = raw?.[f]
      if (v === null || v === undefined || v === '') continue
      const n = Number(v)
      if (Number.isNaN(n)) throw err(`限值 ${f} 不是数字：${v}`)
      vals[f] = n
    }
    const order = LIMIT_FIELDS.filter((f) => f in vals).map((f) => vals[f])
    if (order.some((v, i) => i > 0 && v < order[i - 1])) throw err('限值要满足 低低限 ≤ 低限 ≤ 正常下限 ≤ 正常上限 ≤ 高限 ≤ 高高限')
    return vals
  }

  // ------------------------------------------------------------ 合并（与 object_edits.merge_* 一致）
  private link(tag: string): Any {
    const t = this.d.tagInfo(tag) ?? {}
    return { tag, desc: t.desc ?? '', unit: t.unit ?? '', block: t.block ?? '', station: '', equipment: t.equipment ?? '', limit: t.limit ?? null, own: true, manual: true }
  }
  private applyParam(x: Any, p: Any): Any {
    for (const f of ['name', 'category', 'valueType', 'value', 'description']) if (f in p) x[f] = p[f]
    if ('tags' in p) x.links = p.tags.map((t: string) => this.link(t))
    if (ATTR.includes(x.category)) Object.assign(x, { section: '属性', group: x.category, binding: null, bindingNote: '' })
    else {
      x.section = '参数'
      if ('tags' in p || x.edit === '新增') {
        const own = (x.links ?? []).filter((l: Any) => l.own !== false)
        const missing = own.filter((l: Any) => !this.d.tagInfo(l.tag)).map((l: Any) => l.tag)
        ;[x.binding, x.bindingNote] = missing.length ? ['失效', `位号不在点表中：${missing.join('、')}`] : own.length ? ['已绑定', '人工绑定'] : ['未绑定', '未关联位号']
      }
    }
    return x
  }
  mergeParameters(resp: Any, oid: string): Any {
    const e = this.get(oid, 'parameters')
    const removed = new Set<string>(e.removed)
    const items: Any[] = []
    const gone: Any[] = []
    for (let x of resp.items) {
      const k = x.name
      if (removed.has(k)) { gone.push({ key: k, name: x.name, category: x.category }); continue }
      x.editKey = k
      if (e.modified[k]) { x = this.applyParam(x, e.modified[k]); x.edit = '已修改' }
      items.push(x)
    }
    for (const a of e.added) {
      const x: Any = { group: a.category, name: '', valueType: '', value: null, description: '', note: '', links: [], edit: '新增', editKey: a.key, userParam: true }
      this.applyParam(x, a)
      x.inherited = false
      x.inheritedFrom = null
      items.push(x)
    }
    const order = [...ATTR, ...PARAM]
    const idx = (c: string) => (order.includes(c) ? order.indexOf(c) : order.length)
    items.sort((a, b) => idx(a.category) - idx(b.category) || (a.semantic ? 0 : 1) - (b.semantic ? 0 : 1))
    const counts = Object.fromEntries(order.map((g) => [g, items.filter((x) => x.category === g).length]))
    return Object.assign(resp, {
      items, removedItems: gone, counts, groups: order.filter((g) => counts[g]),
      attrGroups: ATTR.filter((g) => counts[g]), paramGroups: PARAM.filter((g) => counts[g]),
      bindingCounts: Object.fromEntries(BINDING.map((b) => [b, items.filter((x) => x.binding === b).length])),
      tagTotal: new Set(items.flatMap((x) => (x.links ?? []).filter((l: Any) => l.own).map((l: Any) => l.tag))).size,
      canEdit: true, categories: { 属性: ATTR, 参数: PARAM }
    })
  }
  private consRow(a: Any): Any {
    const v = a.values ?? {}
    const lo = v.normalLow
    const hi = v.normalHigh
    return {
      id: a.key, appliesTo: a.appliesTo ?? '', basis: a.note || '人工新增', operatingMode: a.operatingMode ?? '', modePhenomenon: null,
      alarm: { lowLow: v.lowLow, low: v.low, high: v.high, highHigh: v.highHigh },
      normal: lo !== undefined || hi !== undefined ? `${lo ?? ''}~${hi ?? ''}` : null, hasValues: Object.keys(v).length > 0,
      unit: a.unit ?? '', versions: [], status: DRAFT, limitValues: Object.fromEntries(LIMIT_FIELDS.map((f) => [f, v[f] ?? null])),
      inherited: false, inheritedFrom: null, edit: '新增', editKey: a.key, userConstraint: true, note: a.note ?? ''
    }
  }
  mergeConstraints(resp: Any, oid: string): Any {
    const e = this.get(oid, 'constraints')
    const removed = new Set<string>(e.removed)
    const rows: Any[] = []
    const gone: Any[] = []
    for (const c of resp.operating) {
      if (removed.has(c.id)) { gone.push({ key: c.id, name: `${c.id} ${c.appliesTo ?? ''}` }); continue }
      c.editKey = c.id
      const ov = this.s.limits[`${oid}|${c.id}`]
      if (ov) {
        // 与 tabs._constraints 的覆盖合并一致
        c.inheritState = c.inherited ? (ov.disabled ? '已禁用' : '已覆盖') : '已修改'
        c.override = ov
        c.template = { alarm: c.alarm, normal: c.normal }
        const v = ov.values ?? {}
        if (Object.keys(v).length) {
          const alarm = { ...(c.alarm ?? {}) }
          for (const f of ['lowLow', 'low', 'high', 'highHigh']) if (f in v) alarm[f] = v[f]
          c.alarm = alarm
          if ('normalLow' in v || 'normalHigh' in v) {
            const lo = 'normalLow' in v ? v.normalLow : c.limitValues?.normalLow
            const hi = 'normalHigh' in v ? v.normalHigh : c.limitValues?.normalHigh
            c.normal = `${lo ?? ''}~${hi ?? ''}`
          }
          c.hasValues = true
        }
      }
      rows.push(c)
    }
    rows.push(...e.added.map((a: Any) => this.consRow(a)))
    return Object.assign(resp, { operating: rows, removedItems: gone, canEdit: true, canOverride: true })
  }
  private userTopology(oid: string): Any[] {
    const gid = this.d.equipGroup[oid]
    const out: Any[] = []
    for (const u of this.s.relations) {
      for (const [me, other, direction, role] of [[u.from, u.to, 'out', '下游'], [u.to, u.from, 'in', '上游']] as [Any, Any, string, string][]) {
        if (me.id !== oid && me.id !== gid) continue
        const inherited = me.id === gid && gid !== oid
        out.push({
          relationId: u.id, userRelation: true, category: u.type === '物理拓扑' ? '物理拓扑关系' : u.type, predicate: u.label, direction,
          from: u.from.name, to: u.to.name, target: other.name, targetId: other.id, targetType: KIND_TYPE[other.kind] ?? '生产设备',
          mechanism: u.mechanism ?? '', tags: [], source: `人工新增 · ${u.createdAt}`, role, layer: '人工', status: u.status,
          inherited, inheritedFrom: inherited ? `设备组 ${this.d.objectName(gid)}` : null
        })
      }
    }
    return out
  }
  mergeTopology(resp: Any, oid: string): Any {
    const e = this.get(oid, 'topology')
    const removed = new Set<string>(e.removed)
    const items: Any[] = []
    const gone: Any[] = []
    for (const r of [...resp.items, ...this.userTopology(oid)]) {
      const k = `${r.predicate}|${r.direction}|${r.targetId ?? r.target}`
      if (!r.userRelation && removed.has(k)) {
        gone.push({ key: k, name: `${r.direction === 'out' ? '→' : '←'} ${r.predicate}：${r.target}` })
        continue
      }
      r.editKey = k
      items.push(r)
    }
    return Object.assign(resp, { items, removedItems: gone, canEdit: true })
  }
  /** 页头条目数：按新增 / 移除增减。 */
  patchCounts(oid: string, counts: Any): void {
    for (const t of ['parameters', 'constraints']) {
      const e = this.get(oid, t)
      if (counts[t] !== undefined) counts[t] += e.added.length - e.removed.length
    }
    if (counts.topology !== undefined) counts.topology += this.userTopology(oid).length - this.get(oid, 'topology').removed.length
  }

  // ------------------------------------------------------------ 路由
  handle(method: string, path: string, body: Any, q: Query): Any {
    let m: RegExpMatchArray | null
    const dec = decodeURIComponent
    if ((m = path.match(/^\/objects\/([^/]+)\/edits\/([^/]+)\/restore$/)) && method === 'POST') {
      const s = this.slot(m[1], m[2])
      const key = String(body?.key ?? '')
      s.removed = s.removed.filter((k: string) => k !== key)
      delete s.modified[key]
      this.save()
      return { restored: key }
    }
    if ((m = path.match(/^\/objects\/([^/]+)\/edits\/([^/]+)$/)) && method === 'POST') return this.add(m[1], m[2], body ?? {})
    if ((m = path.match(/^\/objects\/([^/]+)\/edits\/([^/]+)\/(.+)$/))) {
      const [oid, tab, key] = [m[1], m[2], dec(m[3])]
      const s = this.slot(oid, tab)
      if (method === 'PUT') {
        const patch = tab === 'parameters' ? this.cleanParam(body ?? {}) : this.cleanCons(body ?? {})
        if (tab === 'parameters' && patch.name && patch.name !== key) {
          const names = new Set(this.mergeParameters(clone(this.d.tab(oid, 'parameters') ?? { items: [] }), oid).items
            .filter((x: Any) => x.editKey !== key).map((x: Any) => x.name))
          if (names.has(patch.name)) throw err(`本对象已有同名参数：${patch.name}`)
        }
        const added = s.added.find((x: Any) => x.key === key)
        if (added) Object.assign(added, patch, { updatedAt: now() })
        else s.modified[key] = { ...(s.modified[key] ?? {}), ...patch, updatedAt: now() }
        this.save()
        return added ?? s.modified[key]
      }
      if (method === 'DELETE') {
        const i = s.added.findIndex((x: Any) => x.key === key)
        let how = '删除'
        if (i >= 0) s.added.splice(i, 1)
        else { how = '移除'; if (!s.removed.includes(key)) s.removed.push(key); delete s.modified[key] }
        this.save()
        return { result: how, key }
      }
    }
    if ((m = path.match(/^\/objects\/([^/]+)\/overrides\/limits\/([^/]+)$/))) {
      const k = `${m[1]}|${m[2]}`
      if (method === 'DELETE') { const had = !!this.s.limits[k]; delete this.s.limits[k]; this.save(); return { restored: had } }
      const disabled = !!body?.disabled
      if (disabled && !this.d.equipGroup[m[1]]) throw err('只有属于设备组的设备才能覆盖继承来的定义')
      const values = disabled ? {} : this.cleanValues(body?.values ?? {})
      if (!disabled && !Object.keys(values).length) throw err('覆盖时至少填写一个限值，或选择禁用')
      this.s.limits[k] = { objectId: m[1], limitId: m[2], disabled, values, note: body?.note ?? '', updatedAt: now(), updatedBy: '演示用户' }
      this.save()
      return this.s.limits[k]
    }
    if (path === '/relation-candidates') return this.candidates(String(q.type ?? ''), String(q.end ?? 'to'), String(q.keyword ?? ''))
    if (path === '/relations' && method === 'POST') return this.createRelation(body ?? {})
    if ((m = path.match(/^\/relations\/([^/]+)$/))) {
      const rel = this.s.relations.find((r) => r.id === m![1])
      if (!rel) throw err(`未找到关系：${m[1]}`, 404)
      if (method === 'DELETE') { this.s.relations = this.s.relations.filter((r) => r !== rel); this.save(); return { deleted: rel.id } }
      if (method === 'PUT') {
        if ('label' in (body ?? {}) && !String(body.label ?? '').trim()) throw err('关系名称不能为空')
        for (const k of ['label', 'mechanism', 'lag', 'status']) if (k in (body ?? {})) rel[k] = body[k]
        rel.updatedAt = now()
        this.save()
        return rel
      }
    }
    return undefined
  }
  private add(oid: string, tab: string, body: Any): Any {
    if (tab === 'topology') throw err('拓扑关系用「新增关系」')
    const s = this.slot(oid, tab)
    const item = tab === 'parameters' ? this.cleanParam(body) : this.cleanCons(body)
    if (tab === 'parameters') {
      if (!item.name || !item.category) throw err('参数名称和类别必填')
      const names = new Set(this.mergeParameters(clone(this.d.tab(oid, 'parameters') ?? { items: [] }), oid).items.map((x: Any) => x.name))
      if (names.has(item.name)) throw err(`本对象已有同名参数：${item.name}`)
    } else if (!item.appliesTo) throw err('适用参数必填')
    const prefix = tab === 'parameters' ? 'UP' : 'UC'
    const nums = s.added.map((x: Any) => Number(String(x.key).split('-').pop())).filter((n: number) => !Number.isNaN(n))
    const out = { ...item, key: `${prefix}-${String((nums.length ? Math.max(...nums) : 0) + 1).padStart(4, '0')}`, createdAt: now(), createdBy: '演示用户' }
    s.added.push(out)
    this.save()
    return out
  }
  private candidates(type: string, end: string, keyword: string): Any {
    const spec = REL_TYPES[type]
    if (!spec) throw err(`关系类型只能是：${Object.keys(REL_TYPES).join('、')}（单文件版不支持新增工艺影响关系）`)
    const allowed = end === 'from' ? spec.from : spec.to
    const kw = keyword.trim().toLowerCase()
    const items: Any[] = []
    for (const [id, kind, name, hint, py] of this.d.endpoints) {
      if (!allowed.includes(kind)) continue
      if (kw && !String(name).toLowerCase().includes(kw) && !(/^[a-z]+$/.test(kw) && String(py).includes(kw))) continue
      items.push({ id, kind, name, hint, kindName: KIND_NAMES[kind] })
      if (items.length >= 30) break
    }
    return { items, allowed: [...allowed].sort().map((k) => KIND_NAMES[k]) }
  }
  private createRelation(body: Any): Any {
    const type = body.type
    const spec = REL_TYPES[type]
    if (!spec) throw err(`关系类型只能是：${Object.keys(REL_TYPES).join('、')}（单文件版不支持新增工艺影响关系）`)
    const index = new Map(this.d.endpoints.map((e: Any) => [e[0], e]))
    const ends: Any[] = []
    for (const [end, allowed, label] of [[body.from ?? {}, spec.from, '起点'], [body.to ?? {}, spec.to, '终点']] as [Any, string[], string][]) {
      const e = index.get(end.id) as Any
      if (!e) throw err(`${label}对象不存在：${end.name ?? end.id}`)
      if (!allowed.includes(e[1])) throw err(`「${type}」的${label}只能是${allowed.map((k) => KIND_NAMES[k]).join('、')}，「${e[2]}」是${KIND_NAMES[e[1]] ?? e[1]}`)
      ends.push({ id: e[0], name: e[2], kind: e[1] })
    }
    const [src, dst] = ends
    if (src.id === dst.id) throw err('起点和终点不能是同一个对象')
    if (this.s.relations.some((r) => r.type === type && r.from.id === src.id && r.to.id === dst.id)) throw err('这条关系已存在')
    const nums = this.s.relations.map((r) => Number(String(r.id).split('-').pop()))
    const rel = { id: `REL-U-${String((nums.length ? Math.max(...nums) : 0) + 1).padStart(4, '0')}`, type, label: body.label || spec.label,
                  from: src, to: dst, mechanism: body.mechanism ?? '', lag: body.lag ?? '', status: DRAFT, source: '人工新增', createdAt: now(), createdBy: '演示用户' }
    this.s.relations.push(rel)
    this.save()
    return rel
  }
}
