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


PARAM_GROUPS = ["基本信息", "设计参数", "工艺属性", "测量", "状态", "控制"]
_KIND_TO_GROUP = {"固有": "基本信息", "工艺属性": "工艺属性", "测量": "测量", "状态": "状态", "控制": "控制"}


def _equipment_type(ctx: AppContext, object_id: str) -> tuple[str, str, str | None]:
    """(名称, 设备类型, 所属设备组名)"""
    dcs = ctx.store.dcs
    if object_id in dcs.equipment_groups:
        g = dcs.equipment_groups[object_id]
        return g["name"], g.get("equipmentType") or "", None
    e = dcs.equipment.get(object_id) or {}
    g = dcs.equipment_groups.get(e.get("equipmentGroupId") or "") or {}
    return e.get("name", object_id), g.get("equipmentType") or "", g.get("name")


def _member_signals(ctx: AppContext, group_id: str, op_id: str | None) -> list[dict[str, Any]]:
    """设备组：成员的测量 / 状态 / 控制参数按名称合并成一行，各台的位号列在一起（原「仪表」页签的内容）。"""
    members = _scope_members(ctx, group_id, op_id) if op_id else ctx.group_members(group_id)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for m in members:
        for a in ctx.profile(m).get("attributes") or []:
            group = _KIND_TO_GROUP.get(a.get("kind") or "")
            if group not in ("测量", "状态", "控制"):
                continue
            row = rows.setdefault((group, a["name"]), {
                "group": group, "name": a["name"], "valueType": a.get("valueType") or "", "value": None,
                "description": "组内各台", "note": "", "links": [], "inheritedFrom": None})
            for l in a.get("dataLinks") or []:
                tag = ctx.tag_by_name.get(l.get("tag") or "") or {}
                if tag.get("equipmentId") != m or any(x["tag"] == l["tag"] for x in row["links"]):
                    continue
                row["links"].append({"tag": l["tag"], "desc": l.get("desc") or tag.get("rawDescription") or "",
                                     "unit": l.get("unit") or tag.get("unit") or "", "block": tag.get("blockType") or "",
                                     "station": tag.get("station") or "", "equipment": tag.get("equipmentName") or "",
                                     "limit": (ctx.limit_of_tag.get(l["tag"]) or {}).get("id"), "own": True})
    out = [r for r in rows.values() if r["links"]]
    for r in out:
        r["description"] = f"组内 {len({l['equipment'] for l in r['links']})} 台"
    return sorted(out, key=lambda r: (["测量", "状态", "控制"].index(r["group"]), r["name"]))


def _parameters(ctx: AppContext, object_id: str, prof: dict[str, Any], op_id: str | None) -> dict[str, Any]:
    """参数 · 仪表：固有属性、设计参数、工艺属性、测量 / 状态 / 控制参数合在一张表，数据关联（DCS 位号）直接列在行里。"""
    dcs = ctx.store.dcs
    allowed: set[str] | None = None
    if object_id.startswith("egrp-"):
        # 设备组在某道工序下只列本工序成员的测点（不属于任何成员的组级测点保留）
        members = set(_scope_members(ctx, object_id, op_id)) if op_id else set()
        if members:
            everyone = set(ctx.group_members(object_id))
            allowed = {t["name"] for e in members for t in ctx.tags_of_equipment.get(e, [])}
            allowed |= {t["name"] for tid in dcs.equipment_groups[object_id].get("tagIds") or []
                        if (t := dcs.tags.get(tid)) and t.get("equipmentId") not in everyone}
    items: list[dict[str, Any]] = []
    for a in prof.get("attributes") or []:
        group = _KIND_TO_GROUP.get(a.get("kind") or "", a.get("kind") or "其他")
        links = []
        for l in a.get("dataLinks") or []:
            if allowed is not None and l.get("tag") not in allowed:
                continue
            tag = ctx.tag_by_name.get(l.get("tag") or "") or {}
            links.append({"tag": l.get("tag"), "desc": l.get("desc") or tag.get("rawDescription") or "",
                          "unit": l.get("unit") or tag.get("unit") or "", "block": l.get("blockType") or tag.get("blockType") or "",
                          "station": l.get("station") or tag.get("station") or "", "equipment": tag.get("equipmentName") or "",
                          "limit": (ctx.limit_of_tag.get(l.get("tag") or "") or {}).get("id"),
                          # 共用设备 / 组级属性会关联到其他设备上的测点，前端淡化显示并标出所在设备
                          "own": object_id.startswith("egrp-") or tag.get("equipmentId") == object_id})
        if allowed is not None and a.get("dataLinks") and not links and group in ("测量", "状态", "控制"):
            continue  # 该测点只在其他工序的成员上
        items.append({"group": group, "name": a.get("name"), "valueType": a.get("valueType") or "",
                      "value": a.get("value"), "description": a.get("description") or "",
                      "note": a.get("note") or "", "links": links, "inheritedFrom": a.get("inheritedFrom"),
                      "linkTotal": a.get("dataLinkTotal"), "groupLinkTotal": a.get("groupLinkTotal")})
    if object_id.startswith("egrp-"):
        items += _member_signals(ctx, object_id, op_id)
    for x in items:
        _inherit(x, bool(x.get("inheritedFrom")), f"设备组 {x.get('inheritedFrom')}" if x.get("inheritedFrom") else None)
    name, etype, group_name = _equipment_type(ctx, object_id)
    design = ctx.design.for_object(name, etype, group_name)
    tpl = (ctx.design.template_for(etype, name) or {}).get("name")
    for x in design:
        _inherit(x, True, f"类「{tpl}」参数模板")
    pos = next((i for i, x in enumerate(items) if x["group"] != "基本信息"), len(items))
    items[pos:pos] = design
    counts = {g: sum(1 for x in items if x["group"] == g) for g in PARAM_GROUPS}
    return {"items": items, "groups": [g for g in PARAM_GROUPS if counts[g]], "counts": counts,
            "tagTotal": len({l["tag"] for x in items for l in x["links"] if l["own"]}),
            "scope": "本组" if object_id.startswith("egrp-") else "本台",
            "designTemplate": (ctx.design.template_for(etype, name) or {}).get("name"),
            "designPending": sum(1 for x in design if x["pending"]),
            "note": "基本信息与设计参数是设备的固定参数；工艺属性与测量 / 状态 / 控制参数的数据关联（DCS 位号）直接列在行里"}


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


