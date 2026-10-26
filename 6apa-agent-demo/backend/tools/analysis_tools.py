"""确定性分析工具：按问题类型、基于本体的通用算法。

为什么要有这一层
----------------
工艺分析类问题（异常溯源、影响验证、关系结构统计）的推理步骤是确定的：
查限值 → 取历史确认异常 → 沿因果图上推 → 落测点 → 同期对比 → 分层结论。
让模型一步步规划要 6~10 次模型调用、每次重发上万 token 的上下文，
本地模型上要一两分钟，还会出现计数算错、看错正负向、空查询反复重试这类问题。

所以这些步骤交给程序：模型只负责把用户随意的说法翻译成确定的入参
（对象、现象、时间窗），调用一次工具拿到完整证据链，再把结论写成人话。

通用性
------
算法只依赖本体的图结构与数据接口，不认识任何具体设备、参数或位号：
换一个工艺量、换一个工段，只要本体里登记了因果关系 / 限值 / 测点就能直接跑；
新增设备只需要补本体数据，不用改这里的代码。
分不同问题类型各写一套模板（本文件三类），类型之外的问题仍由模型自主规划。

判定口径
--------
相关系数阈值、采样点数、上推层数等判定口径集中在下面的常量里，
属于需要工艺人员标定的参数；输出里会写明这是程序按固定口径得出的统计判断，
不等于因果证明。
"""

from __future__ import annotations

import math
import re
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from typing import Any

from .registry import ToolParameter, ToolSpec

# ---------------------------------------------------------------- 判定口径

TZ = timezone(timedelta(hours=8))  # 本体服务与历史库都按东八区解释时间文本
TIME_FMT = "%Y-%m-%d %H:%M:%S"

CORR_SUPPORT = 0.5  # 同向相关达到此值：数据支持
CORR_WEAK = 0.3  # 同向相关达到此值：弱支持；反向达到此值：与本体方向相反
MIN_SAMPLES = 8  # 对齐后的样本少于此数不做统计判断
TARGET_SAMPLES = 96  # 时间窗内每个测点取多少个等间隔样本
MAX_LAG_STEPS = 6  # 原因领先结果最多看几个采样间隔
ANOMALY_QUANTILE = 0.2  # 没有限值时，取最偏的 20% 样本当"异常期"
DEFAULT_DEPTH = 2
MAX_DEPTH = 3
MAX_CANDIDATES = 8
MAX_TARGET_TAGS = 20
MAX_CAUSE_TAGS = 5

_SIGN_BY_PREDICATE = {"正向影响": 1, "负向影响": -1}
_SIGN_LABEL = {1: "正向", -1: "负向", 0: "未标注"}
_CAUSAL_CATEGORIES = {"影响关系", "质量关系"}
_CONTROL_CATEGORY = "控制关系"
_ACTUATOR_PREDICATE = "影响"  # 控制关系里"执行机构 → 被控量"的谓词
_FEEDBACK_PREDICATE = "反馈给"  # 控制关系里"被控量 → 控制器"的谓词
_SYMPTOMS = ("偏高", "偏低", "波动", "异常")
_TAG_RE = re.compile(r"^[A-Za-z]{1,6}[_-]?\d[\w.-]*$")


