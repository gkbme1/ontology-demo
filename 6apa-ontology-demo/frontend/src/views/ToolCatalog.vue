<script setup lang="ts">
/**
 * 固定工具：Agent 的工具清单（读取 Agent 服务 GET /api/tools）。
 * 每个工具列出说明、参数（类型 / 必填 / 可选值 / 说明）、默认值、返回内容，并给出调用示例。
 * 「固定程序」在 Agent 本地按固定算法执行（异常溯源、越限检查、派生量计算等）；
 * 「本体接口」转调本体服务的一个接口。页面不内置任何工具定义。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { agentTools } from '@/api/client'
import type { AgentTool, AgentToolParameter } from '@/api/types'

const route = useRoute()
const router = useRouter()
const tools = ref<AgentTool[]>([])
const error = ref<string | null>(null)
const loading = ref(true)

const KINDS = ['固定程序', '本体接口', '全部'] as const
const kind = ref<(typeof KINDS)[number]>('固定程序')
const keyword = ref('')

const GROUP_LABEL: Record<string, string> = {
  analysis: '分析与计算', core: '基础', structure: '结构与设备', relations: '关系', rules: '规则 / 能力 / 约束',
  timeseries: '实时值 / 历史值', limits: '工艺限值', quality: '数据质量'
}

onMounted(async () => {
  try {
    tools.value = (await agentTools()).items
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})

const counts = computed(() => ({
  固定程序: tools.value.filter((t) => t.kind === '固定程序').length,
  本体接口: tools.value.filter((t) => t.kind !== '固定程序').length,
  全部: tools.value.length
}))

const filtered = computed(() => {
  const kw = keyword.value.trim()
  return tools.value.filter((t) =>
    (kind.value === '全部' || (kind.value === '固定程序' ? t.kind === '固定程序' : t.kind !== '固定程序'))
    && (!kw || [t.name, t.summary ?? '', t.description].some((x) => x.includes(kw))))
})

const current = computed(() => {
  const name = route.query.tool as string | undefined
  return filtered.value.find((t) => t.name === name) ?? filtered.value[0] ?? null
})
function pick(t: AgentTool) {
  router.replace({ query: { ...route.query, tool: t.name } })
}

// 调用示例：必填参数给示例值（声明的示例 > 第一个可选值 > 占位说明）
function sample(p: AgentToolParameter): unknown {
  if (p.example !== undefined) return p.example
  if (p.enum?.length) return p.enum[0]
  if (p.type === 'boolean') return false
  return `<${p.description.split(/[，。；,;]/)[0] || p.name}>`
}
const example = computed(() => {
  const t = current.value
  if (!t) return ''
  const args: Record<string, unknown> = {}
  for (const p of t.parameters.filter((x) => x.required)) args[p.name] = sample(p)
  return JSON.stringify({ name: t.name, arguments: args }, null, 2)
})
const optionalExample = computed(() => {
  const t = current.value
  if (!t || !t.parameters.some((p) => !p.required)) return ''
  const args: Record<string, unknown> = {}
  for (const p of t.parameters) args[p.name] = sample(p)
  return JSON.stringify({ name: t.name, arguments: args }, null, 2)
})
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-[340px_minmax(0,1fr)] h-[calc(100vh-54px)]">
    <aside class="border-r border-line bg-ink-panel min-h-0 flex flex-col">
      <div class="px-4 pt-3 text-fg-mute text-[10.5px] tracking-widest uppercase">Agent 工具清单</div>
      <div class="px-3 pt-2 pb-2 border-b border-line-soft space-y-2">
        <div class="flex gap-1">
          <button v-for="k in KINDS" :key="k" class="ctl !py-0.5 !px-2" :class="{ 'ctl-on': kind === k }" @click="kind = k">
            {{ k }}<span class="font-mono text-fg-mute">{{ counts[k] }}</span></button>
        </div>
        <input v-model="keyword" type="search" placeholder="搜索工具名 / 说明…"
               class="w-full px-3 py-1.5 rounded-md border border-line bg-ink-panel2 text-[12.5px] text-fg placeholder:text-fg-mute focus:outline-none focus:border-brand" />
      </div>
      <div class="flex-1 min-h-0 overflow-y-auto py-1">
        <div v-if="loading" class="px-4 py-3 text-fg-mute text-xs">加载中…</div>
        <button
          v-for="t in filtered" :key="t.name"
          class="block w-full text-left px-4 py-2 border-l-2 hover:bg-ink-panel2"
          :class="current?.name === t.name ? 'bg-brand/[0.13] border-brand' : 'border-transparent'"
          @click="pick(t)"
        >
          <div class="flex items-center gap-1.5">
            <span class="font-mono text-[12px] text-fg truncate">{{ t.name }}</span>
            <span class="ml-auto pill !text-[10px] shrink-0" :class="t.kind === '固定程序' ? 'pill-ok' : 'pill-plain'">{{ t.kind }}</span>
          </div>
          <div class="text-[11.5px] text-fg-dim truncate">{{ t.summary || t.description }}</div>
        </button>
      </div>
      <div class="px-3 py-2 border-t border-line-soft text-[10.5px] text-fg-mute leading-relaxed">
        固定程序：Agent 本地按固定算法执行，结果可复现；本体接口：转调本体服务的一个接口。清单读自 Agent 服务 /api/tools。
      </div>
    </aside>

    <main class="min-w-0 min-h-0 overflow-y-auto px-5 pt-4 pb-12">
      <div v-if="error" class="panel">
        <div class="panel-body text-[13px] text-fg-dim space-y-1">
          <div class="text-err">无法读取 Agent 工具清单：{{ error }}</div>
          <div>请确认 Agent 服务已启动（默认 <code class="font-mono">http://localhost:8800</code>，见 6apa-agent-demo 的 run_backend），
            端口不同时在 frontend/.env 中设置 <code class="font-mono">VITE_AGENT_PROXY</code>。</div>
        </div>
      </div>

      <div v-else-if="current" class="space-y-4">
        <section class="panel">
          <div class="px-4 py-3 bg-gradient-to-r from-brand/[0.10] to-transparent">
            <div class="flex flex-wrap items-center gap-2">
              <h2 class="m-0 text-[17px] font-semibold font-mono">{{ current.name }}</h2>
              <span class="pill" :class="current.kind === '固定程序' ? 'pill-ok' : 'pill-plain'">{{ current.kind }}</span>
              <span v-if="current.group" class="pill pill-plain">{{ GROUP_LABEL[current.group] ?? current.group }}</span>
              <span v-if="current.endpoint" class="pill pill-info font-mono">{{ current.method }} {{ current.endpoint }}</span>
            </div>
            <div v-if="current.summary" class="mt-1 text-[13px] text-fg">{{ current.summary }}</div>
          </div>
          <div class="panel-body text-[12.5px] text-fg-dim leading-relaxed whitespace-pre-line">{{ current.description }}</div>
        </section>

        <section class="panel">
          <div class="panel-head"><h3>参数</h3><span class="text-fg-mute text-[11.5px]">带 * 为必填</span>
            <span class="ml-auto font-mono text-fg-mute text-[11px]">{{ current.parameters.length }} 个</span></div>
          <div v-if="!current.parameters.length" class="empty">无参数</div>
          <table v-else class="tbl">
            <thead><tr><th class="w-[130px]">参数</th><th class="w-[80px]">类型</th><th>说明</th><th class="w-[220px]">可选值 / 示例</th></tr></thead>
            <tbody>
              <tr v-for="p in current.parameters" :key="p.name" class="!cursor-default">
                <td class="font-mono">{{ p.name }}<span v-if="p.required" class="text-err">*</span></td>
                <td class="font-mono text-[11.5px] text-fg-dim">{{ p.type }}</td>
                <td class="text-fg-dim">{{ p.description || '—' }}
                  <div v-if="current.defaults && p.name in current.defaults" class="text-fg-mute text-[11px]">默认 {{ current.defaults[p.name] }}</div></td>
                <td>
                  <div v-if="p.enum?.length" class="flex flex-wrap gap-1">
                    <span v-for="v in p.enum" :key="v" class="pill pill-plain font-mono">{{ v }}</span>
                  </div>
                  <span v-else-if="p.example !== undefined" class="font-mono text-[11.5px]">{{ p.example }}</span>
                  <span v-else class="text-fg-mute">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        <section v-if="current.methods?.length" class="panel">
          <div class="panel-head"><h3>计算方法</h3><span class="text-fg-mute text-[11.5px]">method 参数的取值；不填时由程序按本体自动判断</span></div>
          <table class="tbl">
            <thead><tr><th class="w-[160px]">method</th><th class="w-[200px]">名称</th><th>能算什么</th></tr></thead>
            <tbody>
              <tr v-for="m in current.methods" :key="m.key" class="!cursor-default">
                <td class="font-mono">{{ m.key }}</td><td>{{ m.title }}</td><td class="text-fg-dim">{{ m.summary }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <div class="grid gap-4 xl:grid-cols-2">
          <section class="panel">
            <div class="panel-head"><h3>调用示例</h3><span class="text-fg-mute text-[11.5px]">只含必填参数；尖括号内替换为实际值</span></div>
            <pre class="m-0 px-4 py-3 text-[12px] font-mono text-fg whitespace-pre-wrap">{{ example }}</pre>
          </section>
          <section v-if="optionalExample" class="panel">
            <div class="panel-head"><h3>全部参数示例</h3><span class="text-fg-mute text-[11.5px]">可选参数按需填写，不填用默认</span></div>
            <pre class="m-0 px-4 py-3 text-[12px] font-mono text-fg whitespace-pre-wrap">{{ optionalExample }}</pre>
          </section>
        </div>

        <section class="panel">
          <div class="panel-head"><h3>返回</h3></div>
          <div class="panel-body text-[12.5px] text-fg-dim leading-relaxed">{{ current.returns || '—' }}</div>
        </section>
      </div>

      <div v-else-if="!loading" class="empty">没有匹配的工具</div>
    </main>
  </div>
</template>
