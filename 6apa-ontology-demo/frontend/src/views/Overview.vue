<script setup lang="ts">
/** 首页：生产线本体总览（需求文档第十五章）。全部数字由 Excel 实际数据计算。 */
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useOntologyMeta, fmt } from '@/composables/useOntologyMeta'
import type { Overview, ProcessArea, Relation, DataSourcesPayload } from '@/api/types'

const router = useRouter()
const { edgeColor } = useOntologyMeta()

const overview = ref<Overview | null>(null)
const areas = ref<ProcessArea[]>([])
const relations = ref<Relation[]>([])
const sources = ref<DataSourcesPayload | null>(null)

onMounted(async () => {
  const [o, a, r, s] = await Promise.all([
    api.overview(), api.processAreas(), api.relations(), api.dataSources()
  ])
  overview.value = o
  areas.value = a.items
  relations.value = r.items
  sources.value = s
})

const stats = computed(() => {
  const o = overview.value
  if (!o) return []
  return [
    { k: '生产工段', v: o.processAreaCount, accent: true },
    { k: '控制站', v: o.controlStationCount },
    { k: '设备 / 装置', v: o.equipmentCount },
    { k: '参数语义', v: o.parameterCount },
    { k: 'DCS 点位', v: o.tagCount, accent: true },
    { k: '工业关系', v: o.relationCount },
    { k: '关系对象', v: o.relationObjectCount },
    { k: '测量锚点', v: o.measurementAnchorCount }
  ]
})

const tagStats = computed(() => {
  const t = overview.value?.tagStats
  if (!t) return []
  return [
    { k: '过程测量 PV', v: t.pv, c: '#35c4d7' },
    { k: '控制输出 OP', v: t.op, c: '#4c8dff' },
    { k: '电机控制 MOT', v: t.mot, c: '#ff9f45' },
    { k: '阀门控制 VAL', v: t.val, c: '#b07cff' },
    { k: '开关/状态 DI·DO', v: t.dido, c: '#6f819e' }
  ]
})
const maxTag = computed(() => Math.max(1, ...tagStats.value.map((x) => x.v)))

const relByCategory = computed(() => {
  const map = new Map<string, number>()
  relations.value.forEach((r) => map.set(r.category ?? '未标注', (map.get(r.category ?? '未标注') ?? 0) + 1))
  return [...map.entries()].sort((a, b) => b[1] - a[1])
})
</script>

<template>
  <div v-if="overview">
    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold text-balance">6-APA 生产线工业本体</h2>
      <p class="m-0 text-fg-dim max-w-[78ch]">
        以下全部数字由现场 DCS 点表与工业关系 Excel 实时统计得出，不含任何示例或 Mock 数据。
        数据加载时间 {{ overview.loadedAt }}。
      </p>
    </header>

    <div class="stat-row mb-4">
      <div v-for="s in stats" :key="s.k" class="stat">
        <div class="stat-k">{{ s.k }}</div>
        <div class="stat-v" :class="s.accent ? 'text-brand' : ''">{{ fmt(s.v) }}</div>
      </div>
    </div>

    <section class="panel mb-4">
      <div class="panel-head">
        <h3>生产工段</h3>
        <span class="text-fg-mute text-[11.5px]">点击进入工段 → 设备 → 参数 → DCS 点</span>
      </div>
      <div class="overflow-x-auto">
        <table class="tbl">
          <thead>
            <tr>
              <th>工段</th><th>控制站</th>
              <th class="text-right">设备</th><th class="text-right">参数语义</th>
              <th class="text-right">DCS 点</th><th class="text-right">关系</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in areas" :key="a.id" @click="router.push(`/areas/${a.id}`)">
              <td>
                <strong>{{ a.nameZh }}</strong>
                <div class="font-mono text-fg-mute text-[11px]">{{ a.nameEn }}</div>
              </td>
              <td class="font-mono">{{ a.stations.join('、') }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(a.equipmentCount) }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(a.parameterCount) }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(a.tagCount) }}</td>
              <td class="text-right font-mono tabular-nums">
                <span v-if="a.relationCount">{{ fmt(a.relationCount) }}</span>
                <span v-else class="text-fg-mute">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="grid gap-4 mb-4" style="grid-template-columns: repeat(auto-fit, minmax(320px, 1fr))">
      <section class="panel">
        <div class="panel-head">
          <h3>DCS 点位构成</h3>
          <span class="text-fg-mute text-[11.5px]">共 {{ fmt(overview.tagCount) }} 点</span>
        </div>
        <table class="tbl">
          <tbody>
            <tr v-for="t in tagStats" :key="t.k" class="cursor-default">
              <td>{{ t.k }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(t.v) }}</td>
              <td style="width: 44%">
                <div class="h-[5px] rounded bg-line-soft overflow-hidden min-w-[54px]">
                  <i class="block h-full rounded" :style="{ width: `${(100 * t.v) / maxTag}%`, background: t.c }"></i>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h3>关系大类分布</h3>
          <span class="text-fg-mute text-[11.5px]">共 {{ fmt(relations.length) }} 条关系</span>
        </div>
        <table class="tbl">
          <tbody>
            <tr v-for="[cat, count] in relByCategory" :key="cat"
                @click="router.push({ path: '/relations', query: { category: cat } })">
              <td>
                <span class="pill pill-plain">
                  <i class="w-[7px] h-[7px] rounded-sm" :style="{ background: edgeColor(cat) }"></i>{{ cat }}
                </span>
              </td>
              <td class="text-right font-mono tabular-nums">{{ fmt(count) }}</td>
              <td style="width: 52%">
                <div class="h-[5px] rounded bg-line-soft overflow-hidden min-w-[54px]">
                  <i class="block h-full rounded"
                     :style="{ width: `${(100 * count) / relations.length}%`, background: edgeColor(cat) }"></i>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <h3 class="text-[13px] font-semibold mb-2.5">
      数据源
      <span class="ml-2 font-normal text-fg-mute text-[11.5px]">
        DCS 事实 / 关系事实 / 对象对齐 / 推理规则 四类数据源相互独立
      </span>
    </h3>
    <div class="grid gap-3.5" style="grid-template-columns: repeat(auto-fit, minmax(272px, 1fr))">
      <section v-for="s in sources?.sources ?? []" :key="s.file" class="panel">
        <div class="panel-head">
          <h3>{{ s.sourceTypeLabel }}</h3>
          <span class="ml-auto pill" :class="s.available ? 'pill-ok' : 'pill-mute'">{{ s.status }}</span>
        </div>
        <div class="panel-body">
          <div class="font-mono mb-1.5">{{ s.file }}</div>
          <p class="text-fg-dim m-0 mb-2.5">{{ s.note }}</p>
          <ul class="list-none m-0 p-0">
            <li v-for="sh in s.sheets" :key="sh.sheet" class="py-1.5 border-b border-line-soft last:border-0">
              <span class="font-mono">{{ sh.sheet }}</span>
              <span class="float-right font-mono text-fg-mute">{{ fmt(sh.rows) }} 行</span>
            </li>
          </ul>
        </div>
      </section>
    </div>
  </div>
  <div v-else class="py-16 text-center text-fg-mute">正在加载…</div>
</template>
