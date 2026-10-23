<script setup lang="ts">
/** 设备详情（需求文档第十六章）：点位统计 + 设备→参数→DCS点三层 + 设备关系。 */
import { ref, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { fmt, dash } from '@/composables/useOntologyMeta'
import { useSelection } from '@/composables/useSelection'
import type { DcsTag, Equipment, Parameter, ProcessArea, Relation, RelationEntity, Rule } from '@/api/types'

const props = defineProps<{ equipmentId: string }>()
const router = useRouter()
const { select } = useSelection()

type Detail = Equipment & {
  area: ProcessArea | null
  parameters: Parameter[]
  tags: DcsTag[]
  relations: Relation[]
  relationEntities: RelationEntity[]
  rules: Rule[]
}

const d = ref<Detail | null>(null)

watch(() => props.equipmentId, async (id) => { d.value = id ? await api.equipmentDetail(id) : null }, { immediate: true })

const tagsOf = (parameterId: string) => (d.value?.tags ?? []).filter((t) => t.parameterId === parameterId)

const mismatch = computed(() => {
  const s1 = d.value?.statsFromSheet1
  const total = d.value?.stats.total
  return s1?.totalPoints != null && total != null && s1.totalPoints !== total ? { declared: s1.totalPoints, actual: total } : null
})
</script>

<template>
  <div v-if="d">
    <nav class="flex items-center gap-1.5 mb-3.5 text-xs text-fg-mute">
      <RouterLink to="/" class="text-fg-dim no-underline hover:text-brand">6-APA 生产线</RouterLink>
      <span class="text-line">/</span>
      <RouterLink :to="`/areas/${d.areaId}`" class="text-fg-dim no-underline hover:text-brand">{{ d.area?.nameZh }}</RouterLink>
      <span class="text-line">/</span><span class="text-fg">{{ d.name }}</span>
    </nav>

    <header class="mb-4">
      <h2 class="m-0 mb-1 text-[19px] font-semibold">{{ d.name }}</h2>
      <p class="m-0 text-fg-dim">
        所属工段 {{ d.area?.nameZh }} · 控制站 {{ d.station }} ·
        <span class="font-mono">{{ d.owlSubject }}</span>
      </p>
    </header>

    <div v-if="mismatch" class="flex gap-2 px-3 py-2.5 mb-3 border-l-2 border-warn bg-warn/[0.07] text-fg-dim rounded-r">
      <span>⚠</span>
      <div>
        Sheet1「设备统计」声明 <b>{{ fmt(mismatch.declared) }}</b> 点，
        Sheet2「DCS点位明细」实际 <b>{{ fmt(mismatch.actual) }}</b> 点，已记入数据质量报告，未做任何修正。
      </div>
    </div>

    <div class="stat-row mb-4">
      <div class="stat"><div class="stat-k">总点位</div><div class="stat-v text-brand">{{ fmt(d.stats.total) }}</div></div>
      <div class="stat"><div class="stat-k">过程测量 PV</div><div class="stat-v">{{ fmt(d.stats.pv) }}</div></div>
      <div class="stat"><div class="stat-k">控制输出 OP</div><div class="stat-v">{{ fmt(d.stats.op) }}</div></div>
      <div class="stat"><div class="stat-k">电机控制 MOT</div><div class="stat-v">{{ fmt(d.stats.mot) }}</div></div>
      <div class="stat"><div class="stat-k">阀门控制 VAL</div><div class="stat-v">{{ fmt(d.stats.val) }}</div></div>
      <div class="stat"><div class="stat-k">开关反馈 DI/DO</div><div class="stat-v">{{ fmt(d.stats.dido) }}</div></div>
      <div class="stat"><div class="stat-k">参数语义</div><div class="stat-v">{{ fmt(d.parameterCount) }}</div></div>
    </div>

    <p v-if="d.overview" class="text-fg-dim mb-3">
      <b class="text-fg-dim">核心参数/测点概览：</b>{{ d.overview }}
    </p>

    <section class="panel mb-4">
      <div class="panel-head">
        <h3>设备参数 → DCS 点</h3>
        <span class="text-fg-mute text-[11.5px]">设备 / 参数语义 / DCS 点三层语义模型</span>
      </div>
      <div class="overflow-x-auto max-h-[460px] overflow-y-auto">
        <table class="tbl">
          <thead>
            <tr><th>参数语义名称</th><th>参数分类</th><th>工程单位</th><th>DCS 块</th><th>DCS 点名</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in d.parameters" :key="p.id"
                @click="select('parameter', p.id); router.push(`/parameters/${p.id}`)">
              <td><strong>{{ p.name }}</strong></td>
              <td><span v-for="c in p.categories" :key="c" class="pill pill-plain mr-1">{{ c }}</span></td>
              <td class="font-mono">{{ dash(p.units.join('、')) }}</td>
              <td class="font-mono">{{ dash(p.blockTypes.join('、')) }}</td>
              <td class="font-mono">{{ tagsOf(p.id).map((t) => t.name).join('、') }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel mb-4">
      <div class="panel-head">
        <h3>设备关系</h3>
        <span class="text-fg-mute text-[11.5px]">经对象映射对齐到本设备的工业关系</span>
      </div>
      <div v-if="d.relations.length" class="overflow-x-auto">
        <table class="tbl">
          <thead>
            <tr><th>起始对象</th><th>关系谓词</th><th>目标对象</th><th>关系大类</th><th>工艺机理与业务因果说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in d.relations" :key="r.id" @click="select('relation', r.id)">
              <td>{{ r.subjectEntity }}</td>
              <td><span class="pill pill-info">{{ r.predicate }}</span></td>
              <td>{{ r.objectEntity }}</td>
              <td>{{ r.category }}</td>
              <td class="text-fg-dim">{{ r.domainDescription }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="panel-body">
        <div class="empty">
          该设备当前无关联工业关系。工业关系 Excel 覆盖水解工段与萃取工段的核心工艺对象；关系不会根据设备名称自动推断。
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><h3>关联规则</h3></div>
      <div class="panel-body">
        <div v-if="!d.rules.length" class="empty">
          当前暂无规则数据源。规则必须来自独立规则 Excel / 规则文件，系统不会根据参数名称自动生成生产判断规则。
        </div>
        <ul v-else class="list-none m-0 p-0">
          <li v-for="r in d.rules" :key="r.id" class="py-1.5 border-b border-line-soft last:border-0">
            <span class="font-mono">{{ r.ruleId }}</span> {{ r.name }} — {{ r.conclusion }}
          </li>
        </ul>
      </div>
    </section>
  </div>
  <div v-else class="py-16 text-center text-fg-mute">正在加载…</div>
</template>
