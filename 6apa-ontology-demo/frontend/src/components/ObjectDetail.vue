<script setup lang="ts">
/** 右栏对象详情：按当前选中对象的类型分派到不同的展示形态。 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useSelection } from '@/composables/useSelection'
import { useOntologyMeta, fmt, dash } from '@/composables/useOntologyMeta'
import type { DcsTag, Equipment, Parameter, RelationEntityDetail } from '@/api/types'
import RelationDetail from './RelationDetail.vue'
import SourceTrace from './SourceTrace.vue'

const router = useRouter()
const { selection } = useSelection()
const { nodeColor } = useOntologyMeta()

const entity = ref<RelationEntityDetail | null>(null)
const equipment = ref<(Equipment & { area: unknown; relationEntities: { id: string; name: string }[] }) | null>(null)
const parameter = ref<(Parameter & { measurementAnchors: { tagName: string; blockType: string | null; unit: string | null; rawDescription: string | null }[] }) | null>(null)
const tag = ref<DcsTag | null>(null)

watch(selection, async (sel) => {
  entity.value = null; equipment.value = null; parameter.value = null; tag.value = null
  if (!sel.id) return
  try {
    if (sel.kind === 'relationEntity') entity.value = await api.relationEntityDetail(sel.id)
    else if (sel.kind === 'equipment') equipment.value = await api.equipmentDetail(sel.id) as never
    else if (sel.kind === 'parameter') parameter.value = await api.parameterDetail(sel.id) as never
    else if (sel.kind === 'tag') tag.value = (sel.payload as DcsTag) ?? null
  } catch {
    /* 详情加载失败时保持空态，不阻塞主视图 */
  }
}, { deep: true })

const structuralHelp: Record<string, [string, string]> = {
  mapping: ['对象映射边', '关系对象 → DCS 本体实例，来自人工对象映射表，状态为“待现场确认”。'],
  anchor: ['测量锚点边', '工业语义 → DCS 参数语义，据此绑定到现场测点。'],
  tag: ['boundToTag', '参数语义 → DCS Tag，来自 DCS 点表。'],
  structure: ['本体结构边', '工段 hasEquipment 设备、设备 hasParameter 参数，来自 DCS 点表层级。']
}
const edgePayload = computed(() => (selection.value.payload ?? {}) as { edgeKind?: string; label?: string })
const edgeHelp = computed(() => structuralHelp[edgePayload.value.edgeKind ?? ''])
</script>

