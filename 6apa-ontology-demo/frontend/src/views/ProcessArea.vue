<script setup lang="ts">
/** 工段列表 / 工段详情（需求文档第十五章）。 */
import { ref, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useOntologyMeta, fmt } from '@/composables/useOntologyMeta'
import { useSelection } from '@/composables/useSelection'
import type { Equipment, ProcessArea, Relation, RelationEntity } from '@/api/types'

const props = defineProps<{ areaId?: string }>()
const router = useRouter()
const { edgeColor, nodeColor } = useOntologyMeta()
const { select } = useSelection()

const areas = ref<ProcessArea[]>([])
const detail = ref<(ProcessArea & {
  equipment: Equipment[]
  relations: Relation[]
  relationCategoryCounts: Record<string, number>
}) | null>(null)
const entities = ref<RelationEntity[]>([])

watch(() => props.areaId, async (id) => {
  if (id) {
    const [d, e] = await Promise.all([api.processArea(id), api.relationEntities()])
    detail.value = d
    const names = d.relationAreaNames ?? []
    entities.value = e.items.filter((x) => x.areas.some((a) => names.includes(a)))
  } else {
    detail.value = null
    areas.value = (await api.processAreas()).items
  }
}, { immediate: true })

const catChips = computed(() => Object.entries(detail.value?.relationCategoryCounts ?? {}))
</script>

<template>
  <!-- 工段列表 -->
  <div v-if="!areaId">
    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold">生产工段</h2>
      <p class="m-0 text-fg-dim max-w-[78ch]">
        工段实例来自 DCS 点表「所属工段」字段，共 {{ areas.length }} 个工段。
        关系列统计的是工业关系 Excel 中经对象映射对齐到该工段的关系数。
      </p>
    </header>
    <section class="panel">
      <div class="overflow-x-auto">
        <table class="tbl">
          <thead>
            <tr>
              <th>工段</th><th>英文名</th><th>控制站</th>
              <th class="text-right">设备</th><th class="text-right">DCS 点</th><th class="text-right">关系</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in areas" :key="a.id" @click="router.push(`/areas/${a.id}`)">
              <td><strong>{{ a.nameZh }}</strong></td>
              <td class="font-mono text-fg-mute">{{ a.nameEn }}</td>
              <td class="font-mono">{{ a.stations.join('、') }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(a.equipmentCount) }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(a.tagCount) }}</td>
              <td class="text-right font-mono tabular-nums">{{ a.relationCount || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>

  <!-- 工段详情 -->
  <div v-else-if="detail">
    <nav class="flex items-center gap-1.5 mb-3.5 text-xs text-fg-mute">
      <RouterLink to="/overview" class="text-fg-dim no-underline hover:text-brand">6-APA 生产线</RouterLink>
      <span class="text-line">/</span>
      <RouterLink to="/areas" class="text-fg-dim no-underline hover:text-brand">工段与设备</RouterLink>
      <span class="text-line">/</span>
      <span class="text-fg">{{ detail.nameZh }}</span>
    </nav>

    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold">{{ detail.nameZh }}</h2>
      <p class="m-0 font-mono text-fg-mute">{{ detail.name }}</p>
    </header>

    <div class="stat-row mb-4">
      <div class="stat"><div class="stat-k">控制站</div><div class="stat-v">{{ detail.stations.join('、') }}</div></div>
      <div class="stat"><div class="stat-k">设备 / 装置</div><div class="stat-v">{{ fmt(detail.equipmentCount) }}</div></div>
      <div class="stat"><div class="stat-k">参数语义</div><div class="stat-v">{{ fmt(detail.parameterCount) }}</div></div>
      <div class="stat"><div class="stat-k">DCS 点位</div><div class="stat-v text-brand">{{ fmt(detail.tagCount) }}</div></div>
      <div class="stat"><div class="stat-k">工业关系</div><div class="stat-v">{{ fmt(detail.relationCount) }}</div></div>
    </div>

    <section class="panel mb-4">
      <div class="panel-head">
        <h3>工艺对象</h3>
        <span class="text-fg-mute text-[11.5px]">
          来自工业关系 Excel<span v-if="detail.relationAreaNames.length"> · {{ detail.relationAreaNames.join('、') }}</span>
        </span>
        <div class="ml-auto flex gap-1.5 flex-wrap">
          <span v-for="[cat, count] in catChips" :key="cat" class="pill pill-plain">
            <i class="w-[7px] h-[7px] rounded-sm" :style="{ background: edgeColor(cat) }"></i>{{ cat }} · {{ count }}
          </span>
        </div>
      </div>
      <div v-if="entities.length" class="overflow-x-auto">
        <table class="tbl">
          <thead>
            <tr><th>对象语义名称</th><th>对象类型</th><th class="text-right">关系数</th><th>匹配状态</th><th class="text-right">测点</th></tr>
          </thead>
          <tbody>
            <tr v-for="e in entities" :key="e.id" @click="select('relationEntity', e.id); router.push(`/graph/${e.id}`)">
              <td><strong>{{ e.name }}</strong></td>
              <td>
                <span class="pill pill-plain">
                  <i class="w-[7px] h-[7px] rounded-sm" :style="{ background: nodeColor(e.type) }"></i>{{ e.type }}
                </span>
              </td>
              <td class="text-right font-mono tabular-nums">{{ fmt(e.relationCount) }}</td>
              <td><span class="pill" :class="e.matchStatus === 'MATCHED' ? 'pill-ok' : 'pill-mute'">{{ e.matchStatusLabel }}</span></td>
              <td class="text-right font-mono tabular-nums">{{ e.tagCount || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="panel-body">
        <div class="empty">
          该工段暂无工业关系数据。当前工业关系 Excel 覆盖水解工段、萃取工段与跨工段协同三个范围。
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h3>设备 / 装置</h3>
        <span class="text-fg-mute text-[11.5px]">来自 DCS 点表 · 按点位数排序</span>
      </div>
      <div class="overflow-x-auto max-h-[460px] overflow-y-auto">
        <table class="tbl">
          <thead>
            <tr>
              <th>设备名称</th><th>OWL Subject</th>
              <th class="text-right">点位</th><th class="text-right">参数</th>
              <th class="text-right">PV</th><th class="text-right">OP</th>
              <th class="text-right">VAL</th><th class="text-right">DI/DO</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in detail.equipment" :key="e.id"
                @click="select('equipment', e.id); router.push(`/equipment/${e.id}`)">
              <td><strong>{{ e.name }}</strong></td>
              <td class="font-mono text-fg-mute text-[11px]">{{ e.owlSubject }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(e.tagCount) }}</td>
              <td class="text-right font-mono tabular-nums">{{ fmt(e.parameterCount) }}</td>
              <td class="text-right font-mono tabular-nums">{{ e.stats.pv }}</td>
              <td class="text-right font-mono tabular-nums">{{ e.stats.op }}</td>
              <td class="text-right font-mono tabular-nums">{{ e.stats.val }}</td>
              <td class="text-right font-mono tabular-nums">{{ e.stats.dido }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>

  <div v-else class="py-16 text-center text-fg-mute">正在加载…</div>
</template>
