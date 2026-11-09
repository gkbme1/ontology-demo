/**
 * 全局导航状态：当前分类、空间层级的模式（装置导航 / 单元内）、当前选中对象。
 * 右侧显示区按 selection.type 切换视图。
 */
import { reactive } from 'vue'
import { api } from '@/api/client'

export type SelType =
  | 'none' | 'workshop' | 'segment' | 'op' | 'drawing' | 'section:devices' | 'section:calc'
  | 'section:cond' | 'section:docs' | 'calc' | 'object' | 'domain-object' | 'domain-pending'
  | 'global:calc' | 'global:algo' | 'global:cond' | 'global:docs'

export interface Selection {
  type: SelType
  id?: string // 对象 id / 单元 id / 画面 id / 计算组态 id
  opId?: string
  label?: string
  tab?: string
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

export const nav = reactive({
  category: 'space',
  mode: 'root' as 'root' | 'segment',
  segmentId: '' as string,
  selection: { type: 'none' } as Selection,
  meta: null as Any,
  // 树节点被选中的 key（用于高亮）
  activeKey: '' as string,
  // 编辑后递增，触发各视图刷新
  version: 0,
  // 顶层页面：本体浏览 / 全局图谱
  page: 'browse' as 'browse' | 'graph',
  // 从设备 / 画面跳到全局图谱时的定位
  graphFocus: null as { id: string; hops?: number } | null
})

export async function loadMeta(): Promise<void> {
  if (!nav.meta) nav.meta = await api.meta()
}

export function select(sel: Selection, key?: string): void {
  nav.selection = { ...sel }
  if (key !== undefined) nav.activeKey = key
}

export function enterSegment(segmentId: string, then?: Selection): void {
  nav.category = 'space'
  nav.mode = 'segment'
  nav.segmentId = segmentId
  select(then ?? { type: 'segment', id: segmentId }, then ? undefined : `seg:${segmentId}`)
}

export function backToWorkshop(): void {
  nav.mode = 'root'
  const seg = nav.segmentId
  nav.segmentId = ''
  select({ type: 'segment', id: seg }, `seg:${seg}`)
}

export function openDrawing(opId: string, segmentId?: string): void {
  if (segmentId && (nav.mode !== 'segment' || nav.segmentId !== segmentId)) {
    nav.mode = 'segment'
    nav.segmentId = segmentId
  }
  select({ type: 'drawing', id: opId, opId }, opId)
}

export function openObject(objectId: string, opId?: string, tab?: string): void {
  select({ type: 'object', id: objectId, opId, tab }, opId ? `${opId}|${objectId}` : objectId)
}

export function openGlobalGraph(focusId?: string, hops = 2): void {
  nav.graphFocus = focusId ? { id: focusId, hops } : null
  nav.page = 'graph'
}

export function bump(): void {
  nav.version++
}