<template>
  <!-- 关系边 -->
  <RelationDetail v-if="selection.kind === 'relation' && selection.id" :relation-id="selection.id" />

  <!-- 结构边 -->
  <div v-else-if="selection.kind === 'structuralEdge'">
    <div class="text-fg-mute text-[10.5px] tracking-widest uppercase">
      {{ edgeHelp?.[0] ?? '结构边' }}
    </div>
    <h2 class="mt-1 mb-2.5 text-base font-semibold">{{ edgePayload.label }}</h2>
    <p class="text-fg-dim m-0">
      {{ edgeHelp?.[1] }}
      本边不是工业关系 Excel 中的关系记录，而是本体内部的结构连接。
    </p>
  </div>

  <!-- 关系对象 -->
  <div v-else-if="entity">
    <div class="text-fg-mute text-[10.5px] tracking-widest uppercase">关系对象</div>
    <h2 class="mt-1 mb-2.5 text-base font-semibold text-balance">{{ entity.name }}</h2>
    <div class="mb-3 flex gap-1.5 flex-wrap">
      <span class="pill pill-plain">
        <i class="w-[7px] h-[7px] rounded-sm" :style="{ background: nodeColor(entity.type) }"></i>{{ entity.type }}
      </span>
      <span class="pill" :class="entity.matchStatus === 'MATCHED' ? 'pill-ok' : 'pill-mute'">{{ entity.matchStatusLabel }}</span>
      <span v-if="entity.pendingConfirmation" class="pill pill-warn">映射待现场确认</span>
    </div>

    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">基本信息</h4>
      <dl class="kv">
        <dt>对象类型</dt><dd>{{ dash(entity.type) }}</dd>
        <dt>适用工段</dt><dd>{{ entity.areas.join('、') }}</dd>
        <dt>关系数</dt><dd class="font-mono">{{ entity.relationCount }}（出 {{ entity.outgoingCount }} / 入 {{ entity.incomingCount }}）</dd>
        <dt>匹配方式</dt><dd>{{ entity.matchStrategyLabel }}</dd>
        <dt>本体实例</dt><dd class="font-mono">{{ entity.matchCount }}</dd>
        <dt>测量锚点</dt><dd class="font-mono">{{ entity.tagCount }}</dd>
      </dl>
    </section>

    <section v-if="entity.matches.length" class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">匹配的本体实例</h4>
      <ul class="list-none m-0 p-0">
        <li v-for="m in entity.matches.slice(0, 6)" :key="m.id" class="py-1.5 border-b border-line-soft last:border-0">
          <strong>{{ m.name }}</strong>
          <span class="text-fg-mute"> {{ m.strategyLabel }}</span>
          <span v-if="m.confidence" class="pill ml-1"
                :class="m.confidence === '高' ? 'pill-ok' : m.confidence === '中' ? 'pill-warn' : 'pill-err'">
            置信度 {{ m.confidence }}
          </span>
          <div v-if="m.note" class="text-fg-dim text-[11.5px]">{{ m.note }}</div>
        </li>
      </ul>
    </section>

    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">测量锚点</h4>
      <ul v-if="entity.measurementAnchors.length" class="list-none m-0 p-0">
        <li v-for="a in entity.measurementAnchors.slice(0, 6)" :key="a.tagId" class="py-1.5 border-b border-line-soft last:border-0">
          <span class="font-mono">{{ a.tagName }}</span> · {{ a.blockType }} · {{ dash(a.unit) }}
          <div class="text-fg-mute text-[11.5px]">{{ a.rawDescription }}</div>
        </li>
      </ul>
      <div v-else class="empty">关系对象已加载，当前暂无对应 DCS 测点</div>
    </section>

    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">操作</h4>
      <div class="flex gap-1.5 flex-wrap">
        <button class="ctl" @click="router.push(`/graph/${entity.id}`)">以此为中心绘图</button>
      </div>
    </section>
  </div>

  <!-- 设备 -->
  <div v-else-if="equipment">
    <div class="text-fg-mute text-[10.5px] tracking-widest uppercase">设备实例 · DCS_EXCEL</div>
    <h2 class="mt-1 mb-2.5 text-base font-semibold text-balance">{{ equipment.name }}</h2>
    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">属性</h4>
      <dl class="kv">
        <dt>OWL Subject</dt><dd class="font-mono text-[11px]">{{ equipment.owlSubject }}</dd>
        <dt>所属工段</dt><dd>{{ dash(equipment.areaName) }}</dd>
        <dt>控制站</dt><dd class="font-mono">{{ dash(equipment.station) }}</dd>
        <dt>总点位</dt><dd class="font-mono">{{ fmt(equipment.stats.total) }}</dd>
        <dt>参数语义</dt><dd class="font-mono">{{ fmt(equipment.parameterCount) }}</dd>
        <dt>PV / OP</dt><dd class="font-mono">{{ equipment.stats.pv }} / {{ equipment.stats.op }}</dd>
        <dt>VAL / DI·DO</dt><dd class="font-mono">{{ equipment.stats.val }} / {{ equipment.stats.dido }}</dd>
      </dl>
    </section>
    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">数据来源</h4>
      <SourceTrace :source="equipment.source" :source-type="equipment.sourceType" />
    </section>
    <section class="mt-4">
      <div class="flex gap-1.5 flex-wrap">
        <button class="ctl" @click="router.push(`/equipment/${equipment.id}`)">打开设备详情页</button>
      </div>
    </section>
  </div>

  <!-- 参数 -->
  <div v-else-if="parameter">
    <div class="text-fg-mute text-[10.5px] tracking-widest uppercase">参数语义 · DCS_EXCEL</div>
    <h2 class="mt-1 mb-2.5 text-base font-semibold text-balance">{{ parameter.name }}</h2>
    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">属性</h4>
      <dl class="kv">
        <dt>参数分类</dt><dd>{{ parameter.categories.join('、') }}</dd>
        <dt>工程单位</dt><dd class="font-mono">{{ dash(parameter.units.join('、')) }}</dd>
        <dt>DCS 块类型</dt><dd class="font-mono">{{ dash(parameter.blockTypes.join('、')) }}</dd>
        <dt>所属设备</dt><dd>{{ dash(parameter.equipmentName) }}</dd>
        <dt>OWL Subject</dt><dd class="font-mono text-[11px]">{{ dash(parameter.owlSubject) }}</dd>
      </dl>
    </section>
    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">测量锚点</h4>
      <ul class="list-none m-0 p-0">
        <li v-for="a in parameter.measurementAnchors" :key="a.tagName" class="py-1.5 border-b border-line-soft last:border-0">
          <span class="font-mono">{{ a.tagName }}</span> · {{ a.blockType }} · {{ dash(a.unit) }}
          <div class="text-fg-mute text-[11.5px]">{{ a.rawDescription }}</div>
        </li>
      </ul>
    </section>
    <section class="mt-4">
      <div class="flex gap-1.5 flex-wrap">
        <button class="ctl" @click="router.push(`/parameters/${parameter.id}`)">打开参数详情页</button>
      </div>
    </section>
  </div>

  <!-- DCS 点 -->
  <div v-else-if="tag">
    <div class="text-fg-mute text-[10.5px] tracking-widest uppercase">DCS 点 · DCS_EXCEL</div>
    <h2 class="mt-1 mb-2.5 text-base font-semibold font-mono">{{ tag.name }}</h2>
    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">属性</h4>
      <dl class="kv">
        <dt>原点描述</dt><dd>{{ dash(tag.rawDescription) }}</dd>
        <dt>参数语义</dt><dd>{{ dash(tag.parameterName) }}</dd>
        <dt>参数分类</dt><dd>{{ dash(tag.parameterType) }}</dd>
        <dt>DCS 块类型</dt><dd class="font-mono">{{ dash(tag.blockType) }}</dd>
        <dt>工程单位</dt><dd class="font-mono">{{ dash(tag.unit) }}</dd>
        <dt>控制站</dt><dd class="font-mono">{{ dash(tag.station) }}</dd>
        <dt>所属设备</dt><dd>{{ dash(tag.equipmentName) }}</dd>
        <dt>OWL Subject</dt><dd class="font-mono text-[11px]">{{ dash(tag.owlSubject) }}</dd>
      </dl>
    </section>
    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">数据来源</h4>
      <SourceTrace :source="tag.source" :source-type="tag.sourceType" />
    </section>
  </div>

  <!-- 空态 -->
  <div v-else>
    <div class="text-fg-mute text-[10.5px] tracking-widest uppercase">对象详情</div>
    <h2 class="mt-1 mb-2.5 text-base font-semibold">未选择对象</h2>
    <p class="text-fg-dim m-0">
      在左侧列表、表格行或关系图中点击任意对象或关系边，此处显示其属性、关系、测量锚点与数据来源。
    </p>
    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">数据边界</h4>
      <dl class="kv">
        <dt>DCS_EXCEL</dt><dd>工段 / 设备 / 参数 / DCS 点</dd>
        <dt>RELATION_EXCEL</dt><dd>关系 / 部件 / 属性 / 因果</dd>
        <dt>MAPPING_FILE</dt><dd>抽象对象与现场位号对齐</dd>
        <dt>RULE_FILE</dt><dd>条件 → 推理结论</dd>
      </dl>
    </section>
  </div>
</template>
