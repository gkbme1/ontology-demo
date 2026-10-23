/** Agent 会话状态。所有 SSE 事件在这里汇成视图模型。 */

import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import { deleteConversation, fetchExamples, fetchHealth, fetchTools, streamChat } from '@/api/client'
import type {
  AgentEvent,
  ChatMessage,
  ConversationContext,
  ExampleCatalog,
  GraphPayload,
  HealthInfo,
  ToolCallView,
  ToolCatalogItem,
  TraceStep,
} from '@/types'

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

export const useAgentStore = defineStore('agent', () => {
  const messages = ref<ChatMessage[]>([])
  const steps = ref<TraceStep[]>([])
  const context = ref<ConversationContext | null>(null)
  const conversationId = ref<string | null>(null)
  const health = ref<HealthInfo | null>(null)
  const tools = ref<ToolCatalogItem[]>([])
  const examples = ref<ExampleCatalog | null>(null)
  const graphs = shallowRef<GraphPayload[]>([])
  const busy = ref(false)
  const lastError = ref<string | null>(null)

  let controller: AbortController | null = null

  async function loadMeta() {
    try {
      health.value = await fetchHealth()
    } catch (error) {
      lastError.value = `无法连接 Agent 服务：${(error as Error).message}`
    }
    try {
      tools.value = await fetchTools()
    } catch {
      /* 工具清单拿不到不影响对话 */
    }
    try {
      examples.value = await fetchExamples()
    } catch {
      /* 示例问题拿不到就用组件里的兜底清单 */
    }
  }

  function reset() {
    if (conversationId.value) void deleteConversation(conversationId.value).catch(() => undefined)
    messages.value = []
    steps.value = []
    graphs.value = []
    context.value = null
    conversationId.value = null
    lastError.value = null
  }

  function abort() {
    controller?.abort()
    controller = null
    busy.value = false
  }

  async function send(text: string) {
    const question = text.trim()
    if (!question || busy.value) return

    busy.value = true
    lastError.value = null
    steps.value = []

    messages.value.push({ id: uid(), role: 'user', content: question })
    const reply: ChatMessage = {
      id: uid(),
      role: 'assistant',
      content: '',
      streaming: true,
      steps: [],
      stats: null,
    }
    messages.value.push(reply)

    controller = new AbortController()
    try {
      await streamChat({
        message: question,
        conversationId: conversationId.value,
        signal: controller.signal,
        onEvent: (event) => applyEvent(event, reply),
      })
    } catch (error) {
      if ((error as Error).name !== 'AbortError') {
        reply.error = `请求失败：${(error as Error).message}`
        lastError.value = reply.error
      }
    } finally {
      reply.streaming = false
      reply.steps = [...steps.value]
      busy.value = false
      controller = null
    }
  }

  function applyEvent(event: AgentEvent, reply: ChatMessage) {
    const data = event.data as Record<string, unknown>

    switch (event.type) {
      case 'turn_start':
        conversationId.value = String(data.conversationId ?? '')
        break

      case 'status':
        upsertStatus(String(data.text ?? ''), Boolean(data.done))
        break

      case 'tool_call': {
        const tool: ToolCallView = {
          callId: String(data.callId ?? uid()),
          tool: String(data.tool ?? ''),
          label: String(data.label ?? data.tool ?? ''),
          arguments: (data.arguments as Record<string, unknown>) ?? {},
          status: 'running',
        }
        steps.value.push({ kind: 'tool', id: tool.callId, text: tool.label, done: false, tool })
        break
      }

      case 'tool_result': {
        const callId = String(data.callId ?? '')
        const step = steps.value.find((item) => item.id === callId)
        if (step?.tool) {
          Object.assign(step.tool, data as unknown as Partial<ToolCallView>)
          step.tool.status = (data.status as ToolCallView['status'] | undefined) ?? 'ok'
          step.done = true
        }
        break
      }

      case 'graph':
        graphs.value = [...graphs.value, data as unknown as GraphPayload]
        break

      case 'answer_delta':
        reply.content += String(data.text ?? '')
        break

      case 'answer_reset':
        // 这一段流式文字其实是执行说明，不是最终回答
        reply.content = ''
        break

      case 'answer':
        reply.content = String(data.text ?? '')
        break

      case 'context':
        context.value = data as unknown as ConversationContext
        break

      case 'error':
        reply.error = String(data.message ?? '未知错误')
        lastError.value = reply.error
        break

      case 'done':
        steps.value.forEach((step) => {
          step.done = true
        })
        reply.stats = {
          toolCalls: Number(data.toolCalls ?? 0),
          llmRounds: Number(data.llmRounds ?? 0),
          elapsedMs: Number(data.elapsedMs ?? 0),
          ok: Boolean(data.ok),
        }
        upsertStatus('完成', true)
        break
    }
  }

  function upsertStatus(text: string, done: boolean) {
    if (!text) return
    const existing = steps.value.find((item) => item.kind === 'status' && item.text === text)
    if (existing) {
      existing.done = done
      return
    }
    steps.value.push({ kind: 'status', id: uid(), text, done })
  }

  return {
    messages,
    steps,
    context,
    conversationId,
    health,
    tools,
    examples,
    graphs,
    busy,
    lastError,
    loadMeta,
    send,
    reset,
    abort,
  }
})
