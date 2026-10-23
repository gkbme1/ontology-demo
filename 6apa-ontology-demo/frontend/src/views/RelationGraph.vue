<script setup lang="ts">
/** 关系图谱 / 关系对象详情（需求文档第十一、二十章）。 */
import { ref, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Query } from '@/api/client'
import { fmt } from '@/composables/useOntologyMeta'
import { useSelection } from '@/composables/useSelection'
import OntologyGraph from '@/components/OntologyGraph.vue'
import type { GraphEdge, GraphNode, GraphPayload, Relation, RelationEntity, RelationEntityDetail } from '@/api/types'

const props = defineProps<{ entityId?: string }>()
const router = useRouter()
const { select } = useSelection()

const graph = ref<GraphPayload | null>(null)
const entity = ref<RelationEntityDetail | null>(null)
const allRelations = ref<Relation[]>([])
const entities = ref<RelationEntity[]>([])

const depth = ref(1)
const showDcs = ref(false)
const filters = ref<Query>({})

const uniq = (key: keyof Relation) => {
  const out: string[] = []
  allRelations.value.forEach((r) => {
    const v = r[key]
    if (typeof v === 'string' && v && !out.includes(v)) out.push(v)
  })
  return out.sort()
}

async function reload() {
  const q: Query = { ...filters.value, depth: depth.value, includeDcs: showDcs.value }
  if (props.entityId) q.rootId = props.entityId
  graph.value = await api.graph(q)
}

watch([() => props.entityId, depth, showDcs, filters], async () => {
  if (props.entityId) {
    entity.value = await api.relationEntityDetail(props.entityId)
    select('relationEntity', props.entityId)
  } else {
    entity.value = null
  }
  await reload()
}, { immediate: true, deep: true })

watch(() => props.entityId, async () => {
  if (!allRelations.value.length) {
    const [r, e] = await Promise.all([api.relations(), api.relationEntities()])
    allRelations.value = r.items
    entities.value = e.items
  }
}, { immediate: true })

const onNode = (n: GraphNode) => {
  const id = n.id.replace(/^dcs::/, '')
  if (n.nodeKind === 'relationEntity') router.push(`/graph/${id}`)
  else if (n.nodeKind === 'equipment') select('equipment', id)
  else if (n.nodeKind === 'parameter') select('parameter', id)
  else if (n.nodeKind === 'tag') select('tag', id)
  else if (n.nodeKind === 'area') router.push(`/areas/${id}`)
}
const onEdge = (e: GraphEdge) => {
  if (e.edgeKind === 'relation') select('relation', e.id)
  else select('structuralEdge', e.id, e)
}

const parts = computed(() => entity.value?.outgoingRelations.filter((r) => r.objectType === '设备部件') ?? [])
const props_ = computed(() => entity.value?.outgoingRelations.filter((r) => r.objectType === '工艺属性') ?? [])
const allRels = computed(() =>
  [...(entity.value?.outgoingRelations ?? []), ...(entity.value?.incomingRelations ?? [])])
</script>

