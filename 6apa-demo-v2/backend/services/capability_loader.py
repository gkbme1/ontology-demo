"""能力登记表：本体挂载的能力 = 能力描述 + 调用契约 + 本对象参数绑定。

能力由外部系统实现（实时库、历史库、OPAS 动作程序、推理引擎、模型平台……），本体不实现，
只登记「这类对象能做什么、由谁提供、怎么调用、需要哪些参数」，并在具体对象上把参数绑定好
（例如实时值查询的 nodeIds 绑定为水解罐A 的 17 个位号）。调用时仍去调提供方。

数据源 data/source/能力.xlsx（backend/tools/build_capability_table.py 生成预填版）：
- 「能力」工作表：能力ID、能力名称、能力类型、能力描述、适用对象、适用设备类型、提供方、调用方式、
  端点、本体代调入口、输出、前置条件、登记状态、说明；
- 「能力参数」工作表：能力ID、参数名、类型、必填、说明、绑定。

绑定写法：
- 本对象位号            对象解析出的全部 DCS 位号
- 本对象位号[过程测量]  只取某类位号，可选 过程测量 / 状态 / 启停 / 调节
- …→nodeId              按实时库 nodeId 规则拼接（RTDB_NODE_ID_TEMPLATE，默认 {station}:{name}.PV）
- 本对象ID / 本对象名称 / 本对象适用规则
- 调用方提供            调用时由使用方给出（时间窗、指令值等）
- 常量:xxx              固定取值
必填参数的绑定在某个对象上取不到值时，该能力不适用于这个对象，不在档案里显示。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.ontology.models import Provenance

CAPABILITY_FILE_NAME = "能力.xlsx"
SHEET_CAPS = "能力"
SHEET_PARAMS = "能力参数"

CAP_COLUMNS = ["能力ID", "能力名称", "能力类型", "能力描述", "适用对象", "适用设备类型", "提供方", "调用方式",
               "端点", "本体代调入口", "输出", "前置条件", "登记状态", "说明"]
PARAM_COLUMNS = ["能力ID", "参数名", "类型", "必填", "说明", "绑定"]

STATUS_REGISTERED = "已登记"
STATUS_PENDING = "待登记"
# 对象上的挂载状态
MOUNT_CALLABLE = "可调用"
MOUNT_PENDING = "提供方待登记"

OBJECT_KINDS = {"设备": "equipment", "设备组": "group", "工段": "area", "工艺对象": "entity"}
TAG_FILTERS = {
    "过程测量": lambda t: (t.get("parameterType") or "").startswith("过程测量") or t.get("blockType") in ("AI", "PID"),
    "状态": lambda t: (t.get("parameterType") or "").startswith("状态反馈"),
    "启停": lambda t: t.get("blockType") in ("DO", "DOV") or "启停" in (t.get("variableCategory") or "")
    or "开关指令" in (t.get("variableCategory") or ""),
    "调节": lambda t: t.get("blockType") == "AO" or (t.get("parameterType") or "").startswith("控制输出")
    or "开度" in (t.get("variableCategory") or ""),
}
_TAG_BINDING = re.compile(r"^本对象位号(?:\[(?P<filter>[^\]]+)\])?(?:→(?P<form>nodeId|位号))?$")
PREVIEW = 8  # 每个参数在档案里最多列出的绑定值


class CapabilitySet:
    def __init__(self, file_name: str) -> None:
        self.file = file_name
        self.available = False
        self.items: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.load_stats: dict[str, Any] = {}


def _text(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() == "nan" else text


def load_capabilities(path: Path) -> CapabilitySet:
    caps = CapabilitySet(path.name)
    if not path.exists():
        caps.load_stats = {"file": path.name, "sheets": []}
        return caps
    import pandas as pd

    caps.available = True
    cap_df = pd.read_excel(path, sheet_name=SHEET_CAPS, dtype=str).fillna("")
    try:
        param_df = pd.read_excel(path, sheet_name=SHEET_PARAMS, dtype=str).fillna("")
    except ValueError:
        param_df = pd.DataFrame(columns=PARAM_COLUMNS)

    params: dict[str, list[dict[str, Any]]] = {}
    for i, rec in enumerate(param_df.to_dict("records")):
        cid = _text(rec.get("能力ID"))
        if not cid or not _text(rec.get("参数名")):
            continue
        binding = _text(rec.get("绑定")) or "调用方提供"
        if not _valid_binding(binding):
            caps.issues.append({"severity": "warning", "check": "能力参数绑定无法识别",
                                "detail": f"{cid}.{rec.get('参数名')} 的绑定「{binding}」无法识别，按 调用方提供 处理",
                                "source": Provenance(path.name, SHEET_PARAMS, i + 2).to_dict()})
            binding = "调用方提供"
        params.setdefault(cid, []).append({
            "name": _text(rec.get("参数名")),
            "type": _text(rec.get("类型")) or "string",
            "required": _text(rec.get("必填")) in ("是", "Y", "y", "yes", "必填", "1", "true", "True"),
            "description": _text(rec.get("说明")),
            "binding": binding,
            "source": Provenance(path.name, SHEET_PARAMS, i + 2).to_dict(),
        })

    for i, rec in enumerate(cap_df.to_dict("records")):
        cid = _text(rec.get("能力ID"))
        if not cid:
            continue
        kinds = [k for k in re.split(r"[、,，\s]+", _text(rec.get("适用对象"))) if k]
        status = _text(rec.get("登记状态")) or STATUS_PENDING
        caps.items.append({
            "id": cid,
            "name": _text(rec.get("能力名称")),
            "type": _text(rec.get("能力类型")),
            "description": _text(rec.get("能力描述")),
            "appliesTo": kinds,
            "appliesToKinds": [OBJECT_KINDS[k] for k in kinds if k in OBJECT_KINDS],
            "equipmentTypes": [k for k in re.split(r"[、,，\s]+", _text(rec.get("适用设备类型"))) if k],
            "provider": _text(rec.get("提供方")),
            "protocol": _text(rec.get("调用方式")),
            "endpoint": _text(rec.get("端点")),
            "gateway": _text(rec.get("本体代调入口")),
            "output": _text(rec.get("输出")),
            "preconditions": _text(rec.get("前置条件")),
            "registration": status if status in (STATUS_REGISTERED, STATUS_PENDING) else STATUS_PENDING,
            "note": _text(rec.get("说明")),
            "parameters": params.get(cid, []),
            "source": Provenance(path.name, SHEET_CAPS, i + 2).to_dict(),
        })
    caps.load_stats = {
        "file": path.name,
        "sheets": [{"sheet": SHEET_CAPS, "rows": len(cap_df), "validRows": len(caps.items)},
                   {"sheet": SHEET_PARAMS, "rows": len(param_df), "validRows": sum(len(v) for v in params.values())}],
        "capabilityCount": len(caps.items),
        "registeredCount": sum(1 for c in caps.items if c["registration"] == STATUS_REGISTERED),
    }
    return caps


def _valid_binding(binding: str) -> bool:
    if binding in ("本对象ID", "本对象名称", "本对象适用规则", "调用方提供") or binding.startswith("常量:"):
        return True
    m = _TAG_BINDING.match(binding)
    return bool(m) and (not m.group("filter") or m.group("filter") in TAG_FILTERS)


def expand_endpoint(text: str) -> str:
    """端点里的 {RTDB_BASE_URL} / {HISTORIAN_BASE_URL} 按本体服务的实际配置展开。"""
    from backend.services import process_context as pc
    from backend.services import timeseries as ts

    return (text.replace("{RTDB_BASE_URL}", ts.RTDB_BASE_URL).replace("{HISTORIAN_BASE_URL}", ts.HISTORIAN_BASE_URL)
            .replace("{EBR_BASE_URL}", pc.ebr_base()).replace("{MOM_BASE_URL}", pc.mom_base())
            .replace("{LIMS_BASE_URL}", pc.lims_base()).replace("{OPLOG_BASE_URL}", pc.oplog_base()))


def bind(binding: str, *, object_id: str, tags: list[dict[str, Any]], rules: list[dict[str, Any]],
         object_name: str = "") -> dict[str, Any]:
    """在对象上解析一个参数绑定：返回 {bound, values（预览）, total, text}。"""
    if binding == "调用方提供":
        return {"bound": None, "values": [], "total": 0, "text": "调用时由使用方给出"}
    if binding.startswith("常量:"):
        value = binding[3:]
        return {"bound": True, "values": [value], "total": 1, "text": f"固定为 {value}"}
    if binding == "本对象ID":
        return {"bound": True, "values": [object_id], "total": 1, "text": "本对象 ID"}
    if binding == "本对象名称":
        return {"bound": bool(object_name), "values": [object_name] if object_name else [], "total": 1 if object_name else 0,
                "text": f"本对象名称「{object_name}」"}
    if binding == "本对象适用规则":
        ids = [r.get("ruleId") or r.get("id") for r in rules]
        return {"bound": bool(ids), "values": ids[:PREVIEW], "total": len(ids), "text": f"本对象适用的 {len(ids)} 条规则"}
    m = _TAG_BINDING.match(binding)
    if not m:
        return {"bound": None, "values": [], "total": 0, "text": "调用时由使用方给出"}
    flt = m.group("filter")
    picked = [t for t in tags if TAG_FILTERS[flt](t)] if flt else list(tags)
    if m.group("form") == "nodeId":
        from backend.services.timeseries import NODE_ID_TEMPLATE, node_id_for

        values = [node_id_for(t) for t in picked[:PREVIEW]]
        text = f"本对象{flt or ''}位号 {len(picked)} 个，按 {NODE_ID_TEMPLATE} 拼成 nodeId"
    else:
        values = [t["name"] for t in picked[:PREVIEW]]
        text = f"本对象{flt or ''}位号 {len(picked)} 个"
    return {"bound": bool(picked), "values": values, "total": len(picked), "text": text}


def capabilities_for(caps: CapabilitySet, kind: str, object_id: str, *, tags: list[dict[str, Any]],
                     rules: list[dict[str, Any]], equipment_type: str | None = None, object_name: str = "") -> list[dict[str, Any]]:
    """对象的能力挂载：适用的能力 + 本对象上的参数绑定。必填参数绑定不上的能力不适用。"""
    out = []
    for cap in caps.items:
        if kind not in cap["appliesToKinds"]:
            continue
        if cap["equipmentTypes"] and equipment_type not in cap["equipmentTypes"]:
            continue
        params, applicable = [], True
        for p in cap["parameters"]:
            b = bind(p["binding"], object_id=object_id, tags=tags, rules=rules, object_name=object_name)
            if p["required"] and b["bound"] is False:
                applicable = False
                break
            params.append({k: p[k] for k in ("name", "type", "required", "description", "binding")} | {"bound": b})
        if not applicable:
            continue
        callable_ = cap["registration"] == STATUS_REGISTERED
        out.append({
            "id": cap["id"],
            "name": cap["name"],
            "type": cap["type"],
            "description": cap["description"],
            "provider": cap["provider"],
            "protocol": cap["protocol"],
            "endpoint": expand_endpoint(cap["endpoint"]) if cap["endpoint"] else "",
            "gateway": cap["gateway"].replace("{id}", object_id) if cap["gateway"] else "",
            "output": cap["output"],
            "preconditions": cap["preconditions"],
            "registration": cap["registration"],
            "status": MOUNT_CALLABLE if callable_ else MOUNT_PENDING,
            "note": cap["note"],
            "parameters": params,
            "source": cap["source"],
        })
    return out
