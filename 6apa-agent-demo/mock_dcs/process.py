"""水解罐批次过程模拟：确定性的批次排程，以及跟着批次阶段走的测点值。

S11 酶法水解的 11 台水解罐（A～K）各自按批次循环：进料 → 反应 → 终点判定 → 出料 → 空闲。
排程是 (种子, 罐号) 的纯函数，从 EPOCH 起逐批推算：
- 模拟 DCS 的阀门、搅拌、温度、pH、液位、氨水计量罐测点按当时所处阶段取值；
- 模拟 EBR 的罐批次记录、模拟 MOM 的排班都从同一份排程算出，三者对得上。

刻意放进去的现场经验（10.19 力兴业）：换酶后批次数越多，温度、pH 设定越高，反应时间越长（酶活衰减）；
换酶后约 1000～1200 批换酶，批次计数从 1 重新开始。所有数值只求合理，不代表现场真实工况。
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

TZ = timezone(timedelta(hours=8))
EPOCH_MS = int(datetime(2026, 1, 1, tzinfo=TZ).timestamp() * 1000)
MIN = 60_000
TANKS = "ABCDEFGHIJK"
PHASES = ("进料", "反应", "终点判定", "出料", "空闲")
RUNNING_PHASES = ("进料", "反应", "终点判定")
SHIFT_TEAMS = ("甲", "乙", "丙", "丁")
SHIFTS = (("夜班", 0), ("白班", 8), ("中班", 16))


def _u(*parts: object) -> float:
    digest = hashlib.blake2b("|".join(map(str, parts)).encode("utf-8"), digest_size=8).digest()
    return struct.unpack(">Q", digest)[0] / 2**64


@dataclass
class Batch:
    tank: str
    seq: int  # 自 EPOCH 起本罐第几批
    count: int  # 换酶后第几批
    enzyme_lot: str
    phases: list[tuple[str, int, int]] = field(default_factory=list)  # (阶段, 开始, 结束)

    @property
    def start(self) -> int:
        return self.phases[0][1]

    @property
    def end(self) -> int:
        return self.phases[-1][2]

    @property
    def batch_no(self) -> str:
        return f"SJ-{self.tank}-{self.seq:04d}"

    def phase(self, name: str) -> tuple[int, int] | None:
        return next(((s, e) for p, s, e in self.phases if p == name), None)

    def phase_at(self, t: int) -> tuple[str, int, int] | None:
        return next(((p, s, e) for p, s, e in self.phases if s <= t < e), None)


class TankSchedule:
    """一台水解罐的批次排程（按需向后推算并缓存）。"""

    def __init__(self, seed: str, tank: str) -> None:
        self.seed, self.tank = seed, tank
        self.batches: list[Batch] = []
        self._starts: list[int] = []
        self._t = EPOCH_MS + int(_u(seed, tank, "offset") * 8 * 60) * MIN
        self._count = 50 + int(_u(seed, tank, "count0") * 850)
        self._lot = 1
        self._life = 1000 + int(_u(seed, tank, "life", 1) * 200)

    def _extend(self, until_ms: int) -> None:
        while self._t <= until_ms:
            seq = len(self.batches) + 1
            u = lambda salt: _u(self.seed, self.tank, seq, salt)  # noqa: E731
            wear = min(self._count, 1200) / 1200  # 酶活衰减：批次越多反应越慢
            durations = (
                ("进料", 30 + 15 * u("feed")),
                ("反应", 300 + 90 * u("react") + 60 * wear),
                ("终点判定", 20 + 20 * u("end")),
                ("出料", 30 + 20 * u("out")),
                ("空闲", 20 + 70 * u("idle")),
            )
            phases, t = [], self._t
            for name, minutes in durations:
                end = t + int(minutes) * MIN
                phases.append((name, t, end))
                t = end
            batch = Batch(self.tank, seq, self._count, f"E-{self.tank}-{self._lot:02d}", phases)
            self.batches.append(batch)
            self._starts.append(batch.start)
            self._t = t
            self._count += 1
            if self._count > self._life:  # 换酶
                self._lot += 1
                self._count = 1
                self._life = 1000 + int(_u(self.seed, self.tank, "life", self._lot) * 200)

    def at(self, t_ms: int) -> Batch | None:
        if t_ms < EPOCH_MS:
            return None
        self._extend(t_ms)
        i = bisect_right(self._starts, t_ms) - 1
        return self.batches[i] if i >= 0 and self.batches[i].start <= t_ms < self.batches[i].end else None

    def between(self, start_ms: int, end_ms: int) -> list[Batch]:
        self._extend(end_ms)
        i = max(0, bisect_right(self._starts, start_ms) - 1)
        out = []
        for batch in self.batches[i:]:
            if batch.start > end_ms:
                break
            if batch.end > start_ms:
                out.append(batch)
        return out


_schedules: dict[tuple[str, str], TankSchedule] = {}


def schedule(seed: str, tank: str) -> TankSchedule:
    key = (seed, tank)
    if key not in _schedules:
        _schedules[key] = TankSchedule(seed, tank)
    return _schedules[key]


# 点表里水解相关位号的台号后缀跳过了 I（I 易与 1 混淆）：多数位号 A～H 照旧，水解罐I/J/K 写成 J/K/L；
# 但也有例外（水解罐J 的搅拌、出料流量仍写 J）。所以按点表登记的所属设备定罐号，设备不详时才按后缀推
TAG_LETTER_TO_TANK = dict(zip("ABCDEFGHJKL", "ABCDEFGHIJK"))
TANK_TO_TAG_LETTER = {v: k for k, v in TAG_LETTER_TO_TANK.items()}


def tank_for_tag(letter: str, equipment: str = "") -> str | None:
    return tank_of(equipment) or TAG_LETTER_TO_TANK.get(letter)


def tank_of(unit: str) -> str | None:
    """「水解罐A」/「A」→ A。"""
    m = re.fullmatch(r"(?:水解罐)?([A-K])", (unit or "").strip())
    return m.group(1) if m else None


# ------------------------------------------------------------------ 排班（四班三运转）


def shifts_between(start_ms: int, end_ms: int) -> list[dict]:
    out = []
    day = datetime.fromtimestamp(start_ms / 1000, TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    while int(day.timestamp() * 1000) <= end_ms:
        day_index = (day.date() - datetime(2026, 1, 1).date()).days
        for i, (name, hour) in enumerate(SHIFTS):
            s = int((day + timedelta(hours=hour)).timestamp() * 1000)
            e = s + 8 * 3600 * 1000
            if e > start_ms and s <= end_ms:
                out.append({"date": day.strftime("%Y-%m-%d"), "shift": name, "team": SHIFT_TEAMS[(day_index * 3 + i) % 4],
                            "startTime": s, "endTime": e})
        day += timedelta(days=1)
    return out


# ------------------------------------------------------------------ 测点值


@dataclass
class Overlay:
    """跟着批次阶段取值的测点。discrete=True 时 value 返回 0/1。"""

    tank: str
    discrete: bool
    value_fn: Callable[[Batch | None, str | None, int, int, int], float]
    phases_on: tuple[str, ...] = ()
    seed: str = ""

    def value(self, t_ms: int) -> float:
        batch = schedule(self.seed, self.tank).at(t_ms)
        if batch is None:
            return self.value_fn(None, None, t_ms, 0, 0)
        name, s, e = batch.phase_at(t_ms)
        return self.value_fn(batch, name, t_ms, s, e)

    # 开关量：变位点就是阶段边界
    def changes(self, start_ms: int, end_ms: int, cap: int) -> list[tuple[int, int]]:
        out = [(start_ms, int(self.value(start_ms)))]
        prev = out[0][1]
        for batch in schedule(self.seed, self.tank).between(start_ms, end_ms):
            for _, s, _e in batch.phases:
                if start_ms < s <= end_ms:
                    v = int(self.value(s))
                    if v != prev:
                        out.append((s, v))
                        prev = v
                        if len(out) >= cap:
                            return out
        return out

    def last_change(self, t_ms: int) -> int:
        current = int(self.value(t_ms))
        sched = schedule(self.seed, self.tank)
        batch = sched.at(t_ms)
        candidates = []
        lookback = sched.between(t_ms - 3 * 86_400_000, t_ms)
        for b in lookback:
            for _, s, _e in b.phases:
                if s <= t_ms:
                    candidates.append(s)
        for s in sorted(candidates, reverse=True):
            if int(self.value(s - 1)) != current:
                return s
        return (batch.start if batch else t_ms)


def _noise(seed: str, key: str, t_ms: int, amp: float) -> float:
    return amp * (2 * _u(seed, key, t_ms // 1000) - 1)


def _setpoints(count: int) -> tuple[float, float]:
    """批次越多，温度、pH 设定越高（现场经验 BF-07）。"""
    wear = min(count, 1200) / 1200
    return 33.6 + 1.0 * wear, 7.85 + 0.25 * wear


# ------------------------------------------------------------------ 操作记录（DCS 操作日志）
#
# 每批反应期间，操作员有一定概率改温度 / pH 设定值（下一批恢复），也会有手自动切换。
# 改设定值会真实影响该批后续的罐温 / pH 曲线，用来演示「人为改参数」这一类原因。

OP_STATIONS = ("OS-13-1", "OS-13-2")


@dataclass(frozen=True)
class OpEvent:
    t: int
    tank: str
    batch_no: str
    kind: str  # 设定值修改 / 手自动切换
    tag: str
    param: str
    old: float | str
    new: float | str
    station: str

    @property
    def delta(self) -> float:
        return float(self.new) - float(self.old) if self.kind == "设定值修改" else 0.0


_ops_cache: dict[tuple[str, str, int], tuple[OpEvent, ...]] = {}


def batch_ops(seed: str, batch: Batch) -> tuple[OpEvent, ...]:
    key = (seed, batch.tank, batch.seq)
    if key in _ops_cache:
        return _ops_cache[key]
    u = lambda salt: _u(seed, batch.tank, batch.seq, "op", salt)  # noqa: E731
    react = batch.phase("反应")
    sp_t, sp_ph = _setpoints(batch.count)
    out: list[OpEvent] = []
    station = OP_STATIONS[int(u("station") * 2)]
    if react and u("temp") < 0.22:
        t = react[0] + int(30 + 150 * u("temp_t")) * MIN
        delta = round((0.5 + 0.6 * u("temp_d")) * (1 if u("temp_s") < 0.7 else -1), 1)
        out.append(OpEvent(t, batch.tank, batch.batch_no, "设定值修改", f"TI_1301{TANK_TO_TAG_LETTER[batch.tank]}", "温度设定值",
                           round(sp_t, 1), round(sp_t + delta, 1), station))
    if react and u("ph") < 0.15:
        t = react[0] + int(60 + 180 * u("ph_t")) * MIN
        delta = round((0.08 + 0.08 * u("ph_d")) * (1 if u("ph_s") < 0.6 else -1), 2)
        out.append(OpEvent(t, batch.tank, batch.batch_no, "设定值修改", f"AT_1301{TANK_TO_TAG_LETTER[batch.tank]}1", "pH 设定值",
                           round(sp_ph, 2), round(sp_ph + delta, 2), station))
    if react and u("am") < 0.12:
        t = react[0] + int(20 + 200 * u("am_t")) * MIN
        out.append(OpEvent(t, batch.tank, batch.batch_no, "手自动切换", f"XV_1304{TANK_TO_TAG_LETTER[batch.tank]}", "氨水阀控制方式",
                           "自动", "手动", station))
        out.append(OpEvent(t + int(10 + 30 * u("am_back")) * MIN, batch.tank, batch.batch_no, "手自动切换",
                           f"XV_1304{TANK_TO_TAG_LETTER[batch.tank]}", "氨水阀控制方式", "手动", "自动", station))
    out.sort(key=lambda e: e.t)
    _ops_cache[key] = tuple(out)
    return _ops_cache[key]


def sp_offset(seed: str, batch: Batch | None, param: str, t: int) -> float:
    """t 时刻该批已生效的设定值改动量（改动只在本批有效）。"""
    if batch is None:
        return 0.0
    return sum(e.delta for e in batch_ops(seed, batch) if e.param == param and e.t <= t)


def ops_between(seed: str, tank: str, start_ms: int, end_ms: int) -> list[OpEvent]:
    out = []
    for batch in schedule(seed, tank).between(start_ms, end_ms):
        out.extend(e for e in batch_ops(seed, batch) if start_ms <= e.t <= end_ms)
    return out


# ------------------------------------------------------------------ pH 电极漂移与化验
#
# 电极 1 参与 pH 控制：控制器把电极 1 的读数稳在设定值，电极 1 漂移时真实 pH 反向偏离。
# 每台罐按校准周期从零开始线性漂移；C 罐漂移快（演示「在线与化验差值逐渐扩大」），G 罐中等，其余很小。
# 电极 2 不参与控制，漂移很小，读的近似真实 pH（+0.02）：两支电极的差也随之拉开。
# 化验 pH = 真实 pH + 化验误差；报告时间比取样晚 30～60 分钟。

_DRIFT = {"C": (0.0012, 14), "G": (0.0006, 10)}  # 罐号 → (漂移 pH/小时, 校准周期 天)
_DRIFT_DEFAULT = (0.0001, 7)


def electrode_offset(seed: str, tank: str, t_ms: int) -> float:
    rate, days = _DRIFT.get(tank, _DRIFT_DEFAULT)
    period = days * 86_400_000
    phase = int(_u(seed, tank, "cal") * period)
    hours = ((t_ms - EPOCH_MS - phase) % period) / 3_600_000
    return rate * hours


def last_calibration(seed: str, tank: str, t_ms: int) -> int:
    rate, days = _DRIFT.get(tank, _DRIFT_DEFAULT)
    period = days * 86_400_000
    phase = int(_u(seed, tank, "cal") * period)
    return t_ms - (t_ms - EPOCH_MS - phase) % period


def ph_controlled(seed: str, tank: str, b: Batch | None, ph: str | None, t: int, s: int, e: int) -> float:
    """电极 1 读数（控制器的被控量）。"""
    if b is None:
        return 7.2
    _, sp = _setpoints(b.count)
    sp += sp_offset(seed, b, "pH 设定值", t)
    if ph == "进料":
        return 7.3 + (sp - 7.3) * (t - s) / max(1, e - s)
    if ph == "反应":
        tau = (t - s) / MIN
        return sp - 0.15 * math.exp(-tau / 30) + 0.04 * math.sin(2 * math.pi * tau / 23)
    if ph == "终点判定":
        return sp + 0.02
    return 7.2


def true_ph(seed: str, tank: str, t: int) -> float:
    b = schedule(seed, tank).at(t)
    if b is None:
        return 7.2
    name, s, e = b.phase_at(t)
    controlled = name in ("反应", "终点判定")
    value = ph_controlled(seed, tank, b, name, t, s, e)
    return value - electrode_offset(seed, tank, t) if controlled else value


LAB_ITEMS = {
    "PH": {"name": "水解液pH", "unit": "pH"},
    "ZHL": {"name": "酶解转化率", "unit": "%"},
}


def lab_results(seed: str, tank: str, start_ms: int, end_ms: int) -> list[dict]:
    """某罐时间范围内的化验结果（按取样时间）：反应中取两次 pH，终点取一次 pH 和转化率。"""
    out = []
    for b in schedule(seed, tank).between(start_ms - 86_400_000, end_ms):
        react, endp = b.phase("反应"), b.phase("终点判定")
        if not react or not endp:
            continue
        u = lambda salt: _u(seed, tank, b.seq, "lab", salt)  # noqa: E731
        samples = [
            (react[0] + int(90 + 30 * u("s1")) * MIN, "PH", "反应中"),
            (react[0] + (react[1] - react[0]) * 2 // 3 + int(20 * u("s2")) * MIN, "PH", "反应中"),
            (endp[0] + int(5 + 10 * u("s3")) * MIN, "PH", "终点"),
            (endp[0] + int(5 + 10 * u("s3")) * MIN, "ZHL", "终点"),
        ]
        for i, (t, item, stage) in enumerate(samples):
            if not (start_ms <= t <= end_ms):
                continue
            if item == "PH":
                value = round(true_ph(seed, tank, t) + 0.02 * (2 * _u(seed, tank, b.seq, "labv", i) - 1), 2)
            else:
                ph_dev = abs(true_ph(seed, tank, t) - _setpoints(b.count)[1])
                wear = min(b.count, 1200) / 1200
                temp_dev = abs(sp_offset(seed, b, "温度设定值", t))
                value = round(98.6 - 1.2 * wear - 4.0 * ph_dev - 0.8 * temp_dev + 0.3 * (2 * u("zhl") - 1), 2)
            report = t + int(30 + 30 * _u(seed, tank, b.seq, "rep", i)) * MIN
            out.append({
                "sampleNo": f"LIMS-{b.batch_no}-{i + 1}", "unit": f"水解罐{tank}", "unitCode": tank,
                "batchNo": b.batch_no, "samplePoint": f"水解罐{tank}取样口", "stage": stage,
                "itemCode": item, "itemName": LAB_ITEMS[item]["name"], "value": value, "unitOfMeasure": LAB_ITEMS[item]["unit"],
                "sampleTime": t, "reportTime": report, "source": "LIMS",
            })
    return [r for r in out if r["reportTime"] <= end_ms or r["sampleTime"] <= end_ms]


# 跟随批次阶段的模拟量在整个批次周期（进料 / 反应 / 出料 / 空闲）内的取值范围；
# 画像里的范围只描述反应稳态，带阶段的测点以这里为准
_OVERLAY_RANGES = (
    (r"TI_1301[A-L]", 24.0, 37.5),
    (r"AT_1301[A-L][12]", 7.0, 8.4),
    (r"SJGYW_[A-L]", 0.0, 12.0),
    (r"LT_1302[A-L]", 0.0, 160.0),
)


def overlay_range(name: str) -> tuple[float, float] | None:
    for pattern, lo, hi in _OVERLAY_RANGES:
        if re.fullmatch(pattern, name):
            return lo, hi
    return None


def adjust_profile(name: str, profile: Any) -> Any:
    """带批次阶段的模拟量：画像范围换成整个批次周期的范围，并在规则里注明。"""
    rng = overlay_range(name) if profile.kind == "analog" and not profile.spare else None
    if not rng:
        return profile
    from dataclasses import replace

    return replace(profile, lo=rng[0], hi=rng[1], rule=f"{profile.rule}；S11 水解罐跟随批次阶段取值（process.py）")


def overlay_for(name: str, station: str, discrete: bool, seed: str, equipment: str = "") -> Overlay | None:
    m = re.fullmatch(r"TI_1301([A-L])", name)
    if m:
        tank = tank_for_tag(m.group(1), equipment)
        def temp(b, ph, t, s, e):
            if b is None:
                return 26.0
            sp, _ = _setpoints(b.count)
            sp += sp_offset(seed, b, "温度设定值", t)
            n = _noise(seed, name, t, 0.05)
            if ph == "进料":
                return 28.0 + (sp - 0.6 - 28.0) * (t - s) / max(1, e - s) + n
            if ph == "反应":
                return sp + 0.25 * math.sin(2 * math.pi * (t - s) / (47 * MIN)) + n
            if ph == "终点判定":
                return sp - 0.2 + n
            if ph == "出料":
                return sp - 0.4 - 2.0 * (t - s) / max(1, e - s) + n
            return 26.5 + 0.5 * math.sin(2 * math.pi * t / (6 * 60 * MIN)) + n
        return Overlay(tank, False, lambda b, ph, t, s, e: round(temp(b, ph, t, s, e), 2), seed=seed)

    m = re.fullmatch(r"AT_1301([A-L])([12])", name)
    if m:
        tank, electrode = tank_for_tag(m.group(1), equipment), m.group(2)

        def ph_value(b, ph, t, s, e):
            n = _noise(seed, name, t, 0.01)
            if electrode == "1":
                # 电极 1 参与控制：反应 / 终点判定时读数稳在设定值；其余阶段读真实 pH + 自身漂移
                if ph in ("反应", "终点判定"):
                    return ph_controlled(seed, tank, b, ph, t, s, e) + n
                return ph_controlled(seed, tank, b, ph, t, s, e) + electrode_offset(seed, tank, t) + n
            # 电极 2：不参与控制，读真实 pH（固定偏 +0.02）
            return true_ph(seed, tank, t) + 0.02 + n
        return Overlay(tank, False, lambda b, ph, t, s, e: round(ph_value(b, ph, t, s, e), 2), seed=seed)

    m = re.fullmatch(r"SJGYW_([A-L])", name)
    if m:
        tank = tank_for_tag(m.group(1), equipment)
        def level(b, ph, t, s, e):
            n = _noise(seed, name, t, 0.03)
            if ph == "进料":
                return 1.0 + 10.0 * (t - s) / max(1, e - s) + n
            if ph in ("反应", "终点判定"):
                return 11.0 + n
            if ph == "出料":
                return 11.0 - 10.2 * (t - s) / max(1, e - s) + n
            return 0.8 + n
        return Overlay(tank, False, lambda b, ph, t, s, e: round(level(b, ph, t, s, e), 2), seed=seed)

    m = re.fullmatch(r"LT_1302([A-L])", name)
    if m:
        tank = tank_for_tag(m.group(1), equipment)
        def ammonia(b, ph, t, s, e):
            n = _noise(seed, name, t, 0.3)
            if b is None or ph in ("进料", "出料", "空闲"):
                return 150.0 + n
            r = b.phase("反应")
            total = (r[1] - r[0]) / MIN
            used = 110.0 * (1 - min(b.count, 1200) / 1200 * 0.25)  # 酶活衰减，氨耗下降
            if ph == "反应":
                tau = (t - s) / MIN
                return 150.0 - used * (1 - math.exp(-tau / 90)) / (1 - math.exp(-total / 90)) + n
            return 150.0 - used + n
        return Overlay(tank, False, lambda b, ph, t, s, e: round(ammonia(b, ph, t, s, e), 1), seed=seed)

    if not discrete:
        return None
    rules = (
        (r"XV_1302([A-L])_(DO|VAL2)", ("进料",)),  # RB 进料阀
        (r"XV_1303([A-L])_(DO|VAL2)", ("进料",)),  # 硼酸进料阀
        (r"XV_1304([A-L])_(DO|VAL2)", ("反应",)),  # 氨水进料阀
        (r"XV_1307([A-L])_VAL2", ("进料", "反应")),  # 热水阀
        (r"P_1303([A-L])_(RUN|DO|MOT2)", RUNNING_PHASES),  # 搅拌
        (r"XV_1308([A-L])_FT", ("出料",)),  # 出料流量检测
    )
    for pattern, on in rules:
        m = re.fullmatch(pattern, name)
        if m:
            tank = tank_for_tag(m.group(1), equipment)
            return Overlay(tank, True, lambda b, ph, t, s, e, on=on: 1 if ph in on else 0, on, seed) if tank else None
    return None
