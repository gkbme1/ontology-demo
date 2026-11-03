"""按「当时生效」的限值逐点判断：工艺阶段 × 限值版本 × 换酶后批次数。

为什么
------
同一条限值只在它的适用工况内有意义：PL001（釜内反应温度 33~35℃）的适用工况是「水解反应期」，
进料时罐温从 28℃ 爬升、出料和空闲时罐温下降，拿反应期限值去判这些时段会得出大量「低于正常下沿」的假异常。
限值还会被工艺员在线修改、按换酶后批次数分段，判断历史数据要用「当时生效」的那一版，而不是现在的。

做法（固定程序）
--------------
1. 本体 /process-limits/{id}/versions：基础版本 V0 与后续版本（适用设备、换酶后批次区间、生效 / 失效时间）；
2. 测点所属设备若定义了工艺阶段，取该设备时间窗内的批次与阶段（EBR 优先，DCS 推断兜底，见 context_tools）；
3. 逐个样本：所处阶段对应的限值操作模式 ≠ 限值的适用工况 → 不判断；否则按本体登记的匹配规则选版本
   （条件都匹配的版本中取生效时间最晚的；版本里留空的档位沿用 V0），用选出的取值判断这个样本。
测点所属设备没有定义阶段时不做阶段过滤，只按版本与生效时间选限值，并在说明里写明。
"""

from __future__ import annotations

from bisect import bisect_right
from typing import Any, Callable
from urllib.parse import quote

from .context_tools import BatchWindowError, unit_batches
from .executor import ToolApiError

VALUE_KEYS = ("lowLow", "low", "normalLow", "normalHigh", "high", "highHigh")


def _version_matches(v: dict[str, Any], t: int, unit: str, count: int | None) -> bool:
    if v.get("invalid"):
        return False
    if v.get("effectiveFrom") is not None and t < v["effectiveFrom"]:
        return False
    if v.get("effectiveTo") is not None and t >= v["effectiveTo"]:
        return False
    if v.get("unit") and v["unit"] != unit:
        return False
    if v.get("enzymeMin") is not None or v.get("enzymeMax") is not None:
        if count is None:
            return False
        if (v.get("enzymeMin") is not None and count < v["enzymeMin"]) or (v.get("enzymeMax") is not None and count > v["enzymeMax"]):
            return False
    return True


