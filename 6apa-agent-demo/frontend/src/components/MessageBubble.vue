<script setup lang="ts">
import { computed } from 'vue'
import type { ChatMessage } from '@/types'

const props = defineProps<{ message: ChatMessage }>()

const isUser = computed(() => props.message.role === 'user')

/** 极简 Markdown：标题/粗体/行内代码/有序无序列表。不引第三方库，避免 XSS 面积。 */
function render(text: string): string {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  const lines = escaped.split('\n')
  const out: string[] = []
  let inList: 'ul' | 'ol' | null = null

  const closeList = () => {
    if (inList) {
      out.push(`</${inList}>`)
      inList = null
    }
  }

  const isRow = (l?: string) => /^\s*\|.*\|\s*$/.test(l ?? '')
  const isSep = (l?: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l ?? '')
  const cells = (l: string) =>
    l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => inline(c.trim()))

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd()
    // Markdown 表格：表头行 + 分隔行 + 数据行
    if (isRow(line) && isSep(lines[i + 1])) {
      closeList()
      const head = cells(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && isRow(lines[i])) rows.push(cells(lines[i++]))
      i--
      out.push(
        '<table class="text-xs my-2 border-collapse block overflow-x-auto max-w-full"><thead><tr>' +
          head.map((c) => `<th class="border border-line bg-ink-700 px-2 py-1 text-left text-slate-100">${c}</th>`).join('') +
          '</tr></thead><tbody>' +
          rows
            .map((r) => '<tr>' + r.map((c) => `<td class="border border-line px-2 py-1 align-top">${c}</td>`).join('') + '</tr>')
            .join('') +
          '</tbody></table>',
      )
      continue
    }
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)

    if (bullet) {
      if (inList !== 'ul') {
        closeList()
        out.push('<ul class="list-disc pl-5 space-y-0.5 my-1">')
        inList = 'ul'
      }
      out.push(`<li>${inline(bullet[1])}</li>`)
    } else if (numbered) {
      if (inList !== 'ol') {
        closeList()
        out.push('<ol class="list-decimal pl-5 space-y-0.5 my-1">')
        inList = 'ol'
      }
      out.push(`<li>${inline(numbered[1])}</li>`)
    } else if (heading) {
      closeList()
      out.push(`<p class="font-semibold text-slate-100 mt-2">${inline(heading[2])}</p>`)
    } else if (!line) {
      closeList()
      out.push('<div class="h-2"></div>')
    } else {
      closeList()
      out.push(`<p>${inline(line)}</p>`)
    }
  }
  closeList()
  return out.join('')
}

function inline(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong class="text-slate-100">$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="font-mono text-accent bg-ink-700 px-1 rounded">$1</code>')
}
</script>

<template>
  <div :class="isUser ? 'flex justify-end' : ''">
    <div
      class="max-w-[46rem] rounded-md px-4 py-3 text-sm leading-relaxed"
      :class="isUser ? 'bg-accent-dim/15 border border-accent/30' : 'panel'"
    >
      <p class="text-[11px] font-mono mb-1.5" :class="isUser ? 'text-accent' : 'text-slate-500'">
        {{ isUser ? '你' : 'Agent' }}
      </p>

      <div
        v-if="message.content"
        class="space-y-1 text-slate-200"
        :class="{ caret: message.streaming }"
        v-html="render(message.content)"
      />
      <p v-else-if="message.streaming" class="text-slate-500 text-xs">正在查询本体……</p>

      <p v-if="message.error" class="mt-2 text-xs text-bad">{{ message.error }}</p>

      <p v-if="message.stats" class="mt-2 pt-2 border-t border-line text-[11px] font-mono text-slate-500">
        {{ message.stats.llmRounds }} 轮模型调用 · {{ message.stats.toolCalls }} 次工具调用 ·
        {{ (message.stats.elapsedMs / 1000).toFixed(1) }}s
      </p>
    </div>
  </div>
</template>
