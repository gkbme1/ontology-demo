"""工序、工艺阶段与运行上下文（罐批次、换酶后批次计数、班次）。

本体里只放定义：工序与工段的对应、工序内的阶段及其识别依据（EBR 阶段名或 DCS 位号条件）、
运行上下文由哪个系统提供。批次、排班这些事实在外部系统（EBR、MOM），本体按对象代为查询，
和实时值 / 历史值的代调方式一样，并在返回里标明数据来源与是否模拟。

数据源 data/source/6APA_工序与阶段.xlsx（backend/tools/build_process_steps.py 生成预填版）。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from backend.ontology.models import Provenance

PROCESS_FILE_NAME = "6APA_工序与阶段.xlsx"
SHEET_STEPS = "工序"
SHEET_STAGES = "工艺阶段"
SHEET_CONTEXTS = "运行上下文"
STEP_COLUMNS = ["工序编号", "工序名称", "顺序", "主工段", "辅助工段", "说明", "状态"]
STAGE_COLUMNS = ["工序编号", "阶段编号", "阶段名称", "顺序", "适用设备组", "EBR阶段名", "DCS识别条件", "对应限值操作模式", "说明", "状态"]
CONTEXT_COLUMNS = ["上下文类型", "适用工序", "适用设备组", "来源系统", "能力ID", "关键字段", "说明", "状态"]

_SPLIT = re.compile(r"[、,，;；\s]+")


def _text(v: Any) -> str:
    t = "" if v is None else str(v).strip()
    return "" if t.lower() == "nan" else t


class ProcessModel:
    def __init__(self, file_name: str) -> None:
        self.file = file_name
        self.available = False
        self.steps: list[dict[str, Any]] = []
        self.stages: list[dict[str, Any]] = []
        self.contexts: list[dict[str, Any]] = []
        self.area_step: dict[str, dict[str, Any]] = {}  # 工段编号 → {step, role}
        self.load_stats: dict[str, Any] = {"file": file_name, "sheets": []}

    def step_of_area(self, area_code: str | None) -> dict[str, Any] | None:
        return self.area_step.get(area_code or "")

    def stages_for_group(self, group_name: str | None) -> list[dict[str, Any]]:
        return [s for s in self.stages if s["group"] and s["group"] == group_name]

    def view(self) -> dict[str, Any]:
        return {"steps": self.steps, "stages": self.stages, "contexts": self.contexts, "available": self.available,
                "source": PROCESS_FILE_NAME}


def parse_condition(text: str) -> list[tuple[str, int]]:
    """「P_1303{x}_RUN=1；XV_1304{x}_VAL2=0」→ [(模板, 值)]。"""
    out = []
    for part in re.split(r"[；;]", text or ""):
        if "=" in part:
            tpl, val = part.split("=", 1)
            if tpl.strip() and val.strip().lstrip("-").isdigit():
                out.append((tpl.strip(), int(val.strip())))
    return out


def load_process(path: Path, store: Any) -> ProcessModel:
    pm = ProcessModel(path.name)
    if not path.exists():
        return pm
    import pandas as pd

    pm.available = True
    sheets = {}
    for sheet in (SHEET_STEPS, SHEET_STAGES, SHEET_CONTEXTS):
        try:
            sheets[sheet] = pd.read_excel(path, sheet_name=sheet, dtype=str).fillna("").to_dict("records")
        except ValueError:
            sheets[sheet] = []
    dcs = store.dcs
    for i, rec in enumerate(sheets[SHEET_STEPS]):
        sid = _text(rec.get("工序编号"))
        if not sid:
            continue

        def areas(text: str) -> list[dict[str, Any]]:
            out = []
            for code in _SPLIT.split(text):
                aid = dcs.resolve_area(code) if code else None
                if aid:
                    out.append({"id": aid, "code": dcs.areas[aid]["code"], "name": dcs.areas[aid]["name"]})
            return out

        step = {
            "id": sid, "name": _text(rec.get("工序名称")), "order": int(_text(rec.get("顺序")) or 0),
            "mainAreas": areas(_text(rec.get("主工段"))), "auxAreas": areas(_text(rec.get("辅助工段"))),
            "description": _text(rec.get("说明")), "status": _text(rec.get("状态")) or "草案",
            "source": Provenance(path.name, SHEET_STEPS, i + 2).to_dict(),
        }
        pm.steps.append(step)
        for role, key in (("主工段", "mainAreas"), ("辅助工段", "auxAreas")):
            for a in step[key]:
                pm.area_step[a["code"]] = {"id": sid, "name": step["name"], "role": role}
    pm.steps.sort(key=lambda s: s["order"])
    step_names = {s["id"]: s["name"] for s in pm.steps}
    for i, rec in enumerate(sheets[SHEET_STAGES]):
        if not _text(rec.get("阶段名称")):
            continue
        cond = _text(rec.get("DCS识别条件"))
        pm.stages.append({
            "stepId": _text(rec.get("工序编号")), "stepName": step_names.get(_text(rec.get("工序编号")), ""),
            "id": _text(rec.get("阶段编号")), "name": _text(rec.get("阶段名称")), "order": int(_text(rec.get("顺序")) or 0),
            "group": _text(rec.get("适用设备组")), "ebrPhase": _text(rec.get("EBR阶段名")),
            "dcsCondition": cond, "dcsRules": [{"tag": t, "value": v} for t, v in parse_condition(cond)],
            "limitMode": _text(rec.get("对应限值操作模式")), "description": _text(rec.get("说明")),
            "status": _text(rec.get("状态")) or "草案", "source": Provenance(path.name, SHEET_STAGES, i + 2).to_dict(),
        })
    pm.stages.sort(key=lambda s: (s["stepId"], s["order"]))
    for i, rec in enumerate(sheets[SHEET_CONTEXTS]):
        if _text(rec.get("上下文类型")):
            pm.contexts.append({
                "type": _text(rec.get("上下文类型")), "step": _text(rec.get("适用工序")), "group": _text(rec.get("适用设备组")),
                "system": _text(rec.get("来源系统")), "capabilityId": _text(rec.get("能力ID")),
                "fields": _text(rec.get("关键字段")), "description": _text(rec.get("说明")),
                "status": _text(rec.get("状态")) or "草案", "source": Provenance(path.name, SHEET_CONTEXTS, i + 2).to_dict(),
            })
    pm.load_stats = {
        "file": path.name,
        "sheets": [{"sheet": s, "rows": len(sheets[s]), "validRows": len(sheets[s])} for s in sheets],
        "stepCount": len(pm.steps), "stageCount": len(pm.stages), "contextCount": len(pm.contexts),
    }
    return pm


# ------------------------------------------------------------------ EBR / MOM 代调

def _base(name: str) -> str:
    from backend.services import timeseries as ts

    return (os.environ.get(name) or ts.RTDB_BASE_URL).rstrip("/")


EBR_BATCHES_PATH = os.environ.get("EBR_BATCHES_PATH", "/api/ebr/v1/batches")
MOM_WORKTRANS_PATH = os.environ.get("MOM_WORKTRANS_PATH", "/api/mom/v1/worktrans")
TIMEOUT = float(os.environ.get("CONTEXT_TIMEOUT", "10"))


def ebr_base() -> str:
    return _base("EBR_BASE_URL")


def mom_base() -> str:
    return _base("MOM_BASE_URL")


def _get(url: str, params: dict[str, Any]) -> Any:
    from backend.services.timeseries import ApiError

    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    try:
        with urllib.request.urlopen(f"{url}?{query}" if query else url, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise ApiError(502, f"无法连接上游接口 {url}：{getattr(exc, 'reason', exc)}") from exc
    except Exception as exc:  # pragma: no cover
        raise ApiError(502, f"上游接口 {url} 返回无法解析：{exc}") from exc
    if payload.get("code", 0) != 0:
        status = 400 if str(payload.get("code", "")).startswith("400") else 502
        raise ApiError(status, f"上游接口返回错误 code={payload.get('code')}：{payload.get('message')}")
    return payload.get("data")


def _data_source(kind: str, label: str, base: str, path: str) -> dict[str, Any]:
    from backend.services.timeseries import _upstream_simulated

    simulated = _upstream_simulated(base)
    source = {"sourceType": kind, "sourceTypeLabel": label, "endpoint": f"{base}{path}", "simulated": simulated}
    if simulated:
        source["notice"] = "当前接入的是模拟服务，批次 / 排班数据按排程规则生成，不是现场真实记录。"
    return source


def _equipment(store: Any, object_id: str) -> dict[str, Any]:
    from backend.services.timeseries import ApiError

    dcs = store.dcs
    equip = None
    if object_id.startswith(":"):
        equip = dcs.equipment_by_owl(object_id)
    elif object_id in dcs.equipment:
        equip = dcs.equipment[object_id]
    else:
        hits = [e for e in dcs.equipment_by_name(object_id) if e.get("nature", "实例") == "实例"]
        equip = hits[0] if len(hits) == 1 else None
    if not equip:
        raise ApiError(404, f"未找到设备：{object_id}（批次上下文按设备实例查询，可传 equip- ID、OWL Subject 或设备名）")
    group = dcs.equipment_groups.get(equip.get("equipmentGroupId") or "")
    if not group or not store.process.stages_for_group(group["name"]):
        raise ApiError(404, f"「{equip['name']}」所属设备组没有定义工艺阶段与批次上下文（目前只有水解罐 A～K 定义了）")
    return equip


def _ms(value: Any, field: str) -> int | None:
    if value in (None, ""):
        return None
    from backend.services.timeseries import parse_time

    return parse_time(value, field)


def batches(store: Any, object_id: str, q: dict[str, Any]) -> dict[str, Any]:
    """设备实例的罐批次（EBR）：批号、换酶后批次数、反应起止、各阶段起止。"""
    equip = _equipment(store, object_id)
    group = store.dcs.equipment_groups[equip["equipmentGroupId"]]
    data = _get(f"{ebr_base()}{EBR_BATCHES_PATH}", {
        "unit": equip["name"], "startTime": _ms(q.get("startTime"), "startTime"), "endTime": _ms(q.get("endTime"), "endTime"),
    })
    items = data.get("items") or []
    try:
        limit = max(1, min(200, int(q.get("limit") or 50)))
    except ValueError:
        limit = 50
    _annotate(store, group["name"], items)
    return {
        "scope": {"objectId": equip["id"], "objectName": equip["name"], "group": group["name"],
                  "step": (store.process.step_of_area(equip.get("areaCode")) or {}).get("name")},
        "total": len(items), "items": items[-limit:],
        "dataSource": _data_source("EBR", "电子批记录", ebr_base(), EBR_BATCHES_PATH),
    }


def _annotate(store: Any, group_name: str, items: list[dict[str, Any]]) -> None:
    stages = {s["ebrPhase"]: s for s in store.process.stages_for_group(group_name)}
    for b in items:
        for p in b.get("phases") or []:
            stage = stages.get(p["phase"])
            if stage:
                p["stageId"], p["limitMode"] = stage["id"], stage["limitMode"]


def batch_detail(store: Any, batch_no: str) -> dict[str, Any]:
    """按批号查一个罐批次（EBR），并落到本体设备实例上。"""
    from backend.services.timeseries import ApiError

    try:
        batch = _get(f"{ebr_base()}{EBR_BATCHES_PATH}/{urllib.parse.quote(batch_no.strip())}", {})
    except ApiError as exc:
        if exc.status == 400:
            raise ApiError(404, f"EBR 中没有批次 {batch_no}：{exc}") from exc
        raise
    if not isinstance(batch, dict) or not batch.get("unit"):
        raise ApiError(404, f"EBR 中没有批次 {batch_no}")
    equip = _equipment(store, batch["unit"])
    group = store.dcs.equipment_groups[equip["equipmentGroupId"]]
    _annotate(store, group["name"], [batch])
    return {
        "scope": {"objectId": equip["id"], "objectName": equip["name"], "group": group["name"],
                  "step": (store.process.step_of_area(equip.get("areaCode")) or {}).get("name")},
        "batch": batch,
        "dataSource": _data_source("EBR", "电子批记录", ebr_base(), EBR_BATCHES_PATH),
    }


_UNIT_CODE = re.compile(r"([A-Za-z0-9]+)$")


def unit_scope(store: Any, unit: str) -> tuple[dict[str, Any], set[str]]:
    """「某一台」的范围：本台设备 + 同工段里按台号一一对应的成组设备（水解罐A → 氨水计量罐A）。

    组内按台号一一对应的设备（各罐自带的计量罐、搅拌、阀门）在点表里常挂在别的设备名下，
    按工艺量取数时要一起算进「这一台」。返回 (设备, 设备 ID 集合)。
    """
    from backend.services.instance_links import _letter
    from backend.services.timeseries import ApiError

    dcs = store.dcs
    equip = dcs.equipment.get(unit)
    if not equip:
        hits = [e for e in dcs.equipment_by_name(unit) if e.get("nature", "实例") == "实例"]
        equip = hits[0] if len(hits) == 1 else None
    if not equip:
        raise ApiError(404, f"未找到设备：{unit}（unit 传设备实例名称或 equip- ID，如 水解罐A）")
    ids = {equip["id"]}
    letter = _letter(equip["name"])
    if letter:
        def size(gid: str | None) -> int:
            return sum(1 for e in dcs.equipment.values() if gid and e.get("equipmentGroupId") == gid)

        own = size(equip.get("equipmentGroupId"))
        for e in dcs.equipment.values():
            gid = e.get("equipmentGroupId")
            # 只认台数与本组相当的组（按台号一一对应）；RB储罐A/B 这种两台供十一台的是汇管，不算「这一台」的
            if (e.get("areaCode") == equip.get("areaCode") and e.get("nature", "实例") == "实例" and gid
                    and _letter(e["name"]) == letter and size(gid) >= 0.6 * own):
                ids.add(e["id"])
    return equip, ids


def stage_rules(store: Any, object_id: str) -> dict[str, Any]:
    """设备实例的阶段识别规则，模板里的 {x} 换成本设备的罐号、落到具体 DCS 位号。

    供 EBR 取不到时由调用方（Agent）按 DCS 开关量推断阶段：本体只给定义，不做推断。
    罐号取设备名称末尾的字母数字（水解罐A → A）；换出来的位号在点表里查不到的标 resolved=false。
    """
    equip = _equipment(store, object_id)
    group = store.dcs.equipment_groups[equip["equipmentGroupId"]]
    m = _UNIT_CODE.search(equip["name"])
    code = m.group(1) if m else ""
    names = {t.get("name") for t in store.dcs.tags.values()}
    stages = []
    for s in store.process.stages_for_group(group["name"]):
        rules = []
        for r in s["dcsRules"]:
            tag = r["tag"].replace("{x}", code)
            rules.append({"template": r["tag"], "tag": tag, "value": r["value"], "resolved": tag in names})
        stages.append({k: s[k] for k in ("id", "name", "order", "ebrPhase", "limitMode", "dcsCondition", "status", "source")}
                      | {"rules": rules})
    return {
        "scope": {"objectId": equip["id"], "objectName": equip["name"], "group": group["name"]},
        "unitCode": code,
        "stages": stages,
        "note": "阶段按顺序判定：满足某阶段全部条件即为该阶段；都不满足（无条件的阶段）为其余状态。定义为草案，待工艺确认。",
    }


def shifts(store: Any, q: dict[str, Any]) -> dict[str, Any]:
    data = _get(f"{mom_base()}{MOM_WORKTRANS_PATH}", {
        "startTime": _ms(q.get("startTime"), "startTime"), "endTime": _ms(q.get("endTime"), "endTime"),
    })
    return {"total": data.get("total", 0), "items": data.get("items") or [], "rule": data.get("rule"),
            "dataSource": _data_source("MOM", "MOM 排班（worktrans）", mom_base(), MOM_WORKTRANS_PATH)}


def context(store: Any, object_id: str, q: dict[str, Any]) -> dict[str, Any]:
    """设备实例在某一时刻的运行上下文：所在罐批次、阶段、换酶后批次数、班次、该阶段对应的限值操作模式。"""
    at = _ms(q.get("at"), "at") or int(time.time() * 1000)
    window = {"startTime": at - 2 * 86_400_000, "endTime": at}
    result = batches(store, object_id, window)
    batch = next((b for b in reversed(result["items"]) if b["startTime"] <= at and (b["endTime"] is None or at < b["endTime"])), None)
    phase = None
    if batch:
        phase = next((p for p in batch["phases"] if p["startTime"] <= at and (p["endTime"] is None or at < p["endTime"])), None)
    shift = None
    try:
        shift = next((s for s in shifts(store, {"startTime": at - 3_600_000, "endTime": at})["items"]
                      if s["startTime"] <= at < s["endTime"]), None)
    except Exception:  # 排班取不到不影响批次上下文
        shift = None
    return {
        "scope": result["scope"], "at": at,
        "batch": {k: batch[k] for k in ("batchNo", "status", "enzymeLot", "enzymeBatchCount", "startTime", "reactionStart",
                                        "reactionEnd", "startText")} if batch else None,
        "phase": phase, "shift": shift,
        "notice": None if batch else "该时刻不在任何罐批次内（两批之间或无记录）",
        "dataSource": result["dataSource"],
    }
