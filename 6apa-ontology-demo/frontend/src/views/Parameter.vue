<script setup lang="ts">
/** 参数详情（需求文档第十七章）：参数语义 + 测量锚点 + 关联工艺对象。 */
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { dash } from '@/composables/useOntologyMeta'
import { useSelection } from '@/composables/useSelection'
import type { DcsTag, Equipment, MeasurementAnchor, Parameter, Relation, RelationEntity, Rule } from '@/api/types'

const props = defineProps<{ parameterId: string }>()
const router = useRouter()
const { select } = useSelection()

type Detail = Parameter & {
  equipment: Equipment | null
  tags: DcsTag[]
  measurementAnchors: MeasurementAnchor[]
  relations: Relation[]
  relationEntities: RelationEntity[]
  rules: Rule[]
}

const d = ref<Detail | null>(null)
watch(() => props.parameterId, async (id) => { d.value = id ? await api.parameterDetail(id) : null }, { immediate: true })
</script>

<template>
  <div v-if="d">
    <nav class="flex items-center gap-1.5 mb-3.5 text-xs text-fg-mute">
      <RouterLink to="/overview" class="text-fg-dim no-underline hover:text-brand">6-APA 生产线</RouterLink>
      <span class="text-line">/</span>
      <RouterLink :to="`/areas/${d.areaId}`" class="text-fg-dim no-underline hover:text-brand">{{ d.areaName }}</RouterLink>
      <span class="text-line">/</span>
      <RouterLink :to="`/equipment/${d.equipmentId}`" class="text-fg-dim no-underline hover:text-brand">{{ d.equipmentName }}</RouterLink>
      <span class="text-line">/</span><span class="text-fg">{{ d.name }}</span>
    </nav>

    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold">{{ d.name }}</h2>
      <p class="m-0 text-fg-dim">
        所属设备 {{ d.equipmentName }} · 工段 {{ d.areaName }} ·
        <span class="font-mono">{{ d.owlSubject }}</span>
      </p>
    </header>

    <section class="panel mb-4">
      <div class="panel-head"><h3>参数语义</h3></div>
      <div class="panel-body">
        <dl class="kv" style="grid-template-columns: 120px 1fr">
          <dt>名称</dt><dd>{{ d.name }}</dd>
          <dt>参数分类</dt><dd>{{ d.categories.join('、') }}</dd>
          <dt>工程单位</dt><dd class="font-mono">{{ dash(d.units.join('、')) }}</dd>
          <dt>DCS 块类型</dt><dd class="font-mono">{{ dash(d.blockTypes.join('、')) }}</dd>
          <dt>所属设备</dt><dd>{{ d.equipmentName }}</dd>
          <dt>OWL Subject</dt><dd class="font-mono">{{ d.owlSubject }}</dd>
          <dt>绑定 DCS 点</dt><dd class="font-mono">{{ d.tags.map((t) => t.name).join('、') }}</dd>
        </dl>
      </div>
    </section>

    <section class="panel mb-4">
      <div class="panel-head">
        <h3>测量锚点</h3>
        <span class="text-fg-mute text-[11.5px]">工业语义 → DCS Tag → DCS 块</span>
      </div>
      <div class="panel-body">
        <div v-if="!d.measurementAnchors.length" class="empty">当前暂无对应 DCS 测点</div>
        <div v-for="(a, i) in d.measurementAnchors" :key="a.tagId" :class="i ? 'mt-3.5' : ''">
          <div class="flex flex-col">
            <div class="flex items-center gap-2.5 px-3 py-2 border border-line rounded-md bg-ink-panel2">
              <span class="text-fg-mute text-[10.5px] uppercase min-w-[74px]">工业语义</span>
              <span class="font-medium">{{ a.semanticName }}</span>
              <span class="ml-auto pill pill-plain">{{ a.parameterType }}</span>
            </div>
            <div class="h-4 ml-[30px] border-l border-dashed border-line"></div>
            <div class="flex items-center gap-2.5 px-3 py-2 border border-line rounded-md bg-ink-panel2">
              <span class="text-fg-mute text-[10.5px] uppercase min-w-[74px]">DCS Tag</span>
              <span class="font-medium font-mono">{{ a.tagName }}</span>
              <span class="ml-auto text-fg-mute">{{ a.rawDescription }}</span>
            </div>
            <div class="h-4 ml-[30px] border-l border-dashed border-line"></div>
            <div class="flex items-center gap-2.5 px-3 py-2 border border-line rounded-md bg-ink-panel2">
              <span class="text-fg-mute text-[10.5px] uppercase min-w-[74px]">DCS 块</span>
              <span class="font-medium font-mono">{{ a.blockType }}</span>
              <span class="ml-auto text-fg-mute">工程单位 {{ dash(a.unit) }} · 控制站 {{ a.station }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h3>关联工艺对象</h3>
        <span class="text-fg-mute text-[11.5px]">哪些关系对象以本参数作为测量锚点</span>
      </div>
      <div v-if="d.relationEntities.length" class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>对象语义名称</th><th>对象类型</th><th class="text-right">关系数</th><th>匹配方式</th></tr></thead>
          <tbody>
            <tr v-for="e in d.relationEntities" :key="e.id"
                @click="select('relationEntity', e.id); router.push(`/graph/${e.id}`)">
              <td><strong>{{ e.name }}</strong></td>
              <td>{{ e.type }}</td>
              <td class="text-right font-mono tabular-nums">{{ e.relationCount }}</td>
              <td>{{ e.matchStrategyLabel }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="panel-body"><div class="empty">本参数暂未被工业关系 Excel 引用</div></div>
    </section>
  </div>
  <div v-else class="py-16 text-center text-fg-mute">正在加载…</div>
</template>
