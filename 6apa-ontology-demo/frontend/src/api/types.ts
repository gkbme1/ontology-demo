/** 本体服务返回体类型定义，与 backend/api/routes.py 的契约一一对应。 */

export type SourceType = 'DCS_EXCEL' | 'RELATION_EXCEL' | 'RULE_FILE' | 'MAPPING_FILE' | 'DCS_EXCEL_SCHEMA'

export interface Provenance {
  file: string
  sheet: string
  row?: number
  field?: string
  value?: string
}

export interface Overview {
  productionLine: string
  processAreaCount: number
  controlStationCount: number
  equipmentCount: number
  parameterCount: number
  tagCount: number
  relationCount: number
  relationObjectCount: number
  relationObjectMatchedCount: number
  relationObjectUnmatchedCount: number
  measurementAnchorCount: number
  classCount: number
  categoryCount: number
  coreContentCount: number
  ruleCount: number
  constraintCount: number
  capabilityCount: number
  causalRelationCount: number
  mappingCount: number
  tagStats: { pv: number; op: number; mot: number; val: number; dido: number }
  qualityIssueCount: number
  loadedAt: string
}

export interface OntologyCategory {
  key: string
  index: number
  name: string
  nameEn: string
  core: boolean
  coreIndex?: number
  group: string
  description: string
  endpoint: string
  count: number
}

export interface NodeStyle { type: string; color: string; shape: string }
export interface EdgeStyle { category: string; lineStyle: string; width: number; color: string }

export interface CategoriesPayload {
  categories: OntologyCategory[]
  coreContents: OntologyCategory[]
  nodeStyles: NodeStyle[]
  edgeStyles: EdgeStyle[]
}

export interface ProcessArea {
  id: string
  name: string
  nameZh: string
  nameEn: string | null
  stations: string[]
  equipmentCount: number
  parameterCount: number
  tagCount: number
  relationCount: number
  relationAreaNames: string[]
  sourceType: SourceType
  source: Provenance
}

export interface EquipmentStats { total: number; pv: number; op: number; mot: number; val: number; dido: number }

export interface Equipment {
  id: string
  owlSubject: string
  name: string
  areaId: string | null
  areaName: string | null
  station: string | null
  tagCount: number
  parameterCount: number
  stats: EquipmentStats
  statsFromSheet1: Partial<EquipmentStats> & { totalPoints?: number | null } | null
  overview: string | null
  sourceType: SourceType
  source?: Provenance
  statsSource?: Provenance | null
}

export interface Parameter {
  id: string
  name: string
  equipmentId: string | null
  equipmentName: string | null
  owlSubject: string | null
  areaId: string | null
  areaName: string | null
  station: string | null
  categories: string[]
  units: string[]
  blockTypes: string[]
  tagCount: number
  tagIds: string[]
  sourceType: SourceType
  source?: Provenance
}

export interface DcsTag {
  id: string
  name: string
  rawDescription: string | null
  station: string | null
  areaId: string | null
  areaName: string | null
  equipmentId: string | null
  equipmentName: string | null
  parameterId: string | null
  parameterName: string | null
  parameterType: string | null
  unit: string | null
  blockType: string | null
  owlSubject: string | null
  sourceType: SourceType
  source: Provenance
}

export interface MeasurementAnchor {
  id: string
  semanticName: string
  parameterId: string
  equipmentId: string | null
  equipmentName: string | null
  owlSubject: string | null
  areaId: string | null
  areaName: string | null
  parameterType: string | null
  tagId: string
  tagName: string
  rawDescription: string | null
  blockType: string | null
  unit: string | null
  station: string | null
  relationEntityId?: string
  relationEntityName?: string
  relationEntityType?: string
  sourceType: SourceType
  source: Provenance
}

export interface RelationSide {
  id: string | null
  type: string | null
  entity: string | null
  matchStatus?: string
  matchStatusLabel?: string
  matchCount?: number
}

