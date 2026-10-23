<script setup lang="ts">
/**
 * 本体 12 分类 / 9 项核心内容的统一展示入口（需求文档第四、五、十九章）。
 * 分类定义从 /api/ontology/categories 获取，不在页面中硬编码分类名称。
 */
import { ref, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useOntologyMeta, fmt, dash } from '@/composables/useOntologyMeta'
import { useSelection } from '@/composables/useSelection'
import type { Equipment, MeasurementAnchor, Relation, RelationEntity } from '@/api/types'

const props = defineProps<{ categoryKey: string }>()
const router = useRouter()
const { categoryByKey, edgeColor, load } = useOntologyMeta()
const { select } = useSelection()

const rows = ref<Record<string, unknown>[]>([])
const empty = ref<{ emptyReason: string; expectedSource: string } | null>(null)
const extra = ref<Record<string, unknown> | null>(null)
const loading = ref(false)

const category = computed(() => categoryByKey(props.categoryKey))

watch(() => props.categoryKey, async (key) => {
  loading.value = true
  rows.value = []; empty.value = null; extra.value = null
  await load()
  try {
    switch (key) {
      case 'class': rows.value = (await api.classes()).items; break
      case 'instance': rows.value = (await api.equipment({ limit: 300 })).items as never; break
      case 'property': rows.value = (await api.properties()).items; break
      case 'relation': {
        // 谓词清单：Schema 定义的对象属性 + 关系 Excel 中实际出现的谓词
        const rels = (await api.relations()).items
        const map = new Map<string, { predicate: string; count: number; categories: string[] }>()
        rels.forEach((r) => {
          const k = r.predicate ?? '未标注'
          const e = map.get(k) ?? { predicate: k, count: 0, categories: [] }
          e.count += 1
          if (r.category && !e.categories.includes(r.category)) e.categories.push(r.category)
          map.set(k, e)
        })
        rows.value = [...map.values()].sort((a, b) => b.count - a.count) as never
        break
      }
      case 'constraint': empty.value = await api.constraints() as never; break
      case 'capability': empty.value = await api.capabilities() as never; break
      case 'modelRegistry': empty.value = await api.modelRegistry() as never; break
      case 'rule': router.replace('/rules'); break
      case 'semantic': extra.value = await api.semantics({ limit: 150 }) as never; break
      case 'measurementAnchor': extra.value = await api.measurementAnchors() as never; break
      case 'causal': extra.value = await api.causalRelations() as never; break
      case 'provenance': router.replace('/data-sources'); break
    }
  } finally {
    loading.value = false
  }
}, { immediate: true })

const anchors = computed(() => (extra.value?.items ?? []) as MeasurementAnchor[])
const unanchored = computed(() => (extra.value?.unanchoredEntities ?? []) as RelationEntity[])
const causal = computed(() => (extra.value?.items ?? []) as Relation[])
const dcsSemantics = computed(() => (extra.value?.dcsSemantics ?? []) as Record<string, string>[])
const relSemantics = computed(() => (extra.value?.relationSemantics ?? []) as Record<string, string>[])
</script>

