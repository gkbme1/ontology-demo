/**
 * Agent 服务客户端。
 *
 * 普通接口用 axios；/api/chat 是 POST + SSE，浏览器原生 EventSource 只支持 GET，
 * 所以这里用 fetch + ReadableStream 手工解析 SSE 帧。
 */

import axios from 'axios'
import type { AgentEvent, ExampleCatalog, HealthInfo, ToolCatalogItem } from '@/types'

const baseURL = import.meta.env.VITE_API_BASE || ''

export const http = axios.create({ baseURL, timeout: 15000 })

export async function fetchHealth(): Promise<HealthInfo> {
  const { data } = await http.get<HealthInfo>('/api/health')
  return data
}

export async function fetchTools(): Promise<ToolCatalogItem[]> {
  const { data } = await http.get<{ items: ToolCatalogItem[] }>('/api/tools')
  return data.items
}

/** 示例问题清单。来自 backend/data/examples.json，纯数据。 */
export async function fetchExamples(): Promise<ExampleCatalog> {
  const { data } = await http.get<ExampleCatalog>('/api/examples')
  return data
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await http.delete(`/api/conversations/${conversationId}`)
}

export interface ChatStreamOptions {
  message: string
  conversationId?: string | null
  signal?: AbortSignal
  onEvent: (event: AgentEvent) => void
}

/** 发起一轮对话，逐条回调 SSE 事件。 */
export async function streamChat(options: ChatStreamOptions): Promise<void> {
  const response = await fetch(`${baseURL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: options.message,
      conversationId: options.conversationId ?? null,
    }),
    signal: options.signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(`Agent 服务返回 HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE 以空行分帧；网络分片可能把一帧切断，所以保留最后一段不完整的
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const parsed = parseFrame(frame)
      if (parsed) options.onEvent(parsed)
      boundary = buffer.indexOf('\n\n')
    }
  }

  const tail = parseFrame(buffer)
  if (tail) options.onEvent(tail)
}

function parseFrame(frame: string): AgentEvent | null {
  const lines = frame.split('\n')
  let type = ''
  const dataLines: string[] = []
  for (const line of lines) {
    if (line.startsWith('event:')) type = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!type || dataLines.length === 0) return null
  try {
    return { type, data: JSON.parse(dataLines.join('\n')) } as AgentEvent
  } catch {
    return null
  }
}
