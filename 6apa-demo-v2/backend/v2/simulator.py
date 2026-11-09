"""模拟测点数据（仅用于演示判定规则与计算组态的试算）。

**这里的数据全部是模拟的**，接口返回里带 dataSource.simulated = true，前端会标注。

值是 (种子, 位号, 时间) 的纯函数：同一时间窗查两次结果完全一样，便于演示复现。
- 模拟量：以该测点工艺限值的正常区间为中心做慢周期 + 快周期波动 + 噪声；按 3 小时时间片
  随机出现「偏离片段」，把值推到正常区间外，使现象有机会成立；
- 液位：锯齿形（逐步下降 → 补液），计量罐类下降速率随时间片变化，缓冲罐有持续上涨片段；
- 无限值的模拟量按点表量程取值（深冷点表带量程）；
- 开关量：同一台设备（位号去掉 _RUN/_DO/_FL/_RM 等后缀）共享状态：偶发跳闸（指令 1、运行 0、故障 1）、
  停机（指令 0、运行 0）、就地（远程 0）；阀门开关周期变化，偶发指令与反馈不一致；
- 同一罐的两支 pH 计（AT_1301C1 / C2）共用一条曲线，偶发单支漂移。
"""
from __future__ import annotations

import hashlib
import re
import struct
from datetime import datetime, timedelta
from typing import Any

import numpy as np

SEED = "6apa-demo-v2"
# 模拟基准（只给模拟器用，不是工艺限值）：没有正常区间的位号按这里的典型运行区间生成模拟值
_BAND_FILE = __import__("pathlib").Path(__file__).resolve().parents[2] / "data" / "config" / "模拟基准.json"
SIM_BANDS: dict[str, tuple[float, float]] = {}
if _BAND_FILE.exists():
    import json as _json

    SIM_BANDS = {k: (float(v[0]), float(v[1])) for k, v in _json.loads(_BAND_FILE.read_text("utf-8"))["bands"].items()}
SLOT_MIN = 180  # 偏离片段的时间片
DEV_SLOT_MIN = 120  # 开关量状态片段
TIME_FMT = "%Y-%m-%d %H:%M"

DIGITAL_SUFFIX = re.compile(r"_(RUN|DO|FL|RM|VAL2|VAL|FT|MOT2|DI|ZT|ZS)$", re.I)
DIGITAL_TYPES = ("DI", "DO", "DOV", "MOT2", "VAL2", "VAL", "DIV")
UNIT_RANGES = {
    "ph": (6.5, 7.5), "℃": (20.0, 30.0), "°c": (20.0, 30.0), "m3": (8.0, 20.0), "l": (200.0, 800.0),
    "mpa": (0.45, 0.6), "kpa": (40.0, 60.0), "l/h": (800.0, 1200.0), "m3/h": (5.0, 10.0), "%": (40.0, 60.0),
    "a": (20.0, 40.0), "hz": (30.0, 45.0), "rpm": (800.0, 1200.0),
}


def _u(*parts: object) -> float:
    digest = hashlib.blake2b("|".join(map(str, parts)).encode("utf-8"), digest_size=8).digest()
    return struct.unpack(">Q", digest)[0] / 2**64


def _slot_u(key: str, salt: str, slots: np.ndarray) -> np.ndarray:
    cache: dict[int, float] = {}
    out = np.empty(len(slots))
    for i, s in enumerate(slots):
        s = int(s)
        if s not in cache:
            cache[s] = _u(SEED, key, salt, s)
        out[i] = cache[s]
    return out


