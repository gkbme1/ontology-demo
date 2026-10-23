<script setup lang="ts">
/** 关系详情面板（需求文档第十八章）：三元组 + 关系元数据 + 工艺机理说明 + 来源追溯。 */
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useOntologyMeta } from '@/composables/useOntologyMeta'
import { useSelection } from '@/composables/useSelection'
import type { RelationDetail } from '@/api/types'
import SourceTrace from './SourceTrace.vue'

const props = defineProps<{ relationId: string }>()
const router = useRouter()
const { nodeColor, edgeColor } = useOntologyMeta()
const { select } = useSelection()

const rel = ref<RelationDetail | null>(null)

watch(() => props.relationId, async (id) => {
  rel.value = id ? await api.relationDetail(id) : null
}, { immediate: true })

const openEntity = (id: string | null) => {
  if (!id) return
  select('relationEntity', id)
  router.push(`/graph/${id}`)
}
</script>

<template>
  <div v-if="rel">
    <div class="text-fg-mute text-[10.5px] tracking-widest uppercase">关系详情</div>
    <h2 class="mt-1 mb-2.5 text-base font-semibold text-balance">
      {{ rel.subjectEntity }} → {{ rel.objectEntity }}
    </h2>
    <div class="mb-3 flex gap-1.5 flex-wrap">
      <span class="pill pill-plain">
        <i class="w-[7px] h-[7px] rounded-sm" :style="{ background: edgeColor(rel.category) }"></i>{{ rel.category }}
      </span>
      <span class="pill pill-info">{{ rel.predicate }}</span>
    </div>

    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">关系三元组</h4>
      <div class="flex flex-col">
        <div class="flex items-center gap-2.5 px-3 py-2 border border-line rounded-md bg-ink-panel2">
          <span class="text-fg-mute text-[10.5px] tracking-wide uppercase min-w-[74px]">起始对象</span>
          <span class="font-medium">{{ rel.subjectEntity }}</span>
          <span class="ml-auto pill pill-plain">
            <i class="w-[7px] h-[7px] rounded-sm" :style="{ background: nodeColor(rel.subjectType) }"></i>{{ rel.subjectType }}
          </span>
        </div>
        <div class="h-4 ml-[30px] border-l border-dashed border-line"></div>
        <div class="flex items-center gap-2.5 px-3 py-2 border border-line rounded-md bg-ink-panel2">
          <span class="text-fg-mute text-[10.5px] tracking-wide uppercase min-w-[74px]">关系谓词</span>
          <span class="font-medium">{{ rel.predicate }}</span>
        </div>
        <div class="h-4 ml-[30px] border-l border-dashed border-line"></div>
        <div class="flex items-center gap-2.5 px-3 py-2 border border-line rounded-md bg-ink-panel2">
          <span class="text-fg-mute text-[10.5px] tracking-wide uppercase min-w-[74px]">目标对象</span>
          <span class="font-medium">{{ rel.objectEntity }}</span>
          <span class="ml-auto pill pill-plain">
            <i class="w-[7px] h-[7px] rounded-sm" :style="{ background: nodeColor(rel.objectType) }"></i>{{ rel.objectType }}
          </span>
        </div>
      </div>
    </section>

    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">关系元数据</h4>
      <dl class="kv">
        <dt>工段</dt><dd>{{ rel.area }}</dd>
        <dt>子场景</dt><dd>{{ rel.scenario }}</dd>
        <dt>权重</dt><dd class="font-mono">{{ rel.weight }}</dd>
        <dt>关系标识</dt><dd class="font-mono text-[11px]">{{ rel.id }}</dd>
        <dt>稳定键</dt><dd class="font-mono text-[10.5px] break-all">{{ rel.stableKey }}</dd>
        <dt>对象匹配</dt>
        <dd>{{ rel.matchStatus === 'MATCHED' ? '双端已匹配' : rel.matchStatus === 'PARTIAL' ? '单端已匹配' : '双端未匹配 DCS 实例' }}</dd>
      </dl>
    </section>

    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">
        工艺机理与业务因果说明
      </h4>
      <p class="m-0 text-fg-dim">{{ rel.domainDescription }}</p>
    </section>

    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">数据来源</h4>
      <SourceTrace :source="rel.source" :source-type="rel.sourceType" />
    </section>

    <section class="mt-4">
      <h4 class="m-0 mb-2 text-[10.5px] tracking-widest uppercase text-fg-mute pb-1.5 border-b border-line-soft">操作</h4>
      <div class="flex flex-wrap gap-1.5">
        <button class="ctl" @click="openEntity(rel.subject.id)">查看起始对象</button>
        <button class="ctl" @click="openEntity(rel.object.id)">查看目标对象</button>
        <RouterLink class="ctl no-underline" :to="{ path: '/relations', query: { category: rel.category ?? '' } }">
          同类关系 {{ rel.sameCategoryRelationIds.length }} 条
        </RouterLink>
        <RouterLink class="ctl no-underline" :to="{ path: '/relations', query: { area: rel.area ?? '' } }">
          同工段关系 {{ rel.sameAreaRelationIds.length }} 条
        </RouterLink>
      </div>
    </section>
  </div>
</template>
