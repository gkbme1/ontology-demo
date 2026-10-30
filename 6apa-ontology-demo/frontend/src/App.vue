<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { useOntologyMeta, fmt } from '@/composables/useOntologyMeta'
import ObjectDetail from '@/components/ObjectDetail.vue'

const route = useRoute()
const { sources, categories, load, error } = useOntologyMeta()

onMounted(load)

const fullWidth = computed(() => route.meta.fullWidth === true)

const topTabs = [
  { to: '/', label: '资产本体', match: (p: string) => p === '/' },
  { to: '/overview', label: '本体总览', match: (p: string) => p !== '/' }
]

const navItems = [
  { to: '/overview', label: '本体总览', match: (p: string) => p === '/overview' },
  { to: '/areas', label: '工段与设备', match: (p: string) => p.startsWith('/areas') || p.startsWith('/equipment') || p.startsWith('/parameters') },
  { to: '/graph', label: '关系图谱', match: (p: string) => p.startsWith('/graph') },
  { to: '/relations', label: '关系清单', match: (p: string) => p.startsWith('/relations') }
]

const govItems = [
  { to: '/data-sources', label: '数据源管理' },
  { to: '/data-quality', label: '数据质量' }
]
</script>

<template>
  <div class="grid grid-rows-[auto_1fr] min-h-screen">
    <header
      class="sticky top-0 z-30 flex items-center gap-4 h-[54px] px-5 border-b border-line"
      style="background: linear-gradient(180deg, #14213a, #0e1729)"
    >
      <div class="flex items-baseline gap-2.5 min-w-0">
        <h1 class="m-0 text-[15px] font-semibold tracking-wide whitespace-nowrap">6-APA 生产线工业本体</h1>
        <span class="text-fg-mute text-[11px] tracking-widest uppercase whitespace-nowrap hidden lg:inline">
          Industrial Ontology · 6-APA Production Line
        </span>
      </div>
      <nav class="flex items-center gap-1 ml-4">
        <RouterLink
          v-for="t in topTabs" :key="t.to" :to="t.to"
          class="px-3 py-1 rounded-md text-[12.5px] no-underline border"
          :class="t.match(route.path) ? 'bg-brand/[0.15] border-brand/60 text-fg font-medium' : 'border-transparent text-fg-dim hover:text-fg hover:bg-ink-panel2'"
        >{{ t.label }}</RouterLink>
      </nav>
      <div class="flex-1"></div>
      <div class="hidden 2xl:flex gap-1.5 flex-wrap">
        <span
          v-for="s in sources?.sources ?? []"
          :key="s.file"
          class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[11px] bg-ink-panel2"
          :class="s.available ? 'border-line text-fg-dim' : 'border-line border-dashed text-fg-mute'"
        >
          <span :class="s.available ? 'text-ok' : 'text-fg-mute'">{{ s.available ? '✓' : '○' }}</span>{{ s.file }}
        </span>
      </div>
      <div class="flex items-center gap-2 px-3 py-1 border border-line rounded-full bg-ok/[0.07] text-[11.5px] text-fg-dim whitespace-nowrap">
        <span class="w-[7px] h-[7px] rounded-full" :class="error ? 'bg-err' : 'bg-ok'"></span>
        {{ error ? '本体服务不可达' : '本体服务 · 实时' }}
      </div>
    </header>

    <div v-if="fullWidth" class="min-w-0">
      <div v-if="error" class="mx-5 mt-4 px-3 py-2.5 border-l-2 border-err bg-err/[0.07] text-fg-dim">
        无法连接本体服务：{{ error }}。请确认已执行
        <code class="font-mono">uvicorn backend.main:app --port 8700</code>。
      </div>
      <RouterView />
    </div>

    <div v-else class="grid grid-cols-1 xl:grid-cols-[236px_minmax(0,1fr)_392px]">
      <!-- 左栏：导航 + 12 个本体分类 -->
      <aside class="border-r border-line bg-ink-panel py-3.5 overflow-y-auto xl:sticky xl:top-[54px] xl:max-h-[calc(100vh-54px)]">
        <div class="px-4 pb-1.5 text-fg-mute text-[10.5px] tracking-widest uppercase">生产线</div>
        <RouterLink
          v-for="item in navItems" :key="item.to" :to="item.to"
          class="flex items-center gap-2 w-full px-4 py-1.5 border-l-2 text-[12.5px] no-underline"
          :class="item.match(route.path)
            ? 'bg-brand/[0.13] border-brand text-fg font-medium'
            : 'border-transparent text-fg-dim hover:bg-ink-panel2 hover:text-fg'"
        >{{ item.label }}</RouterLink>

        <div class="px-4 pt-4 pb-1.5 text-fg-mute text-[10.5px] tracking-widest uppercase">本体分类 · 12 项</div>
        <RouterLink
          v-for="c in categories" :key="c.key" :to="`/ontology/${c.key}`"
          class="flex items-center gap-2 w-full px-4 py-1.5 border-l-2 text-[12.5px] no-underline"
          :class="route.params.categoryKey === c.key
            ? 'bg-brand/[0.13] border-brand text-fg font-medium'
            : 'border-transparent text-fg-dim hover:bg-ink-panel2 hover:text-fg'"
        >
          <span class="w-[17px] font-mono text-[10.5px]" :class="c.core ? 'text-brand' : 'text-fg-mute'">{{ c.index }}</span>
          <span>{{ c.name }}</span>
          <span class="ml-auto font-mono text-[10.5px] text-fg-mute tabular-nums">{{ fmt(c.count) }}</span>
        </RouterLink>

        <div class="px-4 pt-4 pb-1.5 text-fg-mute text-[10.5px] tracking-widest uppercase">数据治理</div>
        <RouterLink
          v-for="item in govItems" :key="item.to" :to="item.to"
          class="flex items-center gap-2 w-full px-4 py-1.5 border-l-2 text-[12.5px] no-underline"
          :class="route.path === item.to
            ? 'bg-brand/[0.13] border-brand text-fg font-medium'
            : 'border-transparent text-fg-dim hover:bg-ink-panel2 hover:text-fg'"
        >{{ item.label }}</RouterLink>
      </aside>

      <!-- 中栏：本体可视化区域 -->
      <main class="min-w-0 px-5 pt-4 pb-12 overflow-y-auto xl:max-h-[calc(100vh-54px)]">
        <div v-if="error" class="mb-4 px-3 py-2.5 border-l-2 border-err bg-err/[0.07] text-fg-dim">
          无法连接本体服务：{{ error }}。请确认已执行
          <code class="font-mono">uvicorn backend.main:app --port 8700</code>，
          并用 <code class="font-mono">curl http://localhost:8700/api/health</code> 确认服务与端口。
        </div>
        <RouterView />
      </main>

      <!-- 右栏：对象详情 -->
      <aside class="border-l border-line bg-ink-panel px-4 pt-4 pb-12 overflow-y-auto xl:sticky xl:top-[54px] xl:max-h-[calc(100vh-54px)]">
        <ObjectDetail />
      </aside>
    </div>
  </div>
</template>