export interface Relation {
  id: string
  seq: string
  stableKey: string
  area: string | null
  category: string | null
  predicate: string | null
  subject: RelationSide
  object: RelationSide
  subjectType: string | null
  subjectEntity: string | null
  objectType: string | null
  objectEntity: string | null
  domainDescription: string | null
  scenario: string | null
  weight: number | null
  matchStatus: 'MATCHED' | 'PARTIAL' | 'UNMATCHED'
  isCausal: boolean
  dcsAreaId?: string | null
  sourceType: SourceType
  source: Provenance
}

export interface RelationDetail extends Relation {
  subjectDetail: RelationEntity | null
  objectDetail: RelationEntity | null
  sameCategoryRelationIds: string[]
  sameAreaRelationIds: string[]
  sourceTypeLabel: string
}

export interface EntityMatch {
  objectType: 'equipment' | 'parameter' | 'area'
  id: string
  name: string
  owlSubject?: string
  equipmentName?: string
  tagIds?: string[]
  strategy: string
  strategyLabel: string
  confidence?: string
  status?: string
  note?: string
  sourceType: SourceType
  source?: Provenance
  mappingSource?: Provenance
}

export interface RelationEntity {
  id: string
  name: string
  type: string | null
  areas: string[]
  relationCount: number
  outgoingCount: number
  incomingCount: number
  matchStatus: 'MATCHED' | 'UNMATCHED'
  matchStatusLabel: string
  matchStrategy: string
  matchStrategyLabel: string
  matchCount: number
  tagCount: number
  pendingConfirmation: boolean
  sourceType: SourceType
}

export interface RelationEntityDetail extends RelationEntity {
  matches: EntityMatch[]
  matchStrategies: string[]
  measurementAnchors: MeasurementAnchor[]
  outgoingRelations: Relation[]
  incomingRelations: Relation[]
}

export interface GraphNode {
  id: string
  label: string
  type: string | null
  nodeKind: 'relationEntity' | 'equipment' | 'parameter' | 'tag' | 'area'
  matchStatus?: string
  matchStatusLabel?: string
  matchCount?: number
  tagCount?: number
  relationCount?: number
  owlSubject?: string
  isRoot?: boolean
  sourceType: SourceType
  style: { color: string; shape: string }
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  label: string | null
  category: string | null
  area?: string | null
  scenario?: string | null
  weight: number | null
  domainDescription?: string | null
  matchStatus: string
  edgeKind: 'relation' | 'mapping' | 'anchor' | 'tag' | 'structure'
  sourceType: SourceType
  provenance?: Provenance
  style: { color: string; lineStyle: string; width: number; opacity: number }
}

export interface GraphPayload {
  rootId: string | null
  rootType: string | null
  depth: number
  nodes: GraphNode[]
  edges: GraphEdge[]
  nodeCount: number
  edgeCount: number
  truncated: boolean
  maxNodes: number
  nodeStyles: NodeStyle[]
  edgeStyles: EdgeStyle[]
}

export interface Rule {
  id: string
  ruleId: string | null
  name: string | null
  appliesToType: string | null
  appliesTo: string | null
  area: string | null
  condition: string | null
  logic: string | null
  threshold: string | null
  conclusion: string | null
  severity: string | null
  description: string | null
  sourceType: SourceType
  source: Provenance
}

export interface EmptySet {
  items: never[]
  total: 0
  emptyReason: string
  expectedSource: string
  templateColumns?: string[]
  available?: boolean
}

export interface QualityCheck {
  check: string
  group: string
  description: string
  issueCount: number
  passed: boolean
  severity: 'error' | 'warning' | 'info'
}

export interface QualityIssue {
  check: string
  group: string
  severity: 'error' | 'warning' | 'info'
  detail: string
  objectId?: string
  objectName?: string
  source?: Provenance
}

export interface QualityReport {
  summary: {
    checkCount: number
    passedCount: number
    issueCount: number
    errorCount: number
    warningCount: number
    infoCount: number
  }
  checks: QualityCheck[]
  issues: QualityIssue[]
}

