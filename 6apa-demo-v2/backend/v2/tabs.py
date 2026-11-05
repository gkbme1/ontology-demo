"""设备 / 设备组的 10 个页签。

页签数据大多取自复制来的对象档案（asset_model.profile），按本 Demo 的页签口径重新组织；
现象定义、根因影响关系、计算/指标来自本 Demo 新增的仓库。设备组在某道工序下只列本工序认领的成员。
"""
from __future__ import annotations

from typing import Any

from backend.v2.context import AppContext
from backend.v2.phenomena import rule_text

TABS = [
    ("drawing", "图纸位置与外观"),
    ("parameters", "参数"),
    ("instruments", "仪表"),
    ("constraints", "参数约束"),
    ("topology", "拓扑关系"),
    ("phenomena", "现象定义"),
    ("causal", "根因影响关系"),
    ("influence", "工艺影响关系"),
    ("calc", "计算/指标"),
    ("procedures", "处置规程"),
]
INFLUENCE_CATEGORIES = {"影响关系", "质量关系"}


class TabNotFound(LookupError):
    pass


def _calc_names(ctx: AppContext) -> dict[str, str]:
    return {k: v["name"] for k, v in ctx.calcs.items.items()}


def phenomenon_view(ctx: AppContext, p: dict[str, Any], origin: str = "") -> dict[str, Any]:
    return {
        **p,
        "ruleText": rule_text(p.get("rule"), ctx.limits, _calc_names(ctx)),
        "hasRule": bool(p.get("rule")),
        "roles": ctx.phen.roles(p["id"]),
        "opIds": ctx.phenomenon_ops(p),
        "origin": origin,
    }


def link_view(ctx: AppContext, link: dict[str, Any]) -> dict[str, Any]:
    cause = ctx.phen.phenomena.get(link["cause"]) or {}
    effect = ctx.phen.phenomena.get(link["effect"]) or {}
    return {
        **link,
        "causeName": cause.get("name", link["cause"]), "effectName": effect.get("name", link["effect"]),
        "causeAnchor": (cause.get("anchor") or {}).get("name", ""), "effectAnchor": (effect.get("anchor") or {}).get("name", ""),
    }


def graph_view(ctx: AppContext, phen_ids: set[str], links: list[dict[str, Any]], focus: set[str] | None = None) -> dict[str, Any]:
    ids = set(phen_ids)
    for l in links:
        ids.update((l["cause"], l["effect"]))
    nodes = []
    for pid in ids:
        p = ctx.phen.phenomena.get(pid)
        if not p:
            continue
        roles = ctx.phen.roles(pid)
        nodes.append({"id": pid, "name": p["name"], "category": p.get("category") or "工艺",
                      "anchor": (p.get("anchor") or {}).get("name", ""), "hasRule": bool(p.get("rule")),
                      "asCause": roles["asCause"], "asEffect": roles["asEffect"],
                      "inScope": pid in phen_ids, "focus": bool(focus and pid in focus)})
    return {"nodes": nodes, "links": [link_view(ctx, l) for l in links]}


def _scope_members(ctx: AppContext, object_id: str, op_id: str | None) -> list[str]:
    if object_id.startswith("egrp-"):
        return ctx.group_members(object_id, op_id)
    return []


def header(ctx: AppContext, object_id: str, op_id: str | None) -> dict[str, Any]:
    prof = ctx.profile(object_id)
    h = ctx.hierarchy
    ops = h.ops_of_object(ctx.store, object_id)
    op_id = op_id if op_id in ops else (ops[0] if ops else None)
    counts = {
        "phenomena": len(ctx.phenomena_for_object(object_id)),
        "procedures": len(prof.get("procedures") or []),
        "calc": len(_calcs_for(ctx, object_id)),
    }
    group = None
    gid = (ctx.store.dcs.equipment.get(object_id) or {}).get("equipmentGroupId")
    if gid:
        group = {"id": gid, "name": ctx.store.dcs.equipment_groups[gid]["name"]}
    return {
        "objectId": object_id, "kind": prof.get("kind"), "name": prof.get("name"), "group": group,
        "className": (prof.get("header") or {}).get("className"),
        "classPath": (prof.get("header") or {}).get("classPath"),
        "badges": (prof.get("header") or {}).get("badges") or [],
        "opId": op_id, "opIds": ops, "path": h.path(op_id) if op_id else [],
        "tabs": [{"key": k, "label": label} for k, label in TABS], "counts": counts,
    }


def _calcs_for(ctx: AppContext, object_id: str) -> list[dict[str, Any]]:
    group_id = (ctx.store.dcs.equipment.get(object_id) or {}).get("equipmentGroupId")
    out = []
    for c in ctx.calcs.items.values():
        aid = (c.get("anchor") or {}).get("id")
        if aid == object_id:
            out.append({**c, "origin": "本对象"})
        elif group_id and aid == group_id:
            out.append({**c, "origin": "继承自设备组"})
    return out


