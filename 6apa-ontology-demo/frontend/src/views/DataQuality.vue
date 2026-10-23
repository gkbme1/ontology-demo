<script setup lang="ts">
/** 数据质量报告（需求文档第二十三章）：检查只报告问题，不修改原始数据。 */
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { fmt } from '@/composables/useOntologyMeta'
import type { QualityReport } from '@/api/types'

const q = ref<QualityReport | null>(null)
onMounted(async () => { q.value = await api.dataQuality() })
const pill = (sev: string) => (sev === 'error' ? 'pill-err' : sev === 'warning' ? 'pill-warn' : 'pill-info')
</script>

<template>
  <div v-if="q">
    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold">数据质量报告</h2>
      <p class="m-0 text-fg-dim max-w-[78ch]">导入 Excel 时自动执行一致性校验。检查只报告问题，不修改任何原始数据。</p>
    </header>

    <div class="stat-row mb-4">
      <div class="stat"><div class="stat-k">检查项</div><div class="stat-v">{{ fmt(q.summary.checkCount) }}</div></div>
      <div class="stat"><div class="stat-k">通过</div><div class="stat-v text-ok">{{ fmt(q.summary.passedCount) }}</div></div>
      <div class="stat"><div class="stat-k">错误</div><div class="stat-v text-err">{{ fmt(q.summary.errorCount) }}</div></div>
      <div class="stat"><div class="stat-k">告警</div><div class="stat-v text-warn">{{ fmt(q.summary.warningCount) }}</div></div>
      <div class="stat"><div class="stat-k">提示</div><div class="stat-v text-info">{{ fmt(q.summary.infoCount) }}</div></div>
    </div>

    <section class="panel mb-4">
      <div class="panel-head"><h3>检查项</h3></div>
      <div class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>分组</th><th>检查项</th><th>说明</th><th>结果</th></tr></thead>
          <tbody>
            <tr v-for="c in q.checks" :key="c.check" class="cursor-default">
              <td>{{ c.group }}</td><td><strong>{{ c.check }}</strong></td>
              <td class="text-fg-dim">{{ c.description }}</td>
              <td>
                <span v-if="c.passed" class="pill pill-ok">通过</span>
                <span v-else class="pill" :class="pill(c.severity)">{{ fmt(c.issueCount) }} 项</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h3>问题明细</h3>
        <span class="text-fg-mute text-[11.5px]">共 {{ fmt(q.summary.issueCount) }} 项，显示前 200 项</span>
      </div>
      <div class="overflow-x-auto max-h-[460px] overflow-y-auto">
        <table class="tbl">
          <thead><tr><th>级别</th><th>检查项</th><th>问题描述</th><th>来源</th></tr></thead>
          <tbody>
            <tr v-for="(i, idx) in q.issues.slice(0, 200)" :key="idx" class="cursor-default">
              <td><span class="pill" :class="pill(i.severity)">{{ i.severity }}</span></td>
              <td>{{ i.check }}</td>
              <td class="text-fg-dim">{{ i.detail }}</td>
              <td class="font-mono text-[11px] text-fg-mute">
                {{ i.source ? `${i.source.sheet ?? ''}${i.source.row ? ` 第 ${i.source.row} 行` : ''}` : '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
