/** 工程态使用的类库版本（顶栏标签、基础信息、「发布与导出 · 类库版本」共用）。 */
import { reactive } from 'vue'
import { api } from '@/api/client'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
export const classlibState = reactive({ binding: null as Any, openTab: '' as string })

export async function loadBinding(): Promise<void> {
  try { classlibState.binding = await api.clBinding() } catch { classlibState.binding = null }
}
