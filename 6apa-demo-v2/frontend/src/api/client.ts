/**
 * v2 后端 REST 客户端。页面组件不内置任何设备、测点、现象数据，全部经这里取。
 */
import { staticBackend } from './static'

const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

export type Query = Record<string, string | number | boolean | null | undefined>

function qs(query?: Query): string {
  if (!query) return ''
  const parts: string[] = []
  for (const [k, v] of Object.entries(query)) {
    if (v === null || v === undefined || v === '') continue
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  }
  return parts.length ? `?${parts.join('&')}` : ''
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  if (staticBackend) return staticBackend.handle(method, path, body, query) as Promise<T>
  const res = await fetch(`${BASE}/api/v2${path}${qs(query)}`, {
    method,
    headers: { Accept: 'application/json', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined
  })
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* 非 JSON */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

/** 下载导出文件（Excel / TTL）：取文件名与 X-Export-Info，触发浏览器保存。 */
async function download(path: string, query?: Query): Promise<{ filename: string; info: Any }> {
  if (staticBackend) throw new ApiError(400, '单文件版不支持导出，请在完整版中操作')
  const res = await fetch(`${BASE}/api/v2${path}${qs(query)}`)
  if (!res.ok) {
    let detail = `${res.status}`
    try { detail = (await res.json()).detail } catch { /* ignore */ }
    throw new ApiError(res.status, detail)
  }
  const cd = res.headers.get('Content-Disposition') ?? ''
  const filename = decodeURIComponent((cd.match(/filename\*=UTF-8''([^;]+)/) ?? [])[1] ?? 'export')
  const raw = res.headers.get('X-Export-Info')
  const info = raw ? JSON.parse(decodeURIComponent(raw)) : {}
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  document.body.appendChild(a)  // 部分浏览器要求链接在文档中，下载才会用 download 指定的文件名
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
  return { filename, info }
}

export const api = {
  meta: () => request<Any>('GET', '/meta'),
  navSpace: () => request<Any>('GET', '/nav/space'),
  navSegment: (id: string) => request<Any>('GET', `/nav/segment/${id}`),
  navDomain: (key: string, parent?: string) => request<Any>('GET', `/nav/domain/${key}`, undefined, { parent }),
  globalGraph: () => request<Any>('GET', '/global-graph'),
  scopeConditions: (q: Query) => request<Any>('GET', '/scope/conditions', undefined, q),
  scopeCalculations: (q: Query) => request<Any>('GET', '/scope/calculations', undefined, q),
  scopeDocuments: (q: Query) => request<Any>('GET', '/scope/documents', undefined, q),
  algorithms: () => request<Any>('GET', '/algorithms'),
  validation: () => request<Any>('GET', '/validation'),
  search: (keyword: string) => request<Any>('GET', '/search', undefined, { keyword }),
  segment: (id: string) => request<Any>('GET', `/segments/${id}`),
  op: (id: string) => request<Any>('GET', `/ops/${id}`),
  opDrawing: (id: string) => request<Any>('GET', `/ops/${id}/drawing`),
  opConditions: (id: string) => request<Any>('GET', `/ops/${id}/conditions`),
  opCalculations: (id: string) => request<Any>('GET', `/ops/${id}/calculations`),
  opDocuments: (id: string) => request<Any>('GET', `/ops/${id}/documents`),
  document: (id: string) => request<Any>('GET', `/documents/${id}`),
  object: (id: string, op?: string) => request<Any>('GET', `/objects/${id}`, undefined, { op }),
  objectTab: (id: string, key: string, op?: string) => request<Any>('GET', `/objects/${id}/tabs/${key}`, undefined, { op }),
  objectInfo: (id: string, op?: string) => request<Any>('GET', `/objects/${id}/info`, undefined, { op }),
  objectProfile: (id: string) => request<Any>('GET', `/objects/${id}/profile`),
  objectParameters: (id: string) => request<Any>('GET', `/objects/${id}/parameters`),
  limits: (keyword = '') => request<Any>('GET', '/limits', undefined, { keyword }),
  phenomena: (q: Query) => request<Any>('GET', '/phenomena', undefined, q),
  phenomenon: (id: string) => request<Any>('GET', `/phenomena/${id}`),
  createPhenomenon: (body: Any) => request<Any>('POST', '/phenomena', body),
  updatePhenomenon: (id: string, body: Any) => request<Any>('PUT', `/phenomena/${id}`, body),
  deletePhenomenon: (id: string) => request<Any>('DELETE', `/phenomena/${id}`),
  chain: (id: string, direction: 'up' | 'down' = 'up') => request<Any>('GET', `/phenomena/${id}/chain`, undefined, { direction }),
  evaluate: (id: string, body: Any) => request<Any>('POST', `/phenomena/${id}/evaluate`, body),
  evaluateRule: (body: Any) => request<Any>('POST', '/rules/evaluate', body),
  links: (q: Query) => request<Any>('GET', '/causal-links', undefined, q),
  createLink: (body: Any) => request<Any>('POST', '/causal-links', body),
  updateLink: (id: string, body: Any) => request<Any>('PUT', `/causal-links/${id}`, body),
  deleteLink: (id: string) => request<Any>('DELETE', `/causal-links/${id}`),
  calculations: () => request<Any>('GET', '/calculations'),
  calculation: (id: string) => request<Any>('GET', `/calculations/${id}`),
  calcMeta: () => request<Any>('GET', '/calc-meta'),
  createCalc: (body: Any) => request<Any>('POST', '/calculations', body),
  updateCalc: (id: string, body: Any) => request<Any>('PUT', `/calculations/${id}`, body),
  deleteCalc: (id: string) => request<Any>('DELETE', `/calculations/${id}`),
  runCalc: (id: string, body: Any) => request<Any>('POST', `/calculations/${id}/run`, body),
  overridePhenomenon: (oid: string, pid: string, body: Any) => request<Any>('PUT', `/objects/${oid}/overrides/phenomena/${pid}`, body),
  restorePhenomenon: (oid: string, pid: string) => request<Any>('DELETE', `/objects/${oid}/overrides/phenomena/${pid}`),
  overrideLimit: (oid: string, lid: string, body: Any) => request<Any>('PUT', `/objects/${oid}/overrides/limits/${lid}`, body),
  restoreLimit: (oid: string, lid: string) => request<Any>('DELETE', `/objects/${oid}/overrides/limits/${lid}`),
  relationCandidates: (q: Query) => request<Any>('GET', '/relation-candidates', undefined, q),
  createRelation: (body: Any) => request<Any>('POST', '/relations', body),
  deleteRelation: (id: string) => request<Any>('DELETE', `/relations/${id}`),
  procedure: (id: string) => request<Any>('GET', `/procedures/${id}`),
  updateProcedure: (id: string, body: Any) => request<Any>('PUT', `/procedures/${id}`, body),
  splitCause: (id: string, seq: string, body: Any) => request<Any>('POST', `/procedures/${id}/causes/${seq}/split`, body),
  splitAllCauses: (id: string, body: Any) => request<Any>('POST', `/procedures/${id}/split-all`, body),
  releases: () => request<Any>('GET', '/releases'),
  releasePreview: () => request<Any>('GET', '/releases/preview'),
  publishRelease: (body: Any) => request<Any>('POST', '/releases', body),
  compareReleases: (a: string, b: string) => request<Any>('GET', '/releases/compare', undefined, { a, b }),
  rollbackRelease: (v: string, body: Any) => request<Any>('POST', `/releases/${v}/rollback`, body),
  statusBatch: (body: Any) => request<Any>('POST', '/status-batch', body),
  audit: (q: Query) => request<Any>('GET', '/audit', undefined, q),
  download: (path: string, q?: Query) => download(path, q),
  runtimeStatus: () => request<Any>('GET', '/runtime/status'),
  runtimeEvaluate: (body: Any) => request<Any>('POST', '/runtime/evaluate', body),
  runtimeCauses: (pid: string, target?: string) => request<Any>('GET', `/runtime/causes/${pid}`, undefined, { target }),
  runtimeBindings: () => request<Any>('GET', '/runtime/bindings'),
  knowledge: (status = '') => request<Any>('GET', '/knowledge', undefined, { status }),
  submitKnowledge: (body: Any) => request<Any>('POST', '/knowledge', body),
  reviewKnowledge: (id: string, body: Any) => request<Any>('POST', `/knowledge/${id}/review`, body),
  cl: () => request<Any>('GET', '/classlib'),
  clTree: () => request<Any>('GET', '/classlib/tree'),
  clClass: (id: string) => request<Any>('GET', `/classlib/class/${id}`),
  clClassCreate: (body: Any) => request<Any>('POST', '/classlib/class', body),
  clClassUpdate: (id: string, body: Any) => request<Any>('PUT', `/classlib/class/${id}`, body),
  clClassDelete: (id: string) => request<Any>('DELETE', `/classlib/class/${id}`),
  clItem: (id: string, part: string, code: string, body: Any) => request<Any>('PUT', `/classlib/class/${id}/${part}/${encodeURIComponent(code)}`, body),
  clItemDelete: (id: string, part: string, code: string) => request<Any>('DELETE', `/classlib/class/${id}/${part}/${encodeURIComponent(code)}`),
  clCaps: (id: string, caps: string[]) => request<Any>('PUT', `/classlib/class/${id}/caps`, { caps }),
  clParamTest: (id: string, code: string, body: Any) => request<Any>('POST', `/classlib/class/${id}/params/${encodeURIComponent(code)}/test`, body),
  clPhenPreview: (id: string, code: string) => request<Any>('GET', `/classlib/class/${id}/phenomena/${encodeURIComponent(code)}/preview`),
  clSection: (sec: string) => request<Any>('GET', `/classlib/section/${sec}`),
  clSectionSave: (sec: string, code: string, body: Any) => request<Any>('PUT', `/classlib/section/${sec}/${encodeURIComponent(code)}`, body),
  clSectionDelete: (sec: string, code: string) => request<Any>('DELETE', `/classlib/section/${sec}/${encodeURIComponent(code)}`),
  clHierPreview: () => request<Any>('GET', '/classlib/hierarchy-preview'),
  clMapTest: (body: Any) => request<Any>('POST', '/classlib/mapping-test', body),
  clAlgorithms: () => request<Any>('GET', '/classlib/algorithms'),
  clAlgoTest: (id: string, body: Any) => request<Any>('POST', `/classlib/algorithms/${id}/test`, body),
  clPublish: (note: string) => request<Any>('POST', '/classlib/publish', { note }),
  clNewVersion: (base?: string) => request<Any>('POST', '/classlib/versions', { base }),
  clDiff: (a: string, b: string) => request<Any>('GET', '/classlib/diff', undefined, { a, b }),
  clImport: (body: Any) => request<Any>('POST', '/classlib/import', body),
  resetStore: () => request<Any>('POST', '/admin/reset-store')
}
