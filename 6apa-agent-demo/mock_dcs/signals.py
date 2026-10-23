"""确定性信号发生器。

核心性质：值是 (种子, 测点, 时间) 的纯函数。
因此：
- 同一时刻查实时值和查历史值，拿到的是同一个数；
- 同一段历史查两次，结果完全一样（可复现，便于演示和排查）；
- 服务重启不影响已经"发生过"的历史。

模拟量 = 基线 + 慢周期波动 + 快周期波动 + 扫描噪声，再夹到合理范围内；
开关量 = 按时间片随机切换的设备状态，同一设备的相关测点共享同一状态。
"""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Iterable

from .profiles import Profile, TagMeta, device_key

SCAN_MS = 1_000  # 模拟量扫描周期
RAW_ANALOG_STEP_MS = 5_000  # raw 模式下模拟量的存储步长
FEEDBACK_LAG_MS = 30_000  # 阀位反馈相对给定的滞后
RUN_DUTY = 0.8  # 电流/频率跟随的设备运行占比
MAX_BACKTRACK_SLOTS = 400  # 回溯"上次变位时间"的最大时间片数


def _uniform(*parts: object) -> float:
    """把任意输入确定性地映射到 [0, 1)。"""
    digest = hashlib.blake2b("|".join(map(str, parts)).encode("utf-8"), digest_size=8).digest()
    return struct.unpack(">Q", digest)[0] / 2**64


@dataclass
class Sample:
    t: int
    q: int
    v: float | int | None


