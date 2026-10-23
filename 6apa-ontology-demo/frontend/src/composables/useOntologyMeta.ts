/** 本体元数据（12 分类、9 核心内容、节点/边样式）与数据源状态的全局缓存。 */
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import type { CategoriesPayload, DataSourcesPayload, OntologyCategory } from '@/api/types'

const meta = ref<CategoriesPayload | null>(null)
const sources = ref<DataSourcesPayload | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

let inflight: Promise<void> | null = null

async function load(): Promise<void> {
  if (meta.value && sources.value) return
  if (inflight) return inflight
  loading.value = true
  inflight = (async () => {
    try {
      const [c, s] = await Promise.all([api.categories(), api.dataSources()])
      meta.value = c
      sources.value = s
      error.value = null
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
      inflight = null
    }
  })()
  return inflight
}

export function useOntologyMeta() {
  const categories = computed<OntologyCategory[]>(() => meta.value?.categories ?? [])
  const coreContents = computed<OntologyCategory[]>(() => meta.value?.coreContents ?? [])

  const nodeColor = (type: string | null | undefined): string => {
    const hit = meta.value?.nodeStyles.find((s) => s.type === type)
    return hit?.color ?? '#6b7a90'
  }
  const edgeColor = (category: string | null | undefined): string => {
    const hit = meta.value?.edgeStyles.find((s) => s.category === category)
    return hit?.color ?? '#8fa6c4'
  }
  const categoryByKey = (key: string) => categories.value.find((c) => c.key === key) ?? null

  return { meta, sources, loading, error, load, categories, coreContents, nodeColor, edgeColor, categoryByKey }
}

/** 数字千分位 + 空值占位，页面里统一使用。 */
export function fmt(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : v.toLocaleString('zh-CN')
}

export function dash(v: unknown): string {
  return v === null || v === undefined || v === '' ? '—' : String(v)
}
