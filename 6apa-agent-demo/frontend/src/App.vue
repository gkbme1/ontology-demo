<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAgentStore } from '@/stores/agent'
import ChatPanel from '@/components/ChatPanel.vue'
import TracePanel from '@/components/TracePanel.vue'
import GraphModal from '@/components/GraphModal.vue'
import ToolCatalog from '@/components/ToolCatalog.vue'

const store = useAgentStore()
const showGraph = ref(false)
const showTools = ref(false)

onMounted(() => store.loadMeta())
</script>

<template>
  <div class="h-full flex flex-col bg-ink-900">
    <!-- 顶栏：服务状态一眼可见，现场排障时先看这里 -->
    <header class="h-12 shrink-0 px-4 flex items-center gap-4 border-b border-line bg-ink-800">
      <h1 class="text-sm font-semibold tracking-wide text-slate-100">6-APA 生产车间智能 Agent</h1>

      <div class="flex items-center gap-2 text-[11px] font-mono text-slate-400">
        <span class="tag">
          <i class="w-1.5 h-1.5 rounded-full" :class="store.health?.ontology.reachable ? 'bg-ok' : 'bg-bad'" />
          本体 {{ store.health?.ontology.reachable ? '已连接' : '未连接' }}
        </span>
        <span class="tag">
          <i
            class="w-1.5 h-1.5 rounded-full"
            :class="store.health?.config.llm_api_key_configured ? 'bg-ok' : 'bg-warn'"
          />
          {{ store.health?.config.llm_model ?? '模型未知' }}
        </span>
        <button class="tag hover:border-accent" @click="showTools = true">
          {{ store.health?.toolCount ?? 0 }} 个工具
        </button>
        <span v-if="store.context?.currentEquipment" class="tag text-accent border-accent/40">
          当前设备 {{ store.context.currentEquipment.name }}
        </span>
      </div>

      <div class="ml-auto flex items-center gap-2">
        <button
          class="btn"
          :disabled="!store.graphs.length"
          title="Tool 返回关系图数据时可用"
          @click="showGraph = true"
        >
          查看关系图<span v-if="store.graphs.length"> ({{ store.graphs.length }})</span>
        </button>
        <button class="btn" :disabled="store.busy" @click="store.reset()">新建会话</button>
      </div>
    </header>

    <p v-if="store.lastError" class="px-4 py-2 text-xs text-bad bg-bad/10 border-b border-bad/30">
      {{ store.lastError }}
    </p>

    <main class="flex-1 min-h-0 grid grid-cols-[minmax(0,1fr)_380px]">
      <ChatPanel />
      <TracePanel />
    </main>

    <GraphModal v-if="showGraph" @close="showGraph = false" />
    <ToolCatalog v-if="showTools" @close="showTools = false" />
  </div>
</template>