class Signal:
    """一个测点的信号。"""

    def __init__(self, meta: TagMeta, profile: Profile, seed: str) -> None:
        self.meta = meta
        self.profile = profile
        self.seed = seed
        self.dev_key = device_key(meta)

        # 阀门给定与阀位反馈共用一条底层曲线，才能"反馈跟着给定走"
        valve_linked = profile.is_feedback or profile.category == "调节阀给定"
        self.curve_key = f"{self.dev_key}|valve" if valve_linked else f"{meta.station}:{meta.name}"

        u = lambda salt: _uniform(seed, self.curve_key, salt)  # noqa: E731
        self.base_frac = 0.35 + 0.30 * u("base")
        self.p1 = (20 + 160 * u("p1")) * 60_000  # 20 min ~ 3 h
        self.p2 = (2 + 10 * u("p2")) * 60_000  # 2 ~ 12 min
        self.phi1 = 2 * math.pi * u("phi1")
        self.phi2 = 2 * math.pi * u("phi2")

        # 开关量时间片：15 ~ 90 min 切一次状态
        d = lambda salt: _uniform(seed, self.dev_key, salt)  # noqa: E731
        # 时间片和相位都对齐到整秒，变位时间戳才像 DCS 里记录的样子
        self.slot_ms = int(15 + 75 * d("slot")) * 60_000
        self.slot_offset = int(d("offset") * self.slot_ms) // 1000 * 1000
        self.const_since_min = int(d("since") * 360)

    # ------------------------------------------------------------------ 公共

    @property
    def is_discrete(self) -> bool:
        return self.profile.kind == "discrete"

    def value_at(self, t_ms: int) -> Sample:
        if self.is_discrete:
            return Sample(t_ms, 1, self._discrete_value(t_ms))
        return self._analog_sample(t_ms)

    def realtime(self, now_ms: int) -> Sample:
        """实时值：t 是该值的时间戳。模拟量取最近一次扫描；开关量取最近一次变位时刻。"""
        if self.is_discrete:
            value = self._discrete_value(now_ms)
            return Sample(self._last_change(now_ms), 1, value)
        scan_t = now_ms - now_ms % SCAN_MS
        sample = self._analog_sample(scan_t)
        return sample

    def raw(self, start_ms: int, end_ms: int, cap: int) -> list[Sample]:
        """原始存储值：开关量只存变位点，模拟量按存储步长存。"""
        if self.is_discrete:
            return self._discrete_changes(start_ms, end_ms, cap)
        first = start_ms + (-start_ms) % RAW_ANALOG_STEP_MS
        return [self._analog_sample(t) for t in range(first, end_ms + 1, RAW_ANALOG_STEP_MS)][:cap]

    def aggregate(self, start_ms: int, end_ms: int, mode: str) -> Sample:
        """区间统计：在窗口内均匀取 30 个子样本计算 avg / max / min。"""
        n = 30
        span = max(1, end_ms - start_ms)
        points = [self.value_at(start_ms + int(span * i / n)) for i in range(n)]
        good = [p.v for p in points if p.q == 1 and p.v is not None]
        if not good:
            return Sample(start_ms, 0, None)
        if mode == "max":
            value = max(good)
        elif mode == "min":
            value = min(good)
        else:
            value = sum(good) / len(good)
            value = round(value, 3 if self.is_discrete else self.profile.decimals)
        return Sample(start_ms, 1, value)

    # ------------------------------------------------------------------ 模拟量

    def _analog_sample(self, t_ms: int) -> Sample:
        p = self.profile
        if p.spare:
            return Sample(t_ms, 0, 0.0)  # 未接线：坏质量

        if p.follows_run and not self._run_state(t_ms):
            return Sample(t_ms, 1, 0.0)  # 设备停机，电流/频率/转速归零

        effective_t = t_ms - FEEDBACK_LAG_MS if p.is_feedback else t_ms
        value = self._curve(effective_t)
        if p.is_feedback:
            # 反馈相对给定再叠一点点测量误差
            span = p.hi - p.lo
            value += span * 0.004 * (2 * _uniform(self.seed, self.meta.name, "fb", t_ms // SCAN_MS) - 1)
            value = min(p.hi, max(p.lo, value))
        return Sample(t_ms, 1, round(value, p.decimals))

    def _curve(self, t_ms: int) -> float:
        p = self.profile
        span = p.hi - p.lo
        value = (
            p.lo
            + span * self.base_frac
            + span * 0.18 * math.sin(2 * math.pi * t_ms / self.p1 + self.phi1)
            + span * 0.05 * math.sin(2 * math.pi * t_ms / self.p2 + self.phi2)
            + span * 0.012 * (2 * _uniform(self.seed, self.curve_key, "n", t_ms // SCAN_MS) - 1)
        )
        return min(p.hi, max(p.lo, value))

    # ------------------------------------------------------------------ 开关量

    def _slot(self, t_ms: int) -> int:
        return (t_ms + self.slot_offset) // self.slot_ms

    def _slot_start(self, slot: int) -> int:
        return slot * self.slot_ms - self.slot_offset

    def _state_in_slot(self, slot: int, duty: float) -> int:
        return 1 if _uniform(self.seed, self.dev_key, "state", slot) < duty else 0

    def _run_state(self, t_ms: int) -> int:
        return self._state_in_slot(self._slot(t_ms), RUN_DUTY)

    def _discrete_value(self, t_ms: int) -> int:
        role = self.profile.role
        if role in ("pulse", "fault"):
            return 0
        if role == "const1":
            return 1
        state = self._state_in_slot(self._slot(t_ms), self.profile.duty)
        return 1 - state if role == "inverse" else state

    def _last_change(self, t_ms: int) -> int:
        role = self.profile.role
        if role in ("pulse", "fault", "const1"):
            # 常值点：给一个稳定的"很早以前"的时间戳（当天 0 点起若干分钟，或前一天）
            day_ms = 86_400_000
            day_start = t_ms - t_ms % day_ms
            candidate = day_start + self.const_since_min * 60_000
            return candidate if candidate <= t_ms else candidate - day_ms
        slot = self._slot(t_ms)
        current = self._discrete_value(t_ms)
        for _ in range(MAX_BACKTRACK_SLOTS):
            previous = slot - 1
            if self._discrete_value(self._slot_start(previous)) != current:
                break
            slot = previous
        return self._slot_start(slot)

    def _discrete_changes(self, start_ms: int, end_ms: int, cap: int) -> list[Sample]:
        # 区间起点先给一个"当时的值"，此后只记变位点
        out = [Sample(start_ms, 1, self._discrete_value(start_ms))]
        if self.profile.role in ("pulse", "fault", "const1"):
            return out
        slot = self._slot(start_ms) + 1
        last_slot = self._slot(end_ms)
        previous = out[0].v
        while slot <= last_slot and len(out) < cap:
            t = self._slot_start(slot)
            value = self._discrete_value(t)
            if value != previous:
                out.append(Sample(t, 1, value))
                previous = value
            slot += 1
        return out


def interpolated(signal: Signal, times: Iterable[int]) -> list[Sample]:
    return [signal.value_at(t) for t in times]
