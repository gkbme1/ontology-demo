<script setup lang="ts">
/** 数据源管理（需求文档第二十五章）。 */
import { onMounted, ref } from 'vue'
import { api, API_ENDPOINTS } from '@/api/client'
import { fmt } from '@/composables/useOntologyMeta'
import type { DataSourcesPayload } from '@/api/types'

const ds = ref<DataSourcesPayload | null>(null)
onMounted(async () => { ds.value = await api.dataSources() })
</script>

<template>
  <div v-if="ds">
    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold">数据源管理</h2>
      <p class="m-0 text-fg-dim max-w-[78ch]">
        现场 DCS 数据、工业关系 Excel、对象映射与规则数据源相互独立，
        API 返回体以 <span class="font-mono">sourceType</span> 字段区分来源。
      </p>
    </header>

    <section v-for="s in ds.sources" :key="s.file" class="panel mb-4">
      <div class="panel-head">
        <h3>{{ s.sourceTypeLabel }}</h3>
        <span class="font-mono text-fg-mute text-[11.5px]">{{ s.sourceType }}</span>
        <span class="ml-auto pill" :class="s.available ? 'pill-ok' : 'pill-mute'">{{ s.status }}</span>
      </div>
      <div class="panel-body">
        <dl class="kv">
          <dt>文件</dt><dd class="font-mono">{{ s.file }}</dd>
          <dt>加载时间</dt><dd class="font-mono">{{ s.loadedAt ?? '—' }}</dd>
          <template v-for="(v, k) in s.stats" :key="k"><dt>{{ k }}</dt><dd class="font-mono">{{ fmt(v) }}</dd></template>
        </dl>
        <p class="text-fg-dim mt-2.5 mb-0">{{ s.note }}</p>
        <div v-if="s.sheets.length" class="overflow-x-auto mt-2">
          <table class="tbl">
            <thead><tr><th>Sheet</th><th class="text-right">数据行数</th><th class="text-right">有效行数</th><th class="text-right">异常行数</th></tr></thead>
            <tbody>
              <tr v-for="sh in s.sheets" :key="sh.sheet" class="cursor-default">
                <td class="font-mono">{{ sh.sheet }}</td>
                <td class="text-right font-mono tabular-nums">{{ fmt(sh.rows) }}</td>
                <td class="text-right font-mono tabular-nums">{{ fmt(sh.validRows) }}</td>
                <td class="text-right font-mono tabular-nums" :class="sh.errorRows ? 'text-err' : ''">{{ sh.errorRows ?? 0 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="panel mb-4">
      <div class="panel-head"><h3>数据边界</h3><span class="text-fg-mute text-[11.5px]">四类数据源各自回答什么问题</span></div>
      <table class="tbl">
        <thead><tr><th>sourceType</th><th>职责</th></tr></thead>
        <tbody>
          <tr v-for="(v, k) in ds.boundary" :key="k" class="cursor-default">
            <td class="font-mono">{{ k }}</td><td>{{ v }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>REST 接口清单</h3><span class="text-fg-mute text-[11.5px]">{{ API_ENDPOINTS.length }} 个接口</span></div>
      <table class="tbl">
        <thead><tr><th class="w-[70px]">方法</th><th>路径</th></tr></thead>
        <tbody>
          <tr v-for="p in API_ENDPOINTS" :key="p" class="cursor-default">
            <td class="font-mono">GET</td><td class="font-mono">{{ p }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
