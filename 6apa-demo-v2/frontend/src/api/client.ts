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
  resetStore: () => request<Any>('POST', '/admin/reset-store')
}
