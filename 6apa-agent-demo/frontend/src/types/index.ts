/** Agent SSE 事件与视图模型的类型定义。与后端 backend/agent/events.py 一一对应。 */

export type AgentEventType =
  | 'turn_start'
  | 'status'
  | 'tool_call'
  | 'tool_result'
  | 'graph'
  | 'answer_delta'
  | 'answer_reset'
  | 'answer'
  | 'context'
  | 'error'
  | 'done'

export interface AgentEvent {
  type: AgentEventType
  data: Record<string, unknown>
}

export interface ToolCallView {
  callId: string
  tool: string
  label: string
  arguments: Record<string, unknown>
  status: 'running' | 'ok' | 'empty' | 'error'
  httpStatus?: number | null
  url?: string
  durationMs?: number
  rawBytes?: number
  truncated?: boolean
  truncationNote?: string
  resultSummary?: string
  resultPreview?: string | null
  error?: string | null
  hasGraph?: boolean
}

export interface TraceStep {
  kind: 'status' | 'tool'
  id: string
  text: string
  done: boolean
  tool?: ToolCallView
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  steps?: TraceStep[]
  stats?: TurnStats | null
  error?: string | null
}

export interface TurnStats {
  toolCalls: number
  llmRounds: number
  elapsedMs: number
  ok: boolean
}

export interface GraphNode {
  id: string
  label: string
  type?: string
  nodeKind?: string
  relationCount?: number
  isRoot?: boolean
}

export interface GraphEdge {
  source: string
  target: string
  predicate?: string
  category?: string
  weight?: number
}

export interface GraphPayload {
  callId: string
  tool: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  rootId?: string
  depth?: number
  truncated?: boolean
}

export interface EntityRef {
  kind: string
  label: string
  id: string
  name: string
  fromTool: string
}

export interface ConversationContext {
  conversationId: string
  turn: number
  currentTask: string | null
  currentEquipment: EntityRef | null
  currentProcessArea: EntityRef | null
  currentEntities: EntityRef[]
  droppedTurns: number
}

export interface ToolCatalogItem {
  name: string
  description: string
  method: string
  endpoint: string
  returns: string
  parameters: { name: string; type: string; required: boolean; description: string }[]
}

/** 示例问题。纯数据，点击只是把 question 填进输入框，不绑定任何工具或流程。 */
export interface ExampleItem {
  id: string
  question: string
  /** 这条示例想演示什么，鼠标悬停时显示 */
  intent?: string
  /** 仅供演示与验收对照，不下发给模型，也不参与 Agent 规划 */
  referenceToolChain?: string[]
  expectation?: string
}

export interface ExampleGroup {
  key: string
  title: string
  description?: string
  count: number
  items: ExampleItem[]
}

export interface ExampleCatalog {
  version: string | null
  notice?: string | null
  groups: ExampleGroup[]
  total: number
  available: boolean
  emptyReason?: string
}

export interface HealthInfo {
  service: string
  status: string
  framework: string
  toolCount: number
  config: {
    llm_model: string
    llm_api_key_configured: boolean
    ontology_base_url: string
    max_tool_calls_per_turn: number
  }
  ontology: { reachable: boolean; detail: string }
}
