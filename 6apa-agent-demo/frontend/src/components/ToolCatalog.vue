<script setup lang="ts">
/** 工具清单。清单来自后端 /api/tools，前端不维护第二份工具定义。 */
import { ref } from 'vue'
import { useAgentStore } from '@/stores/agent'

const emit = defineEmits<{ close: [] }>()
const store = useAgentStore()
const keyword = ref('')
</script>

<template>
  <div class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" @click.self="emit('close')">
    <div class="panel w-full max-w-4xl h-[80vh] flex flex-col">
      <div class="h-11 shrink-0 px-4 flex items-center gap-3 border-b border-line">
        <h3 class="text-sm font-semibold text-slate-100">Agent 可用工具（{{ store.tools.length }}）</h3>
        <input
          v-model="keyword"
          placeholder="过滤……"
          class="bg-ink-700 border border-line rounded px-2 py-1 text-xs outline-none focus:border-accent"
        />
        <button class="btn ml-auto" @click="emit('close')">关闭</button>
      </div>

      <div class="flex-1 min-h-0 overflow-y-auto p-3 space-y-2">
        <div
          v-for="tool in store.tools.filter(
            (item) => !keyword || item.name.includes(keyword) || item.description.includes(keyword),
          )"
          :key="tool.name"
          class="border border-line rounded p-3"
        >
          <div class="flex items-baseline gap-2 flex-wrap">
            <code class="text-xs font-mono text-accent">{{ tool.name }}</code>
            <span class="text-[10px] font-mono text-slate-500">{{ tool.method }} {{ tool.endpoint }}</span>
          </div>
          <p class="mt-1 text-xs text-slate-400 leading-relaxed">{{ tool.description }}</p>
          <div v-if="tool.parameters.length" class="mt-2 flex flex-wrap gap-1">
            <span
              v-for="param in tool.parameters"
              :key="param.name"
              class="tag"
              :class="param.required ? 'border-accent/50 text-accent' : 'text-slate-400'"
              :title="param.description"
            >
              {{ param.name }}<span class="text-slate-600">:{{ param.type }}</span>
              <span v-if="param.required" class="text-accent">*</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
