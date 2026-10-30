"""计算方法：液位差消耗量 / 加料速率。

适用对象（只看本体结构）：
- 对象本身是液位量（名称含"液位"且有测点）——液位下降量就是从罐里出去的量；
- 或对象是由液位算出来的派生量：本体里有"某液位量 →负向影响→ 它"的关系，且它的描述或该关系的
  机理说明里提到液位（如「氨水累计加量」：描述"由计量罐液位差计算"，关系"计量罐液位下降量即加氨量"）。

算法：
- 取液位量全部测点在时间窗内的等间隔历史值；
- 逐点跟踪液位，只累计"下降"作为消耗/加出量，"上升"视为补液单独累计，不抵扣消耗；
- 用死区过滤仪表抖动：相对上一个锚点变化不超过死区的不计（死区 = 该表时间窗内量程的 DEADBAND_RATIO）；
- 平均速率 = 消耗量 / 时间窗长度；近期速率 = 时间窗最后 RECENT_FRACTION 段内的消耗量 / 该段时长。
液位测点单位是体积（L、m3）时结果就是体积速率；是高度或百分比时只能给出液位下降速率，需罐体截面数据才能换算。
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from ..analysis_tools import (
    TIME_FMT,
    _SIGN_LABEL,
    _SIMULATED_TAIL,
    _history,
    _now,
    _parse_time,
    _r,
    _source_text,
    _target_view,
)
from .base import CalcContext, CalcMethod, CalcSource, register

LEVEL_WORD = "液位"
DEADBAND_RATIO = 0.01  # 死区：该表时间窗内量程的 1%，现场按仪表精度标定
DEFAULT_WINDOW_MINUTES = 60  # "当前一段时间"默认看最近 1 小时
TARGET_SAMPLES = 240
RECENT_FRACTION = 0.25
VOLUME_UNITS = {"L", "l", "升", "m3", "m³", "立方", "m^3"}


async def detect(api: Any, entity: dict[str, Any], detail: dict[str, Any]) -> CalcSource | None:
    name = entity.get("name") or detail.get("name") or ""
    if LEVEL_WORD in name and (detail.get("tagCount") or entity.get("tagCount")):
        return CalcSource(
            method="level_consumption",
            source={"id": entity["id"], "name": name},
            derived=None,
            basis=f"「{name}」本身是液位量：液位下降量即从罐内出去的量，上升为补液。",
        )
    description = detail.get("description") or entity.get("description") or ""
    for rel in detail.get("incomingRelations") or []:
        subject = rel.get("subject") or {}
        subject_name = subject.get("entity") or rel.get("subjectEntity") or ""
        if not str(subject.get("id", "")).startswith("robj-") or LEVEL_WORD not in subject_name:
            continue
        if rel.get("predicate") != "负向影响":
            continue
        mechanism = rel.get("domainDescription") or ""
        if LEVEL_WORD not in description + mechanism:
            continue
        return CalcSource(
            method="level_consumption",
            source={"id": subject["id"], "name": subject_name},
            derived={"id": entity["id"], "name": name},
            basis=(
                f"本体记载 {subject_name} →{_SIGN_LABEL[-1]}→ {name}（{mechanism}）；"
                f"「{name}」描述：{description or '无'}；来源 {_source_text(rel)}"
            ),
        )
    return None


def level_movements(values: list[float], deadband: float) -> dict[str, Any]:
    """按死区跟踪液位：返回累计下降量、累计上升量、补液（上升段）次数。"""
    anchor = values[0]
    dropped = risen = 0.0
    refills = 0
    rising = False
    for value in values[1:]:
        if value < anchor - deadband:
            dropped += anchor - value
            anchor = value
            rising = False
        elif value > anchor + deadband:
            if not rising:
                refills += 1
                rising = True
            risen += value - anchor
            anchor = value
    return {"dropped": dropped, "risen": risen, "refills": refills}


def _window(arguments: dict[str, Any]) -> tuple[str, str, int, float]:
    end = _parse_time(arguments.get("endTime"), _now())
    start = _parse_time(arguments.get("startTime"), end - timedelta(minutes=DEFAULT_WINDOW_MINUTES))
    span_ms = int((end - start).total_seconds() * 1000)
    interval = max(60_000, math.ceil(span_ms / TARGET_SAMPLES / 60_000) * 60_000)
    return start.strftime(TIME_FMT), end.strftime(TIME_FMT), interval, span_ms / 60_000


def _rate_text(amount: float, minutes: float, unit: str) -> str:
    if minutes <= 0:
        return "-"
    per_min = amount / minutes
    return f"{_r(per_min, 3)} {unit}/min（{_r(per_min * 60, 2)} {unit}/h）"


async def run(ctx: CalcContext) -> dict[str, Any]:
    start, end, interval, span_min = _window(ctx.arguments)
    hist = await _history(ctx.api, ctx.source.source["id"], start, end, interval, keyword=ctx.arguments.get("focus"), limit=50)
    title = "液位差消耗量 / 加料速率"
    base: dict[str, Any] = {
        "analysisType": f"计算：{title}",
        "target": _target_view(ctx.target),
        "source": ctx.source.source["name"],
        "basis": ctx.source.basis,
        "window": {"start": start, "end": end, "minutes": int(round(span_min)), "intervalMinutes": interval // 60_000},
    }
    if not hist["tags"]:
        return {**base, "conclusion": f"「{ctx.source.source['name']}」在时间窗内没有可取历史值的现场测点，无法计算。"}

    recent_from = _parse_time(end, _now()).timestamp() * 1000 - span_min * RECENT_FRACTION * 60_000
    rows, units = [], set()
    total_dropped = total_risen = total_recent = 0.0
    for tag in hist["tags"]:
        times = sorted(tag["series"])
        values = [tag["series"][t] for t in times]
        deadband = max(values) - min(values)
        deadband = deadband * DEADBAND_RATIO if deadband > 0 else 0.0
        whole = level_movements(values, deadband)
        recent_values = [tag["series"][t] for t in times if t >= recent_from]
        recent = level_movements(recent_values, deadband) if len(recent_values) > 1 else {"dropped": 0.0}
        unit = tag.get("unit") or ""
        units.add(unit)
        total_dropped += whole["dropped"]
        total_risen += whole["risen"]
        total_recent += recent["dropped"]
        # 逐表只给数字，单位统一写在顶层，表多时也压得进上下文预算
        rows.append(
            {
                "tag": tag["tag"],
                "desc": tag["desc"],
                "startEnd": [_r(values[0]), _r(values[-1])],
                "consumed": _r(whole["dropped"]),
                "refilled": _r(whole["risen"]),
                "refills": whole["refills"],
                "perMin": _r(whole["dropped"] / span_min, 3),
                "recentPerMin": _r(recent["dropped"] / (span_min * RECENT_FRACTION), 3),
            }
        )

    unit = units.pop() if len(units) == 1 else None
    is_volume = unit in VOLUME_UNITS
    what = (ctx.source.derived or {}).get("name") or f"{ctx.source.source['name']}下降量"
    if unit is not None:
        conclusion = (
            f"按「{ctx.source.source['name']}」{len(rows)} 支表计算（{start[5:16]}~{end[5:16]}，{int(round(span_min))} 分钟）："
            f"{what}合计 {_r(total_dropped)} {unit}，平均速率 {_rate_text(total_dropped, span_min, unit)}，"
            f"最近 {int(round(span_min * RECENT_FRACTION))} 分钟速率 {_rate_text(total_recent, span_min * RECENT_FRACTION, unit)}；"
            f"期间补液合计 {_r(total_risen)} {unit}（已从消耗量中排除）。"
        )
        if not is_volume:
            conclusion += f"液位单位是 {unit or '未标注'}，以上是液位下降速率，换算成体积需要罐体截面数据。"
    else:
        conclusion = f"按「{ctx.source.source['name']}」{len(rows)} 支表分别计算；各表单位不一致（{'、'.join(sorted(u or '未标注' for u in units))}），不做合计。"
    if hist["simulated"]:
        conclusion += _SIMULATED_TAIL

    if unit is None:
        for row, tag in zip(rows, hist["tags"]):
            row["unit"] = tag.get("unit") or ""
    result = {
        **base,
        "unit": unit,
        "byTagFields": "startEnd=[窗起液位, 窗末液位]；consumed=消耗/加出量；refilled=补液量；refills=补液次数；perMin / recentPerMin=平均 / 近期速率（单位/分钟）",
        "total": (
            {
                "consumed": _r(total_dropped),
                "refilled": _r(total_risen),
                "avgRate": _rate_text(total_dropped, span_min, unit),
                "recentRate": _rate_text(total_recent, span_min * RECENT_FRACTION, unit),
            }
            if unit is not None
            else None
        ),
        "byTag": rows,
        "conclusion": conclusion,
        "method": (
            f"只累计液位下降段作为消耗/加出量，上升段视为补液、单独统计不抵扣；死区为各表时间窗内量程的 {DEADBAND_RATIO:.0%}，"
            f"用于过滤仪表抖动；采样间隔 {interval // 60_000} 分钟。未指定时间段时默认最近 {DEFAULT_WINDOW_MINUTES} 分钟。"
        ),
        "next": "数值已由程序算好，照实转述并写明时间段与口径；不要自己用首末液位相减重算（补液会算错）。",
    }
    return {k: v for k, v in result.items() if v is not None}


register(
    CalcMethod(
        key="level_consumption",
        title="液位差消耗量 / 加料速率",
        summary="液位量本身，或本体写明由液位差算出的量（如加料量、消耗量）：算时间窗内的消耗/加出量与平均、近期速率，补液段单独扣除",
        detect=detect,
        run=run,
    )
)
