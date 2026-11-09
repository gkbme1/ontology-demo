"""左侧导航树。

- 空间层级：第一屏只有装置 → 单元；进入单元后是单元内的层级树：
  画面 → 设备 / 计算组态 / 工况与根因 / 文档提取，装置下是设备组（文件夹）→ 设备、未入组设备；
- 其余分类复用复制来的资产导航（asset_model.tree）的对应本体域；无数据源的分类标「待建」。
"""
from __future__ import annotations

from typing import Any

from backend.services import asset_model
from backend.v2 import documents
from backend.v2.context import AppContext
from backend.v2.hierarchy import OP_SECTIONS

CATEGORIES = [
    {"key": "space", "label": "空间层级", "hint": "装置 → 单元 → 画面 → 设备"},
    {"key": "assets", "label": "工业资产", "domain": "dom:assets", "hint": "资产大类 → 设备类型 → 设备组 → 设备"},
    {"key": "process", "label": "工艺参数", "domain": "dom:process", "hint": "各工段的工艺属性"},
    {"key": "material", "label": "物料与产品", "domain": "dom:material", "hint": "物料流股、公用介质"},
    {"key": "quality", "label": "质量", "domain": "dom:quality", "hint": "质量指标"},
    {"key": "org", "label": "组织与人员", "pending": True, "hint": "待建：暂无数据源"},
    {"key": "energy", "label": "能源", "pending": True, "hint": "待建：暂无数据源"},
    {"key": "business", "label": "经营与成本", "domain": "dom:business", "hint": "业务指标（成本数据待建）"},
]


def space_root(ctx: AppContext) -> dict[str, Any]:
    h = ctx.hierarchy
    items = []
    for ws in h.workshops:
        segs = [s for s in h.segments.values() if s["workshopId"] == ws["id"]]
        items.append({
            "id": ws["id"], "label": ws["name"], "kind": "workshop", "description": ws["description"],
            "children": [{"id": s["id"], "label": s["name"], "kind": "segment", "count": len(s["opIds"]),
                          "description": s["description"]} for s in segs] + global_nodes(ctx),
        })
    return {"items": items, "notIncluded": h.not_included, "globals": global_nodes(ctx)}


GLOBAL_SECTIONS = [
    ("global:calc", "计算组态", "全部计算组态：设备级与跨设备 / 跨工艺的统计，引用算法库并绑定本体参数"),
    ("global:algo", "算法库", "算法的调用契约（调用方式、输入参数、输出），由算法服务提供"),
    ("global:cond", "工况与根因", "全装置的现象 / 工况定义与根因影响关系（含跨设备的导致关系）"),
    ("global:docs", "文档提取", "规程文档与数据源，以及从中提取进本体的对象"),
]


def global_nodes(ctx: AppContext) -> list[dict[str, Any]]:
    counts = {"global:calc": len(ctx.calcs.items), "global:algo": len(ctx.algos.items),
              "global:cond": sum(1 for p in ctx.phen.phenomena.values() if ctx.phenomenon_ops(p)),
              "global:docs": len(documents.REGISTRY)}
    return [{"id": k, "label": label, "kind": k, "hint": hint, "count": counts[k]} for k, label, hint in GLOBAL_SECTIONS]


def _device_nodes(ctx: AppContext, op_id: str) -> list[dict[str, Any]]:
    h = ctx.hierarchy
    dcs = ctx.store.dcs
    nodes = []
    for gid in h.op_groups.get(op_id, []):
        members = h.op_group_members.get((op_id, gid), [])
        nodes.append({
            "id": f"{op_id}|{gid}", "objectId": gid, "opId": op_id, "label": dcs.equipment_groups[gid]["name"],
            "kind": "group", "count": len(members),
            "children": [{"id": f"{op_id}|{e}", "objectId": e, "opId": op_id, "label": dcs.equipment[e]["name"],
                          "kind": "equipment", "count": len(dcs.equipment[e].get("tagIds") or [])} for e in members],
        })
    for e in h.op_ungrouped.get(op_id, []):
        nodes.append({"id": f"{op_id}|{e}", "objectId": e, "opId": op_id, "label": dcs.equipment[e]["name"],
                      "kind": "equipment", "ungrouped": True, "count": len(dcs.equipment[e].get("tagIds") or [])})
    return nodes


def op_phenomena(ctx: AppContext, op_id: str) -> list[dict[str, Any]]:
    return [p for p in ctx.phen.phenomena.values() if op_id in ctx.phenomenon_ops(p)]


def op_calcs(ctx: AppContext, op_id: str) -> list[dict[str, Any]]:
    return [c for c in ctx.calcs.items.values() if op_id in ctx.scope_ops((c.get("anchor") or {}).get("id") or "")]


def segment_tree(ctx: AppContext, seg_id: str) -> dict[str, Any]:
    h = ctx.hierarchy
    seg = h.segments.get(seg_id)
    if not seg:
        raise LookupError(seg_id)
    ops = []
    for op_id in seg["opIds"]:
        op = h.ops[op_id]
        # 画面下直接是设备组 / 设备；计算组态、工况与根因、文档提取移到全局（跨设备 / 跨工艺）
        ops.append({"id": op_id, "opId": op_id, "label": op["name"], "kind": "op", "screen": op["screen"],
                    "status": op["status"], "count": len(h.op_equipment(op_id)), "children": _device_nodes(ctx, op_id)})
    return {"segment": {k: seg[k] for k in ("id", "name", "description")}, "items": ops}


def domain_tree(ctx: AppContext, key: str, parent: str | None) -> dict[str, Any]:
    cat = next((c for c in CATEGORIES if c["key"] == key), None)
    if not cat:
        raise LookupError(key)
    if cat.get("pending"):
        return {"category": cat, "items": [], "pending": True}
    return {"category": cat, **asset_model.tree(ctx.store, parent or cat["domain"])}
