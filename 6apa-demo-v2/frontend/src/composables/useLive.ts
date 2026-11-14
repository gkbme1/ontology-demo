/**
 * 运行态实时刷新（模拟数据）：每 5 秒 tick 一次，订阅方按 tick 重新取实时值 / 现象状态。
 * 值来自确定性模拟器（完整版后端或单文件版浏览器内实现），不是现场数据。
 */
import { reactive } from 'vue'
import { nav } from './useNav'

export const live = reactive({ tick: 0, paused: false, at: '', intervalSec: 5 })

let timer: number | undefined
export function startLive(): void {
  if (timer) return
  timer = window.setInterval(() => { if (nav.stage === 'run' && !live.paused && !document.hidden) live.tick++ }, live.intervalSec * 1000)
}

const ALARM_CLASS: Record<string, string> = { HH: 'pill-err', LL: 'pill-err', H: 'pill-warn', L: 'pill-warn', 偏离: 'pill-warn' }
export const alarmClass = (a?: string | null): string => (a ? ALARM_CLASS[a] ?? 'pill-warn' : 'pill-ok')
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function fmtLive(x: any): string {
  if (!x || x.v === null || x.v === undefined) return x?.quality ?? '—'
  if (x.digital) return x.v >= 0.5 ? '1' : '0'
  const v = Number(x.v)
  return Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(2)
}
