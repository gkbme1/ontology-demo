"""调查固定程序：在线—化验偏差判定、漂移检测、操作记录关联，以及候选方向收敛（Top 3～5、人机料法环、权重）。

定义在本体，执行在这里：
- 判定规则（对象、在线位号、对比数据、判据、阈值、适用阶段）、化验项目与对齐方式、漂移口径、
  原因分类与权重都登记在本体（6APA_调查知识.xlsx），本模块按定义取数、比对、统计；
- 阈值与权重都是草案，输出里写明用的哪条规则 / 口径，供工艺人员标定。
"""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote

from .context_tools import (
    BatchWindowError,
    DEFAULT_PHASE,
    PHASES,
    UNIT_SCOPE,
    _fmt,
    _now_ms,
    _parse_ms,
    unit_batches,
)
from .executor import ToolApiError
from .registry import ToolParameter, ToolSpec

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
DEFAULT_LOOKBACK_DAYS = 3
MAX_ROWS = 8  # 对齐样本只回最近几条（本地小模型上下文有限）；判定用的是全部样本


class InvestigationInputError(ValueError):
    pass


def _clarify(message: str, candidates: list | None = None) -> dict[str, Any]:
    return {"status": "needs_clarification", "message": message, "candidates": candidates or []}


def _r(v: float | None, n: int = 3) -> float | None:
    return None if v is None else round(v, n)


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def theil_sen(xs: list[float], ys: list[float]) -> float | None:
    """中位数斜率：两两点斜率的中位数，个别离群点（如某批人为改了设定值）影响不了趋势。"""
    slopes = sorted((ys[j] - ys[i]) / (xs[j] - xs[i]) for i in range(len(xs)) for j in range(i + 1, len(xs)) if xs[j] != xs[i])
    if not slopes:
        return None
    mid = len(slopes) // 2
    return slopes[mid] if len(slopes) % 2 else (slopes[mid - 1] + slopes[mid]) / 2


def linear_slope(xs: list[float], ys: list[float]) -> float | None:
    """最小二乘斜率（单位：y / x）。"""
    if len(xs) < 2:
        return None
    mx, my = _mean(xs), _mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return None if den == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