export interface DataSource {
  sourceType: SourceType
  sourceTypeLabel: string
  file: string
  status: string
  available: boolean
  loadedAt: string | null
  sheets: { sheet: string; rows: number; validRows: number; errorRows?: number }[]
  stats: Record<string, number>
  note: string | null
}

export interface DataSourcesPayload {
  loadedAt: string
  sources: DataSource[]
  boundary: Record<string, string>
}

export interface Paged<T> { items: T[]; total: number; offset: number }

// ------------------------------------------------------------ 资产本体视图（导航树 + 本体档案）

export type AssetNodeKind = 'domain' | 'area' | 'class' | 'type' | 'group' | 'bucket' | 'equipment' | 'entity'

export interface AssetNode {
  id: string
  label: string
  kind: AssetNodeKind
  hasChildren: boolean
  count?: number
  objectId?: string
  badge?: string
  hint?: string
}

export interface AssetSearchHit {
  objectId: string
  label: string
  kind: AssetNodeKind
  hint: string
  path: string[]
}

export interface DataLink {
  tagId: string
  tag: string
  desc?: string | null
  unit?: string | null
  blockType?: string | null
  station?: string | null
}

export interface ProfileAttribute {
  kind: '固有' | '工艺属性' | '测量' | '状态' | '控制' | string
  name: string
  valueType?: string
  value?: string | number | null
  note?: string | null
  refId?: string | null
  category?: string
  description?: string | null
  dataLinks?: DataLink[]
  dataLinkTotal?: number
  groupLinkTotal?: number
  matchStatus?: string
  pendingConfirmation?: boolean
  inheritedFrom?: string
  entityId?: string
  parameterId?: string
}

export interface ProfileRelation {
  role: string
  category?: string
  predicate?: string
  direction?: 'in' | 'out'
  from?: string
  to?: string
  target: string
  targetId?: string | null
  targetType?: string
  mechanism: string
  tags?: string[]
  source?: string
}

export interface AttributeRelation {
  kind: '计算' | '传递' | '关联' | string
  from: string
  to: string
  predicate: string
  category?: string
  mechanism: string
  source?: string
}

export interface ProfileCapability {
  type: string
  name: string
  status: '已挂载' | '具备挂载点' | '未挂载' | string
  mount: string
  basis: string
}

export interface StructureCheck { text: string; satisfied: boolean; detail: string }

export interface OperatingConstraint {
  id: string
  appliesTo?: string
  parameter?: string
  unit?: string
  operatingMode?: string
  normal?: string | null
  alarm: Record<string, number>
  hasValues?: boolean
  status?: string
  confidence?: string
  basis?: string
  matchedTargets?: string[]
}

export interface ProfileRule {
  id: string
  name?: string
  condition?: string
  conclusion?: string
  severity?: string
  limitRefs?: string[]
  draft?: boolean
  matchedBy?: string
}

export interface EquipmentAlias {
  id: string
  name: string
  owlSubject: string
  station?: string | null
  tagCount: number
  mergeKind: string
  rule?: string
  basis?: string
}

export interface AssetProfile {
  objectId: string
  kind: 'equipment' | 'group' | 'entity' | 'area'
  name: string
  header: {
    className: string
    classPath: string[]
    code?: string | null
    area?: string | null
    station?: string | null
    overview?: string | null
    badges: string[]
    source?: Provenance | null
    aliases?: EquipmentAlias[]
  }
  instances?: { id: string; name: string; tagCount: number; station?: string }[]
  attributes: ProfileAttribute[]
  relations: { classRelations: ProfileRelation[]; attributeRelations: AttributeRelation[] }
  capabilities: ProfileCapability[]
  constraints: { structure: StructureCheck[]; operating: OperatingConstraint[]; safety: { text: string; mechanism: string; source: string }[] }
  rules: ProfileRule[]
  treePath: string[]
  focusTag?: string
}