def tab(ctx: AppContext, object_id: str, key: str, op_id: str | None = None) -> dict[str, Any]:
    prof = ctx.profile(object_id)
    dcs = ctx.store.dcs
    if key == "drawing":
        ops = ctx.hierarchy.ops_of_object(ctx.store, object_id)
        op = op_id if op_id in ops else (ops[0] if ops else None)
        group_id = object_id if object_id.startswith("egrp-") else (dcs.equipment.get(object_id) or {}).get("equipmentGroupId")
        appearance = [a for a in prof.get("attributes") or [] if a.get("kind") == "固有"]
        members = [{"id": e, "name": dcs.equipment[e]["name"], "tagCount": len(dcs.equipment[e].get("tagIds") or [])}
                   for e in _scope_members(ctx, object_id, op)]
        return {"opId": op, "opIds": ops, "highlight": [x for x in (object_id, group_id) if x],
                "appearance": appearance, "header": prof.get("header"), "members": members,
                "note": "外观照片 / 三维模型暂无数据源，这里列出设备的固有属性"}
    if key == "parameters":
        items = [a for a in prof.get("attributes") or [] if a.get("kind") == "工艺属性"]
        return {"items": items, "note": "本体工艺属性（工艺量）；数据关联列出落到本对象的 DCS 测点"}
    if key == "instruments":
        if object_id.startswith("egrp-"):
            members = _scope_members(ctx, object_id, op_id) or ctx.group_members(object_id)
            tags = [t for e in members for t in ctx.tags_of_equipment.get(e, [])]
            own = set(members)
            tags += [t for tid in dcs.equipment_groups[object_id].get("tagIds") or []
                     if (t := dcs.tags.get(tid)) and t.get("equipmentId") not in own]
        else:
            tags = ctx.tags_of_equipment.get(object_id, [])
        rows = [{
            "tag": t["name"], "description": t.get("rawDescription") or "", "equipment": t.get("equipmentName") or "",
            "parameter": t.get("parameterName") or "", "type": t.get("parameterType") or "",
            "unit": t.get("unit") or t.get("standardUnit") or "", "block": t.get("blockType") or "",
            "station": t.get("station") or "", "screen": t.get("processScreen") or "",
            "limit": (ctx.limit_of_tag.get(t["name"]) or {}).get("id"),
        } for t in tags]
        rows.sort(key=lambda r: (r["equipment"], r["tag"]))
        kinds = {k: [a for a in prof.get("attributes") or [] if a.get("kind") == k] for k in ("测量", "状态", "控制")}
        return {"items": rows, "byKind": kinds, "total": len(rows)}
    if key == "constraints":
        cons = prof.get("constraints") or {}
        return {"operating": cons.get("operating") or [], "safety": cons.get("safety") or [],
                "structure": cons.get("structure") or [], "check": cons.get("check")}
    if key == "topology":
        rel = prof.get("relations") or {}
        items = [r for r in (rel.get("classRelations") or []) + (rel.get("groupRelations") or [])
                 if r.get("category") in ("物理拓扑关系", "空间层级", "设备分类", "结构关系")]
        return {"items": items, "instances": prof.get("instances") or []}
    if key == "phenomena":
        items = [phenomenon_view(ctx, p, origin) for p, origin in ctx.phenomena_for_object(object_id)]
        return {"items": items}
    if key == "causal":
        own = {p["id"] for p, _ in ctx.phenomena_for_object(object_id)}
        links = [l for l in ctx.phen.links.values() if l["cause"] in own or l["effect"] in own]
        return {"links": [link_view(ctx, l) for l in links], "graph": graph_view(ctx, own, links)}
    if key == "influence":
        rel = prof.get("relations") or {}
        items = [r for r in rel.get("attributeRelations") or [] if r.get("category") in INFLUENCE_CATEGORIES]
        return {"items": items, "note": "工艺属性之间的影响关系（正向 / 负向影响、质量关系），来自工业关系表"}
    if key == "calc":
        calcs = [{**c, "methodText": c.get("method")} for c in _calcs_for(ctx, object_id)]
        derived = [a for a in prof.get("attributes") or [] if a.get("kind") == "工艺属性" and not a.get("dataLinks")]
        return {"items": calcs, "capabilities": prof.get("capabilities") or [],
                "derivedCandidates": [{"name": a["name"], "description": a.get("description") or ""} for a in derived]}
    if key == "procedures":
        return {"items": prof.get("procedures") or []}
    raise TabNotFound(key)