class AnalysisInputError(ValueError):
    """入参无法落到本体对象上。转成结构化结果回给模型，让它换个说法或问用户。"""

    def __init__(self, message: str, candidates: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.candidates = candidates or []


# ================================================================ 公共步骤


def _now() -> datetime:
    return datetime.now(TZ)


def _parse_time(text: str | None, default: datetime) -> datetime:
    if not text:
        return default
    raw = str(text).strip()
    if raw.isdigit():
        return datetime.fromtimestamp(int(raw) / 1000, TZ)
    for fmt in (TIME_FMT, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    raise AnalysisInputError(f"时间格式无法识别：{raw}。请用 yyyy-MM-dd HH:mm:ss（东八区）。")


def _window(arguments: dict[str, Any]) -> tuple[str, str, int]:
    """返回 (开始, 结束, 采样间隔毫秒)。不给时间默认看最近 24 小时。"""
    end = _parse_time(arguments.get("endTime"), _now())
    start = _parse_time(arguments.get("startTime"), end - timedelta(hours=24))
    if start >= end:
        raise AnalysisInputError("startTime 必须早于 endTime。")
    span_ms = int((end - start).total_seconds() * 1000)
    interval = max(60_000, math.ceil(span_ms / TARGET_SAMPLES / 60_000) * 60_000)
    return start.strftime(TIME_FMT), end.strftime(TIME_FMT), interval


def _fmt_t(t_ms: int) -> str:
    return datetime.fromtimestamp(t_ms / 1000, TZ).strftime("%m-%d %H:%M")


def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _source_text(rel: dict[str, Any]) -> str:
    src = rel.get("source") or {}
    if not src:
        return ""
    return f"{src.get('file', '')} {src.get('sheet', '')} 第{src.get('row', '?')}行".strip()


def _bigrams(text: str) -> set[str]:
    text = re.sub(r"\s+", "", text or "")
    return {text[i : i + 2] for i in range(len(text) - 1)} or ({text} if text else set())


async def _resolve_entity(api: Any, raw: str) -> dict[str, Any]:
    """把用户说法落到关系对象（robj-）上。

    依次尝试：robj- ID → 关系对象名称 → DCS 位号 / 测点描述（经"绑定测点"关系反查）。
    都不中时按字面相似度给出候选，**不自动挑**——让模型或用户来选。
    """
    text = (raw or "").strip()
    if not text:
        raise AnalysisInputError("缺少分析对象。")

    if text.startswith("robj-"):
        detail = await api.get_json(f"/api/ontology/relation-entities/{text}")
        return {"id": detail["id"], "name": detail["name"], "type": detail.get("type"), "focusTag": None}

    found = await api.get_json("/api/ontology/relation-entities", {"keyword": text, "limit": 20})
    items = found.get("items") or []
    compact_text = re.sub(r"\s+", "", text)
    if not items and compact_text != text:
        # "反应体系 pH" 这类多打了空格的说法
        found = await api.get_json("/api/ontology/relation-entities", {"keyword": compact_text, "limit": 20})
        items = found.get("items") or []
    exact = [e for e in items if re.sub(r"\s+", "", e.get("name") or "") == compact_text]
    if len(exact) == 1 or (len(items) == 1 and not exact):
        pick = exact[0] if exact else items[0]
        return {"id": pick["id"], "name": pick["name"], "type": pick.get("type"), "focusTag": None}

    # 位号或测点描述：找到测点，再沿"绑定测点"关系找到它代表的工艺量
    # 只在位号 / 描述精确相等，或关键词只命中一个测点时才采用，"温度"这种宽泛说法不走这条路
    tags = await api.get_json("/api/ontology/tags", {"keyword": text, "limit": 5})
    tag_items = tags.get("items") or []
    exact_tags = [t for t in tag_items if text in (t.get("name"), t.get("description"), t.get("rawDescription"))]
    if not exact_tags and (tags.get("total") or len(tag_items)) == 1:
        exact_tags = tag_items
    for tag in exact_tags:
        binding = await api.get_json(
            "/api/ontology/relations",
            {"keyword": tag.get("name"), "category": "测点绑定关系", "limit": 5},
        )
        for rel in binding.get("items") or []:
            subject = rel.get("subject") or {}
            if subject.get("id", "").startswith("robj-"):
                return {
                    "id": subject["id"],
                    "name": subject.get("entity") or rel.get("subjectEntity"),
                    "type": subject.get("type"),
                    "focusTag": tag.get("name"),
                }
        if _TAG_RE.match(text):
            break

    pool = items
    if not pool:
        everything = await api.get_json("/api/ontology/relation-entities", {})
        wanted = _bigrams(text)
        scored = []
        for entity in everything.get("items") or []:
            score = len(wanted & _bigrams(entity.get("name") or "")) * 2 + len(
                wanted & _bigrams(entity.get("belongsTo") or "")
            )
            if score and entity.get("tagCount"):
                score += 1  # 有测点的对象更可能是用户想分析的那个
            if score:
                scored.append((score, entity.get("relationCount") or 0, entity))
        scored.sort(key=lambda item: (-item[0], -item[1]))
        pool = [entity for _, _, entity in scored[:8]]
    candidates = [
        {"id": e["id"], "name": e["name"], "type": e.get("type"), "belongsTo": e.get("belongsTo"), "tagCount": e.get("tagCount")}
        for e in pool[:8]
    ]
    raise AnalysisInputError(f"「{text}」没有唯一对应的本体对象，请从候选里选一个，用它的 id 或完整名称重新调用。", candidates)


async def _incoming_causes(api: Any, entity_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    """一个对象的直接原因：带方向的影响/质量关系 + 控制回路里的执行机构。

    第二个返回值是它所在的控制回路控制器（"反馈给"关系），用于提醒补偿效应。
    """
    detail = await api.get_json(f"/api/ontology/relation-entities/{entity_id}")
    causes: list[dict[str, Any]] = []
    for rel in detail.get("incomingRelations") or []:
        subject = rel.get("subject") or {}
        if not str(subject.get("id", "")).startswith("robj-"):
            continue
        category, predicate = rel.get("category"), rel.get("predicate")
        if category in _CAUSAL_CATEGORIES:
            kind = "影响"
        elif category == _CONTROL_CATEGORY and predicate == _ACTUATOR_PREDICATE:
            kind = "控制执行机构"
        else:
            continue
        causes.append(
            {
                "id": subject["id"],
                "name": subject.get("entity") or rel.get("subjectEntity"),
                "type": subject.get("type"),
                "sign": _SIGN_BY_PREDICATE.get(predicate, 0),
                "predicate": predicate,
                "kind": kind,
                "mechanism": rel.get("domainDescription") or "",
                "source": _source_text(rel),
                "confidence": rel.get("confidence"),
            }
        )
    controllers = [
        (rel.get("object") or {}).get("entity") or rel.get("objectEntity")
        for rel in detail.get("outgoingRelations") or []
        if rel.get("category") == _CONTROL_CATEGORY and rel.get("predicate") == _FEEDBACK_PREDICATE
    ]
    return causes, [c for c in controllers if c]


async def _cause_tree(api: Any, root: dict[str, Any], depth: int) -> tuple[list[dict[str, Any]], list[str]]:
    """沿因果关系往上游做广度优先遍历，路径方向按正负号相乘传播。

    控制执行机构不再继续往上推（再往上是控制器，属于控制回路本身，不是扰动来源）。
    """
    found: list[dict[str, Any]] = []
    controllers: list[str] = []
    seen = {root["id"]}
    # 队列元素：(对象 ID, 层级, 到根的累计方向, 到根的路径文本)
    queue: deque[tuple[str, int, int, str]] = deque([(root["id"], 0, 1, root["name"])])
    while queue:
        node_id, level, path_sign, path = queue.popleft()
        if level >= depth:
            continue
        causes, loop = await _incoming_causes(api, node_id)
        if level == 0:
            controllers = loop
        for cause in causes:
            if cause["id"] in seen:
                continue
            seen.add(cause["id"])
            # 任一环节方向未标注，整条路径的方向就无法确定
            sign = path_sign * cause["sign"]
            arrow = _SIGN_LABEL[cause["sign"]] if cause["kind"] == "影响" else "控制"
            item = {**cause, "level": level + 1, "pathSign": sign, "path": f"{cause['name']} →{arrow}→ {path}"}
            found.append(item)
            if cause["kind"] == "影响":
                queue.append((cause["id"], level + 1, sign, item["path"]))
    found.sort(key=lambda c: (c["level"], -abs(c["pathSign"])))
    return found, controllers


async def _history(
    api: Any, entity_id: str, start: str, end: str, interval: int, *, keyword: str | None, limit: int
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "startTime": start,
        "endTime": end,
        "interval": interval,
        "sampleMode": "interpolated",
        "limit": limit,
    }
    if keyword:
        params["keyword"] = keyword
    data = await api.get_json(f"/api/ontology/{entity_id}/history", params)
    tags = []
    for item in data.get("items") or []:
        series = {
            int(p["t"]): float(p["v"])
            for p in item.get("values") or []
            if p.get("v") is not None and p.get("q", 1) == 1
        }
        if series:
            tags.append(
                {
                    "tag": item.get("tagName"),
                    "desc": item.get("description"),
                    "unit": item.get("unit"),
                    "series": series,
                }
            )
    return {"tags": tags, "total": data.get("total") or 0, "simulated": bool((data.get("dataSource") or {}).get("simulated"))}


async def _limit_for(api: Any, entity: dict[str, Any]) -> dict[str, Any] | None:
    """只认 appliesTo 就是该对象本身、且已填数值的限值；绝不借用别的对象的限值。"""
    data = await api.get_json(f"/api/ontology/{entity['id']}/limits")
    for item in data.get("items") or []:
        if item.get("appliesTo") == entity["name"] and item.get("hasValues"):
            return item
    return None


# ================================================================ 统计


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: list[float]) -> float:
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < MIN_SAMPLES or len(xs) != len(ys):
        return None
    sx, sy = _std(xs), _std(ys)
    if sx == 0 or sy == 0:
        return None
    mx, my = _mean(xs), _mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) * sx * sy)


