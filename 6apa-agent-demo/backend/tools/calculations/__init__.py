"""计算模块：派生量计算的统一入口 calculate_quantity。

用户问"某某速度/速率/累计量/消耗量能不能算、是多少"时，这个量往往没有直接测点，
而是由别的测点按本体里写明的方法算出来的。模型只负责把用户说法传进来，
"用哪种算法、从哪个对象取数、怎么算"全部由程序按本体结构决定并完成计算。

新增一种计算见 base.py 的说明：新建模块 → register(CalcMethod(...)) → 在下面 import。
"""

from __future__ import annotations

import re
from typing import Any

from ..analysis_tools import (
    _QUANTITY_TYPES,
    AnalysisInputError,
    _clarify,
    _resolve_entity,
    _target_view,
)
from ..registry import ToolParameter, ToolSpec
from .base import CALC_METHODS, CalcContext, CalcMethod, CalcSource, register

# 在这里 import 各计算方法模块，完成登记（新增方法模块时加到这一行和 _METHOD_MODULES 里）
from . import level_consumption

_METHOD_MODULES = (level_consumption,)

# 用户常把"要算的量"说成"X 的速度 / 速率 / 用量"，解析对象前先把这些说法剥掉
_RATE_WORDS = (
    "滴加速度", "滴加速率", "加料速度", "加料速率", "加入速度", "进料速度", "消耗速度", "消耗速率",
    "下降速度", "下降速率", "消耗量", "用量", "加入量", "速度", "速率",
)
MAX_PROBE = 40


def _strip_rate_words(text: str) -> str:
    core = re.sub(r"\s+", "", text or "")
    changed = True
    while changed:
        changed = False
        for word in _RATE_WORDS:
            if core.endswith(word) and len(core) > len(word):
                core = core[: -len(word)]
                changed = True
        if core.endswith("的"):
            core, changed = core[:-1], True
    return core


async def _detect(api: Any, entity: dict[str, Any], methods: list[CalcMethod]) -> tuple[CalcMethod, CalcSource] | None:
    detail = await api.get_json(f"/api/ontology/relation-entities/{entity['id']}")
    for method in methods:
        source = await method.detect(api, entity, detail)
        if source:
            return method, source
    return None


async def _pick_target(api: Any, raw: str, methods: list[CalcMethod]) -> tuple[dict[str, Any], CalcMethod, CalcSource] | dict[str, Any]:
    """解析要算的对象并找到适用的算法。

    1. 用户说法能唯一落到某个本体对象上：就是它；
    2. 否则剥掉"速度/速率/用量"等说法，按核心词找候选工艺量，只保留有算法适用的；
       其中"派生量"（由别的量算出来的，如"氨水累计加量"）只有一个时直接采用，
       否则候选里只有一个适用时采用；仍然多个就返回候选让模型 / 用户选。
    返回 (对象, 算法, 取数依据)，或给模型看的结果字典（候选 / 无法计算）。
    """
    try:
        entity = await _resolve_entity(api, raw)
    except AnalysisInputError as exc:
        core = _strip_rate_words(raw)
        found = (await api.get_json("/api/ontology/relation-entities", {"keyword": core, "limit": 100})).get("items") if core else []
        pool = [e for e in found or [] if e.get("type") in _QUANTITY_TYPES][:MAX_PROBE]
        if not pool:
            return _clarify(exc)
        hits = []
        for candidate in pool:
            matched = await _detect(api, candidate, methods)
            if matched:
                hits.append((candidate, *matched))
        derived = [h for h in hits if h[2].derived]
        chosen = derived if len(derived) == 1 else hits if len(hits) == 1 else None
        if chosen:
            entity, method, source = chosen[0]
            entity = {
                "id": entity["id"],
                "name": entity["name"],
                "type": entity.get("type"),
                "matchedBy": f"「{raw}」按核心词「{core}」找到可计算的「{entity['name']}」",
            }
            return entity, method, source
        if hits:
            return {
                "status": "needs_clarification",
                "message": f"「{raw}」对应多个可以计算的量，请选一个，用它的 id 或完整名称重新调用。",
                "candidates": [
                    {"id": e["id"], "name": e["name"], "method": m.title, "source": s.source["name"]} for e, m, s in hits[:10]
                ],
            }
        return _no_method(raw, [{"id": e["id"], "name": e["name"], "type": e.get("type")} for e in pool[:8]])

    matched = await _detect(api, entity, methods)
    if not matched:
        return _no_method(raw, [{"id": entity["id"], "name": entity["name"], "type": entity.get("type")}])
    return entity, *matched


def _no_method(raw: str, objects: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "no_method",
        "message": (
            f"「{raw}」目前没有适用的计算方法：本体里没有写明它由哪些测点、按什么方法算出，"
            "或计算模块还没有实现对应算法。请如实告诉用户算不了以及缺什么，不要自己估算或编造数值。"
        ),
        "objects": objects,
        "availableMethods": [{"key": m.key, "title": m.title, "covers": m.summary} for m in CALC_METHODS.values()],
    }


async def calculate_quantity(registry: Any, arguments: dict[str, Any], api: Any) -> dict[str, Any]:
    wanted = arguments.get("method")
    methods = [CALC_METHODS[wanted]] if wanted in CALC_METHODS else list(CALC_METHODS.values())
    picked = await _pick_target(api, arguments.get("target", ""), methods)
    if isinstance(picked, dict):
        return picked
    entity, method, source = picked
    result = await method.run(CalcContext(api=api, target=entity, source=source, arguments=arguments))
    result.setdefault("target", _target_view(entity))
    return result


def _tool_description() -> str:
    lines = "；".join(f"{m.key}（{m.title}）：{m.summary}" for m in CALC_METHODS.values())
    return (
        "派生量计算（确定性计算，优先使用）。用户问'某某速度/速率/累计量/消耗量/加料量能不能算出来、是多少'时直接调用，"
        "不要自己取历史值手算，也不要先反问用户。程序会按本体写明的关系判断这个量由哪个测点、用哪种方法算，"
        "取全部相关测点的历史值完成计算，并写明计算口径与本体依据；算不了时返回 status=no_method，此时如实说明算不了、缺什么。"
        f"目前支持的计算方法：{lines}。"
        "target 直接传用户说的量（如 氨水滴加速度、氨水累计加量、氨水计量罐液位）。"
    )


CALCULATION_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="calculate_quantity",
        description=_tool_description(),
        path="",
        parameters=(
            ToolParameter("target", "string", "要计算的量，直接传用户的说法，如 氨水滴加速度。", required=True),
            ToolParameter("method", "string", "指定计算方法；不填由程序按本体自动判断。", enum=tuple(CALC_METHODS)),
            ToolParameter("startTime", "string", "时间段开始，yyyy-MM-dd HH:mm:ss（东八区），按【当前时间】换算；用户说'当前一段时间'且没给范围时不填，由程序取默认时间窗。"),
            ToolParameter("endTime", "string", "时间段结束，格式同上，默认当前时刻。"),
            ToolParameter("focus", "string", "只算某一支表，如 LT_1302A。"),
        ),
        group="analysis",
        summary="派生量计算：按本体写明的方法算速度、消耗量、累计量",
        returns="target、source（取数对象）、basis（本体依据）、window、unit、total、byTag[]、conclusion、method；算不了时 status=no_method。",
        handler=calculate_quantity,
    )
]

__all__ = ["CALCULATION_TOOLS", "CALC_METHODS", "CalcContext", "CalcMethod", "CalcSource", "register", "calculate_quantity"]