def _group_name(ctx: AppContext, object_id: str) -> str | None:
    gid = (ctx.store.dcs.equipment.get(object_id) or {}).get("equipmentGroupId")
    return ctx.store.dcs.equipment_groups[gid]["name"] if gid else None


def _inherit(item: dict[str, Any], inherited: bool, source: str | None) -> dict[str, Any]:
    """统一的继承标记：inherited = 是否继承自类对象（设备组 / 设备类型模板），inheritedFrom = 来源说明。"""
    item["inherited"] = bool(inherited)
    item["inheritedFrom"] = source if inherited else None
    return item


def _limit_area(ctx: AppContext, limit: dict[str, Any]) -> str | None:
    name = (limit.get("area") or "").strip().lower().replace("（", "(").replace("）", ")")
    aid = ctx.store.dcs.area_by_name.get(name)
    return aid[5:] if aid else None


def _condition_phen(ctx: AppContext, key: str | None) -> dict[str, Any] | None:
    """按 conditionKey 找工况现象（参数约束引用）。"""
    if not key:
        return None
    p = next((p for p in ctx.phen.phenomena.values() if p.get("conditionKey") == key), None)
    return {"id": p["id"], "name": p["name"], "hasRule": bool(p.get("rule")),
            "anchor": (p.get("anchor") or {}).get("name", "")} if p else None


