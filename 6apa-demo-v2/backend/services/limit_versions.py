"""限值版本：工艺限值的条件化与动态修改（在线修改、版本、生效时间）。

- 6APA_工艺限值.xlsx 里的每条限值是该限值的基础版本（V0，自始生效，来源按「依据类型」）；
- 6APA_限值版本.xlsx「限值版本」工作表登记后续版本：适用设备、换酶后批次区间、六档取值、来源类型
  （人工设定 / 模型最优值±差值 / 规程 / 推断）、最优值与差值、生效 / 失效时间、状态、修改人、修改原因；
- 工艺员在线修改限值 = 追加一个版本（POST），不改旧版本，修改人、原因、记录时间留在表里；
- 查「某时刻、某台、换酶后第几批」的生效限值：条件都匹配的版本中取生效时间最晚的一个，没有则用 V0。
  版本里留空的档位沿用 V0；来源为「模型最优值±差值」且没填正常区间时，正常区间 = 最优值 ± 差值。

本体只登记限值版本与匹配规则；按「异常发生时的生效限值」逐点判断由 Agent 的固定程序执行。
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.services import process_limits

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "data" / "source" / "6APA_限值版本.xlsx"
SHEET = "限值版本"
COLUMNS = ["版本编号", "限值编号", "适用设备", "换酶后批次下限", "换酶后批次上限", "低低限 LL", "低限 L", "正常下限",
           "正常上限", "高限 H", "高高限 HH", "来源类型", "最优值", "差值", "生效时间", "失效时间", "状态", "修改人",
           "修改原因", "记录时间"]
VALUE_KEYS = ("lowLow", "low", "normalLow", "normalHigh", "high", "highHigh")
SOURCE_TYPES = ("人工设定", "模型最优值±差值", "规程", "推断")
TZ = timezone(timedelta(hours=8))
TIME_FMT = "%Y-%m-%d %H:%M:%S"
MATCH_RULE = ("条件（适用设备、换酶后批次区间、生效 / 失效时间）都匹配的版本中取生效时间最晚的一个；都不匹配时用基础版本 V0。"
              "版本里留空的档位沿用 V0；「模型最优值±差值」未填正常区间时按 最优值 ± 差值。"
              "限值只在其「适用工况」对应的工艺阶段内判断（见 6APA_工序与阶段.xlsx 的「对应限值操作模式」）。")

_cache: dict[str, Any] = {"mtime": None, "items": []}
_lock = threading.Lock()


class VersionError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _num(v: Any) -> float | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _ms(v: Any) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return int((v if v.tzinfo else v.replace(tzinfo=TZ)).timestamp() * 1000)
    if isinstance(v, (int, float)):
        return int(v)
    raw = str(v).strip()
    if raw.isdigit():
        return int(raw)
    for fmt in (TIME_FMT, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(raw, fmt).replace(tzinfo=TZ).timestamp() * 1000)
        except ValueError:
            continue
    raise VersionError(400, f"时间格式无法识别：{raw}（用 yyyy-MM-dd HH:mm:ss）")


def _fmt(ms: int | None) -> str | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, TZ).strftime(TIME_FMT)


def _load() -> list[dict[str, Any]]:
    if not VERSION_FILE.is_file():
        return []
    mtime = VERSION_FILE.stat().st_mtime
    with _lock:
        if _cache["mtime"] == mtime:
            return _cache["items"]
        from openpyxl import load_workbook

        wb = load_workbook(VERSION_FILE, read_only=True, data_only=True)
        ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]
        items = []
        for index, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            cell = lambda i: row[i] if row and len(row) > i else None  # noqa: E731
            if not _text(cell(0)) or not _text(cell(1)):
                continue
            items.append(_row_view([cell(i) for i in range(len(COLUMNS))], {"file": VERSION_FILE.name, "sheet": ws.title, "row": index}))
        wb.close()
        _cache.update(mtime=mtime, items=items)
        return items


def _row_view(row: list[Any], source: dict[str, Any]) -> dict[str, Any]:
    v = {
        "id": _text(row[0]), "limitId": _text(row[1]), "unit": _text(row[2]),
        "enzymeMin": _num(row[3]), "enzymeMax": _num(row[4]),
        **{k: _num(row[5 + i]) for i, k in enumerate(VALUE_KEYS)},
        "sourceType": _text(row[11]) or "人工设定", "optimum": _num(row[12]), "delta": _num(row[13]),
        "effectiveFrom": None, "effectiveTo": None, "status": _text(row[16]) or "草案", "editor": _text(row[17]),
        "reason": _text(row[18]), "recordedAt": _text(row[19]), "source": source, "base": False,
    }
    try:
        v["effectiveFrom"], v["effectiveTo"] = _ms(row[14]), _ms(row[15])
    except VersionError:
        v["invalid"] = "生效 / 失效时间无法识别"
    if v["sourceType"] == "模型最优值±差值" and v["normalLow"] is None and v["normalHigh"] is None \
            and v["optimum"] is not None and v["delta"] is not None:
        v["normalLow"], v["normalHigh"] = round(v["optimum"] - v["delta"], 4), round(v["optimum"] + v["delta"], 4)
    v["effectiveFromText"], v["effectiveToText"] = _fmt(v["effectiveFrom"]), _fmt(v["effectiveTo"])
    v["conditionText"] = _condition_text(v)
    return v


def _condition_text(v: dict[str, Any]) -> str:
    parts = []
    if v.get("unit"):
        parts.append(f"仅 {v['unit']}")
    if v.get("enzymeMin") is not None or v.get("enzymeMax") is not None:
        lo = int(v["enzymeMin"]) if v.get("enzymeMin") is not None else 1
        hi = int(v["enzymeMax"]) if v.get("enzymeMax") is not None else "∞"
        parts.append(f"换酶后第 {lo}～{hi} 批")
    return "；".join(parts) or "全部"


def _limit(limit_id: str) -> dict[str, Any]:
    hit = next((x for x in process_limits._load() if x["id"] == limit_id), None)
    if not hit:
        raise VersionError(404, f"未找到工艺限值：{limit_id}")
    return hit


def _base(limit: dict[str, Any]) -> dict[str, Any]:
    basis = limit.get("basisType") or ""
    source_type = "规程" if "规程" in basis else "推断"
    return {
        "id": f"{limit['id']}-V0", "limitId": limit["id"], "unit": "", "enzymeMin": None, "enzymeMax": None,
        **{k: limit.get(k) for k in VALUE_KEYS}, "sourceType": source_type, "optimum": None, "delta": None,
        "effectiveFrom": None, "effectiveTo": None, "effectiveFromText": None, "effectiveToText": None,
        "status": limit.get("status"), "editor": "", "reason": f"基础版本（{process_limits.LIMIT_FILE.name}，依据类型：{basis or '未填'}）",
        "recordedAt": "", "conditionText": "全部", "source": limit.get("source"), "base": True,
    }


def versions(store: Any, limit_id: str) -> dict[str, Any]:
    limit = _limit(limit_id)
    own = sorted((v for v in _load() if v["limitId"] == limit_id), key=lambda v: (v["effectiveFrom"] or 0, v["id"]))
    return {
        "limit": {k: limit.get(k) for k in ("id", "appliesTo", "appliesToType", "area", "operatingMode", "parameter", "unit",
                                            "status", "basis")},
        "items": [_base(limit), *own], "total": len(own) + 1, "matchRule": MATCH_RULE,
        "source": {"file": VERSION_FILE.name, "sheet": SHEET}, "available": VERSION_FILE.is_file(),
    }


def _matches(v: dict[str, Any], at: int, unit: str, count: int | None) -> tuple[bool, str]:
    if v.get("invalid"):
        return False, v["invalid"]
    if v["effectiveFrom"] is not None and at < v["effectiveFrom"]:
        return False, "尚未生效"
    if v["effectiveTo"] is not None and at >= v["effectiveTo"]:
        return False, "已失效"
    if v["unit"] and unit and v["unit"] != unit:
        return False, "适用设备不同"
    if v["unit"] and not unit:
        return False, "限定设备，但未指明设备"
    if v["enzymeMin"] is not None or v["enzymeMax"] is not None:
        if count is None:
            return False, "限定换酶后批次区间，但不知道换酶后批次数"
        if (v["enzymeMin"] is not None and count < v["enzymeMin"]) or (v["enzymeMax"] is not None and count > v["enzymeMax"]):
            return False, "换酶后批次数不在区间内"
    return True, "匹配"


def resolve(store: Any, limit_id: str, at: int, unit: str = "", count: int | None = None) -> dict[str, Any]:
    limit = _limit(limit_id)
    base = _base(limit)
    chosen, checks = None, []
    for v in sorted((v for v in _load() if v["limitId"] == limit_id), key=lambda v: (v["effectiveFrom"] or 0, v["id"])):
        ok, why = _matches(v, at, unit, count)
        checks.append({"versionId": v["id"], "matched": ok, "reason": why})
        if ok:
            chosen = v  # 按生效时间升序，最后一个匹配的即最晚生效
    picked = chosen or base
    values = {k: (picked[k] if picked[k] is not None else base[k]) for k in VALUE_KEYS}
    return {
        "limitId": limit_id, "appliesTo": limit["appliesTo"], "operatingMode": limit["operatingMode"], "unit": limit["unit"],
        "at": at, "atText": _fmt(at), "conditions": {"unit": unit or None, "enzymeBatchCount": count},
        "version": {k: picked[k] for k in ("id", "sourceType", "status", "editor", "reason", "effectiveFromText",
                                           "effectiveToText", "conditionText", "optimum", "delta", "base")},
        "values": values, "checks": checks, "matchRule": MATCH_RULE,
    }


def effective(store: Any, limit_id: str, q: dict[str, Any]) -> dict[str, Any]:
    at = _ms(q.get("at")) or int(time.time() * 1000)
    count = q.get("enzymeBatchCount")
    try:
        count = int(count) if count not in (None, "") else None
    except ValueError as exc:
        raise VersionError(400, "enzymeBatchCount 必须是整数") from exc
    return resolve(store, limit_id, at, (q.get("unit") or "").strip(), count)


def add_version(store: Any, limit_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """在线修改限值 = 追加一个版本。必须写明修改人与原因；不改旧版本。"""
    limit = _limit(limit_id)
    if not isinstance(body, dict):
        raise VersionError(400, "请求体必须是 JSON 对象")
    editor, reason = _text(body.get("editor")), _text(body.get("reason"))
    if not editor or not reason:
        raise VersionError(400, "修改限值必须填写修改人（editor）与修改原因（reason）")
    source_type = _text(body.get("sourceType")) or "人工设定"
    if source_type not in SOURCE_TYPES:
        raise VersionError(400, f"sourceType 只能取 {'、'.join(SOURCE_TYPES)}")
    values = {k: _num(body.get(k)) for k in VALUE_KEYS}
    optimum, delta = _num(body.get("optimum")), _num(body.get("delta"))
    if source_type == "模型最优值±差值":
        if optimum is None or delta is None or delta <= 0:
            raise VersionError(400, "来源为「模型最优值±差值」时须给出最优值 optimum 与正的差值 delta")
    elif all(values[k] is None for k in VALUE_KEYS):
        raise VersionError(400, "至少要改一档限值")
    merged = {k: values[k] if values[k] is not None else limit.get(k) for k in VALUE_KEYS}
    if source_type == "模型最优值±差值" and values["normalLow"] is None and values["normalHigh"] is None:
        merged["normalLow"], merged["normalHigh"] = optimum - delta, optimum + delta
    order = [merged[k] for k in VALUE_KEYS if merged[k] is not None]
    if order != sorted(order):
        raise VersionError(400, "限值须满足 低低限 ≤ 低限 ≤ 正常下限 ≤ 正常上限 ≤ 高限 ≤ 高高限（留空的档位沿用基础版本）")
    effective_from = _ms(body.get("effectiveFrom")) or int(time.time() * 1000)
    effective_to = _ms(body.get("effectiveTo"))
    if effective_to is not None and effective_to <= effective_from:
        raise VersionError(400, "失效时间必须晚于生效时间")
    emin, emax = _num(body.get("enzymeMin")), _num(body.get("enzymeMax"))
    if emin is not None and emax is not None and emin > emax:
        raise VersionError(400, "换酶后批次下限不能大于上限")
    unit = _text(body.get("unit"))
    if unit and not [e for e in store.dcs.equipment_by_name(unit) if e.get("nature", "实例") == "实例"]:
        raise VersionError(400, f"未找到设备实例：{unit}")

    from openpyxl import Workbook, load_workbook

    with _lock:
        if VERSION_FILE.is_file():
            wb = load_workbook(VERSION_FILE)
            ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = SHEET
            ws.append(COLUMNS)
        n = sum(1 for r in ws.iter_rows(min_row=2, values_only=True) if r and r[1] == limit_id)
        vid = f"{limit_id}-V{n + 1}"
        while any(r and r[0] == vid for r in ws.iter_rows(min_row=2, values_only=True)):
            n += 1
            vid = f"{limit_id}-V{n + 1}"
        row = [vid, limit_id, unit, emin, emax, *[values[k] for k in VALUE_KEYS], source_type, optimum, delta,
               _fmt(effective_from), _fmt(effective_to), _text(body.get("status")) or "已生效·待复核", editor, reason,
               _fmt(int(time.time() * 1000))]
        ws.append(row)
        index = ws.max_row
        wb.save(VERSION_FILE)
        _cache["mtime"] = None
    return {"created": _row_view(row, {"file": VERSION_FILE.name, "sheet": SHEET, "row": index}),
            "note": "已追加为新版本，旧版本保留；判断历史数据时按当时生效的版本。"}


def summary_for(limit_id: str) -> dict[str, Any]:
    own = [v for v in _load() if v["limitId"] == limit_id]
    return {"versionCount": len(own) + 1, "conditional": any(v["unit"] or v["enzymeMin"] is not None or v["enzymeMax"] is not None
                                                              for v in own)}