def zscore_average(series_list: list[dict[int, float]]) -> dict[int, float]:
    """同一工艺量的多个测点（如 11 台罐的温度）先各自标准化再取平均，避免挑最好看的那支。"""
    common = set.intersection(*(set(s) for s in series_list)) if series_list else set()
    if not common:
        return {}
    normed = []
    for s in series_list:
        values = [s[t] for t in common]
        m, sd = _mean(values), _std(values) or 1.0
        normed.append({t: (s[t] - m) / sd for t in common})
    return {t: _mean([n[t] for n in normed]) for t in sorted(common)}


def lagged_correlation(cause: dict[int, float], effect: dict[int, float], sign: int) -> dict[str, Any]:
    """原因领先结果 0..MAX_LAG_STEPS 个采样间隔，取与预期方向最一致的那个滞后。

    sign=0（本体未标方向）时取绝对值最大的。
    """
    times = sorted(set(cause) & set(effect))
    xs = [cause[t] for t in times]
    ys = [effect[t] for t in times]
    step_ms = (times[1] - times[0]) if len(times) > 1 else 0
    best: tuple[float, int, float] | None = None  # (排序键, 滞后步数, 相关系数)
    for lag in range(0, min(MAX_LAG_STEPS, max(0, len(times) - MIN_SAMPLES)) + 1):
        corr = pearson(xs[: len(xs) - lag] if lag else xs, ys[lag:])
        if corr is None:
            continue
        key = corr * sign if sign else abs(corr)
        if best is None or key > best[0]:
            best = (key, lag, corr)
    corr0 = pearson(xs, ys)
    return {
        "n": len(times),
        "corr": _r(best[2]) if best else None,
        "leadMinutes": int(best[1] * step_ms / 60_000) if best else None,
        "corrNoLag": _r(corr0),
    }