async def _unit_and_window(api: Any, arguments: dict[str, Any], *, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> tuple[str, int, int, dict[str, Any]]:
    """unit / batchNo / startTime / endTime → (设备名, 开始, 结束, 依据)。给 batchNo 时取整批。"""
    batch_no = (arguments.get("batchNo") or "").strip()
    unit = (arguments.get("unit") or "").strip()
    if batch_no:
        try:
            detail = await api.get_json(f"/api/ontology/batches/{quote(batch_no)}")
        except ToolApiError as exc:
            raise InvestigationInputError(f"没有找到批次 {batch_no}：{exc}") from exc
        b = detail["batch"]
        end = b.get("endTime") or _now_ms()
        return (detail.get("scope") or {}).get("objectName") or unit, b["startTime"], end, {
            "type": "批次", "batchNo": batch_no, "text": f"批次 {batch_no} 整批（{_fmt(b['startTime'])} ~ {_fmt(end)}）"}
    if not unit:
        raise InvestigationInputError("请给出设备（unit，如 水解罐C）或批号（batchNo）。")
    end = min(_parse_ms(arguments.get("endTime"), _now_ms()), _now_ms())
    start = _parse_ms(arguments.get("startTime"), end - lookback_days * DAY_MS)
    if start >= end:
        raise InvestigationInputError("startTime 必须早于 endTime。")
    return unit, start, end, {"type": "时间范围", "text": f"{_fmt(start)} ~ {_fmt(end)}"}


async def _tag_series(api: Any, tag: str, start: int, end: int, interval: int) -> dict[int, float]:
    data = await api.get_json("/api/ontology/history", {"keyword": tag, "startTime": start, "endTime": end,
                                                        "interval": interval, "sampleMode": "interpolated", "limit": 20})
    for item in data.get("items") or []:
        if item.get("tagName") == tag:
            return {int(p["t"]): float(p["v"]) for p in item.get("values") or [] if p.get("v") is not None and p.get("q", 1) == 1}
    return {}


def _phase_lookup(batches: list[dict[str, Any]]):
    segs = sorted(((p["startTime"], p.get("endTime"), p["phase"], b.get("batchNo") or b.get("inferredId"))
                   for b in batches for p in b.get("phases") or []), key=lambda s: s[0])

    def at(t: int) -> tuple[str | None, str | None]:
        for s, e, name, no in segs:
            if s <= t and (e is None or t < e):
                return name, no
        return None, None

    return at


# ================================================================ 在线—化验 / 双电极偏差


def judge_differences(times: list[int], diffs: list[float], rule: dict[str, Any]) -> dict[str, Any]:
    """差值序列按规则判定：扩大 / 恒定偏差 / 正常 / 样本不足。阈值来自本体判定规则。"""
    n = len(diffs)
    min_n = rule.get("minSamples") or 4
    const_thr = rule.get("constantThreshold") or 0.1
    grow_thr = rule.get("growthThresholdPerDay") or 0.03
    if n < min_n:
        return {"verdict": "样本不足", "n": n, "reason": f"对齐后只有 {n} 个样本，少于规则要求的 {min_n} 个"}
    days = [(t - times[0]) / DAY_MS for t in times]
    slope = linear_slope(days, diffs) or 0.0
    third = max(1, n // 3)
    early, late = _mean(diffs[:third]), _mean(diffs[-third:])
    mean = _mean(diffs)
    sign = 1 if late >= 0 else -1
    same_sign = sum(1 for d in diffs if d * (1 if mean >= 0 else -1) > 0) / n
    span_days = max(days[-1], 1e-9)
    out = {"n": n, "meanDiff": _r(mean), "stdDiff": _r(_std(diffs)), "slopePerDay": _r(slope, 4),
           "earlyMean": _r(early), "lateMean": _r(late), "spanDays": _r(span_days, 2),
           "thresholds": {"恒定偏差": const_thr, "扩大(每天)": grow_thr}}
    growing = slope * sign >= grow_thr and abs(late) - abs(early) >= grow_thr * span_days * 0.5 and abs(late) >= const_thr * 0.5
    if growing:
        out["verdict"] = "差值扩大"
        out["reason"] = (f"差值从前段均值 {early:+.3f} 变到后段 {late:+.3f}，线性趋势 {slope:+.4f}/天，"
                         f"超过规则阈值 {grow_thr}/天")
    elif abs(mean) >= const_thr and same_sign >= 0.8:
        out["verdict"] = "恒定偏差"
        out["reason"] = f"差值均值 {mean:+.3f}，{same_sign:.0%} 的样本同号，超过规则阈值 {const_thr}"
    else:
        out["verdict"] = "正常"
        out["reason"] = f"差值均值 {mean:+.3f}、趋势 {slope:+.4f}/天，均未超过规则阈值"
    return out


async def _rule_lab(api: Any, unit: str, rule: dict[str, Any], start: int, end: int, phase_at) -> dict[str, Any]:
    item = rule["compareWith"].split(":", 1)[1] if ":" in rule["compareWith"] else rule["compareWith"]
    labs = await api.get_json(f"/api/ontology/{quote(unit)}/lab-results", {"startTime": start, "endTime": end, "item": item})
    defs = {x["code"]: x for x in labs.get("labItems") or []}
    align = float((defs.get(item) or {}).get("alignMinutes") or 2)
    tag = (rule.get("onlineTagResolved") or {}).get("tag")
    if not tag or not (rule.get("onlineTagResolved") or {}).get("resolved"):
        return {"verdict": "无法判定", "reason": f"本台没有登记在线位号（模板 {rule.get('onlineTag')}）"}
    online = await _tag_series(api, tag, start - HOUR_MS, end, 60_000)
    rows, times, diffs = [], [], []
    for r in sorted(labs.get("items") or [], key=lambda x: x["sampleTime"]):
        t = r["sampleTime"]
        phase, batch = phase_at(t)
        if rule.get("phases") and phase not in rule["phases"]:
            continue
        near = [v for ts, v in online.items() if abs(ts - t) <= align * 60_000]
        if not near:
            continue
        on = _mean(near)
        d = on - float(r["value"])
        times.append(t)
        diffs.append(d)
        rows.append({"sampleTime": r.get("sampleText") or _fmt(t), "batchNo": r.get("batchNo") or batch, "phase": phase,
                     "lab": r["value"], "online": _r(on), "diff": _r(d), "source": r.get("source")})
    out = judge_differences(times, diffs, rule)
    out.update({"onlineTag": tag, "compareWith": f"化验项目 {item}", "alignment": f"取样时刻 ±{align:g} 分钟在线均值（按取样时间，不按报告时间）",
                "samples": rows[-MAX_ROWS:], "simulated": bool((labs.get("dataSource") or {}).get("simulated"))})
    return out


async def _rule_tags(api: Any, rule: dict[str, Any], start: int, end: int, phase_at) -> dict[str, Any]:
    a, b = rule.get("onlineTagResolved") or {}, rule.get("compareTagResolved") or {}
    if not (a.get("resolved") and b.get("resolved")):
        return {"verdict": "无法判定", "reason": f"本台缺少对比位号（{a.get('template')} / {b.get('template')}）"}
    interval = max(60_000, (end - start) // 400 // 60_000 * 60_000)
    sa = await _tag_series(api, a["tag"], start, end, interval)
    sb = await _tag_series(api, b["tag"], start, end, interval)
    # 按批次阶段取样：每个适用阶段段取一个均值，作为一个对比样本
    groups: dict[str, list[tuple[int, float]]] = {}
    for t, va in sa.items():
        if t not in sb:
            continue
        phase, batch = phase_at(t)
        if rule.get("phases") and phase not in rule["phases"]:
            continue
        groups.setdefault(f"{batch}|{phase}", []).append((t, va - sb[t]))
    rows, times, diffs = [], [], []
    for key, pts in sorted(groups.items(), key=lambda kv: kv[1][0][0]):
        if len(pts) < 3:
            continue
        t_mid = pts[len(pts) // 2][0]
        d = _mean([d for _, d in pts])
        times.append(t_mid)
        diffs.append(d)
        batch, phase = key.split("|")
        rows.append({"batchNo": batch, "phase": phase, "time": _fmt(t_mid), "diff": _r(d), "points": len(pts)})
    out = judge_differences(times, diffs, rule)
    out.update({"onlineTag": a["tag"], "compareWith": f"位号 {b['tag']}", "alignment": "同一时刻两支电极读数相减，按批次阶段取均值",
                "samples": rows[-MAX_ROWS:], "simulated": True})
    return out


async def run_deviation_rules(api: Any, unit: str, start: int, end: int, rule_id: str | None = None) -> dict[str, Any]:
    rules = await api.get_json(f"/api/ontology/{quote(unit)}/judgement-rules")
    items = [r for r in rules.get("rules") or [] if not rule_id or r["id"] == rule_id]
    try:
        got = await unit_batches(api, unit, start, end)
        phase_at, phase_source = _phase_lookup(got["items"]), got["source"]
    except BatchWindowError:
        phase_at, phase_source = (lambda t: (None, None)), None
    results = []
    for rule in items:
        if rule["compareWith"].startswith("化验"):
            res = await _rule_lab(api, unit, rule, start, end, phase_at)
        else:
            res = await _rule_tags(api, rule, start, end, phase_at)
        results.append({"ruleId": rule["id"], "ruleName": rule["name"], "object": rule["object"], "criterion": rule["criterion"],
                        "category": rule.get("category"), "ruleStatus": rule.get("status"), "basis": rule.get("basis"),
                        "phases": rule.get("phases"), **res})
    return {"unit": (rules.get("scope") or {}).get("objectName") or unit, "results": results, "phaseSource": phase_source}


async def check_measurement_deviation(registry: Any, arguments: dict[str, Any], api: Any) -> dict[str, Any]:
    try:
        unit, start, end, basis = await _unit_and_window(api, arguments)
        got = await run_deviation_rules(api, unit, start, end, arguments.get("ruleId"))
    except InvestigationInputError as exc:
        return _clarify(str(exc))
    except ToolApiError as exc:
        if exc.kind in ("not_found", "bad_request"):
            return _clarify(f"「{arguments.get('unit') or arguments.get('batchNo')}」没有定义判定规则或不是设备实例：{exc}")
        raise
    results = got["results"]
    if not results:
        return {"analysisType": "测量偏差判定", "unit": got["unit"], "conclusion": "本体中没有适用于该设备的判定规则。"}
    flagged = [r for r in results if r.get("verdict") in ("差值扩大", "恒定偏差")]
    lines = [f"{r['ruleName']}（{r['ruleId']}）：{r.get('verdict')}。{r.get('reason', '')}" for r in results]
    conclusion = f"「{got['unit']}」{basis['text']}，按本体判定规则逐条比对：" + "；".join(lines) + "。"
    if flagged:
        conclusion += "按规则判定此处异常，优先排查测量（如 pH 电极漂移，需校准或比对后再判断工艺本身）。"
    if any(r.get("simulated") for r in results):
        conclusion += "（化验与在线数据来自模拟服务，不是现场真实记录。）"
    return {
        "analysisType": "测量偏差判定",
        "unit": got["unit"],
        "range": basis,
        "phaseSource": got["phaseSource"],
        "results": results,
        "flagged": [r["ruleId"] for r in flagged],
        "conclusion": conclusion,
        "method": "判定规则、阈值、适用阶段、对齐方式都来自本体（6APA_调查知识.xlsx，草案待标定）；"
                  "扩大 = 差值线性趋势超过阈值且后段比前段更偏；恒定偏差 = 差值均值超过阈值且八成以上样本同号。",
    }


# ================================================================ 漂移检测


def cusum(values: list[float], mean: float, sd: float, k: float, h: float) -> dict[str, Any]:
    """双侧 CUSUM（标准化后）：返回首次越过 h 的位置与方向。"""
    if sd <= 0:
        return {"alarm": False}
    hi = lo = 0.0
    for i, v in enumerate(values):
        z = (v - mean) / sd
        hi = max(0.0, hi + z - k)
        lo = max(0.0, lo - z - k)
        if hi > h:
            return {"alarm": True, "index": i, "direction": 1, "statistic": _r(hi, 2)}
        if lo > h:
            return {"alarm": True, "index": i, "direction": -1, "statistic": _r(lo, 2)}
    return {"alarm": False, "max": _r(max(hi, lo), 2)}


def _criteria(knowledge: dict[str, Any], method: str, target: str) -> dict[str, Any]:
    rows = [d for d in knowledge.get("drift") or [] if d["method"] == method]
    hit = next((d for d in rows if d["object"] == target), None) or next((d for d in rows if d["object"] == "默认"), None)
    return hit or {"id": None, "params": {}}


async def detect_drift(registry: Any, arguments: dict[str, Any], api: Any) -> dict[str, Any]:
    from .analysis_tools import AnalysisInputError, _history, _limit_for, _resolve_entity, _target_view

    try:
        target = await _resolve_entity(api, arguments.get("target", ""))
    except AnalysisInputError as exc:
        return {"status": "needs_clarification", "message": str(exc), "candidates": exc.candidates}
    phase = arguments.get("phase") or DEFAULT_PHASE
    if phase not in PHASES:
        return _clarify(f"phase 只能取 {'、'.join(PHASES)}。")
    knowledge = await api.get_json("/api/ontology/investigation-knowledge")
    limit = await _limit_for(api, target)
    unit = (arguments.get("unit") or "").strip()
    end = min(_parse_ms(arguments.get("endTime"), _now_ms()), _now_ms())
    batches_wanted = int(_criteria(knowledge, "批间均值", target["name"])["params"].get("batches") or 8)
    start = _parse_ms(arguments.get("startTime"), end - max(DEFAULT_LOOKBACK_DAYS, math.ceil(batches_wanted * 9 / 24)) * DAY_MS)
    if start >= end:
        return _clarify("startTime 必须早于 endTime。")
    token = UNIT_SCOPE.set(unit or None)
    try:
        interval = max(60_000, (end - start) // 1500 // 60_000 * 60_000)
        hist = await _history(api, target["id"], _fmt(start), _fmt(end), interval, keyword=arguments.get("focus"), limit=30)
    finally:
        UNIT_SCOPE.reset(token)
    if not hist["tags"]:
        return {"analysisType": "漂移检测", "target": _target_view(target), "conclusion": f"「{target['name']}」没有可取历史值的测点。"}

    batch_crit = _criteria(knowledge, "批间均值", target["name"])
    cusum_crit = _criteria(knowledge, "CUSUM", target["name"])
    slope_crit = _criteria(knowledge, "斜率", target["name"])
    ratio = float(batch_crit["params"].get("ratio") or 0.15)
    width = (limit["normalHigh"] - limit["normalLow"]) if limit and limit.get("normalHigh") is not None and limit.get("normalLow") is not None else None
    units_cache: dict[str, Any] = {}
    rows = []
    for tag in hist["tags"]:
        equip = tag.get("equipment") or ""
        if equip not in units_cache:
            try:
                units_cache[equip] = await unit_batches(api, equip, start, end) if equip else None
            except BatchWindowError:
                units_cache[equip] = None
        got = units_cache[equip]
        row: dict[str, Any] = {"tag": tag["tag"], "desc": tag["desc"], "equipment": equip}
        series = tag["series"]
        if got and got["items"]:
            # 批间：逐批取该阶段均值，看是否单向漂移
            means = []
            for b in got["items"]:
                spans = [(p["startTime"], p.get("endTime") or end) for p in b.get("phases") or [] if p["phase"] == phase or phase == "全批"]
                if not spans or b.get("partialStart"):
                    continue
                pts = [v for t, v in series.items() if any(s <= t < e for s, e in spans)]
                if len(pts) >= 5 and (b.get("status") == "已完成" or phase != "全批"):
                    means.append((b.get("batchNo") or b.get("inferredId"), spans[0][0], _mean(pts)))
            means = means[-batches_wanted:]
            row["mode"] = "批间均值"
            row["batchMeans"] = [{"batchNo": no, "start": _fmt(t), "mean": _r(m)} for no, t, m in means]
            if len(means) >= 4:
                xs = list(range(len(means)))
                ys = [m for _, _, m in means]
                slope = theil_sen(xs, ys) or 0.0
                change = slope * (len(means) - 1)
                med = sorted(y - slope * x for x, y in zip(xs, ys))[len(ys) // 2]
                resid = _std([y - (med + slope * x) for x, y in zip(xs, ys)]) or 1e-9
                threshold = ratio * width if width else 3 * resid
                row.update({"perBatchSlope": _r(slope, 4), "totalChange": _r(change), "threshold": _r(threshold),
                            "criteria": batch_crit.get("id")})
                row["drift"] = abs(change) >= threshold
                row["direction"] = "上升" if change > 0 else "下降"
                if limit:
                    inside = all((limit.get("normalLow") is None or m >= limit["normalLow"]) and
                                 (limit.get("normalHigh") is None or m <= limit["normalHigh"]) for _, _, m in means)
                    row["withinLimits"] = inside
            else:
                row["drift"] = None
                row["note"] = f"只有 {len(means)} 批完整的{phase}数据，批间漂移至少需要 4 批"
        else:
            # 时间窗：CUSUM + 斜率
            times = sorted(series)
            values = [series[t] for t in times]
            n0 = max(5, len(values) // 4)
            base = values[:n0]
            mean, sd = _mean(base), _std(base)
            k = float(cusum_crit["params"].get("k") or 0.5)
            h = float(cusum_crit["params"].get("h") or 5)
            res = cusum(values[n0:], mean, sd, k, h)
            hours = [(t - times[0]) / HOUR_MS for t in times]
            slope = linear_slope(hours, values) or 0.0
            change = slope * (hours[-1] if hours else 0)
            sigma = float(slope_crit["params"].get("sigma") or 3)
            row.update({"mode": "时间窗", "baselineMean": _r(mean), "baselineStd": _r(sd), "cusum": res,
                        "slopePerHour": _r(slope, 4), "totalChange": _r(change), "criteria": [cusum_crit.get("id"), slope_crit.get("id")]})
            if res.get("alarm"):
                row["cusum"]["at"] = _fmt(times[n0 + res["index"]])
            row["drift"] = bool(res.get("alarm")) and abs(change) >= sigma * max(sd, 1e-9)
            row["direction"] = "上升" if change > 0 else "下降"
        rows.append(row)

    drifting = [r for r in rows if r.get("drift")]
    drifting.sort(key=lambda r: -abs(r.get("totalChange") or 0))
    quiet = [r["tag"] for r in rows if r.get("drift") is False]
    detail = [r for r in rows if r.get("drift") or r.get("drift") is None]
    parts = [f"「{target['name']}」{len(rows)} 个测点中 {len(drifting)} 个检出漂移"]
    if drifting:
        parts.append("：" + "、".join(
            f"{r['tag']}（{r['equipment']}，{r['mode']}，{r['direction']} {abs(r.get('totalChange') or 0):.3g}"
            + ("，仍在正常区间内——限值内的缓慢漂移" if r.get("withinLimits") else "") + "）" for r in drifting[:6]))
    parts.append("。")
    if any(r.get("withinLimits") for r in drifting):
        parts.append("限值内漂移不会触发越限报警，需要结合化验或电极比对确认是测量漂移还是工艺本身在变。")
    result = {
        "analysisType": "漂移检测",
        "target": _target_view(target),
        "range": {"start": _fmt(start), "end": _fmt(end)},
        "phase": phase,
        "limit": {"id": limit.get("id"), "正常区间": f"{limit.get('normalLow')}~{limit.get('normalHigh')}"} if limit else None,
        "drifting": drifting[:10],
        "noDrift": quiet,
        "others": [r for r in detail if r.get("drift") is None][:5],
        "conclusion": "".join(parts) + ("（数值来自模拟数据服务。）" if hist["simulated"] else ""),
        "method": ("有批次记录的设备按批间均值判断：逐批取同一阶段均值，中位数斜率（Theil–Sen）估计的总变化 ≥ 正常区间宽度 × "
                   f"{ratio}（无限值时 ≥ 3 倍批间波动）判漂移；没有批次的按时间窗 CUSUM（k、h）与整窗斜率判断。"
                   "口径来自本体「漂移口径」（草案，待标定）。"),
    }
    return result


# ================================================================ 操作记录关联


async def analyze_operations(registry: Any, arguments: dict[str, Any], api: Any) -> dict[str, Any]:
    try:
        unit, start, end, basis = await _unit_and_window(api, arguments)
        data = await api.get_json(f"/api/ontology/{quote(unit)}/operations", {"startTime": start, "endTime": end})
    except InvestigationInputError as exc:
        return _clarify(str(exc))
    except ToolApiError as exc:
        if exc.kind in ("not_found", "bad_request"):
            return _clarify(f"「{arguments.get('unit') or arguments.get('batchNo')}」查不到操作记录：{exc}")
        raise
    items = data.get("items") or []
    rows = []
    for r in items:
        row = {k: r.get(k) for k in ("timeText", "batchNo", "kind", "tag", "param", "oldValue", "newValue", "station", "shift")}
        row["properties"] = r.get("properties")
        if r.get("kind") == "设定值修改" and r.get("tag"):
            series = await _tag_series(api, r["tag"], r["time"] - 30 * 60_000, r["time"] + 90 * 60_000, 60_000)
            before = [v for t, v in series.items() if t < r["time"]]
            after = [v for t, v in series.items() if t >= r["time"] + 30 * 60_000]
            if before and after:
                row["measuredBefore"] = _r(_mean(before))
                row["measuredAfter"] = _r(_mean(after))
                row["measuredChange"] = _r(_mean(after) - _mean(before))
                row["followed"] = (row["measuredChange"] or 0) * (float(r["newValue"]) - float(r["oldValue"])) > 0
        rows.append(row)
    sp = [r for r in rows if r["kind"] == "设定值修改"]
    by_shift: dict[str, int] = {}
    for r in rows:
        key = (r.get("shift") or "未知班次").split(" ", 1)[-1]
        by_shift[key] = by_shift.get(key, 0) + 1
    conclusion = f"「{unit}」{basis['text']} 共 {len(rows)} 条操作记录，其中设定值修改 {len(sp)} 次"
    if sp:
        conclusion += "：" + "；".join(
            f"{r['timeText'][5:16]} {r['param']} {r['oldValue']}→{r['newValue']}（{r.get('shift') or '班次未知'}，批次 {r['batchNo']}"
            + (f"，实测变化 {r['measuredChange']:+}" if r.get("measuredChange") is not None else "") + "）" for r in sp[:8])
    conclusion += "。"
    if data.get("dataSource", {}).get("simulated"):
        conclusion += "（操作日志来自模拟服务。）"
    return {
        "analysisType": "操作记录",
        "unit": (data.get("scope") or {}).get("objectName") or unit,
        "range": basis,
        "count": len(rows),
        "setpointChanges": len(sp),
        "byShift": by_shift,
        "operations": rows[-30:],
        "conclusion": conclusion,
        "method": "设定值修改后看对应位号：改前 30 分钟均值 与 改后 30~90 分钟均值 之差（实测变化），判断参数是否跟随改动。",
    }


# ================================================================ 候选方向收敛（供 investigate_process_anomaly 调用）

TOP_MIN, TOP_MAX = 3, 5
SCORING_NOTE = "候选方向按 证据分 × 本体原因权重 排序取前 3～5 条。"
SCORING_DETAIL = ("证据分：数据支持 1.0、同期强相关 0.75、弱支持 0.6、无测点 0.35、未发现支持 0.15、方向相反 0.05；"
                  "人为改同一参数且方向一致 0.9、改同一参数 0.6；测量偏差扩大 0.9、恒定 0.75；乘本体原因权重后封顶 1。")
CONFIDENCE_THRESHOLD = 0.5  # 最高分低于此值：证据不足，提示转人工
INCLUDE_THRESHOLD = 0.3  # 低于此分只用于凑满 3 条，并标「证据弱」
EVIDENCE_SCORE = {
    "数据支持": 1.0,
    "同期强相关（本体未标方向）": 0.75,
    "弱支持": 0.6,
    "无测点，无法用数据验证": 0.35,
    "未发现支持证据": 0.15,
    "与本体方向相反": 0.05,
}


def _score(base: float, weight: float) -> float:
    return round(min(1.0, base * weight), 3)


async def converge_directions(api: Any, target: dict[str, Any], judged: dict[str, Any], focus: dict[str, Any],
                              candidates: list[dict[str, Any]], window: tuple[str, str, int]) -> dict[str, Any]:
    """候选方向收敛：本体因果候选 + 「人」（操作记录）+ 「机」（测量偏差规则），按人机料法环归类、叠加权重，取 Top 3～5。"""
    ids = ",".join(c["id"] for c in candidates if c.get("id"))
    profiles = {}
    categories = []
    try:
        prof = await api.get_json("/api/ontology/cause-profile", {"ids": ids, "names": "人为修改设定值"})
        profiles = {p["id"] or p["name"]: p for p in prof.get("items") or []}
        categories = prof.get("categories") or []
    except ToolApiError:
        pass
    directions: list[dict[str, Any]] = []
    for c in candidates:
        p = profiles.get(c["id"]) or {}
        base = EVIDENCE_SCORE.get(c.get("verdict"), 0.2)
        weight = float(p.get("weight") or 1.0)
        evidence = c.get("verdict")
        if c.get("corr") is not None:
            evidence += f"（相关 {c['corr']}，领先 {c.get('leadMinutes')} 分钟）"
        # 依据只写路径：来源行、机理在 candidates 里已有，不重复占上下文
        directions.append({"factor": c["factor"], "category": p.get("category") or "法",
                           "score": _score(base, weight), "weight": weight, "evidence": evidence})

    start_ms = int(_parse_ms(window[0], _now_ms()))
    end_ms = int(_parse_ms(window[1], _now_ms()))
    unit = None
    focus_tag = focus.get("tag")
    # 「这一台」：关注测点所属设备（定义了批次的设备才有操作记录 / 判定规则）
    for t in [focus]:
        unit = t.get("equipment") or None
    notes = []
    if unit:
        # 人：时间窗内对本工艺量的设定值修改
        try:
            ops = await api.get_json(f"/api/ontology/{quote(unit)}/operations", {"startTime": start_ms - 2 * HOUR_MS, "endTime": end_ms})
            sp = [o for o in ops.get("items") or [] if o.get("kind") == "设定值修改"]
            mine = [o for o in sp if target["name"] in (o.get("properties") or [])]
            human_w = float((profiles.get("人为修改设定值") or {}).get("weight") or 1.0)
            if mine:
                direction = judged.get("direction") or 0
                agree = [o for o in mine if direction and (float(o["newValue"]) - float(o["oldValue"])) * direction > 0]
                base = 0.9 if agree else 0.6
                pick = (agree or mine)[-1]
                directions.append({
                    "factor": f"人为修改{pick['param']}", "category": "人",
                    "score": _score(base, human_w), "weight": human_w,
                    "evidence": f"{pick['timeText'][5:16]} {pick['param']} {pick['oldValue']}→{pick['newValue']}（{pick.get('shift') or '班次未知'}，"
                                f"{pick.get('station')}）" + ("，改动方向与异常方向一致" if agree else "") + f"；窗内共 {len(mine)} 次",
                    "basis": "DCS 操作日志"})
            elif sp:
                directions.append({"factor": "人为修改其他参数", "category": "人",
                                   "score": _score(0.25, human_w), "weight": human_w,
                                   "evidence": f"窗内有 {len(sp)} 次设定值修改，但不涉及「{target['name']}」",
                                   "basis": "DCS 操作日志"})
        except ToolApiError as exc:
            notes.append(f"操作记录取不到（{exc.kind}），「人」这一类未验证")
        # 机：本工艺量的测量偏差判定规则（如 pH 在线—化验）
        try:
            rules = await api.get_json(f"/api/ontology/{quote(unit)}/judgement-rules")
            mine = [r for r in rules.get("rules") or [] if r.get("object") == target["name"]]
            if mine:
                got = await run_deviation_rules(api, unit, min(start_ms, end_ms - DEFAULT_LOOKBACK_DAYS * DAY_MS), end_ms)
                for r in got["results"]:
                    if r["object"] != target["name"]:
                        continue
                    base = {"差值扩大": 0.9, "恒定偏差": 0.75, "正常": 0.1}.get(r.get("verdict"), 0.3)
                    weight = float((profiles.get("水解反应釜组(水解罐A–K)·双pH电极") or {}).get("weight") or 1.0)
                    directions.append({
                        "factor": f"测量偏差：{r['ruleName']}", "category": r.get("category") or "机",
                        "score": _score(base, weight), "weight": weight,
                        "evidence": f"{r.get('verdict')}：{r.get('reason', '')}", "basis": f"本体判定规则 {r['ruleId']}"})
        except ToolApiError as exc:
            notes.append(f"判定规则取不到（{exc.kind}）")
    else:
        notes.append("关注测点没有对应到具体设备，「人」（操作记录）与测量偏差未验证")

    directions.sort(key=lambda d: -d["score"])
    chosen = [d for d in directions if d["score"] >= INCLUDE_THRESHOLD][:TOP_MAX]
    if len(chosen) < TOP_MIN:
        for d in directions:
            if d not in chosen and len(chosen) < TOP_MIN:
                chosen.append({**d, "weak": True})
    for i, d in enumerate(chosen, 1):
        d["rank"] = i
        if d.get("weight") == 1.0:
            d.pop("weight")  # 默认权重不重复写
    top = chosen[0]["score"] if chosen else 0.0
    by_cat: dict[str, list[str]] = {}
    for d in chosen:
        by_cat.setdefault(d["category"], []).append(d["factor"])
    order = [c["key"] for c in categories] or ["人", "机", "料", "法", "环"]
    return {
        "directions": chosen,
        "byCategory": {k: by_cat[k] for k in order if k in by_cat},
        "uncovered": [k for k in order if k not in by_cat],
        "confidence": {"topScore": top, "threshold": CONFIDENCE_THRESHOLD, "needsHuman": top < CONFIDENCE_THRESHOLD},
        "unit": unit,
        "focusTag": focus_tag,
        "notes": notes,
        "scoring": SCORING_DETAIL,
    }


# ================================================================ 工具定义

_UNIT_PARAMS = (
    ToolParameter("unit", "string", "设备实例，如 水解罐C。"),
    ToolParameter("batchNo", "string", "批号，如 SJ-C-0830；给了就看整批，不用再给 unit 和时间。"),
    ToolParameter("startTime", "string", f"开始时间 yyyy-MM-dd HH:mm:ss，默认 endTime 往前 {DEFAULT_LOOKBACK_DAYS} 天。"),
    ToolParameter("endTime", "string", "结束时间，默认当前。"),
)

INVESTIGATION_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="check_measurement_deviation",
        description=(
            "测量偏差判定（固定程序）。问'pH 表准不准''在线 pH 和化验对得上吗''两支电极是不是有一支漂了'"
            "，或调查 pH 类异常要先排除仪表问题时调用。程序按本体判定规则逐条执行："
            "在线与化验 pH 按取样时间对齐比对、双电极互比，判断差值是「恒定偏差」「差值扩大」还是正常（BF-05）。"
        ),
        path="",
        parameters=(*_UNIT_PARAMS, ToolParameter("ruleId", "string", "只执行某条规则，如 J-S11-01；不填执行全部适用规则。")),
        group="analysis",
        summary="测量偏差判定：在线—化验、双电极按本体规则比对，判恒定 / 扩大",
        returns="results[]（规则、判定、理由、差值均值与趋势、对齐样本）、flagged、conclusion、method。",
        handler=check_measurement_deviation,
    ),
    ToolSpec(
        name="detect_drift",
        description=(
            "漂移检测（固定程序）。问'某参数这两天是不是一直往上跑''有没有在限值内慢慢偏''温水煮青蛙'时调用。"
            "有批次的设备逐批取同一阶段均值看批间趋势，没有批次的按时间窗 CUSUM 与斜率判断；会标出仍在正常区间内的漂移。"
        ),
        path="",
        parameters=(
            ToolParameter("target", "string", "工艺量 / 位号 / 测点描述，如 反应体系pH、AT_1301C2。", required=True),
            ToolParameter("unit", "string", "只看某一台，如 水解罐B；不填看该工艺量的全部测点。"),
            ToolParameter("phase", "string", f"批间比较用哪个阶段，默认 {DEFAULT_PHASE}。", enum=PHASES),
            ToolParameter("startTime", "string", "开始时间，默认覆盖最近约 8 批。"),
            ToolParameter("endTime", "string", "结束时间，默认当前。"),
            ToolParameter("focus", "string", "只看某个测点。"),
        ),
        group="analysis",
        summary="漂移检测：批间均值趋势 / CUSUM / 斜率，标出限值内漂移",
        returns="drifting[]（测点、设备、方式、方向、总变化、阈值、是否仍在限值内、逐批均值）、noDrift、conclusion、method。",
        handler=detect_drift,
    ),
    ToolSpec(
        name="analyze_operations",
        description=(
            "操作记录关联（固定程序）。问'有没有人改过参数''夜班动过设定值吗''这批谁改的温度'时调用。"
            "程序取 DCS 操作日志（设定值修改、手自动切换），附班次，并算出改设定值前后对应位号的实测变化。"
        ),
        path="",
        parameters=_UNIT_PARAMS,
        group="analysis",
        summary="操作记录：设定值修改 / 手自动切换、班次、改动前后实测变化",
        returns="operations[]（时间、批次、类型、位号、参数、旧值、新值、操作站、班次、实测变化）、byShift、conclusion。",
        handler=analyze_operations,
    ),
]

__all__ = ["INVESTIGATION_TOOLS", "converge_directions", "cusum", "judge_differences", "linear_slope", "run_deviation_rules",
           "theil_sen"]
