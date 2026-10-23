<script setup lang="ts">
import { ref } from 'vue'
import { useAgentStore } from '@/stores/agent'
import type { ToolCallView } from '@/types'

const store = useAgentStore()
const expanded = ref<Set<string>>(new Set())

function toggle(id: string) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function markClass(tool?: ToolCallView) {
  if (!tool) return 'text-slate-400'
  if (tool.status === 'error') return 'text-bad'
  if (tool.status === 'empty') return 'text-warn'
  return 'text-ok'
}

function mark(done: boolean, tool?: ToolCallView) {
  if (!done) return '●'
  if (tool?.status === 'error') return '✕'
  if (tool?.status === 'empty') return '○'
  return '✓'
}
</script>

<template>
  <aside class="flex flex-col min-h-0 bg-ink-900">
    <div class="h-9 shrink-0 px-4 flex items-center border-b border-line">
      <h2 class="text-xs font-semibold tracking-wide text-slate-300">Agent 执行过程</h2>
      <span class="ml-auto text-[11px] font-mono text-slate-500">
        {{ store.steps.filter((s) => s.kind === 'tool').length }} 次调用
      </span>
    </div>

    <div class="flex-1 min-h-0 overflow-y-auto px-3 py-3 space-y-1.5">
      <p v-if="!store.steps.length" class="text-xs text-slate-500 px-1">
        提问后，这里实时显示 Agent 选了哪些工具、参数是什么、返回了多少条数据。
      </p>

      <div v-for="step in store.steps" :key="step.id">
        <!-- 纯状态行 -->
        <div v-if="step.kind === 'status'" class="flex items-start gap-2 px-1 py-1 text-xs">
          <span :class="step.done ? 'text-ok' : 'text-accent animate-pulse'">
            {{ step.done ? '✓' : '●' }}
          </span>
          <span class="text-slate-400">{{ step.text }}</span>
        </div>

        <!-- 工具调用卡片 -->
        <div v-else class="panel overflow-hidden">
          <button
            class="w-full text-left px-2.5 py-2 hover:bg-ink-700 transition-colors"
            @click="toggle(step.id)"
          >
            <div class="flex items-start gap-2">
              <span :class="[markClass(step.tool), step.done ? '' : 'animate-pulse']">
                {{ mark(step.done, step.tool) }}
              </span>
              <div class="min-w-0 flex-1">
                <p class="text-xs font-mono text-slate-200 truncate">{{ step.tool?.tool }}</p>
                <p class="text-[11px] text-slate-500 truncate">{{ step.text }}</p>
                <p v-if="step.tool?.resultSummary" class="text-[11px] text-slate-400 mt-0.5">
                  {{ step.tool.resultSummary }}
                  <span v-if="step.tool.truncated" class="text-warn">· 已裁剪</span>
                </p>
                <p v-if="step.tool?.error" class="text-[11px] text-bad mt-0.5 line-clamp-2">
                  {{ step.tool.error }}
                </p>
              </div>
              <span v-if="step.tool?.durationMs != null" class="text-[10px] font-mono text-slate-500 shrink-0">
                {{ step.tool.durationMs }}ms
              </span>
            </div>
          </button>

          <div v-if="expanded.has(step.id)" class="border-t border-line bg-ink-900/60 px-2.5 py-2 space-y-2">
            <div>
              <p class="text-[10px] uppercase tracking-wider text-slate-500 mb-1">请求</p>
              <p class="text-[11px] font-mono text-slate-400 break-all">
                {{ step.tool?.url || '—' }}
              </p>
              <pre class="mt-1 text-[11px] font-mono text-slate-300 whitespace-pre-wrap">{{
                JSON.stringify(step.tool?.arguments ?? {}, null, 2)
              }}</pre>
            </div>

            <div v-if="step.tool?.truncationNote">
              <p class="text-[10px] uppercase tracking-wider text-warn mb-1">裁剪说明</p>
              <p class="text-[11px] text-warn/90">{{ step.tool.truncationNote }}</p>
            </div>

            <div v-if="step.tool?.resultPreview">
              <p class="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
                返回结果摘要
                <span v-if="step.tool.rawBytes" class="text-slate-600">
                  （原始 {{ step.tool.rawBytes }} 字节，HTTP {{ step.tool.httpStatus }}）
                </span>
              </p>
              <pre
                class="text-[11px] font-mono text-slate-300 whitespace-pre-wrap max-h-64 overflow-y-auto"
                >{{ step.tool.resultPreview }}</pre
              >
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 会话上下文：让"它=哪台设备"这件事可见可核对 -->
    <div v-if="store.context" class="shrink-0 border-t border-line px-3 py-2 space-y-1">
      <p class="text-[10px] uppercase tracking-wider text-slate-500">会话上下文</p>
      <p v-if="store.context.currentEquipment" class="text-[11px] font-mono text-slate-300">
        设备 · {{ store.context.currentEquipment.name }}
        <span class="text-slate-500">{{ store.context.currentEquipment.id }}</span>
      </p>
      <p v-if="store.context.currentProcessArea" class="text-[11px] font-mono text-slate-300">
        工段 · {{ store.context.currentProcessArea.name }}
      </p>
      <p v-if="!store.context.currentEquipment && !store.context.currentProcessArea" class="text-[11px] text-slate-500">
        暂无锁定实体
      </p>
    </div>
  </aside>
</template>
