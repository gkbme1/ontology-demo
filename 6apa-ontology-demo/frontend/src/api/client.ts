/**
 * 本体服务 REST 客户端。
 *
 * 前端所有数据访问都经过本模块，页面组件不允许内置任何设备、点位、
 * 关系或规则数据（需求文档第二十一、二十四章）。
 */
import type {
  AssetNode, AssetProfile, AssetSearchHit,
  CategoriesPayload, DataSourcesPayload, DcsTag, EmptySet, Equipment,
  GraphPayload, MeasurementAnchor, Overview, Paged, Parameter, ProcessArea,
  QualityReport, Relation, RelationDetail, RelationEntity, RelationEntityDetail, Rule
} from './types'

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
  constructor(public status: number, public path: string, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function get<T>(path: string, query?: Query): Promise<T> {
  const res = await fetch(`${BASE}${path}${qs(query)}`, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new ApiError(res.status, path, `本体服务返回 ${res.status}：${path}`)
  }
  return (await res.json()) as T
}

const P = '/api/ontology'

export const api = {
  health: () => get<{ service: string; status: string }>('/api/health'),

  // 概览与元数据
  overview: () => get<Overview>(`${P}/overview`),
  categories: () => get<CategoriesPayload>(`${P}/categories`),

  // 工段 / 设备 / 参数 / DCS 点
  processAreas: () => get<{ items: ProcessArea[]; total: number }>(`${P}/process-areas`),
  processArea: (areaId: string) =>
    get<ProcessArea & { equipment: Equipment[]; relations: Relation[]; relationCategoryCounts: Record<string, number> }>(
      `${P}/process-areas/${areaId}`
    ),
  equipment: (q?: Query) => get<Paged<Equipment>>(`${P}/equipment`, q),
  equipmentDetail: (id: string) =>
    get<Equipment & {
      area: ProcessArea | null
      parameters: Parameter[]
      tags: DcsTag[]
      relations: Relation[]
      relationEntities: RelationEntity[]
      rules: Rule[]
    }>(`${P}/equipment/${id}`),
  parameters: (q?: Query) => get<Paged<Parameter>>(`${P}/parameters`, q),
  parameterDetail: (id: string) =>
    get<Parameter & {
      equipment: Equipment | null
      tags: DcsTag[]
      measurementAnchors: MeasurementAnchor[]
      relations: Relation[]
      relationEntities: RelationEntity[]
      rules: Rule[]
    }>(`${P}/parameters/${id}`),
  tags: (q?: Query) => get<Paged<DcsTag>>(`${P}/tags`, q),

  // 本体 9 项核心内容
  classes: () => get<{ items: Record<string, unknown>[]; total: number }>(`${P}/classes`),
  properties: () => get<{ items: Record<string, unknown>[]; total: number }>(`${P}/properties`),
  relations: (q?: Query) => get<Paged<Relation>>(`${P}/relations`, q),
  relationDetail: (id: string) => get<RelationDetail>(`${P}/relations/${id}`),
  relationEntities: (q?: Query) => get<{ items: RelationEntity[]; total: number }>(`${P}/relation-entities`, q),
  relationEntityDetail: (id: string) => get<RelationEntityDetail>(`${P}/relation-entities/${id}`),
  graph: (q?: Query) => get<GraphPayload>(`${P}/graph`, q),
  rules: (q?: Query) => get<{ items: Rule[]; total: number } & Partial<EmptySet>>(`${P}/rules`, q),
  constraints: () => get<EmptySet>(`${P}/constraints`),
  capabilities: () => get<EmptySet>(`${P}/capabilities`),
  modelRegistry: () => get<EmptySet>(`${P}/model-registry`),
  semantics: (q?: Query) =>
    get<{
      dcsSemantics: Record<string, unknown>[]
      dcsSemanticTotal: number
      relationSemantics: Record<string, unknown>[]
      relationSemanticTotal: number
    }>(`${P}/semantics`, q),
  measurementAnchors: (q?: Query) =>
    get<{ items: MeasurementAnchor[]; total: number; unanchoredEntities: RelationEntity[] }>(
      `${P}/measurement-anchors`, q
    ),
  causalRelations: () => get<{ items: Relation[]; total: number; categories: string[] }>(`${P}/causal-relations`),

  // 通用对象关系查询：支持 OWL Subject URI / 设备 ID / 参数 ID / 关系对象 ID
  objectRelations: (objectId: string) =>
    get<Record<string, unknown>>(`${P}/${encodeURIComponent(objectId)}/relations`),

  // 资产本体视图：导航树（按需展开）、搜索、对象本体档案
  assetTree: (parent?: string) => get<{ parent: string | null; items: AssetNode[]; total: number }>(`${P}/asset-tree`, { parent }),
  assetSearch: (keyword: string, limit = 30) =>
    get<{ items: AssetSearchHit[]; total: number }>(`${P}/asset-tree/search`, { keyword, limit }),
  assetProfile: (objectId: string) => get<AssetProfile>(`${P}/asset-profile/${encodeURIComponent(objectId)}`),

  // 数据治理
  dataSources: () => get<DataSourcesPayload>(`${P}/data-sources`),
  dataQuality: () => get<QualityReport>(`${P}/data-quality`),
  turtle: () => get<{ lines: string[]; sourceType: string; source: { file: string; sheet: string } }>(`${P}/turtle`)
}

export const API_ENDPOINTS = [
  `${P}/overview`, `${P}/categories`, `${P}/process-areas`, `${P}/process-areas/{id}`,
  `${P}/equipment`, `${P}/equipment/{id}`, `${P}/parameters`, `${P}/parameters/{id}`,
  `${P}/tags`, `${P}/classes`, `${P}/properties`, `${P}/relations`, `${P}/relations/{id}`,
  `${P}/relation-entities`, `${P}/relation-entities/{id}`, `${P}/graph`, `${P}/rules`,
  `${P}/capabilities`, `${P}/constraints`, `${P}/model-registry`, `${P}/semantics`,
  `${P}/measurement-anchors`, `${P}/causal-relations`, `${P}/{id}/relations`,
  `${P}/data-sources`, `${P}/data-quality`,
  `${P}/asset-tree`, `${P}/asset-tree/search`, `${P}/asset-profile/{id}`
]
