/**
 * 单文件版的实时值模拟器：backend/v2/simulator.py 的浏览器版（同一套公式与随机数，值与完整版一致）。
 * **全部是模拟数据**，不是现场数据。随机数 = blake2b(8 字节摘要) 按大端读成 [0, 1) 的小数，与 Python 的 _u() 相同。
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any

// ------------------------------------------------------------------ blake2b（RFC 7693，BigInt 实现，输入很短，够用）
const MASK = (1n << 64n) - 1n
const IV = [0x6a09e667f3bcc908n, 0xbb67ae8584caa73bn, 0x3c6ef372fe94f82bn, 0xa54ff53a5f1d36f1n,
  0x510e527fade682d1n, 0x9b05688c2b3e6c1fn, 0x1f83d9abfb41bd6bn, 0x5be0cd19137e2179n]
const SIGMA = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
  [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4], [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
  [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13], [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
  [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11], [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
  [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5], [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0]]
const rotr = (x: bigint, n: bigint): bigint => ((x >> n) | (x << (64n - n))) & MASK

function compress(h: bigint[], block: Uint8Array, t: bigint, last: boolean): void {
  const m: bigint[] = []
  for (let i = 0; i < 16; i++) {
    let w = 0n
    for (let b = 7; b >= 0; b--) w = (w << 8n) | BigInt(block[i * 8 + b])
    m.push(w)
  }
  const v = [...h, ...IV]
  v[12] ^= t & MASK
  v[13] ^= t >> 64n
  if (last) v[14] ^= MASK
  const G = (a: number, b: number, c: number, d: number, x: bigint, y: bigint): void => {
    v[a] = (v[a] + v[b] + x) & MASK; v[d] = rotr(v[d] ^ v[a], 32n)
    v[c] = (v[c] + v[d]) & MASK; v[b] = rotr(v[b] ^ v[c], 24n)
    v[a] = (v[a] + v[b] + y) & MASK; v[d] = rotr(v[d] ^ v[a], 16n)
    v[c] = (v[c] + v[d]) & MASK; v[b] = rotr(v[b] ^ v[c], 63n)
  }
  for (let r = 0; r < 12; r++) {
    const s = SIGMA[r % 10]
    G(0, 4, 8, 12, m[s[0]], m[s[1]]); G(1, 5, 9, 13, m[s[2]], m[s[3]])
    G(2, 6, 10, 14, m[s[4]], m[s[5]]); G(3, 7, 11, 15, m[s[6]], m[s[7]])
    G(0, 5, 10, 15, m[s[8]], m[s[9]]); G(1, 6, 11, 12, m[s[10]], m[s[11]])
    G(2, 7, 8, 13, m[s[12]], m[s[13]]); G(3, 4, 9, 14, m[s[14]], m[s[15]])
  }
  for (let i = 0; i < 8; i++) h[i] ^= v[i] ^ v[i + 8]
}

/** blake2b，摘要 8 字节，返回第一个 64 位字（小端）。 */
function blake2b8(data: Uint8Array): bigint {
  const h = [...IV]
  h[0] ^= 0x01010000n ^ 8n
  let off = 0
  while (data.length - off > 128) {
    compress(h, data.subarray(off, off + 128), BigInt(off + 128), false)
    off += 128
  }
  const last = new Uint8Array(128)
  last.set(data.subarray(off))
  compress(h, last, BigInt(data.length), true)
  return h[0]
}

const enc = new TextEncoder()
const cache = new Map<string, number>()
/** 与 simulator._u 相同：blake2b("|".join(parts)) 的 8 字节按大端读成 [0, 1)。 */
export function u(...parts: (string | number)[]): number {
  const key = parts.join('|')
  const hit = cache.get(key)
  if (hit !== undefined) return hit
  const w = blake2b8(enc.encode(key))
  let be = 0n
  for (let i = 0; i < 8; i++) be = (be << 8n) | ((w >> BigInt(8 * i)) & 0xffn)  // 小端字节按大端重组
  const x = Number(be) / 2 ** 64
  if (cache.size > 20000) cache.clear()
  cache.set(key, x)
  return x
}

