/** 右侧“对象详情”面板的选中状态。任意视图都可以通过它推送当前对象。 */
import { ref } from 'vue'

export type SelectionKind = 'relation' | 'relationEntity' | 'equipment' | 'parameter' | 'tag' | 'structuralEdge' | null

export interface Selection {
  kind: SelectionKind
  id: string | null
  payload?: unknown
}

const selection = ref<Selection>({ kind: null, id: null })

export function useSelection() {
  const select = (kind: SelectionKind, id: string | null, payload?: unknown) => {
    selection.value = { kind, id, payload }
  }
  const clear = () => { selection.value = { kind: null, id: null } }
  return { selection, select, clear }
}