<template>
  <div>
    <nav v-if="entity" class="flex items-center gap-1.5 mb-3.5 text-xs text-fg-mute">
      <RouterLink to="/" class="text-fg-dim no-underline hover:text-brand">6-APA 生产线</RouterLink>
      <span class="text-line">/</span>
      <RouterLink to="/graph" class="text-fg-dim no-underline hover:text-brand">关系图谱</RouterLink>
      <span class="text-line">/</span><span class="text-fg">{{ entity.name }}</span>
    </nav>

    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold">{{ entity?.name ?? '关系图谱' }}</h2>
      <p v-if="entity" class="m-0 text-fg-dim">
        <span class="pill pill-plain mr-1">{{ entity.type }}</span>
        <span class="pill mr-1" :class="entity.matchStatus === 'MATCHED' ? 'pill-ok' : 'pill-mute'">{{ entity.matchStatusLabel }}</span>
        <span v-if="entity.pendingConfirmation" class="pill pill-warn mr-1">映射待现场确认</span>
        · 关系 {{ entity.relationCount }} 条 · 工段 {{ entity.areas.join('、') }}
      </p>
      <p v-else class="m-0 text-fg-dim max-w-[78ch]">
        关系边全部来自工业关系 Excel。系统不根据设备名称、编号或参数名称推断任何关系。
      </p>
    </header>

    <section class="panel mb-4">
      <div v-if="!entityId" class="flex flex-wrap gap-2 px-4 py-3 border-b border-line-soft">
        <label class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">中心对象
          <select class="ctl min-w-[220px]" @change="(e) => router.push(`/graph/${(e.target as HTMLSelectElement).value}`)">
            <option value="">（不指定中心，显示全部筛选结果）</option>
            <option v-for="e in entities" :key="e.id" :value="e.id">{{ e.name }} · {{ e.type }}</option>
          </select>
        </label>
        <label v-for="f in ([['area','工段'],['category','关系大类'],['predicate','关系谓词'],['subjectType','起始对象类型'],['objectType','目标对象类型'],['scenario','子场景']] as const)"
               :key="f[0]" class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">
          {{ f[1] }}
          <select class="ctl" :value="(filters[f[0]] as string) ?? ''"
                  @change="(e) => filters = { ...filters, [f[0]]: (e.target as HTMLSelectElement).value || undefined }">
            <option value="">全部</option>
            <option v-for="v in uniq(f[0] as keyof Relation)" :key="v" :value="v">{{ v }}</option>
          </select>
        </label>
        <label class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">最小权重
          <input class="ctl w-[78px]" type="number" step="0.5" :value="filters.minWeight ?? ''"
                 @input="(e) => filters = { ...filters, minWeight: (e.target as HTMLInputElement).value || undefined }" />
        </label>
        <label class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">最大权重
          <input class="ctl w-[78px]" type="number" step="0.5" :value="filters.maxWeight ?? ''"
                 @input="(e) => filters = { ...filters, maxWeight: (e.target as HTMLInputElement).value || undefined }" />
        </label>
        <label class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">匹配状态
          <select class="ctl" :value="filters.matched ?? ''"
                  @change="(e) => filters = { ...filters, matched: (e.target as HTMLSelectElement).value || undefined }">
            <option value="">全部</option>
            <option value="1">仅已匹配 DCS 实例</option>
            <option value="0">仅未匹配</option>
          </select>
        </label>
        <label class="inline-flex flex-col gap-1 text-[10px] uppercase tracking-wider text-fg-mute">&nbsp;
          <button class="ctl" @click="filters = {}">重置筛选</button>
        </label>
      </div>

      <div class="relative">
        <div class="absolute right-3 top-3 z-10 flex gap-1.5">
          <button v-for="d in [1, 2, 3]" :key="d" class="ctl" :class="depth === d ? 'ctl-on' : ''" @click="depth = d">{{ d }} 跳</button>
          <button class="ctl" :class="showDcs ? 'ctl-on' : ''" @click="showDcs = !showDcs">DCS 实例</button>
        </div>
        <OntologyGraph :graph="graph" :height="entityId ? '560px' : '640px'" @node-click="onNode" @edge-click="onEdge" />
      </div>
    </section>

    <template v-if="entity">
      <section v-for="block in [{ t: '设备部件', n: 'predicate = 具有部件', rows: parts, empty: '本对象无部件关系' },
                                { t: '工艺属性', n: 'predicate = 具有属性', rows: props_, empty: '本对象无属性关系' },
                                { t: '全部关系', n: `${entity.outgoingCount} 条出边 · ${entity.incomingCount} 条入边`, rows: allRels, empty: '无关系' }]"
               :key="block.t" class="panel mb-4">
        <div class="panel-head"><h3>{{ block.t }}</h3><span class="text-fg-mute text-[11.5px]">{{ block.n }}</span></div>
        <div v-if="block.rows.length" class="overflow-x-auto">
          <table class="tbl">
            <thead><tr><th>关系谓词</th><th>对象</th><th>类型</th><th>子场景</th><th class="text-right">权重</th><th>工艺机理与业务因果说明</th></tr></thead>
            <tbody>
              <tr v-for="r in block.rows" :key="r.id" @click="select('relation', r.id)">
                <td><span class="pill pill-info">{{ r.predicate }}</span></td>
                <td><strong>{{ r.subject.id === entity.id ? r.objectEntity : r.subjectEntity }}</strong></td>
                <td>{{ r.subject.id === entity.id ? r.objectType : r.subjectType }}</td>
                <td>{{ r.scenario }}</td>
                <td class="text-right font-mono tabular-nums">{{ r.weight }}</td>
                <td class="text-fg-dim">{{ r.domainDescription }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="panel-body"><div class="empty">{{ block.empty }}</div></div>
      </section>

      <section class="panel mb-4">
        <div class="panel-head"><h3>匹配的本体实例</h3><span class="text-fg-mute text-[11.5px]">关系对象 → DCS 本体对象</span></div>
        <div v-if="entity.matches.length" class="overflow-x-auto max-h-[420px] overflow-y-auto">
          <table class="tbl">
            <thead><tr><th>本体对象</th><th>类型</th><th>标识</th><th>匹配方式</th><th>置信度</th><th>确认状态</th><th>映射说明</th></tr></thead>
            <tbody>
              <tr v-for="m in entity.matches" :key="m.objectType + m.id"
                  @click="m.objectType === 'equipment' ? select('equipment', m.id) : m.objectType === 'parameter' ? select('parameter', m.id) : null">
                <td><strong>{{ m.name }}</strong></td>
                <td>{{ { equipment: '设备', parameter: '参数', area: '工段' }[m.objectType] }}</td>
                <td class="font-mono text-[11px]">{{ m.owlSubject ?? m.equipmentName }}</td>
                <td>{{ m.strategyLabel }}</td>
                <td>
                  <span v-if="m.confidence" class="pill"
                        :class="m.confidence === '高' ? 'pill-ok' : m.confidence === '中' ? 'pill-warn' : 'pill-err'">{{ m.confidence }}</span>
                  <span v-else>—</span>
                </td>
                <td><span v-if="m.status" class="pill pill-warn">{{ m.status }}</span><span v-else>—</span></td>
                <td class="text-fg-dim">{{ m.note }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="panel-body">
          <div class="empty">
            未匹配 DCS 实例。该关系对象已加载并保留为外部关系对象，未在 DCS 点表或对象映射表中找到对应实例，关系数据不会被丢弃。
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h3>测量锚点</h3><span class="text-fg-mute text-[11.5px]">共 {{ fmt(entity.measurementAnchors.length) }} 条</span></div>
        <div v-if="entity.measurementAnchors.length" class="overflow-x-auto max-h-[420px] overflow-y-auto">
          <table class="tbl">
            <thead><tr><th>设备</th><th>参数语义</th><th>DCS 点名</th><th>DCS 块</th><th>单位</th><th>原点描述</th></tr></thead>
            <tbody>
              <tr v-for="a in entity.measurementAnchors" :key="a.tagId" @click="select('parameter', a.parameterId)">
                <td>{{ a.equipmentName }}</td><td>{{ a.semanticName }}</td>
                <td class="font-mono">{{ a.tagName }}</td><td class="font-mono">{{ a.blockType }}</td>
                <td class="font-mono">{{ a.unit ?? '—' }}</td><td class="text-fg-dim">{{ a.rawDescription }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="panel-body">
          <div class="empty">关系对象已加载，当前暂无对应 DCS 测点。不虚构任何 DCS 点。</div>
        </div>
      </section>
    </template>
  </div>
</template>
