<script setup lang="ts">
/** 关系清单（需求文档 11.4 / 19.3）：按工段、大类、谓词、对象类型、子场景、权重筛选。 */
import { ref, watch, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type Query } from '@/api/client'
import { useOntologyMeta } from '@/composables/useOntologyMeta'
import { useSelection } from '@/composables/useSelection'
import type { Relation } from '@/api/types'

const route = useRoute()
const router = useRouter()
const { edgeColor } = useOntologyMeta()
const { select } = useSelection()

const all = ref<Relation[]>([])
const items = ref<Relation[]>([])
const filters = ref<Query>({})

onMounted(async () => {
  all.value = (await api.relations()).items
  filters.value = { ...route.query } as Query
})

watch(filters, async (f) => { items.value = (await api.relations(f)).items }, { deep: true, immediate: true })

const uniq = (key: keyof Relation) => {
  const out: string[] = []
  all.value.forEach((r) => {
    const v = r[key]
    if (typeof v === 'string' && v && !out.includes(v)) out.push(v)
  })
  return out.sort()
}

const setFilter = (key: string, value: string) => {
  filters.value = { ...filters.value, [key]: value || undefined }
  router.replace({ query: Object.fromEntries(Object.entries(filters.value).filter(([, v]) => v != null)) as never })
}

const statusLabel = (r: Relation) =>
  r.matchStatus === 'MATCHED' ? '双端已匹配' : r.matchStatus === 'PARTIAL' ? '单端已匹配' : '双端未匹配'
const fields = [
  ['area', '工段'], ['category', '关系大类'], ['predicate', '关系谓词'],
  ['subjectType', '起始对象类型'], ['objectType', '目标对象类型'], ['scenario', '子场景']
] as const
</script>

<template>
  <div>
    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold">关系清单</h2>
      <p class="m-0 text-fg-dim max-w-[78ch]">
        共 {{ all.length }} 条关系，全部来自 <span class="font-mono">6APA_工业关系.xlsx</span> 的「关系明细」Sheet。
        当前筛选命中 {{ items.length }} 条。
      </p>
    </header>

    <section class="panel">
      <div class="flex flex-wrap gap-2 px-4 py-3 border-b border-line-soft">
        <label v-for="f in fields" :key="f[0]" class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">
          {{ f[1] }}
          <select class="ctl" :value="(filters[f[0]] as string) ?? ''" @change="(e) => setFilter(f[0], (e.target as HTMLSelectElement).value)">
            <option value="">全部</option>
            <option v-for="v in uniq(f[0] as keyof Relation)" :key="v" :value="v">{{ v }}</option>
          </select>
        </label>
        <label class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">最小权重
          <input class="ctl w-[78px]" type="number" step="0.5" :value="filters.minWeight ?? ''"
                 @input="(e) => setFilter('minWeight', (e.target as HTMLInputElement).value)" />
        </label>
        <label class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">最大权重
          <input class="ctl w-[78px]" type="number" step="0.5" :value="filters.maxWeight ?? ''"
                 @input="(e) => setFilter('maxWeight', (e.target as HTMLInputElement).value)" />
        </label>
        <label class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">关键词
          <input class="ctl" placeholder="对象 / 谓词 / 机理说明" :value="filters.keyword ?? ''"
                 @input="(e) => setFilter('keyword', (e.target as HTMLInputElement).value)" />
        </label>
        <label class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">&nbsp;
          <button class="ctl" @click="filters = {}; router.replace({ query: {} })">重置</button>
        </label>
      </div>

      <div class="overflow-x-auto">
        <table class="tbl">
          <thead>
            <tr>
              <th>工段</th><th>关系大类</th><th>起始对象</th><th>谓词</th><th>目标对象</th>
              <th>子场景</th><th class="text-right">权重</th><th>工艺机理与业务因果说明</th><th>匹配</th><th>来源</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in items" :key="r.id" @click="select('relation', r.id)">
              <td>{{ r.area }}</td>
              <td>
                <span class="pill pill-plain">
                  <i class="w-[7px] h-[7px] rounded-sm" :style="{ background: edgeColor(r.category) }"></i>{{ r.category }}
                </span>
              </td>
              <td @click.stop="r.subject.id && router.push(`/graph/${r.subject.id}`)">
                <strong>{{ r.subjectEntity }}</strong>
                <div class="text-fg-mute text-[11px]">{{ r.subjectType }}</div>
              </td>
              <td><span class="pill pill-info">{{ r.predicate }}</span></td>
              <td @click.stop="r.object.id && router.push(`/graph/${r.object.id}`)">
                <strong>{{ r.objectEntity }}</strong>
                <div class="text-fg-mute text-[11px]">{{ r.objectType }}</div>
              </td>
              <td>{{ r.scenario }}</td>
              <td class="text-right font-mono tabular-nums">{{ r.weight }}</td>
              <td class="text-fg-dim max-w-[260px]">{{ r.domainDescription }}</td>
              <td><span class="pill" :class="r.matchStatus === 'MATCHED' ? 'pill-ok' : 'pill-mute'">{{ statusLabel(r) }}</span></td>
              <td class="font-mono text-[11px] text-fg-mute">第 {{ r.source.row }} 行</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
