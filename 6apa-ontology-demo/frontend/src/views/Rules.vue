<script setup lang="ts">
/** 规则视图（需求文档第十三章）：规则只来自独立规则文件，缺失时显示空状态。 */
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type { Rule } from '@/api/types'

const payload = ref<{ items: Rule[]; total: number; emptyReason?: string; expectedSource?: string; templateColumns?: string[] } | null>(null)
onMounted(async () => { payload.value = await api.rules() })
</script>

<template>
  <div v-if="payload">
    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold">规则 · Rule</h2>
      <p class="m-0 text-fg-dim max-w-[78ch]">
        推理规则，来自独立规则 Excel / 规则文件，不从参数名称自动生成。
        <span class="font-mono text-fg-mute">/api/ontology/rules</span>
      </p>
    </header>

    <section v-if="payload.total" class="panel">
      <div class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>规则编号</th><th>规则名称</th><th>适用对象</th><th>条件</th><th>推理结论</th><th>严重程度</th><th>来源</th></tr></thead>
          <tbody>
            <tr v-for="r in payload.items" :key="r.id" class="cursor-default">
              <td class="font-mono">{{ r.ruleId }}</td><td><strong>{{ r.name }}</strong></td>
              <td>{{ r.appliesTo }}</td><td>{{ r.condition }}</td>
              <td>{{ r.conclusion }}</td><td>{{ r.severity }}</td>
              <td class="font-mono text-[11px] text-fg-mute">{{ r.sourceType }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-else class="panel">
      <div class="panel-head"><h3>规则数据源</h3><span class="ml-auto pill pill-mute">未提供</span></div>
      <div class="panel-body">
        <div class="empty">{{ payload.emptyReason }}</div>
        <p class="text-fg-dim mt-4">
          规则文件就位后即自动加载，期望文件名
          <span class="font-mono">{{ payload.expectedSource }}</span>，Sheet「规则明细」字段如下
          （仓库内已提供空表模板 <span class="font-mono">6APA_规则.模板.xlsx</span>）：
        </p>
        <ul class="list-none m-0 p-0 columns-2 gap-7">
          <li v-for="c in payload.templateColumns ?? []" :key="c" class="font-mono py-1.5 border-b border-line-soft">{{ c }}</li>
        </ul>
      </div>
    </section>
  </div>
</template>