def verdict(sign: int, corr: float | None, n: int) -> str:
    if corr is None or n < MIN_SAMPLES:
        return "数据不足，无法判断"
    if sign == 0:
        strength = abs(corr)
        if strength >= CORR_SUPPORT:
            return "同期强相关（本体未标方向）"
        if strength >= CORR_WEAK:
            return "同期弱相关（本体未标方向）"
        return "未发现支持证据"
    signed = corr * sign
    if signed >= CORR_SUPPORT:
        return "数据支持"
    if signed >= CORR_WEAK:
        return "弱支持"
    if signed <= -CORR_WEAK:
        return "与本体记载方向相反"
    return "未发现支持证据"


_VERDICT_RANK = {
    "数据支持": 0,
    "同期强相关（本体未标方向）": 1,
    "弱支持": 2,
    "同期弱相关（本体未标方向）": 3,
    "未发现支持证据": 4,
    "与本体记载方向相反": 5,
    "数据不足，无法判断": 6,
    "无测点，无法用数据验证": 7,
}


def assess_tag(series: dict[int, float], limit: dict[str, Any] | None) -> dict[str, Any]:
    """单个测点在时间窗内的表现；有限值时逐档统计越限样本数。"""
    times = sorted(series)
    values = [series[t] for t in times]
    out: dict[str, Any] = {"max": _r(max(values)), "min": _r(min(values)), "avg": _r(_mean(values))}
    if not limit:
        return out
    bands = (
        ("aboveHighHigh", "highHigh", lambda v, b: v > b),
        ("aboveHigh", "high", lambda v, b: v > b),
        ("aboveNormal", "normalHigh", lambda v, b: v > b),
        ("belowNormal", "normalLow", lambda v, b: v < b),
        ("belowLow", "low", lambda v, b: v < b),
        ("belowLowLow", "lowLow", lambda v, b: v < b),
    )
    for key, field, test in bands:
        bound = limit.get(field)
        count = sum(1 for v in values if bound is not None and test(v, bound))
        if count:
            out[key] = count
    lo, hi = limit.get("normalLow"), limit.get("normalHigh")
    abnormal = [t for t, v in zip(times, values) if (hi is not None and v > hi) or (lo is not None and v < lo)]
    if abnormal:
        out["firstOut"] = _fmt_t(abnormal[0])
        out["lastOut"] = _fmt_t(abnormal[-1])
    return out


def anomaly_mask(series: dict[int, float], limit: dict[str, Any] | None, direction: int) -> set[int]:
    """异常期：有限值时取越出正常区间（按方向）的时刻；没有限值时取最偏的 20%。"""
    if direction == 0:
        return set()
    if limit and (limit.get("normalHigh") is not None or limit.get("normalLow") is not None):
        hi, lo = limit.get("normalHigh"), limit.get("normalLow")
        if direction > 0 and hi is not None:
            return {t for t, v in series.items() if v > hi}
        if direction < 0 and lo is not None:
            return {t for t, v in series.items() if v < lo}
        return set()
    ordered = sorted(series.items(), key=lambda kv: kv[1], reverse=direction > 0)
    return {t for t, _ in ordered[: max(1, int(len(ordered) * ANOMALY_QUANTILE))]}


def shift_during(cause: dict[int, float], mask: set[int]) -> float | None:
    """异常期内原因的均值相对其余时段偏了多少个标准差。"""
    inside = [v for t, v in cause.items() if t in mask]
    outside = [v for t, v in cause.items() if t not in mask]
    if len(inside) < 2 or len(outside) < 2:
        return None
    sd = _std(list(cause.values()))
    if sd == 0:
        return None
    return _r((_mean(inside) - _mean(outside)) / sd)


# ================================================================ 证据


def _limit_brief(limit: dict[str, Any] | None) -> dict[str, Any] | None:
    if not limit:
        return None
    return {
        "id": limit.get("id"),
        "normal": f"{limit.get('normalLow')}~{limit.get('normalHigh')} {limit.get('unit') or ''}".strip(),
        "low": limit.get("low"),
        "lowLow": limit.get("lowLow"),
        "high": limit.get("high"),
        "highHigh": limit.get("highHigh"),
        "status": limit.get("status"),
        "basis": (limit.get("basis") or "")[:60],
    }


