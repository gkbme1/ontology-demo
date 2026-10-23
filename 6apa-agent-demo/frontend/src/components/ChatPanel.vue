<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useAgentStore } from '@/stores/agent'
import MessageBubble from '@/components/MessageBubble.vue'
import type { ExampleGroup } from '@/types'

const store = useAgentStore()
const draft = ref('')
const scroller = ref<HTMLElement | null>(null)

// 服务端 /api/examples 拿不到时的兜底；正常情况下示例问题来自 backend/data/examples.json
const FALLBACK_SAMPLES = [
  '昨天水解罐温度异常，帮我调查一下原因',
  '6-APA 生产车间有多少设备？',
  '介绍一下一层排渣泵',
  '它有哪些参数？',
  '从本体中，你能告诉我目前有哪些类型的知识吗？',
]

/** 点一下只是把问题填进输入框；Agent 收到后照常自己规划工具链，这里不绑定任何工具。 */
const sampleGroups = computed<ExampleGroup[]>(() => {
  const catalog = store.examples
  if (catalog?.available && catalog.groups.length) return catalog.groups
  return [
    {
      key: 'fallback',
      title: '示例问题',
      count: FALLBACK_SAMPLES.length,
      items: FALLBACK_SAMPLES.map((question, index) => ({ id: `F${index}`, question })),
    },
  ]
})

async function submit() {
  const text = draft.value.trim()
  if (!text || store.busy) return
  draft.value = ''
  await store.send(text)
}

function useSample(text: string) {
  draft.value = text
}

watch(
  () => [store.messages.length, store.messages[store.messages.length - 1]?.content],
  async () => {
    await nextTick()
    scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
  },
)
</script>

<template>
  <section class="flex flex-col min-h-0 border-r border-line">
    <div ref="scroller" class="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4">
      <div v-if="!store.messages.length" class="text-sm text-slate-400 space-y-3 max-w-2xl">
        <p>
          用自然语言提问即可。Agent 会自己决定调用哪些本体接口、调用几次，
          右侧实时显示它的执行过程。
        </p>
        <div v-for="group in sampleGroups" :key="group.key" class="space-y-2">
          <h4 class="text-xs font-semibold text-slate-200 flex items-center gap-2">
            {{ group.title }}
            <span class="font-normal text-slate-500">{{ group.count }} 个</span>
          </h4>
          <p v-if="group.description" class="text-xs text-slate-400 leading-relaxed">
            {{ group.description }}
          </p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="item in group.items"
              :key="item.id"
              class="btn text-xs text-left whitespace-normal leading-relaxed max-w-full"
              :title="item.intent || ''"
              @click="useSample(item.question)"
            >
              {{ item.question }}
            </button>
          </div>
        </div>
        <p
          v-if="store.examples?.notice"
          class="text-[11px] text-slate-500 leading-relaxed border-t border-line pt-2.5"
        >
          {{ store.examples.notice }}
        </p>
      </div>

      <MessageBubble v-for="message in store.messages" :key="message.id" :message="message" />
    </div>

    <div class="shrink-0 border-t border-line bg-ink-800 p-3">
      <div class="flex gap-2 items-end">
        <textarea
          v-model="draft"
          rows="2"
          placeholder="输入问题……（Enter 发送，Shift+Enter 换行）"
          class="flex-1 resize-none bg-ink-700 border border-line rounded px-3 py-2 text-sm outline-none focus:border-accent placeholder:text-slate-500"
          @keydown.enter.exact.prevent="submit"
        />
        <button v-if="store.busy" class="btn" @click="store.abort()">停止</button>
        <button class="btn btn-primary" :disabled="store.busy || !draft.trim()" @click="submit">
          发送
        </button>
      </div>
      <p class="mt-1.5 text-[11px] text-slate-500 font-mono">
        会话 {{ store.conversationId ?? '未开始' }}
        <span v-if="store.context"> · 第 {{ store.context.turn }} 轮</span>
        <span v-if="store.context?.droppedTurns"> · 已省略 {{ store.context.droppedTurns }} 轮早期对话</span>
      </p>
    </div>
  </section>
</template>