<template>
  <div>
    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold">{{ category?.name }} · {{ category?.nameEn }}</h2>
      <p class="m-0 text-fg-dim max-w-[78ch]">
        {{ category?.description }}
        <span class="font-mono text-fg-mute ml-2">{{ category?.endpoint }}</span>
      </p>
    </header>

    <div v-if="loading" class="py-16 text-center text-fg-mute">正在加载…</div>

    <!-- 空数据源分类：约束 / 能力 / 模型注册 -->
    <section v-else-if="empty" class="panel">
      <div class="panel-body">
        <div class="empty">{{ empty.emptyReason }}<br />期望数据源：{{ empty.expectedSource }}</div>
      </div>
    </section>

    <!-- 类 -->
    <section v-else-if="categoryKey === 'class'" class="panel">
      <div class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>URI</th><th>中文语义</th><th>建模要素</th><th class="text-right">实例数</th><th>三元组示例</th><th>来源</th></tr></thead>
          <tbody>
            <tr v-for="(c, i) in rows" :key="i" class="cursor-default">
              <td class="font-mono">{{ dash(c.uri) }}</td>
              <td><strong>{{ c.label }}</strong></td>
              <td>{{ c.kind }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(c.instanceCount as number) }}</td>
              <td class="font-mono text-[11px] text-fg-dim">{{ dash(c.example) }}</td>
              <td class="font-mono text-[11px] text-fg-mute">{{ c.sourceType }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 实例 -->
    <section v-else-if="categoryKey === 'instance'" class="panel">
      <div class="panel-head"><h3>设备实例</h3><span class="text-fg-mute text-[11.5px]">按点位数排序，显示前 300 台</span></div>
      <div class="overflow-x-auto max-h-[560px] overflow-y-auto">
        <table class="tbl">
          <thead><tr><th>设备</th><th>OWL Subject</th><th>工段</th><th>控制站</th><th class="text-right">参数</th><th class="text-right">点位</th></tr></thead>
          <tbody>
            <tr v-for="e in (rows as unknown as Equipment[])" :key="e.id"
                @click="select('equipment', e.id); router.push(`/equipment/${e.id}`)">
              <td><strong>{{ e.name }}</strong></td>
              <td class="font-mono text-[11px]">{{ e.owlSubject }}</td>
              <td>{{ e.areaName }}</td><td class="font-mono">{{ e.station }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(e.parameterCount) }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(e.tagCount) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 属性 -->
    <section v-else-if="categoryKey === 'property'" class="panel">
      <div class="overflow-x-auto max-h-[620px] overflow-y-auto">
        <table class="tbl">
          <thead><tr><th>属性名 / 字段</th><th>中文语义</th><th>建模要素</th><th>Domain</th><th>Range</th><th>来源</th></tr></thead>
          <tbody>
            <tr v-for="(p, i) in rows" :key="i" class="cursor-default">
              <td class="font-mono">{{ p.name }}</td><td>{{ dash(p.label) }}</td>
              <td>{{ p.kind }}</td>
              <td class="font-mono text-[11px]">{{ dash(p.domain) }}</td>
              <td class="font-mono text-[11px]">{{ dash(p.range) }}</td>
              <td class="font-mono text-[11px] text-fg-mute">{{ p.sourceType }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 关系谓词 -->
    <section v-else-if="categoryKey === 'relation'" class="panel">
      <div class="panel-head"><h3>关系谓词</h3><span class="text-fg-mute text-[11.5px]">来自关系 Excel；点击跳转到关系清单</span></div>
      <div class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>谓词 / 边类型</th><th>所属关系大类</th><th class="text-right">出现次数</th></tr></thead>
          <tbody>
            <tr v-for="(p, i) in rows" :key="i"
                @click="router.push({ path: '/relations', query: { predicate: p.predicate as string } })">
              <td class="font-mono">{{ p.predicate }}</td>
              <td>
                <span v-for="c in (p.categories as string[])" :key="c" class="pill pill-plain mr-1">
                  <i class="w-[7px] h-[7px] rounded-sm" :style="{ background: edgeColor(c) }"></i>{{ c }}
                </span>
              </td>
              <td class="text-right font-mono tabular-nums">{{ fmt(p.count as number) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 语义 -->
    <template v-else-if="categoryKey === 'semantic'">
      <section class="panel mb-4">
        <div class="panel-head">
          <h3>DCS 语义提升</h3>
          <span class="text-fg-mute text-[11.5px]">
            DCS 原始描述 → 参数语义 → 工业对象 · 共 {{ fmt(extra?.dcsSemanticTotal as number) }} 条
          </span>
        </div>
        <div class="overflow-x-auto max-h-[460px] overflow-y-auto">
          <table class="tbl">
            <thead><tr><th>DCS 原始描述</th><th>参数语义</th><th>工业对象</th><th>OWL Subject</th><th>DCS 点名</th></tr></thead>
            <tbody>
              <tr v-for="(s, i) in dcsSemantics" :key="i" @click="select('parameter', s.parameterId)">
                <td class="text-fg-dim">{{ s.rawDescription }}</td>
                <td><strong>{{ s.parameterSemantic }}</strong></td>
                <td>{{ s.industrialObject }}</td>
                <td class="font-mono text-[11px]">{{ s.owlSubject }}</td>
                <td class="font-mono">{{ s.tagName }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h3>关系语义</h3><span class="text-fg-mute text-[11.5px]">起始对象 → 谓词 → 目标对象 → 工艺机理说明</span></div>
        <div class="overflow-x-auto max-h-[460px] overflow-y-auto">
          <table class="tbl">
            <thead><tr><th>起始对象</th><th>谓词</th><th>目标对象</th><th>工艺机理与业务因果说明</th></tr></thead>
            <tbody>
              <tr v-for="(s, i) in relSemantics" :key="i" @click="select('relation', s.id)">
                <td><strong>{{ s.subjectEntity }}</strong></td>
                <td><span class="pill pill-info">{{ s.predicate }}</span></td>
                <td>{{ s.objectEntity }}</td>
                <td class="text-fg-dim">{{ s.domainDescription }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <!-- 测量锚点 -->
    <template v-else-if="categoryKey === 'measurementAnchor'">
      <section class="panel mb-4">
        <div class="panel-head">
          <h3>已建立的测量锚点</h3>
          <span class="text-fg-mute text-[11.5px]">工业语义 → DCS Tag → DCS 块，共 {{ fmt(anchors.length) }} 条</span>
        </div>
        <div class="overflow-x-auto max-h-[460px] overflow-y-auto">
          <table class="tbl">
            <thead><tr><th>关系对象</th><th>设备</th><th>参数语义</th><th>DCS 点名</th><th>DCS 块</th><th>单位</th><th>控制站</th><th>原点描述</th></tr></thead>
            <tbody>
              <tr v-for="a in anchors" :key="a.tagId + a.relationEntityId" @click="select('parameter', a.parameterId)">
                <td><strong>{{ a.relationEntityName ?? a.semanticName }}</strong></td>
                <td>{{ a.equipmentName }}</td><td>{{ a.semanticName }}</td>
                <td class="font-mono">{{ a.tagName }}</td><td class="font-mono">{{ a.blockType }}</td>
                <td class="font-mono">{{ dash(a.unit) }}</td><td class="font-mono">{{ a.station }}</td>
                <td class="text-fg-dim">{{ a.rawDescription }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head">
          <h3>暂无 DCS 测量锚点的关系对象</h3>
          <span class="text-fg-mute text-[11.5px]">{{ unanchored.length }} 个 · 关系数据已加载，不虚构 DCS 点</span>
        </div>
        <div class="overflow-x-auto max-h-[420px] overflow-y-auto">
          <table class="tbl">
            <thead><tr><th>对象</th><th>类型</th><th>匹配状态</th><th class="text-right">关系数</th></tr></thead>
            <tbody>
              <tr v-for="e in unanchored" :key="e.id" @click="router.push(`/graph/${e.id}`)">
                <td><strong>{{ e.name }}</strong></td><td>{{ e.type }}</td>
                <td><span class="pill" :class="e.matchStatus === 'MATCHED' ? 'pill-ok' : 'pill-mute'">{{ e.matchStatusLabel }}</span></td>
                <td class="text-right font-mono tabular-nums">{{ e.relationCount }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <!-- 因果关系 -->
    <section v-else-if="categoryKey === 'causal'" class="panel">
      <div class="panel-head">
        <h3>因果 / 影响 / 质量关系</h3>
        <span class="text-fg-mute text-[11.5px]">共 {{ causal.length }} 条，直接来自关系 Excel，不重新推断</span>
      </div>
      <div class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>工段</th><th>关系大类</th><th>原因对象</th><th>影响方向</th><th>结果对象</th><th class="text-right">权重</th><th>工艺机理与业务因果说明</th></tr></thead>
          <tbody>
            <tr v-for="r in causal" :key="r.id" @click="select('relation', r.id)">
              <td>{{ r.area }}</td>
              <td>
                <span class="pill pill-plain">
                  <i class="w-[7px] h-[7px] rounded-sm" :style="{ background: edgeColor(r.category) }"></i>{{ r.category }}
                </span>
              </td>
              <td><strong>{{ r.subjectEntity }}</strong></td>
              <td><span class="pill" :class="String(r.predicate).includes('负向') ? 'pill-err' : 'pill-ok'">{{ r.predicate }}</span></td>
              <td><strong>{{ r.objectEntity }}</strong></td>
              <td class="text-right font-mono tabular-nums">{{ r.weight }}</td>
              <td class="text-fg-dim">{{ r.domainDescription }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