def time_axis(hours: float = 24, step_sec: int = 60, end: datetime | None = None) -> np.ndarray:
    """返回分钟级 epoch 时间（秒）数组，末端对齐到整分钟。"""
    end = (end or datetime.now()).replace(second=0, microsecond=0)
    n = max(2, int(hours * 3600 // step_sec) + 1)
    end_s = int(end.timestamp())
    return np.arange(end_s - (n - 1) * step_sec, end_s + 1, step_sec, dtype=np.int64)


def fmt_times(times: np.ndarray) -> list[str]:
    return [datetime.fromtimestamp(int(t)).strftime(TIME_FMT) for t in times]


def is_digital(tag: dict[str, Any]) -> bool:
    block = str(tag.get("blockType") or "").upper()
    ptype = str(tag.get("parameterType") or "")
    return block in DIGITAL_TYPES or "开关" in ptype or "状态" in ptype or bool(DIGITAL_SUFFIX.search(tag["name"]))


def _band(tag: dict[str, Any], limit: dict[str, Any] | None) -> tuple[float, float]:
    if limit:
        lo, hi = limit.get("normalLow"), limit.get("normalHigh")
        if lo is None and hi is not None:  # 只有「< 上限」：正常运行在上限的 20%～55%
            lo, hi = (hi * 0.2, hi * 0.55) if hi > 0 else (hi - 1, hi)
        if hi is None and lo is not None:  # 只有「≥ 下限」
            lo, hi = (lo * 1.1, lo * 1.5) if lo > 0 else (lo, lo + 1)
        if lo is not None and hi is not None and hi > lo:
            return float(lo), float(hi)
        h = limit.get("high")
        if h is not None and h > 0 and tag["name"] not in SIM_BANDS:  # 只有报警高限：正常运行在高限的 45%～75%
            return h * 0.45, h * 0.75
    if tag["name"] in SIM_BANDS:
        return SIM_BANDS[tag["name"]]
    rlo, rhi = tag.get("rangeLow"), tag.get("rangeHigh")
    if rlo is not None and rhi is not None and rhi > rlo:
        # 没有限值时按量程的 35%～60% 取值（深冷点表带量程，如 -150～50 ℃）
        span = rhi - rlo
        return rlo + 0.35 * span, rlo + 0.6 * span
    unit = str(tag.get("unit") or tag.get("standardUnit") or "").strip().lower()
    return UNIT_RANGES.get(unit, (40.0, 60.0))


def _analog(tag: dict[str, Any], limit: dict[str, Any] | None, t: np.ndarray) -> np.ndarray:
    name = tag["name"]
    lo, hi = _band(tag, limit)
    mid, half = (lo + hi) / 2, (hi - lo) / 2
    # 同一罐两支 pH 计共用曲线
    curve = re.sub(r"^(AT_\d+[A-Z])[12]$", r"\1", name)
    minutes = t / 60.0
    p1 = 60 + 300 * _u(SEED, curve, "p1")
    p2 = 8 + 30 * _u(SEED, curve, "p2")
    ph1, ph2 = 6.283 * _u(SEED, curve, "f1"), 6.283 * _u(SEED, curve, "f2")
    v = mid + 0.45 * half * np.sin(6.283 * minutes / p1 + ph1) + 0.15 * half * np.sin(6.283 * minutes / p2 + ph2)
    noise = np.array([_u(SEED, name, "n", int(m)) for m in minutes]) - 0.5
    v = v + 0.08 * half * noise
    # 偏离片段：在 3 小时片内的一段时间把值推出正常区间
    slots = (minutes // SLOT_MIN).astype(np.int64)
    pos = minutes % SLOT_MIN
    u = _slot_u(curve, "exc", slots)
    start = 20 + 60 * _slot_u(curve, "exs", slots)
    length = 15 + 70 * _slot_u(curve, "exl", slots)
    sign = np.where(_slot_u(curve, "exd", slots) < 0.5, 1.0, -1.0)
    active = (u < 0.22) & (pos >= start) & (pos < start + length)
    ramp = np.clip(np.minimum(pos - start, start + length - pos) / 8.0, 0, 1)
    v = v + np.where(active, sign * 1.7 * half * ramp, 0.0)
    # 单支 pH 漂移
    if re.match(r"^AT_\d+[A-Z]2$", name):
        drift = _slot_u(name, "drift", slots) < 0.18
        v = v + np.where(drift, 0.35 * np.clip(pos / 40.0, 0, 1), 0.0)
    return v


def _level(tag: dict[str, Any], limit: dict[str, Any] | None, t: np.ndarray) -> np.ndarray:
    name = tag["name"]
    unit = str(tag.get("unit") or "").lower()
    lo, hi = (100.0, 900.0) if unit == "l" else (3.0, 28.0)
    if limit or (tag.get("rangeLow") is not None and tag.get("rangeHigh") is not None):
        # 有限值或量程时：锯齿在正常区间附近上下摆动（略超出两端，便于液位高 / 低现象试算）
        blo, bhi = _band(tag, limit)
        pad = (bhi - blo) * 0.25
        lo, hi = blo - pad, bhi + pad
    minutes = t / 60.0
    if name == "LT_1303":  # 水解液缓冲罐：大部分时间平稳，偶有持续上涨（下游不接收）
        slots = (minutes // SLOT_MIN).astype(np.int64)
        pos = minutes % SLOT_MIN
        base = 12 + 2 * np.sin(6.283 * minutes / 97.0)
        rising = _slot_u(name, "rise", slots) < 0.3
        return base + np.where(rising, np.clip(pos - 30, 0, 120) * 0.12, 0.0)
    period = 90 + 120 * _u(SEED, name, "period")
    phase = (minutes + period * _u(SEED, name, "ph")) % period
    refill = 8.0
    fall = np.clip(phase / (period - refill), 0, 1)
    v = np.where(phase < period - refill, hi - (hi - lo) * fall, lo + (hi - lo) * (phase - (period - refill)) / refill)
    # 下降速率按时间片变化（加氨快 / 慢）
    slots = (minutes // SLOT_MIN).astype(np.int64)
    fast = _slot_u(name, "fast", slots) < 0.25
    # 加料快的时间片：下降段斜率翻倍，降到低位后保持到补液
    fast_v = np.where(phase < period - refill, hi - (hi - lo) * np.clip(fall * 2, 0, 1), v)
    v = np.where(fast, fast_v, v)
    noise = np.array([_u(SEED, name, "n", int(m)) for m in minutes]) - 0.5
    return np.clip(v + (hi - lo) * 0.004 * noise, 0, None)


def _digital(tag: dict[str, Any], t: np.ndarray) -> np.ndarray:
    name = tag["name"]
    suffix_m = DIGITAL_SUFFIX.search(name)
    suffix = suffix_m.group(1).upper() if suffix_m else ""
    dev = DIGITAL_SUFFIX.sub("", name)
    minutes = t / 60.0
    slots = (minutes // DEV_SLOT_MIN).astype(np.int64)
    pos = minutes % DEV_SLOT_MIN
    u = _slot_u(dev, "dev", slots)
    start = 10 + 80 * _slot_u(dev, "devs", slots)
    length = 3 + 25 * _slot_u(dev, "devl", slots)
    inside = (pos >= start) & (pos < start + length)
    trip = inside & (u < 0.06)
    stop = inside & (u >= 0.06) & (u < 0.10)
    local = inside & (u >= 0.10) & (u < 0.13)
    mismatch = inside & (u >= 0.13) & (u < 0.17)
    is_valve = dev.startswith(("XV", "HV")) or suffix in ("VAL2", "VAL")
    if is_valve:
        period = 40 + 140 * _u(SEED, dev, "vp")
        duty = 0.3 + 0.5 * _u(SEED, dev, "vd")
        cmd = (((minutes + period * _u(SEED, dev, "vph")) % period) < period * duty).astype(float)
        if suffix in ("VAL2", "VAL", "ZT", "ZS"):
            return np.where(mismatch, 1 - cmd, cmd)
        if suffix == "FT":
            return cmd * (_slot_u(dev, "ft", slots) < 0.5)
        return cmd
    text = f"{tag.get('parameterName') or ''}{tag.get('variableCategory') or ''}{tag.get('rawDescription') or ''}"
    if not suffix and re.search(r"报警|故障|停机|超温|跳闸|首出", text):
        # 报警 / 故障 / 停机类开关量平时为 0，跳闸片段为 1（深冷点表的 DI、ESD 通讯点）
        return np.where(trip, 1.0, 0.0)
    if suffix == "DO":
        return np.where(stop, 0.0, 1.0)
    if suffix == "FL":
        return np.where(trip & (_slot_u(dev, "fl", slots) < 0.6), 1.0, 0.0)
    if suffix == "RM":
        return np.where(local, 0.0, 1.0)
    # RUN / MOT2 / 其他反馈
    return np.where(trip | stop | local, 0.0, 1.0)


def series(tag: dict[str, Any], limit: dict[str, Any] | None, t: np.ndarray) -> np.ndarray:
    name = tag["name"]
    if is_digital(tag):
        return _digital(tag, t)
    if re.match(r"^(LT_|SJGYW_)", name) or "液位" in (tag.get("parameterName") or ""):
        return _level(tag, limit, t)
    return _analog(tag, limit, t)


DATA_SOURCE = {"simulated": True, "label": "模拟数据", "note": "测点值由本 Demo 内置的确定性模拟器生成，不是现场数据"}
