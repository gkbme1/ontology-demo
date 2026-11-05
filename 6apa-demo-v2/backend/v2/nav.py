"""左侧导航树。

- 空间层级：第一屏只有车间 → 工艺段；进入工艺段后是工艺段内的层级树：
  工序 → 装置 / 计算组态 / 工况与根因 / 文档提取，装置下是设备组（文件夹）→ 设备、未入组设备；
- 其余分类复用复制来的资产导航（asset_model.tree）的对应本体域；无数据源的分类标「待建」。
"""
from __future__ import annotations

from typing import Any

from backend.services import asset_model
from backend.v2 import documents
from backend.v2.context import AppContext
from backend.v2.hierarchy import OP_SECTIONS

CATEGORIES = [
    {"key": "space", "label": "空间层级", "hint": "车间 → 工艺段 → 工序 → 装置"},
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
                          "description": s["description"]} for s in segs],
        })
    return {"items": items, "notIncluded": h.not_included}


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
    return [c for c in ctx.calcs.items.values()
            if op_id in ctx.hierarchy.ops_of_object(ctx.store, (c.get("anchor") or {}).get("id") or "")]


def segment_tree(ctx: AppContext, seg_id: str) -> dict[str, Any]:
    h = ctx.hierarchy
    seg = h.segments.get(seg_id)
    if not seg:
        raise LookupError(seg_id)
    ops = []
    for op_id in seg["opIds"]:
        op = h.ops[op_id]
        sections = []
        for key, label, hint in OP_SECTIONS:
            node: dict[str, Any] = {"id": f"{op_id}|{key}", "opId": op_id, "label": label, "kind": f"section:{key}", "hint": hint}
            if key == "devices":
                node["children"] = _device_nodes(ctx, op_id)
                node["count"] = len(h.op_equipment(op_id))
            elif key == "calc":
                calcs = op_calcs(ctx, op_id)
                node["count"] = len(calcs)
                node["children"] = [{"id": f"{op_id}|calc|{c['id']}", "opId": op_id, "calcId": c["id"],
                                     "label": c["name"], "kind": "calc"} for c in calcs]
            elif key == "cond":
                node["count"] = len(op_phenomena(ctx, op_id))
            elif key == "docs":
                node["count"] = len(documents.for_op(ctx, op_id)["documents"])
            sections.append(node)
        ops.append({"id": op_id, "opId": op_id, "label": op["name"], "kind": "op", "screen": op["screen"],
                    "status": op["status"], "children": sections})
    return {"segment": {k: seg[k] for k in ("id", "name", "description")}, "items": ops}


def domain_tree(ctx: AppContext, key: str, parent: str | None) -> dict[str, Any]:
    cat = next((c for c in CATEGORIES if c["key"] == key), None)
    if not cat:
        raise LookupError(key)
    if cat.get("pending"):
        return {"category": cat, "items": [], "pending": True}
    return {"category": cat, **asset_model.tree(ctx.store, parent or cat["domain"])}
