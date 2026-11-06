"""v2 接口。全部挂在 /api/v2 下。"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from backend.services import asset_model
from backend.v2 import calculations, documents, drawing, global_graph, nav, rule_eval, tabs
from backend.v2.context import get_ctx, reload_ctx
from backend.v2.phenomena import (
    AGGREGATES, CATEGORIES, CONFIDENCE, LIMIT_FIELDS, OPERATORS, STATUSES, NotFound, ValidationError,
)

router = APIRouter(prefix="/api/v2")


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (NotFound, LookupError, KeyError, tabs.TabNotFound, asset_model.ProfileNotFound) as exc:
        raise HTTPException(404, f"未找到：{exc}")
    except (ValidationError, calculations.CalcError, rule_eval.EvalError) as exc:
        raise HTTPException(400, str(exc))


# ------------------------------------------------------------------ 元数据
@router.get("/health")
def health() -> dict[str, Any]:
    ctx = get_ctx()
    return {"status": "ok", "loadedAt": ctx.store.loaded_at, "phenomena": len(ctx.phen.phenomena),
            "links": len(ctx.phen.links), "calculations": len(ctx.calcs.items)}


@router.get("/meta")
def meta() -> dict[str, Any]:
    return {
        "categories": nav.CATEGORIES, "operators": OPERATORS, "limitFields": LIMIT_FIELDS, "aggregates": AGGREGATES,
        "phenomenonCategories": CATEGORIES, "statuses": STATUSES, "confidence": CONFIDENCE,
        "calcMethods": calculations.METHODS, "tabs": [{"key": k, "label": l} for k, l in tabs.TABS],
    }


@router.post("/admin/reload")
def admin_reload() -> dict[str, Any]:
    reload_ctx()
    return health()


@router.post("/admin/reset-store")
def admin_reset() -> dict[str, Any]:
    ctx = get_ctx()
    ctx.phen.reset_to_seed()
    ctx.calcs.reset_to_seed()
    return health()


# ------------------------------------------------------------------ 导航
@router.get("/nav/space")
def nav_space() -> dict[str, Any]:
    return nav.space_root(get_ctx())


@router.get("/nav/segment/{seg_id}")
def nav_segment(seg_id: str) -> dict[str, Any]:
    return _guard(nav.segment_tree, get_ctx(), seg_id)


@router.get("/nav/domain/{key}")
def nav_domain(key: str, parent: Optional[str] = None) -> dict[str, Any]:
    return _guard(nav.domain_tree, get_ctx(), key, parent)


@router.get("/global-graph")
def global_graph_view() -> dict[str, Any]:
    """全局图谱：全部节点与关系（前端按视图 / 布局 / 跳数筛选）。"""
    return global_graph.build(get_ctx())


@router.get("/search")
def search(keyword: str = "", limit: int = 30) -> dict[str, Any]:
    ctx = get_ctx()
    kw = keyword.strip()
    if not kw:
        return {"items": []}
    items = []
    h = ctx.hierarchy
    for op in h.ops.values():
        if kw in op["name"] or kw in op["screen"]:
            items.append({"kind": "op", "id": op["id"], "label": op["name"], "hint": " / ".join(p["name"] for p in h.path(op["id"])[:2]),
                          "segmentId": op["segmentId"], "opId": op["id"]})
    dcs = ctx.store.dcs
    for gid, g in dcs.equipment_groups.items():
        if kw in g["name"] and h.ops_of_group.get(gid):
            op_id = h.ops_of_group[gid][0]
            items.append({"kind": "group", "id": gid, "label": g["name"], "hint": h.ops[op_id]["name"],
                          "segmentId": h.ops[op_id]["segmentId"], "opId": op_id})
    for eid, e in dcs.equipment.items():
        if kw in e["name"] and eid in h.op_of_equipment:
            op_id = h.op_of_equipment[eid]
            items.append({"kind": "equipment", "id": eid, "label": e["name"], "hint": h.ops[op_id]["name"],
                          "segmentId": h.ops[op_id]["segmentId"], "opId": op_id})
    tag = ctx.tag_by_name.get(kw.upper()) or ctx.tag_by_name.get(kw)
    if tag and tag.get("equipmentId") in h.op_of_equipment:
        op_id = h.op_of_equipment[tag["equipmentId"]]
        items.insert(0, {"kind": "tag", "id": tag["equipmentId"], "label": f"{tag['name']}（{tag.get('rawDescription') or ''}）",
                         "hint": f"{tag.get('equipmentName')} · {h.ops[op_id]['name']}",
                         "segmentId": h.ops[op_id]["segmentId"], "opId": op_id})
    for p in ctx.phen.phenomena.values():
        if kw in p["name"]:
            ops = ctx.phenomenon_ops(p)
            if ops:
                items.append({"kind": "phenomenon", "id": p["id"], "label": p["name"], "hint": (p.get("anchor") or {}).get("name"),
                              "segmentId": h.ops[ops[0]]["segmentId"], "opId": ops[0]})
    return {"items": items[:limit], "total": len(items)}


# ------------------------------------------------------------------ 工艺段 / 工序
@router.get("/segments/{seg_id}")
def segment(seg_id: str) -> dict[str, Any]:
    ctx = get_ctx()
    h = ctx.hierarchy
    seg = h.segments.get(seg_id)
    if not seg:
        raise HTTPException(404, seg_id)
    ops = []
    for op_id in seg["opIds"]:
        op = h.ops[op_id]
        ops.append({**op, "equipmentCount": len(h.op_equipment(op_id)), "groupCount": len(h.op_groups.get(op_id, [])),
                    "phenomenonCount": len(nav.op_phenomena(ctx, op_id)), "calcCount": len(nav.op_calcs(ctx, op_id))})
    return {**seg, "ops": ops}


def _op(op_id: str) -> dict[str, Any]:
    ctx = get_ctx()
    if op_id not in ctx.hierarchy.ops:
        raise HTTPException(404, op_id)
    return ctx.hierarchy.ops[op_id]


@router.get("/ops/{op_id}")
def op_detail(op_id: str) -> dict[str, Any]:
    ctx = get_ctx()
    op = _op(op_id)
    h = ctx.hierarchy
    return {**op, "path": h.path(op_id), "equipmentCount": len(h.op_equipment(op_id)),
            "groupCount": len(h.op_groups.get(op_id, [])), "phenomenonCount": len(nav.op_phenomena(ctx, op_id)),
            "calcCount": len(nav.op_calcs(ctx, op_id))}


@router.get("/ops/{op_id}/drawing")
def op_drawing(op_id: str) -> dict[str, Any]:
    _op(op_id)
    return drawing.build(get_ctx(), op_id)


@router.get("/drawings/{op_id}/image", include_in_schema=False)
def drawing_image(op_id: str):  # noqa: ANN201
    from fastapi.responses import FileResponse
    path = drawing.image_path(op_id)
    if not path:
        raise HTTPException(404, f"工序 {op_id} 没有现场图纸")
    return FileResponse(path)


@router.get("/ops/{op_id}/conditions")
def op_conditions(op_id: str) -> dict[str, Any]:
    ctx = get_ctx()
    _op(op_id)
    phen = nav.op_phenomena(ctx, op_id)
    ids = {p["id"] for p in phen}
    links = [l for l in ctx.phen.links.values() if l["cause"] in ids or l["effect"] in ids]
    return {"phenomena": [tabs.phenomenon_view(ctx, p) for p in phen],
            "links": [tabs.link_view(ctx, l) for l in links], "graph": tabs.graph_view(ctx, ids, links)}


@router.get("/ops/{op_id}/calculations")
def op_calculations(op_id: str) -> dict[str, Any]:
    _op(op_id)
    return {"items": nav.op_calcs(get_ctx(), op_id)}


@router.get("/ops/{op_id}/documents")
def op_documents(op_id: str) -> dict[str, Any]:
    _op(op_id)
    return documents.for_op(get_ctx(), op_id)


@router.get("/documents/{doc_id}")
def document(doc_id: str) -> dict[str, Any]:
    return _guard(documents.read, doc_id)


# ------------------------------------------------------------------ 本体对象
@router.get("/objects/{object_id}")
def object_header(object_id: str, op: Optional[str] = None) -> dict[str, Any]:
    return _guard(tabs.header, get_ctx(), object_id, op)


@router.get("/objects/{object_id}/tabs/{key}")
def object_tab(object_id: str, key: str, op: Optional[str] = None) -> dict[str, Any]:
    return _guard(tabs.tab, get_ctx(), object_id, key, op)


@router.get("/objects/{object_id}/profile")
def object_profile(object_id: str) -> dict[str, Any]:
    return _guard(get_ctx().profile, object_id)


@router.get("/objects/{object_id}/parameters")
def object_parameters(object_id: str) -> dict[str, Any]:
    """判定规则编辑器用：对象可引用的属性（含组内第一台可落到的测点）。"""
    ctx = get_ctx()
    items = _guard(ctx.parameter_names, object_id)
    if object_id.startswith("egrp-"):
        members = ctx.group_members(object_id)
        seen = {i["name"] for i in items}
        for m in members[:3]:
            for p in ctx.parameter_names(m):
                if p["name"] not in seen:
                    items.append({**p, "fromMember": ctx.object_name(m)})
                    seen.add(p["name"])
    return {"items": items}


@router.get("/limits")
def limits(keyword: str = "") -> dict[str, Any]:
    ctx = get_ctx()
    items = [{k: l.get(k) for k in ("id", "appliesTo", "area", "operatingMode", "unit", "lowLow", "low", "normalLow",
                                     "normalHigh", "high", "highHigh", "status")}
             for l in ctx.limits.values() if not keyword or keyword in (l.get("appliesTo") or "") or keyword in l["id"]]
    return {"items": items}


# ------------------------------------------------------------------ 现象
@router.get("/phenomena")
def phenomena(anchor: Optional[str] = None, op: Optional[str] = None, keyword: str = "") -> dict[str, Any]:
    ctx = get_ctx()
    items = []
    for p in ctx.phen.phenomena.values():
        if anchor and (p.get("anchor") or {}).get("id") != anchor:
            continue
        if op and op not in ctx.phenomenon_ops(p):
            continue
        if keyword and keyword not in p["name"]:
            continue
        items.append(tabs.phenomenon_view(ctx, p))
    return {"items": items, "total": len(items)}


@router.get("/phenomena/{pid}")
def phenomenon(pid: str) -> dict[str, Any]:
    ctx = get_ctx()
    p = _guard(ctx.phen.get, pid)
    view = tabs.phenomenon_view(ctx, p)
    view["causes"] = [tabs.link_view(ctx, l) for l in ctx.phen.causes_of(pid)]
    view["effects"] = [tabs.link_view(ctx, l) for l in ctx.phen.effects_of(pid)]
    return view


@router.post("/phenomena")
def create_phenomenon(body: dict = Body(...)) -> dict[str, Any]:
    ctx = get_ctx()
    return tabs.phenomenon_view(ctx, _guard(ctx.phen.create_phenomenon, body))


@router.put("/phenomena/{pid}")
def update_phenomenon(pid: str, body: dict = Body(...)) -> dict[str, Any]:
    ctx = get_ctx()
    return tabs.phenomenon_view(ctx, _guard(ctx.phen.update_phenomenon, pid, body))


@router.delete("/phenomena/{pid}")
def delete_phenomenon(pid: str) -> dict[str, Any]:
    return _guard(get_ctx().phen.delete_phenomenon, pid)


@router.get("/phenomena/{pid}/chain")
def phenomenon_chain(pid: str, direction: str = Query("up", pattern="^(up|down)$"), depth: int = 6) -> dict[str, Any]:
    ctx = get_ctx()
    chain = _guard(ctx.phen.chain, pid, direction, max(1, min(depth, 10)))
    graph = tabs.graph_view(ctx, set(chain["levels"]), chain["links"], focus={pid})
    for node in graph["nodes"]:
        node["level"] = chain["levels"].get(node["id"], 0)
    return {**chain, "graph": graph}


@router.post("/phenomena/{pid}/evaluate")
def evaluate_phenomenon(pid: str, body: dict = Body(default={})) -> dict[str, Any]:
    ctx = get_ctx()
    p = _guard(ctx.phen.get, pid)
    return _guard(rule_eval.evaluate, ctx, p.get("rule"), p["anchor"]["id"], hours=float(body.get("hours") or 24),
                  op_id=body.get("opId"), target_id=body.get("targetId"))


@router.post("/rules/evaluate")
def evaluate_rule(body: dict = Body(...)) -> dict[str, Any]:
    """保存前试算：body = {anchorId, rule, hours?, opId?, targetId?}"""
    from backend.v2.phenomena import validate_rule
    ctx = get_ctx()
    _guard(validate_rule, body.get("rule"))
    if not body.get("anchorId"):
        raise HTTPException(400, "缺少 anchorId")
    return _guard(rule_eval.evaluate, ctx, body.get("rule"), body["anchorId"], hours=float(body.get("hours") or 24),
                  op_id=body.get("opId"), target_id=body.get("targetId"))


# ------------------------------------------------------------------ 根因影响关系
@router.get("/causal-links")
def causal_links(op: Optional[str] = None, phenomenon: Optional[str] = None) -> dict[str, Any]:
    ctx = get_ctx()
    links = list(ctx.phen.links.values())
    if phenomenon:
        links = [l for l in links if phenomenon in (l["cause"], l["effect"])]
    if op:
        ids = {p["id"] for p in nav.op_phenomena(ctx, op)}
        links = [l for l in links if l["cause"] in ids or l["effect"] in ids]
    return {"items": [tabs.link_view(ctx, l) for l in links], "total": len(links)}


@router.post("/causal-links")
def create_link(body: dict = Body(...)) -> dict[str, Any]:
    ctx = get_ctx()
    return tabs.link_view(ctx, _guard(ctx.phen.create_link, body))


@router.put("/causal-links/{lid}")
def update_link(lid: str, body: dict = Body(...)) -> dict[str, Any]:
    ctx = get_ctx()
    return tabs.link_view(ctx, _guard(ctx.phen.update_link, lid, body))


@router.delete("/causal-links/{lid}")
def delete_link(lid: str) -> dict[str, Any]:
    return _guard(get_ctx().phen.delete_link, lid)


# ------------------------------------------------------------------ 计算组态
@router.get("/calculations")
def calc_list() -> dict[str, Any]:
    return {"items": list(get_ctx().calcs.items.values())}


@router.get("/calculations/{cid}")
def calc_get(cid: str) -> dict[str, Any]:
    ctx = get_ctx()
    c = _guard(ctx.calcs.get, cid)
    used_by = [{"id": p["id"], "name": p["name"]} for p in ctx.phen.phenomena.values() if cid in str(p.get("rule"))]
    return {**c, "usedBy": used_by, "opIds": ctx.hierarchy.ops_of_object(ctx.store, (c.get("anchor") or {}).get("id") or "")}


@router.post("/calculations")
def calc_create(body: dict = Body(...)) -> dict[str, Any]:
    return _guard(get_ctx().calcs.create, body)


@router.put("/calculations/{cid}")
def calc_update(cid: str, body: dict = Body(...)) -> dict[str, Any]:
    return _guard(get_ctx().calcs.update, cid, body)


@router.delete("/calculations/{cid}")
def calc_delete(cid: str) -> dict[str, Any]:
    return _guard(get_ctx().calcs.delete, cid)


@router.post("/calculations/{cid}/run")
def calc_run(cid: str, body: dict = Body(default={})) -> dict[str, Any]:
    ctx = get_ctx()
    calc = _guard(ctx.calcs.get, cid)
    return _guard(rule_eval.run_calc, ctx, calc, hours=float(body.get("hours") or 6), op_id=body.get("opId"),
                  target_id=body.get("targetId"))