// ------------------------------------------------------------------ 模拟器（单点）
const SEED = '6apa-demo-v2'
const SLOT_MIN = 180
const DEV_SLOT_MIN = 120
const DIGITAL_SUFFIX = /_(RUN|DO|FL|RM|VAL2|VAL|FT|MOT2|DI|ZT|ZS)$/i
const DIGITAL_TYPES = ['DI', 'DO', 'DOV', 'MOT2', 'VAL2', 'VAL', 'DIV']
const UNIT_RANGES: Record<string, [number, number]> = {
  ph: [6.5, 7.5], '℃': [20, 30], '°c': [20, 30], m3: [8, 20], l: [200, 800], mpa: [0.45, 0.6], kpa: [40, 60], 'l/h': [800, 1200],
  'm3/h': [5, 10], '%': [40, 60], a: [20, 40], hz: [30, 45], rpm: [800, 1200]
}
const clip = (x: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, x))
const pyMod = (a: number, b: number): number => ((a % b) + b) % b

export interface SimTag { name: string; blockType: string; parameterType: string; parameterName: string; unit: string; standardUnit: string }

export function isDigital(t: SimTag): boolean {
  return DIGITAL_TYPES.includes(String(t.blockType || '').toUpperCase()) || t.parameterType.includes('开关') ||
    t.parameterType.includes('状态') || DIGITAL_SUFFIX.test(t.name)
}
function band(t: SimTag, limit: Any): [number, number] {
  if (limit) {
    let lo = limit.normalLow
    let hi = limit.normalHigh
    if ((lo === null || lo === undefined) && hi !== null && hi !== undefined) lo = hi > 0 ? hi * 0.85 : hi - 1
    if ((hi === null || hi === undefined) && lo !== null && lo !== undefined) hi = lo > 0 ? lo * 1.15 : lo + 1
    if (lo !== null && lo !== undefined && hi !== null && hi !== undefined && hi > lo) return [Number(lo), Number(hi)]
  }
  return UNIT_RANGES[String(t.unit || t.standardUnit || '').trim().toLowerCase()] ?? [40, 60]
}
function analog(t: SimTag, limit: Any, sec: number): number {
  const name = t.name
  const [lo, hi] = band(t, limit)
  const mid = (lo + hi) / 2
  const half = (hi - lo) / 2
  const curve = name.replace(/^(AT_\d+[A-Z])[12]$/, '$1')
  const minutes = sec / 60
  const p1 = 60 + 300 * u(SEED, curve, 'p1')
  const p2 = 8 + 30 * u(SEED, curve, 'p2')
  const ph1 = 6.283 * u(SEED, curve, 'f1')
  const ph2 = 6.283 * u(SEED, curve, 'f2')
  let v = mid + 0.45 * half * Math.sin(6.283 * minutes / p1 + ph1) + 0.15 * half * Math.sin(6.283 * minutes / p2 + ph2)
  v += 0.08 * half * (u(SEED, name, 'n', Math.trunc(minutes)) - 0.5)
  const slot = Math.floor(minutes / SLOT_MIN)
  const pos = pyMod(minutes, SLOT_MIN)
  const start = 20 + 60 * u(SEED, curve, 'exs', slot)
  const length = 15 + 70 * u(SEED, curve, 'exl', slot)
  const sign = u(SEED, curve, 'exd', slot) < 0.5 ? 1 : -1
  if (u(SEED, curve, 'exc', slot) < 0.22 && pos >= start && pos < start + length) {
    v += sign * 1.7 * half * clip(Math.min(pos - start, start + length - pos) / 8, 0, 1)
  }
  if (/^AT_\d+[A-Z]2$/.test(name) && u(SEED, name, 'drift', slot) < 0.18) v += 0.35 * clip(pos / 40, 0, 1)
  return v
}
function level(t: SimTag, sec: number): number {
  const name = t.name
  const unit = String(t.unit || '').toLowerCase()
  const [lo, hi] = unit === 'l' ? [100, 900] : [3, 28]
  const minutes = sec / 60
  const slot = Math.floor(minutes / SLOT_MIN)
  const pos = pyMod(minutes, SLOT_MIN)
  if (name === 'LT_1303') {
    const base = 12 + 2 * Math.sin(6.283 * minutes / 97)
    return base + (u(SEED, name, 'rise', slot) < 0.3 ? clip(pos - 30, 0, 120) * 0.12 : 0)
  }
  const period = 90 + 120 * u(SEED, name, 'period')
  const phase = pyMod(minutes + period * u(SEED, name, 'ph'), period)
  const refill = 8
  const fall = clip(phase / (period - refill), 0, 1)
  let v = phase < period - refill ? hi - (hi - lo) * fall : lo + (hi - lo) * (phase - (period - refill)) / refill
  if (u(SEED, name, 'fast', slot) < 0.25 && phase < period - refill) v = hi - (hi - lo) * clip(fall * 2, 0, 1)
  return Math.max(0, v + (hi - lo) * 0.004 * (u(SEED, name, 'n', Math.trunc(minutes)) - 0.5))
}
function digital(t: SimTag, sec: number): number {
  const name = t.name
  const sm = name.match(DIGITAL_SUFFIX)
  const suffix = sm ? sm[1].toUpperCase() : ''
  const dev = name.replace(DIGITAL_SUFFIX, '')
  const minutes = sec / 60
  const slot = Math.floor(minutes / DEV_SLOT_MIN)
  const pos = pyMod(minutes, DEV_SLOT_MIN)
  const uu = u(SEED, dev, 'dev', slot)
  const start = 10 + 80 * u(SEED, dev, 'devs', slot)
  const length = 3 + 25 * u(SEED, dev, 'devl', slot)
  const inside = pos >= start && pos < start + length
  const trip = inside && uu < 0.06
  const stop = inside && uu >= 0.06 && uu < 0.10
  const local = inside && uu >= 0.10 && uu < 0.13
  const mismatch = inside && uu >= 0.13 && uu < 0.17
  if (dev.startsWith('XV') || dev.startsWith('HV') || suffix === 'VAL2' || suffix === 'VAL') {
    const period = 40 + 140 * u(SEED, dev, 'vp')
    const duty = 0.3 + 0.5 * u(SEED, dev, 'vd')
    const cmd = pyMod(minutes + period * u(SEED, dev, 'vph'), period) < period * duty ? 1 : 0
    if (['VAL2', 'VAL', 'ZT', 'ZS'].includes(suffix)) return mismatch ? 1 - cmd : cmd
    if (suffix === 'FT') return cmd * (u(SEED, dev, 'ft', slot) < 0.5 ? 1 : 0)
    return cmd
  }
  if (suffix === 'DO') return stop ? 0 : 1
  if (suffix === 'FL') return trip && u(SEED, dev, 'fl', slot) < 0.6 ? 1 : 0
  if (suffix === 'RM') return local ? 0 : 1
  return trip || stop || local ? 0 : 1
}

/** 与 simulator.series 相同的单点取值（sec = epoch 秒）。 */
export function valueAt(t: SimTag, limit: Any, sec: number): number {
  if (isDigital(t)) return digital(t, sec)
  if (/^(LT_|SJGYW_)/.test(t.name) || t.parameterName.includes('液位')) return level(t, sec)
  return analog(t, limit, sec)
}

const ALARM_KEYS: [string, string, number][] = [['highHigh', 'HH', 1], ['high', 'H', 1], ['lowLow', 'LL', -1], ['low', 'L', -1]]
/** 与 runtime.alarm_of 相同。 */
export function alarmOf(v: number, limit: Any): string | null {
  if (!limit) return null
  for (const [k, label, sign] of ALARM_KEYS) {
    const x = limit[k]
    if (x !== null && x !== undefined && (sign > 0 ? v >= x : v <= x)) return label
  }
  const lo = limit.normalLow
  const hi = limit.normalHigh
  if ((lo !== null && lo !== undefined && v < lo) || (hi !== null && hi !== undefined && v > hi)) return '偏离'
  return null
}
