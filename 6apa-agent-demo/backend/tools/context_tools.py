"""运行上下文：罐批次、工艺阶段、班次，以及「按批次 / 阶段取时间窗」。

为什么要有这一层
----------------
现场讨论异常时说的是「A 罐这一批」「反应期间」「夜班」，不是「最近 24 小时」：
同一个温度在进料、反应、出料时的正常范围不一样，跨批次取一整天的数据会把
几个批次的进料和出料混在一起，越限统计和相关分析都不可信。
所以分析工具的时间窗可以落到「某罐某批的某个阶段」上，由本模块统一换算。

取数顺序（固定程序，不由模型决定）
--------------------------------
1. EBR（经本体代调 /api/ontology/{设备}/batches、/api/ontology/batches/{批号}）：批号、换酶后批次数、各阶段起止；
2. EBR 取不到时，按本体「工艺阶段」里登记的 DCS 识别条件（/api/ontology/{设备}/stage-rules）
   用开关量历史推断阶段与批次边界，结果标明「DCS 推断」，没有批号与换酶后批次数。
阶段定义在本体，取数和推断在 Agent：本体只说「反应 = 搅拌运行且氨水进料阀开」，不负责算。
"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from .executor import ToolApiError
from .registry import ToolParameter, ToolSpec

TZ = timezone(timedelta(hours=8))
TIME_FMT = "%Y-%m-%d %H:%M:%S"
DAY_MS = 86_400_000
DEFAULT_LOOKBACK_DAYS = 3  # 不给时间范围时往前看几天的批次
MAX_LOOKBACK_DAYS = 31
PHASE_WHOLE = "全批"
DEFAULT_PHASE = "反应"
PHASES = ("反应", "进料", "终点判定", "出料", PHASE_WHOLE)
SOURCE_EBR = "EBR"
SOURCE_DCS = "DCS推断"
MAX_BATCH_ROWS = 12


# 本次分析限定的设备（如 水解罐A）。分析工具取历史值时带上 unit，本体只返回该台及按台号对应设备的测点。
UNIT_SCOPE: ContextVar[str | None] = ContextVar("unit_scope", default=None)


class BatchWindowError(ValueError):
    """批次 / 设备无法解析。转成 needs_clarification 回给模型。"""

    def __init__(self, message: str, candidates: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.candidates = candidates or []


def _now_ms() -> int:
    return int(datetime.now(TZ).timestamp() * 1000)


def _fmt(ms: int | None) -> str | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, TZ).strftime(TIME_FMT)


def _parse_ms(text: str | None, default: int) -> int:
    if not text:
        return default
    raw = str(text).strip()
    if raw.isdigit():
        return int(raw)
    for fmt in (TIME_FMT, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(raw, fmt).replace(tzinfo=TZ).timestamp() * 1000)
        except ValueError:
            continue
    raise BatchWindowError(f"时间格式无法识别：{raw}。请用 yyyy-MM-dd HH:mm:ss（东八区）。")


def _range(arguments: dict[str, Any]) -> tuple[int, int]:
    end = min(_parse_ms(arguments.get("endTime"), _now_ms()), _now_ms())
    start = _parse_ms(arguments.get("startTime"), end - DEFAULT_LOOKBACK_DAYS * DAY_MS)
    if start >= end:
        raise BatchWindowError("startTime 必须早于 endTime。")
    if end - start > MAX_LOOKBACK_DAYS * DAY_MS:
        raise BatchWindowError(f"查批次的时间范围不能超过 {MAX_LOOKBACK_DAYS} 天。")
    return start, end


# ================================================================ 取批次：EBR 优先，DCS 推断兜底


async def _ebr_batches(api: Any, unit: str, start: int, end: int) -> dict[str, Any]:
    return await api.get_json(f"/api/ontology/{quote(unit)}/batches", {"startTime": start, "endTime": end, "limit": 200})


async def _raw_changes(api: Any, tag: str, start: int, end: int) -> list[tuple[int, int]]:
    data = await api.get_json(
        "/api/ontology/history",
        {"keyword": tag, "startTime": start, "endTime": end, "sampleMode": "raw", "maxPoints": 5000, "limit": 20},
    )
    for item in data.get("items") or []:
        if item.get("tagName") == tag:
            return [(int(p["t"]), int(round(float(p["v"])))) for p in item.get("values") or []
                    if p.get("v") is not None and p.get("q", 1) == 1]
    return []


def _value_at(changes: list[tuple[int, int]], t: int) -> int | None:
    value = None
    for ct, cv in changes:
        if ct > t:
            break
        value = cv
    return value


async def infer_batches_from_dcs(api: Any, unit: str, start: int, end: int) -> dict[str, Any]:
    """按本体登记的阶段识别条件，用开关量变位推断阶段；以第一个阶段（进料）的开始作为批次边界。"""
    rules = await api.get_json(f"/api/ontology/{quote(unit)}/stage-rules")
    stages = sorted(rules.get("stages") or [], key=lambda s: s.get("order") or 0)
    if not stages:
        return {"items": [], "notice": "本体没有为该设备定义工艺阶段，无法推断。"}
    unresolved = sorted({r["tag"] for s in stages for r in s.get("rules") or [] if not r.get("resolved")})
    tags = sorted({r["tag"] for s in stages for r in s.get("rules") or [] if r.get("resolved")})
    changes = {tag: await _raw_changes(api, tag, start, end) for tag in tags}
    missing = [t for t, c in changes.items() if not c]
    points = sorted({start, *[t for c in changes.values() for t, _ in c if start <= t < end]})
    fallback = next((s for s in stages if not s.get("rules")), None)

    def stage_at(t: int) -> dict[str, Any] | None:
        for s in stages:
            conds = s.get("rules") or []
            if conds and all(_value_at(changes.get(r["tag"]) or [], t) == r["value"] for r in conds):
                return s
        return fallback

    segments: list[list[Any]] = []  # [stage, start, end]
    for i, t in enumerate(points):
        s = stage_at(t)
        seg_end = points[i + 1] if i + 1 < len(points) else end
        if segments and segments[-1][0] is s:
            segments[-1][2] = seg_end
        else:
            segments.append([s, t, seg_end])

    first = stages[0]
    batches: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for s, a, b in segments:
        if s is first or current is None:
            current = {"phases": [], "partialStart": s is not first}
            batches.append(current)
        name = (s or {}).get("ebrPhase") or (s or {}).get("name") or "未识别"
        current["phases"].append({
            "phase": name, "startTime": a, "endTime": b, "startText": _fmt(a), "endText": _fmt(b),
            "stageId": (s or {}).get("id"), "limitMode": (s or {}).get("limitMode"),
        })
    items = []
    for n, b in enumerate(batches, 1):
        phases = b["phases"]
        # 只有「空闲」的片段不是批次
        if all(p["stageId"] == (fallback or {}).get("id") for p in phases):
            continue
        last = phases[-1]
        ongoing = last["endTime"] >= end and last["stageId"] != (fallback or {}).get("id")
        if ongoing:
            last["endTime"], last["endText"] = None, None
        reaction = next((p for p in phases if p["phase"] == DEFAULT_PHASE), None)
        items.append({
            "batchNo": None, "inferredId": f"DCS推断#{n}", "status": "进行中" if ongoing else "已完成",
            "partialStart": b["partialStart"], "enzymeLot": None, "enzymeBatchCount": None,
            "startTime": phases[0]["startTime"], "endTime": None if ongoing else last["endTime"],
            "startText": phases[0]["startText"], "endText": None if ongoing else last["endText"],
            "reactionStart": reaction["startTime"] if reaction else None,
            "reactionEnd": reaction["endTime"] if reaction else None,
            "phases": phases,
        })
    notice = []
    if unresolved:
        notice.append(f"点表里找不到的识别位号：{'、'.join(unresolved)}")
    if missing:
        notice.append(f"没有取到历史值的识别位号：{'、'.join(missing)}")
    return {"items": items, "rules": [{"stage": s["name"], "condition": s.get("dcsCondition")} for s in stages],
            "notice": "；".join(notice) or None, "scope": rules.get("scope")}


async def unit_batches(api: Any, unit: str, start: int, end: int) -> dict[str, Any]:
    """某设备时间范围内的批次。返回 {source, items, scope, notice, simulated}。"""
    try:
        data = await _ebr_batches(api, unit, start, end)
        return {"source": SOURCE_EBR, "items": data.get("items") or [], "scope": data.get("scope"),
                "simulated": bool((data.get("dataSource") or {}).get("simulated")), "notice": None}
    except ToolApiError as exc:
        if exc.kind == "not_found":
            raise BatchWindowError(f"「{unit}」不是定义了工艺阶段的设备实例，无法按批次取数：{exc}") from exc
        if exc.kind == "bad_request":
            raise BatchWindowError(str(exc)) from exc
        ebr_error = str(exc)
    inferred = await infer_batches_from_dcs(api, unit, start, end)
    notice = f"EBR 暂时取不到（{ebr_error[:80]}），按本体登记的 DCS 阶段识别条件推断；推断结果没有批号和换酶后批次数。"
    if inferred.get("notice"):
        notice += inferred["notice"]
    return {"source": SOURCE_DCS, "items": inferred["items"], "scope": inferred.get("scope"), "simulated": True,
            "notice": notice, "rules": inferred.get("rules")}


def _phase_span(batch: dict[str, Any], phase: str, now: int) -> tuple[int, int | None] | None:
    if phase == PHASE_WHOLE:
        return batch["startTime"], batch.get("endTime")
    hits = [p for p in batch.get("phases") or [] if p["phase"] == phase]
    if not hits:
        return None
    return hits[0]["startTime"], hits[-1].get("endTime")


def _batch_brief(b: dict[str, Any]) -> dict[str, Any]:
    out = {
        "batchNo": b.get("batchNo") or b.get("inferredId"),
        "status": b.get("status"),
        "start": b.get("startText"),
        "end": b.get("endText"),
        "reaction": (
            f"{_fmt(b['reactionStart'])} ~ {_fmt(b['reactionEnd']) or '进行中'}" if b.get("reactionStart") else None
        ),
        "enzymeBatchCount": b.get("enzymeBatchCount"),
        "enzymeLot": b.get("enzymeLot"),
    }
    if b.get("partialStart"):
        out["note"] = "批次开始早于查询范围，只看到后半段"
    return {k: v for k, v in out.items() if v is not None}


# ================================================================ 给分析工具用：按批次 / 阶段换算时间窗


def wants_batch_window(arguments: dict[str, Any]) -> bool:
    return bool(arguments.get("batchNo") or arguments.get("unit") or arguments.get("phase"))


async def resolve_batch_window(api: Any, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """把 batchNo / unit / phase 换算成时间窗。

    返回 None 表示没有给批次类参数（按原来的 startTime / endTime 处理）；否则返回
    {start, end, unit, basis}，start / end 为 yyyy-MM-dd HH:mm:ss，basis 写明时间窗依据。
    规则：
    - 给了 batchNo：取该批次的 phase 阶段（默认反应；全批 = 批次起止）；
    - 只给 unit（+ phase）且没给时间：取该设备最近一个该阶段已结束的批次；
    - 给了 unit 和 startTime/endTime、没给 phase：时间窗按用户给的，只把取数范围限定在该设备。
    """
    if not wants_batch_window(arguments):
        return None
    phase = arguments.get("phase") or DEFAULT_PHASE
    if phase not in PHASES:
        raise BatchWindowError(f"phase 只能取 {'、'.join(PHASES)}。")
    now = _now_ms()
    batch_no = (arguments.get("batchNo") or "").strip()
    unit = (arguments.get("unit") or "").strip()

    if batch_no:
        try:
            detail = await api.get_json(f"/api/ontology/batches/{quote(batch_no)}")
        except ToolApiError as exc:
            if exc.kind in ("not_found", "bad_request"):
                raise BatchWindowError(f"没有找到批次 {batch_no}：{exc}") from exc
            raise BatchWindowError(f"EBR 暂时取不到，无法按批号 {batch_no} 定位；可改用 unit + startTime/endTime。{exc}") from exc
        batch = detail["batch"]
        unit = (detail.get("scope") or {}).get("objectName") or unit
        source, simulated, notice = SOURCE_EBR, bool((detail.get("dataSource") or {}).get("simulated")), None
    else:
        if not unit:
            raise BatchWindowError("按阶段取时间窗需要知道是哪台设备：请给 unit（如 水解罐A）或 batchNo。")
        if (arguments.get("startTime") or arguments.get("endTime")) and not arguments.get("phase"):
            return {"start": None, "end": None, "unit": unit,
                    "basis": {"type": "用户时间窗", "unit": unit, "text": f"时间窗按用户给定，取数范围限定在「{unit}」"}}
        start, end = _range(arguments)
        got = await unit_batches(api, unit, start, end)
        source, simulated, notice = got["source"], got["simulated"], got["notice"]
        unit = (got.get("scope") or {}).get("objectName") or unit
        done = [b for b in got["items"] if (span := _phase_span(b, phase, now)) and span[1] is not None]
        if not done:
            raise BatchWindowError(
                f"「{unit}」在 {_fmt(start)} ~ {_fmt(end)} 内没有{phase}已结束的批次"
                + ("（只有进行中的批次，可传它的 batchNo 看到目前为止的数据）" if got["items"] else "")
                + "。",
                [_batch_brief(b) for b in got["items"][-MAX_BATCH_ROWS:]],
            )
        batch = done[-1]

    span = _phase_span(batch, phase, now)
    if not span:
        raise BatchWindowError(f"批次 {batch.get('batchNo') or batch.get('inferredId')} 还没有进入「{phase}」阶段。",
                               [_batch_brief(batch)])
    start_ms, end_ms = span
    ongoing = end_ms is None
    limit_mode = next((p.get("limitMode") for p in batch.get("phases") or [] if p["phase"] == phase), None)
    end_ms = end_ms or now
    label = batch.get("batchNo") or batch.get("inferredId")
    basis = {
        "type": "批次阶段",
        "unit": unit,
        "batchNo": label,
        "phase": phase,
        "source": source,
        "start": _fmt(start_ms),
        "end": _fmt(end_ms),
        "ongoing": ongoing,
        "enzymeBatchCount": batch.get("enzymeBatchCount"),
        "limitMode": limit_mode,
        "text": (
            f"时间窗 = {unit} 批次 {label} 的{phase if phase != PHASE_WHOLE else '整批'}"
            f"（{_fmt(start_ms)} ~ {_fmt(end_ms)}{'，阶段进行中，截至当前' if ongoing else ''}），来源 {source}"
            + (f"，换酶后第 {batch['enzymeBatchCount']} 批" if batch.get("enzymeBatchCount") else "")
        ),
    }
    if simulated:
        basis["simulated"] = True
    if notice:
        basis["notice"] = notice
    return {"start": _fmt(start_ms), "end": _fmt(end_ms), "unit": unit, "basis": basis}


def with_batch_window(handler: Any) -> Any:
    """包一层：入参带 batchNo / unit / phase 时，先换算出时间窗并把取数限定在该设备，再交给原分析工具。"""

    async def wrapped(registry: Any, arguments: dict[str, Any], api: Any) -> dict[str, Any]:
        try:
            resolved = await resolve_batch_window(api, arguments)
        except BatchWindowError as exc:
            return {"status": "needs_clarification", "message": str(exc), "candidates": exc.candidates}
        if not resolved:
            return await handler(registry, arguments, api)
        args = {k: v for k, v in arguments.items() if k not in ("batchNo", "phase", "unit")}
        if resolved["start"]:
            args["startTime"], args["endTime"] = resolved["start"], resolved["end"]
        token = UNIT_SCOPE.set(resolved["unit"])
        try:
            result = await handler(registry, args, api)
        finally:
            UNIT_SCOPE.reset(token)
        if isinstance(result, dict) and result.get("status") != "needs_clarification":
            result["windowBasis"] = resolved["basis"]
        return result

    wrapped.__name__ = getattr(handler, "__name__", "wrapped")
    wrapped.__wrapped__ = handler
    return wrapped


BATCH_WINDOW_PARAMS = (
    ToolParameter("unit", "string", "只看某一台设备（如 水解罐A）。给了 unit 没给时间时，时间窗取该罐最近一个已结束批次的 phase 阶段。"),
    ToolParameter("batchNo", "string", "按罐批次取时间窗（如 SJ-A-0830）；时间窗为该批次的 phase 阶段，不用再给 startTime/endTime。"),
    ToolParameter("phase", "string", f"配合 unit / batchNo：取批次的哪个阶段，默认 {DEFAULT_PHASE}；{PHASE_WHOLE} = 整批起止。", enum=PHASES),
)


# ================================================================ 工具：批次与运行上下文


async def get_batch_context(registry: Any, arguments: dict[str, Any], api: Any) -> dict[str, Any]:
    unit = (arguments.get("unit") or "").strip()
    batch_no = (arguments.get("batchNo") or "").strip()
    try:
        if batch_no:
            try:
                detail = await api.get_json(f"/api/ontology/batches/{quote(batch_no)}")
            except ToolApiError as exc:
                raise BatchWindowError(f"没有找到批次 {batch_no}：{exc}") from exc
            b = detail["batch"]
            return {
                "analysisType": "罐批次",
                "unit": (detail.get("scope") or {}).get("objectName"),
                "source": SOURCE_EBR,
                "batch": _batch_brief(b),
                "phases": [{k: p.get(k) for k in ("phase", "startText", "endText", "limitMode")} for p in b.get("phases") or []],
                "conclusion": _batch_sentence((detail.get("scope") or {}).get("objectName"), b),
                "simulated": bool((detail.get("dataSource") or {}).get("simulated")),
            }
        if not unit:
            raise BatchWindowError("请给出设备（unit，如 水解罐A）或批号（batchNo）。")
        start, end = _range(arguments)
        got = await unit_batches(api, unit, start, end)
    except BatchWindowError as exc:
        return {"status": "needs_clarification", "message": str(exc), "candidates": exc.candidates}

    unit_name = (got.get("scope") or {}).get("objectName") or unit
    items = got["items"]
    at = _parse_ms(arguments.get("at"), _now_ms()) if arguments.get("at") else None
    current = None
    if at is not None or not arguments.get("endTime"):
        probe = at if at is not None else _now_ms()
        for b in items:
            if b["startTime"] <= probe and (b.get("endTime") is None or probe < b["endTime"]):
                phase = next((p for p in b["phases"] if p["startTime"] <= probe and (p.get("endTime") is None or probe < p["endTime"])), None)
                current = {"at": _fmt(probe), "batch": _batch_brief(b), "phase": (phase or {}).get("phase"),
                           "limitMode": (phase or {}).get("limitMode")}
    shift = None
    if current:
        try:
            probe = _parse_ms(current["at"], _now_ms())
            data = await api.get_json("/api/ontology/shifts", {"startTime": probe - 3_600_000, "endTime": probe})
            s = next((x for x in data.get("items") or [] if x["startTime"] <= probe < x["endTime"]), None)
            if s:
                shift = f"{s.get('date')} {s.get('shift')} {s.get('team') or ''}".strip()
        except ToolApiError:
            shift = None
        current["shift"] = shift
    rows = [_batch_brief(b) for b in items[-MAX_BATCH_ROWS:]]
    counts = [b.get("enzymeBatchCount") for b in items if b.get("enzymeBatchCount")]
    durations = [round((b["reactionEnd"] - b["reactionStart"]) / 60_000) for b in items if b.get("reactionStart") and b.get("reactionEnd")]
    conclusion = f"「{unit_name}」{_fmt(start)} ~ {_fmt(end)} 共 {len(items)} 个批次（来源 {got['source']}）。"
    if durations:
        conclusion += f"已完成反应的 {len(durations)} 批，反应时长 {min(durations)}~{max(durations)} 分钟。"
    if counts:
        conclusion += f"换酶后批次数 {min(counts)}~{max(counts)}。"
    if current:
        conclusion += f"{current['at']} 处于批次 {current['batch'].get('batchNo')} 的{current['phase'] or '未识别'}阶段"
        conclusion += f"，班次 {shift}。" if shift else "。"
    result: dict[str, Any] = {
        "analysisType": "罐批次与运行上下文",
        "unit": unit_name,
        "range": {"start": _fmt(start), "end": _fmt(end)},
        "source": got["source"],
        "batchCount": len(items),
        "batches": rows,
        "current": current,
        "conclusion": conclusion,
        "next": "要分析某一批的数据时，把 batchNo（及 phase）传给分析工具，时间窗会自动落到该批次该阶段。",
    }
    if len(items) > MAX_BATCH_ROWS:
        result["truncationNote"] = f"共 {len(items)} 批，只列出最近 {MAX_BATCH_ROWS} 批。"
    if got.get("notice"):
        result["notice"] = got["notice"]
    if got.get("rules"):
        result["inferenceRules"] = got["rules"]
    if got.get("simulated"):
        result["simulated"] = True
    return result


def _batch_sentence(unit: str | None, b: dict[str, Any]) -> str:
    text = f"{unit or ''}批次 {b.get('batchNo')}（{b.get('status')}），{b.get('startText')} 开始"
    if b.get("reactionStart"):
        text += f"，反应 {_fmt(b['reactionStart'])} ~ {_fmt(b.get('reactionEnd')) or '进行中'}"
    if b.get("enzymeBatchCount"):
        text += f"，换酶后第 {b['enzymeBatchCount']} 批（酶批号 {b.get('enzymeLot')}）"
    return text + "。"


CONTEXT_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_batch_context",
        description=(
            "罐批次与运行上下文（固定程序）。问'A 罐最近几批''这一批什么时候开始反应、反应了多久''现在是第几批/换酶后第几批'"
            "'某时刻处于哪个阶段、哪个班'时调用；也用于在分析前先确定要看哪一批。"
            "程序先查 EBR（经本体代调），EBR 取不到时按本体登记的 DCS 阶段识别条件推断，并标明来源。"
        ),
        path="",
        parameters=(
            ToolParameter("unit", "string", "设备实例名称，如 水解罐A（目前定义了阶段的是水解罐 A～K）。"),
            ToolParameter("batchNo", "string", "批号，如 SJ-A-0830；给了批号就不用给 unit。"),
            ToolParameter("startTime", "string", f"查批次的范围开始，yyyy-MM-dd HH:mm:ss，默认 endTime 往前 {DEFAULT_LOOKBACK_DAYS} 天。"),
            ToolParameter("endTime", "string", "范围结束，默认当前时刻。"),
            ToolParameter("at", "string", "看某一时刻处于哪个批次 / 阶段 / 班次，默认当前时刻。"),
        ),
        group="analysis",
        summary="罐批次与运行上下文：批号、阶段起止、换酶后批次数、班次（EBR 优先，DCS 推断兜底）",
        returns=(
            "batches[]（批号、状态、起止、反应起止、换酶后批次数、酶批号）、current（当前或 at 时刻的批次 / 阶段 / 对应限值操作模式 / 班次）、"
            "source（EBR 或 DCS推断）、conclusion；按批号查时返回 batch 与 phases[]。"
        ),
        handler=get_batch_context,
    )
]

__all__ = [
    "BATCH_WINDOW_PARAMS",
    "CONTEXT_TOOLS",
    "BatchWindowError",
    "get_batch_context",
    "infer_batches_from_dcs",
    "resolve_batch_window",
    "unit_batches",
    "wants_batch_window",
    "with_batch_window",
]