def _constraints(ctx: AppContext, object_id: str, prof: dict[str, Any]) -> dict[str, Any]:
    """参数约束：工艺限值 + 限值版本；适用工况、版本适用条件都关联到「工况」现象。"""
    from backend.services import limit_versions

    cons = prof.get("constraints") or {}
    group_name = _group_name(ctx, object_id)
    inherited_attrs = {a["name"] for a in prof.get("attributes") or [] if a.get("inheritedFrom")}
    items = []
    for c in cons.get("operating") or []:
        limit = ctx.limits.get(c["id"]) or {}
        code = _limit_area(ctx, limit)
        mode = c.get("operatingMode") or ""
        versions = []
        try:
            raw = limit_versions.versions(ctx.store, c["id"])["items"]
        except Exception:  # noqa: BLE001
            raw = []
        ranged = any(v.get("enzymeMin") is not None or v.get("enzymeMax") is not None for v in raw)
        # 基础版本 V0 覆盖「其余批次」：若只有一个 [a, ∞) 的版本，V0 实际对应 1～a-1 批
        open_ended = [v for v in raw if v.get("enzymeMin") is not None and v.get("enzymeMax") is None]
        bounded = [v for v in raw if v.get("enzymeMax") is not None]
        base_phen = None
        if len(open_ended) == 1 and not bounded:
            a = int(open_ended[0]["enzymeMin"])
            base_phen = _condition_phen(ctx, f"batch:{code}:1-{a - 1}") or _condition_phen(ctx, f"batch:{code}:0-{a - 1}")
        for v in raw:
            lo, hi = v.get("enzymeMin"), v.get("enzymeMax")
            phen = base_phen if v.get("base") else None
            if lo is not None or hi is not None:
                phen = _condition_phen(ctx, f"batch:{code}:{int(lo) if lo is not None else 0}-{'' if hi is None else int(hi)}")
            versions.append({
                "id": v["id"], "base": v.get("base"), "conditionText": v.get("conditionText") or "",
                "conditionNote": "其余情况（基础版本）" if v.get("base") and ranged else "",
                "phenomenon": phen,
                "normal": f"{v.get('normalLow')}~{v.get('normalHigh')}", "lh": f"{v.get('low')}~{v.get('high')}",
                "llhh": f"{v.get('lowLow')}~{v.get('highHigh')}", "sourceType": v.get("sourceType") or "",
                "effective": v.get("effectiveFromText") or "自始", "editor": v.get("editor") or "",
                "reason": v.get("reason") or "", "status": v.get("status") or "",
            })
        inherited = object_id.startswith("equip-") and c.get("appliesTo") in inherited_attrs
        items.append(_inherit({**c, "modePhenomenon": _condition_phen(ctx, f"mode:{code}:{mode}") if mode else None,
                               "versions": versions}, inherited, f"设备组 {group_name}"))
    return {"operating": items, "safety": cons.get("safety") or [],
            "note": "工况与版本适用条件都是「工况」类现象，点击可跳到现象定义；判断历史数据时按当时生效的版本"}


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
        return _parameters(ctx, object_id, prof, op_id)
    if key == "constraints":
        return _constraints(ctx, object_id, prof)
    if key == "topology":
        rel = prof.get("relations") or {}
        items = [r for r in (rel.get("classRelations") or []) + (rel.get("groupRelations") or [])
                 if r.get("category") in ("物理拓扑关系", "空间层级", "设备分类", "结构关系")]
        gname = _group_name(ctx, object_id)
        items = [_inherit(dict(r), r.get("layer") == "所属组", f"设备组 {gname}") for r in items]
        return {"items": items, "instances": prof.get("instances") or []}
    if key == "phenomena":
        gname = _group_name(ctx, object_id)
        items = [_inherit(phenomenon_view(ctx, p, origin), origin == "继承自设备组", f"设备组 {gname}")
                 for p, origin in ctx.phenomena_for_object(object_id)]
        return {"items": items}
    if key == "causal":
        pairs = ctx.phenomena_for_object(object_id)
        own = {p["id"] for p, _ in pairs}
        mine = {p["id"] for p, o in pairs if o == "本对象"}
        links = [l for l in ctx.phen.links.values() if l["cause"] in own or l["effect"] in own]
        gname = _group_name(ctx, object_id)
        views = [_inherit(link_view(ctx, l), not ({l["cause"], l["effect"]} & mine), f"设备组 {gname}") for l in links]
        return {"links": views, "graph": graph_view(ctx, own, links)}
    if key == "influence":
        rel = prof.get("relations") or {}
        items = [r for r in rel.get("attributeRelations") or [] if r.get("category") in INFLUENCE_CATEGORIES]
        own_attrs = {a["name"] for a in prof.get("attributes") or [] if not a.get("inheritedFrom")}
        gname = _group_name(ctx, object_id)
        items = [_inherit(dict(r), object_id.startswith("equip-") and not ({r.get("from"), r.get("to")} & own_attrs),
                          f"设备组 {gname}") for r in items]
        return {"items": items, "note": "工艺属性之间的影响关系（正向 / 负向影响、质量关系），来自工业关系表"}
    if key == "calc":
        gname = _group_name(ctx, object_id)
        calcs = [_inherit({**c, "methodText": c.get("method")}, c["origin"] == "继承自设备组", f"设备组 {gname}")
                 for c in _calcs_for(ctx, object_id)]
        derived = [a for a in prof.get("attributes") or [] if a.get("kind") == "工艺属性" and not a.get("dataLinks")]
        return {"items": calcs, "capabilities": prof.get("capabilities") or [],
                "derivedCandidates": [{"name": a["name"], "description": a.get("description") or ""} for a in derived]}
    if key == "procedures":
        return {"items": prof.get("procedures") or []}
    raise TabNotFound(key)
