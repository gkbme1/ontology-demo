<script setup lang="ts">
/** 其他分类（工业资产 / 工艺参数 / 物料与产品 / 质量 / 经营）里选中对象的档案：属性 + 关系。 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import { enterSegment, openObject } from '@/composables/useNav'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ objectId: string }>()
const prof = ref<Any>(null)
const head = ref<Any>(null)
const error = ref('')

watch(() => props.objectId, async (id) => {
  error.value = ''
  prof.value = null
  head.value = null
  try {
    prof.value = await api.objectProfile(id)
    if (/^(equip-|egrp-)/.test(id)) head.value = await api.object(id)
  } catch (e) {
    error.value = String((e as Error).message)
  }
}, { immediate: true })

const rels = computed(() => {
  const r = prof.value?.relations ?? {}
  return [...(r.classRelations ?? []), ...(r.attributeRelations ?? []), ...(r.groupRelations ?? [])]
})
function gotoSpace(): void {
  const h = head.value
  if (!h?.opId) return
  enterSegment(h.path[1].id, { type: 'object', id: props.objectId, opId: h.opId })
  openObject(props.objectId, h.opId)
}
</script>

<template>
  <div class="h-full overflow-auto p-5 space-y-4">
    <div v-if="error" class="empty">{{ error }}</div>
    <template v-if="prof">
      <div class="flex items-center gap-3">
        <h2 class="text-[18px] font-semibold">{{ prof.name }}</h2>
        <span class="pill pill-plain">{{ prof.header?.className ?? prof.kind }}</span>
        <span class="flex-1" />
        <button v-if="head?.opId" class="btn btn-primary" @click="gotoSpace">在空间层级中打开（10 个页签）</button>
      </div>
      <div v-if="prof.header?.classPath" class="text-xs text-fg-mute">{{ prof.header.classPath.join(' › ') }}</div>
      <div class="card">
        <div class="sec-title">属性</div>
        <table class="tbl"><tbody>
          <tr v-for="a in prof.attributes" :key="a.name" class="!cursor-default">
            <td class="text-fg-mute whitespace-nowrap">{{ a.kind }}</td><td class="font-medium">{{ a.name }}</td>
            <td class="text-fg-dim">{{ a.value ?? a.valueType }}</td>
            <td class="text-fg-mute text-xs">{{ a.description ?? a.note ?? '' }}</td>
          </tr>
        </tbody></table>
      </div>
      <div class="card">
        <div class="sec-title">关系（{{ rels.length }}）</div>
        <table class="tbl"><tbody>
          <tr v-for="(r, i) in rels" :key="i" class="!cursor-default">
            <td class="text-fg-mute whitespace-nowrap">{{ r.category }}</td>
            <td>{{ r.from ?? (r.direction === 'in' ? r.target : prof.name) }}</td>
            <td class="text-brand whitespace-nowrap">{{ r.predicate }}</td>
            <td>{{ r.to ?? (r.direction === 'in' ? prof.name : r.target) }}</td>
            <td class="text-fg-dim text-xs">{{ r.mechanism }}</td>
          </tr>
        </tbody></table>
      </div>
    </template>
  </div>
</template>