class LimitTimeline:
    """某条限值在时间窗内、对每个测点逐时刻的生效取值。"""

    def __init__(self, limit: dict[str, Any], versions: list[dict[str, Any]], phases: dict[str, dict[str, Any] | None]) -> None:
        self.limit = limit
        self.base = next((v for v in versions if v.get("base")), None) or {**{k: limit.get(k) for k in VALUE_KEYS}, "id": f"{limit.get('id')}-V0"}
        self.versions = sorted((v for v in versions if not v.get("base")), key=lambda v: (v.get("effectiveFrom") or 0, v["id"]))
        self.phases = phases  # 设备名 → {starts, segs, source} 或 None（没有定义阶段）
        self.mode = limit.get("operatingMode") or ""
        self.used: dict[str, int] = {}  # 版本 → 样本数
        self.skipped: dict[str, int] = {}  # 不在适用阶段：阶段 → 样本数
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    @property
    def phase_aware_units(self) -> list[str]:
        return [u for u, p in self.phases.items() if p]

    def _segment(self, unit: str, t: int) -> dict[str, Any] | None:
        info = self.phases.get(unit)
        if not info:
            return None
        i = bisect_right(info["starts"], t) - 1
        if i < 0:
            return {"phase": "无批次记录", "limitMode": "", "count": None}
        seg = info["segs"][i]
        if seg["end"] is not None and t >= seg["end"]:
            return {"phase": "无批次记录", "limitMode": "", "count": None}
        return seg

    def applicable(self, unit: str, t: int) -> bool:
        """t 时刻是否处于限值的适用阶段（不计入统计）。"""
        seg = self._segment(unit, t)
        return seg is None or not self.mode or seg["limitMode"] == self.mode

    def values_at(self, unit: str, t: int) -> dict[str, Any] | None:
        """t 时刻该设备上的生效取值；不在适用阶段时返回 None。"""
        seg = self._segment(unit, t)
        count = None
        if seg is not None:
            if self.mode and seg["limitMode"] != self.mode:
                self.skipped[seg["phase"]] = self.skipped.get(seg["phase"], 0) + 1
                return None
            count = seg["count"]
        chosen = None
        for v in self.versions:
            if _version_matches(v, t, unit, count):
                chosen = v
        picked = chosen or self.base
        key = (picked["id"], unit)
        if key not in self._cache:
            self._cache[key] = {
                **self.limit,
                **{k: (picked.get(k) if picked.get(k) is not None else self.base.get(k)) for k in VALUE_KEYS},
                "versionId": picked["id"],
            }
        self.used[picked["id"]] = self.used.get(picked["id"], 0) + 1
        return self._cache[key]

    def for_unit(self, unit: str | None) -> Callable[[int], dict[str, Any] | None]:
        return lambda t: self.values_at(unit or "", t)

    def dominant(self) -> dict[str, Any]:
        """本次判断用得最多的版本的取值（用于对外展示限值，避免把 V0 当成当时的判据）。"""
        if not self.used:
            return {**self.limit, "versionId": self.base["id"]}
        vid = max(self.used, key=self.used.get)
        picked = next((v for v in [self.base, *self.versions] if v["id"] == vid), self.base)
        return {**self.limit, **{k: (picked.get(k) if picked.get(k) is not None else self.base.get(k)) for k in VALUE_KEYS},
                "versionId": vid}

    def summary(self, step_min: float) -> dict[str, Any]:
        out: dict[str, Any] = {
            "operatingMode": self.mode or None,
            "phaseFiltered": bool(self.phase_aware_units),
            "versionsUsed": [
                {"versionId": vid, "minutes": int(round(n * step_min)),
                 "condition": next((v.get("conditionText") for v in [self.base, *self.versions] if v["id"] == vid), None),
                 "source": next((v.get("sourceType") for v in [self.base, *self.versions] if v["id"] == vid), None)}
                for vid, n in sorted(self.used.items())
            ],
        }
        if self.skipped:
            out["notJudged"] = {phase: int(round(n * step_min)) for phase, n in self.skipped.items()}
        sources = {p["source"] for p in self.phases.values() if p}
        if sources:
            out["phaseSource"] = "、".join(sorted(sources))
        return out

    def note(self, step_min: float) -> str:
        s = self.summary(step_min)
        parts = []
        if s["phaseFiltered"]:
            parts.append(f"限值 {self.limit.get('id')} 只在「{self.mode}」对应的阶段内判断（阶段来源 {s.get('phaseSource')}）")
            if s.get("notJudged"):
                parts.append("不在适用阶段、未判断：" + "、".join(f"{k} {v} 分钟" for k, v in s["notJudged"].items()))
        elif self.mode:
            parts.append(f"测点所属设备未定义工艺阶段，未按「{self.mode}」过滤阶段")
        used = s["versionsUsed"]
        if len(used) > 1 or (used and not used[0]["versionId"].endswith("-V0")):
            parts.append("按当时生效的限值版本判断：" + "、".join(f"{u['versionId']}（{u['condition']}，{u['minutes']} 分钟）" for u in used))
        return "；".join(parts) + ("。" if parts else "")


async def _unit_phases(api: Any, unit: str, start_ms: int, end_ms: int) -> dict[str, Any] | None:
    try:
        got = await unit_batches(api, unit, start_ms, end_ms)
    except (BatchWindowError, ToolApiError):
        return None
    segs = []
    for b in got["items"]:
        for p in b.get("phases") or []:
            segs.append({"phase": p["phase"], "start": p["startTime"], "end": p.get("endTime"),
                         "limitMode": p.get("limitMode") or "", "count": b.get("enzymeBatchCount")})
    segs.sort(key=lambda s: s["start"])
    return {"starts": [s["start"] for s in segs], "segs": segs, "source": got["source"]}


async def build_timeline(api: Any, limit: dict[str, Any] | None, units: list[str | None], start_ms: int, end_ms: int) -> LimitTimeline | None:
    """限值 + 测点所属设备 → LimitTimeline。没有限值返回 None；版本接口不可用时只用 V0。"""
    if not limit or not limit.get("id"):
        return None
    try:
        data = await api.get_json(f"/api/ontology/process-limits/{quote(limit['id'])}/versions")
        versions = data.get("items") or []
    except ToolApiError:
        versions = []
    phases: dict[str, dict[str, Any] | None] = {}
    for unit in sorted({u for u in units if u}):
        phases[unit] = await _unit_phases(api, unit, start_ms, end_ms) if limit.get("operatingMode") else None
    return LimitTimeline(limit, versions, phases)


__all__ = ["LimitTimeline", "build_timeline"]