def _judge_target(
    hist: dict[str, Any], limit: dict[str, Any] | None, symptom: str, focus_tag: str | None
) -> dict[str, Any]:
    """确认异常是否成立，并选出用于对比的"关注测点"。"""
    per_tag = []
    for tag in hist["tags"]:
        stats = assess_tag(tag["series"], limit)
        up = stats.get("aboveNormal", 0)
        down = stats.get("belowNormal", 0)
        per_tag.append({"tag": tag["tag"], "desc": tag["desc"], "unit": tag["unit"], "up": up, "down": down, **stats, "_series": tag["series"]})

    if symptom == "偏高":
        direction = 1
    elif symptom == "偏低":
        direction = -1
    else:
        ups = sum(t["up"] for t in per_tag)
        downs = sum(t["down"] for t in per_tag)
        direction = 0 if symptom == "波动" or ups == downs else (1 if ups > downs else -1)

    if focus_tag:
        focus = next((t for t in per_tag if t["tag"] == focus_tag), per_tag[0])
    elif limit:
        # 越限次数相同时，按更严重的档位（高限/高高限、低限/低低限）再比
        def severity(t: dict[str, Any]) -> tuple[int, int, int]:
            up = (t["up"], t.get("aboveHigh", 0), t.get("aboveHighHigh", 0))
            down = (t["down"], t.get("belowLow", 0), t.get("belowLowLow", 0))
            if direction > 0:
                return up
            if direction < 0:
                return down
            return max(up, down)

        focus = max(per_tag, key=severity)
    else:
        def spread(t: dict[str, Any]) -> float:
            if direction > 0:
                return t["max"] - t["avg"]
            if direction < 0:
                return t["avg"] - t["min"]
            return t["max"] - t["min"]

        focus = max(per_tag, key=spread)

    if limit:
        hits = [t for t in per_tag if (t["up"] if direction > 0 else t["down"] if direction < 0 else t["up"] + t["down"])]
        established = "成立" if hits else "不成立（时间窗内未越出正常区间）"
    else:
        hits = []
        established = "无法按限值判定（本体中暂无该对象的工艺限值）"

    shown = sorted(hits, key=lambda t: -(t["up"] + t["down"]))[:5] if hits else [focus]
    public = [{k: v for k, v in t.items() if not k.startswith("_") and k not in ("up", "down")} for t in shown]
    return {
        "established": established,
        "direction": direction,
        "abnormalTagCount": len(hits),
        "tagCount": len(per_tag),
        "tags": public,
        "focus": focus,
    }


async def _evidence(
    api: Any,
    cause: dict[str, Any],
    effect_series: dict[int, float],
    mask: set[int],
    direction: int,
    window: tuple[str, str, int],
) -> dict[str, Any]:
    hist = await _history(api, cause["id"], *window, keyword=None, limit=MAX_CAUSE_TAGS)
    tags = [t["tag"] for t in hist["tags"]]
    if not hist["tags"]:
        return {"tags": [], "verdict": "无测点，无法用数据验证", "simulated": hist["simulated"]}
    merged = zscore_average([t["series"] for t in hist["tags"]])
    stats = lagged_correlation(merged, effect_series, cause["pathSign"])
    out: dict[str, Any] = {
        "tags": tags[:3] + ([f"等{hist['total']}个"] if hist["total"] > 3 else []),
        "corr": stats["corr"],
        "leadMinutes": stats["leadMinutes"],
        "verdict": verdict(cause["pathSign"], stats["corr"], stats["n"]),
        "simulated": hist["simulated"],
    }
    shift = shift_during(merged, mask) if mask else None
    if shift is not None:
        out["shiftSigma"] = shift
        if cause["pathSign"] and direction:
            expected = cause["pathSign"] * direction
            out["shiftMatches"] = (shift * expected) > 0
    return out


def _expectation(path_sign: int, direction: int) -> str:
    if not path_sign:
        return "本体未标方向"
    if not direction:
        return "应与结果同向波动" if path_sign > 0 else "应与结果反向波动"
    return "同期应偏高" if path_sign * direction > 0 else "同期应偏低"


def _method_note(simulated: bool) -> str:
    note = (
        f"以上由程序按固定口径计算：原因领先结果 0~{MAX_LAG_STEPS} 个采样间隔内，"
        f"与本体方向一致的相关系数≥{CORR_SUPPORT} 判为数据支持、≥{CORR_WEAK} 判为弱支持；"
        "多个测点先标准化再平均。这是统计判断，不等于因果证明，判定口径需工艺人员标定。"
    )
    if simulated:
        note += "历史值来自模拟数据服务，不是现场真实读数。"
    return note


# ================================================================ 工具一：异常溯源


