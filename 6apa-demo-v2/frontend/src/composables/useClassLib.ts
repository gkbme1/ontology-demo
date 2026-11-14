/** 开发态类库的共享状态：当前版本、是否可编辑、枚举；编辑后 reloadLib() 刷新。 */
import { reactive } from 'vue'
import { api } from '@/api/client'
import { staticBackend } from '@/api/static'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
export const lib = reactive({ summary: null as Any, page: 'meta' as string, focusClass: '' as string, error: '' as string, msg: '' as string })

export async function reloadLib(): Promise<void> {
  try { lib.summary = await api.cl() } catch (e) { lib.error = String((e as Error).message) }
}
export const canEdit = (): boolean => !staticBackend && lib.summary?.current?.status === '编辑中'
export function flash(msg: string): void {
  lib.msg = msg
  setTimeout(() => { if (lib.msg === msg) lib.msg = '' }, 4000)
}
/** 执行一次写操作：成功提示 + 刷新版本信息；失败弹出原因。 */
export async function act<T>(fn: () => Promise<T>, okMsg?: string): Promise<T | undefined> {
  try {
    const r = await fn()
    if (okMsg) flash(okMsg)
    reloadLib()
    return r
  } catch (e) {
    alert((e as Error).message)
    return undefined
  }
}