async def investigate_process_anomaly(registry: Any, arguments: dict[str, Any], api: Any) -> dict[str, Any]:
    symptom = arguments.get("symptom") or "异常"
    depth = max(1, min(MAX_DEPTH, int(arguments.get("depth") or DEFAULT_DEPTH)))
    try:
        target = await _resolve_entity(api, arguments.get("target", ""))
        window = _window(arguments)
    except AnalysisInputError as exc:
        return _clarify(exc)

    focus_kw = arguments.get("focus") or target.get("focusTag")
    limit = await _limit_for(api, target)
    hist = await _history(api, target["id"], *window, keyword=focus_kw, limit=MAX_TARGET_TAGS)
    if not hist["tags"]:
        # 目标本身测不到：异常无法确认，但本体记载的候选原因仍然有参考价值
        causes, _ = await _cause_tree(api, target, depth)
        return {
            "analysisType": "异常溯源",
            "target": {"id": target["id"], "name": target["name"], "symptom": symptom},
            "window": {"start": window[0], "end": window[1]},
            "status": "no_data",
            "limit": _limit_brief(limit),
            "candidates": [
                {
                    "factor": c["name"],
                    "id": c["id"],
                    "level": c["level"],
                    "path": c["path"],
                    "mechanism": c["mechanism"][:50],
                    "source": c["source"],
                }
                for c in causes[:MAX_CANDIDATES]
            ],
            "conclusion": (
                f"「{target['name']}」在本体中没有可取历史值的现场测点，无法确认异常，也无法做数据对比；"
                f"本体记载的候选原因 {len(causes)} 个，仅能作为排查方向。"
            ),
        }

    judged = _judge_target(hist, limit, symptom, focus_kw if focus_kw and _TAG_RE.match(focus_kw) else None)
    focus = judged.pop("focus")
    mask = anomaly_mask(focus["_series"], limit, judged["direction"])
    causes, controllers = await _cause_tree(api, target, depth)

    candidates = []
    simulated = hist["simulated"]
    for cause in causes[:MAX_CANDIDATES]:
        ev = await _evidence(api, cause, focus["_series"], mask, judged["direction"], window)
        simulated = ev.pop("simulated") or simulated
        candidates.append(
            {
                "factor": cause["name"],
                "id": cause["id"],
                "level": cause["level"],
                "path": cause["path"],
                "relation": cause["kind"] if cause["kind"] != "影响" else f"{cause['predicate']}",
                "mechanism": cause["mechanism"][:50],
                "source": cause["source"],
                "expected": _expectation(cause["pathSign"], judged["direction"]),
                **ev,
            }
        )
    candidates.sort(key=lambda c: (_VERDICT_RANK.get(c["verdict"], 9), c["level"]))

    gaps = [f"{c['factor']}：本体记载有影响，但没有现场测点" for c in candidates if not c["tags"]]
    if not limit:
        gaps.append(f"{target['name']}：本体中暂无工艺限值，无法判定是否越限")
    elif limit.get("status") != "已确认":
        gaps.append(f"限值 {limit.get('id')} 状态为「{limit.get('status')}」，越限结论仅供调查参考")
    if len(causes) > MAX_CANDIDATES:
        gaps.append(f"上推共找到 {len(causes)} 个因素，本次只验证了最近的 {MAX_CANDIDATES} 个")

    supported = [c["factor"] for c in candidates if c["verdict"] in ("数据支持", "弱支持", "同期强相关（本体未标方向）")]
    unverifiable = [c["factor"] for c in candidates if not c["tags"]]
    conclusion = [f"异常{judged['established']}（关注测点 {focus['tag']}）。"]
    if not causes:
        conclusion.append("本体中没有登记影响该对象的因果关系，无法从本体给出候选原因。")
    else:
        conclusion.append(f"本体记载的候选原因 {len(causes)} 个（上推 {depth} 层）。")
        conclusion.append(f"数据支持或弱支持：{'、'.join(supported)}。" if supported else "有测点的因素中未发现数据支持。")
        if unverifiable:
            conclusion.append(f"无测点无法验证：{'、'.join(unverifiable)}。")
    if controllers:
        conclusion.append(
            f"分析对象「{target['name']}」本身处于闭环控制（{'、'.join(controllers)}），"
            "控制器会补偿扰动，各原因在数据上的信号可能被削弱。"
        )

    return {
        "analysisType": "异常溯源",
        "target": {"id": target["id"], "name": target["name"], "symptom": symptom},
        "window": {"start": window[0], "end": window[1], "intervalMinutes": window[2] // 60_000},
        "limit": _limit_brief(limit),
        "anomaly": judged,
        "candidates": candidates,
        "dataGaps": gaps,
        "conclusion": "".join(conclusion),
        "method": _method_note(simulated),
        "next": _NEXT_HINT,
    }


# ================================================================ 工具二：影响验证


async def _find_path(api: Any, cause_id: str, effect: dict[str, Any], depth: int) -> dict[str, Any] | None:
    tree, _ = await _cause_tree(api, effect, depth)
    return next((c for c in tree if c["id"] == cause_id), None)


async def verify_process_influence(registry: Any, arguments: dict[str, Any], api: Any) -> dict[str, Any]:
    try:
        cause = await _resolve_entity(api, arguments.get("cause", ""))
        effect = await _resolve_entity(api, arguments.get("effect", ""))
        window = _window(arguments)
    except AnalysisInputError as exc:
        return _clarify(exc)

    path = await _find_path(api, cause["id"], effect, MAX_DEPTH)
    reverse = None if path else await _find_path(api, effect["id"], cause, MAX_DEPTH)
    sign = path["pathSign"] if path else 0

    limit = await _limit_for(api, effect)
    effect_hist = await _history(api, effect["id"], *window, keyword=arguments.get("focus"), limit=MAX_TARGET_TAGS)
    base = {
        "analysisType": "影响验证",
        "cause": {"id": cause["id"], "name": cause["name"]},
        "effect": {"id": effect["id"], "name": effect["name"]},
        "window": {"start": window[0], "end": window[1], "intervalMinutes": window[2] // 60_000},
        "ontology": (
            {"recorded": True, "path": path["path"], "direction": _SIGN_LABEL[sign], "mechanism": path["mechanism"][:60], "source": path["source"]}
            if path
            else {
                "recorded": False,
                "note": (
                    f"本体记载的是反方向：{reverse['path']}" if reverse else "本体中没有登记这两个量之间的影响路径（上推 3 层内）"
                ),
            }
        ),
        "limit": _limit_brief(limit),
    }
    if not effect_hist["tags"]:
        return {**base, "verdict": "无测点，无法用数据验证", "conclusion": f"「{effect['name']}」没有可取历史值的现场测点。"}

    judged = _judge_target(effect_hist, limit, arguments.get("symptom") or "异常", None)
    focus = judged.pop("focus")
    mask = anomaly_mask(focus["_series"], limit, judged["direction"])
    probe = {"id": cause["id"], "pathSign": sign}
    ev = await _evidence(api, probe, focus["_series"], mask, judged["direction"], window)
    simulated = ev.pop("simulated") or effect_hist["simulated"]

    if not path:
        ev["verdict"] = f"仅统计参考：{ev['verdict']}（本体未记载该影响路径）"
    conclusion = (
        f"本体记载 {path['path']}（{_SIGN_LABEL[sign]}）。" if path else base["ontology"]["note"] + "。"
    ) + f"同期数据对比结论：{ev['verdict']}。"
    return {
        **base,
        "effectAnomaly": judged,
        "evidence": {"expected": _expectation(sign, judged["direction"]), **ev},
        "conclusion": conclusion,
        "method": _method_note(simulated),
        "next": _NEXT_HINT,
    }


# ================================================================ 工具三：工段关系结构统计


async def summarize_area_relations(registry: Any, arguments: dict[str, Any], api: Any) -> dict[str, Any]:
    raw = (arguments.get("area") or "").strip()
    areas = (await api.get_json("/api/ontology/process-areas")).get("items") or []
    area = next(
        (a for a in areas if raw in (a.get("id"), a.get("code"), a.get("name"))),
        None,
    ) or next((a for a in areas if raw and (raw in (a.get("name") or "") or (a.get("name") or "") in raw)), None)
    if not area:
        # 只列字面相近的工段（如"水解工段"→水解辅料配制 / 酶法水解）；一个都不像才列全部
        wanted = _bigrams(raw)
        similar = [a for a in areas if wanted & _bigrams(a.get("name") or "")]
        options = [{"id": a.get("id"), "code": a.get("code"), "name": a.get("name")} for a in (similar or areas)]
        return _clarify(AnalysisInputError(f"「{raw}」没有唯一对应的工段，请从候选里选一个重新调用。", options))

    data = await api.get_json(
        "/api/ontology/relations", {"area": area["name"], "limit": 10000, "view": "compact"}
    )
    rels = data.get("items") or []
    by_category = Counter(r.get("category") for r in rels)
    by_predicate: dict[str, Counter] = {}
    degree: Counter = Counter()
    degree_by_cat: dict[str, Counter] = {}
    types: dict[str, str] = {}
    for r in rels:
        by_predicate.setdefault(r.get("category"), Counter())[r.get("predicate")] += 1
        for side in ("subject", "object"):
            name = r.get(f"{side}Entity")
            if not name:
                continue
            # 测点绑定关系的客体是位号本身，不算作设备/工艺量的关联
            if r.get("category") == "测点绑定关系" and side == "object":
                continue
            degree[name] += 1
            degree_by_cat.setdefault(name, Counter())[r.get("category")] += 1
            types.setdefault(name, r.get(f"{side}Type") or "")

    def top_entities(type_filter: set[str] | None) -> list[dict[str, Any]]:
        rows = [(n, c) for n, c in degree.most_common() if type_filter is None or types.get(n) in type_filter]
        return [
            {"name": n, "type": types.get(n), "relations": c, "byCategory": dict(degree_by_cat[n].most_common(3))}
            for n, c in rows[:8]
        ]

    equipment_types = {"生产设备", "设备", "设备实例", "仪表", "控制器", "执行机构"}
    return {
        "analysisType": "工段关系结构统计",
        "area": {"id": area.get("id"), "code": area.get("code"), "name": area.get("name")},
        "total": len(rels),
        "byCategory": [
            {"category": c, "count": n, "predicates": dict(by_predicate[c].most_common(4))}
            for c, n in by_category.most_common()
        ],
        "topEntities": top_entities(None),
        "topEquipment": top_entities(equipment_types),
        "entityTypes": dict(Counter(types.values()).most_common()),
        "note": (
            "以上计数来自该工段的全量关系（未抽样，total 即真实总数）。"
            "关联数按对象作为主体或客体出现的次数统计；测点绑定关系只计入被绑定的工艺量一侧。"
        ),
    }


# ================================================================ 注册


_NEXT_HINT = "证据链已完整，请直接按 数据事实 / 本体记载 / 统计判断 三层作答并列出 dataGaps，不要用相同参数重复调用本工具。"


def _clarify(exc: AnalysisInputError) -> dict[str, Any]:
    return {"status": "needs_clarification", "message": str(exc), "candidates": exc.candidates}


_WINDOW_PARAMS = (
    ToolParameter("startTime", "string", "分析时间窗开始，yyyy-MM-dd HH:mm:ss（东八区）；按【当前时间】换算'昨天''夜班'等。不填默认最近 24 小时。"),
    ToolParameter("endTime", "string", "分析时间窗结束，格式同上，默认当前时刻。"),
)

ANALYSIS_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="investigate_process_anomaly",
        description=(
            "异常溯源（确定性分析，优先使用）。用户问'某参数异常/偏高/偏低/波动，帮我查原因''是什么引起的'时，直接调用本工具，"
            "不要自己逐步调限值、历史、关系工具。程序会按固定算法一次完成："
            "查工艺限值 → 取时间窗历史确认异常是否成立 → 沿本体因果关系往上游推（正负向逐层传播）→ "
            "逐个原因查测点 → 同期历史对比（领先滞后、方向、异常期偏移）→ 排序并列出数据缺口。"
            "target 可传本体工艺量名称（如 釜内反应温度）、robj- ID、DCS 位号（TI_1301A）或测点描述（水解罐A温度）；"
            "不确定时直接传用户的说法，没有唯一匹配时工具会返回候选让你选。"
        ),
        path="",
        parameters=(
            ToolParameter("target", "string", "出现异常的工艺量 / 位号 / 测点描述。", required=True),
            ToolParameter("symptom", "string", "异常表现；用户没说具体方向时用 异常。", enum=_SYMPTOMS),
            *_WINDOW_PARAMS,
            ToolParameter("focus", "string", "只看该工艺量下的某个测点，如 TI_1301A 或 水解罐A；不填则自动选越限最多的测点。"),
            ToolParameter("depth", "integer", f"沿因果关系往上游推几层，默认 {DEFAULT_DEPTH}，最多 {MAX_DEPTH}。"),
        ),
        group="analysis",
        summary="异常溯源：限值确认→因果上推→测点→同期对比，一次给出证据链",
        returns=(
            "limit（限值及确认状态）、anomaly（异常是否成立、越限测点与次数、首末越限时刻）、"
            "candidates[]（因素、路径、本体方向、机理、来源行、预期方向、测点、相关系数、领先分钟、异常期偏移σ、判断）、"
            "dataGaps、conclusion（程序给出的分层结论）、method（判定口径与模拟数据声明）。"
            "status=needs_clarification 时返回 candidates 供选择。"
        ),
        handler=investigate_process_anomaly,
    ),
    ToolSpec(
        name="verify_process_influence",
        description=(
            "影响验证（确定性分析，优先使用）。用户问'X 是不是 Y 引起的''X 会不会影响 Y''用数据验证一下 X 对 Y 的影响'时直接调用。"
            "程序会查本体里 cause→effect 的影响路径与正负向（上推 3 层），取同一时间窗两端的历史值，"
            "按本体方向判断数据是否支持，并说明本体有没有记载这条路径。"
            "cause / effect 的写法同 investigate_process_anomaly 的 target。"
        ),
        path="",
        parameters=(
            ToolParameter("cause", "string", "疑似原因的工艺量 / 位号 / 测点描述。", required=True),
            ToolParameter("effect", "string", "被影响的工艺量 / 位号 / 测点描述。", required=True),
            ToolParameter("symptom", "string", "结果一侧的异常表现，默认 异常。", enum=_SYMPTOMS),
            *_WINDOW_PARAMS,
            ToolParameter("focus", "string", "结果一侧只看某个测点，如 AT_1301A1。"),
        ),
        group="analysis",
        summary="影响验证：本体路径与方向 + 两端同期数据对比",
        returns="ontology（是否记载、路径、方向、机理、来源）、limit、effectAnomaly、evidence（预期方向、测点、相关系数、领先分钟、判断）、conclusion、method。",
        handler=verify_process_influence,
    ),
    ToolSpec(
        name="summarize_area_relations",
        description=(
            "工段关系结构统计（确定性分析，优先使用）。问'某工段的关系结构/哪些设备关联较多/关系主要是什么类型'时直接调用。"
            "程序取该工段全量关系精确计数：各类别数量与谓词分布、关联最多的对象与设备、对象类型分布。"
            "不要自己分页拉关系再数，容易漏类别。"
        ),
        path="",
        parameters=(ToolParameter("area", "string", "工段 ID（area-S11）、编号（S11）或名称（酶法水解）。", required=True),),
        group="analysis",
        summary="工段关系结构精确统计：类别分布、关联最多的对象",
        returns="total、byCategory[]（类别、数量、谓词分布）、topEntities[]、topEquipment[]、entityTypes、note。",
        handler=summarize_area_relations,
    ),
]
