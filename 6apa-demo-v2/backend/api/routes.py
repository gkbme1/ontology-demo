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
        "bindingKinds": calculations.BINDING_KINDS, "tabs": [{"key": k, "label": l} for k, l in tabs.TABS],
        # 画面 → 所属单元：从图纸 / 图谱打开对象时，左侧树切到该单元并展开定位
        "opSegment": {o["id"]: o["segmentId"] for o in get_ctx().hierarchy.ops.values()},
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
    ctx.overrides.reset()
    ctx.relations.reset()
    ctx.procedure_edits.reset()
    ctx.knowledge.reset()
    ctx.classlib.reset()
    ctx.audit.reset()
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
def search(keyword: str = "", limit: int = 80) -> dict[str, Any]:
    """全局搜索：名称 / 编码 / 位号 / 拼音首字母，结果带类型与所属位置（前端按类型分组）。"""
    from backend.v2 import search as search_mod
    return search_mod.search(get_ctx(), keyword, limit)


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


# ------------------------------------------------------------------ 全局（跨装置 / 跨工艺）
def _scope(seg: Optional[str], op: Optional[str]) -> list[str]:
    """筛选范围 → 工序列表（都不给 = 全车间）。"""
    h = get_ctx().hierarchy
    if op:
        if op not in h.ops:
            raise HTTPException(404, op)
        return [op]
    if seg:
        if seg not in h.segments:
            raise HTTPException(404, seg)
        return list(h.segments[seg]["opIds"])
    return list(h.ops)


@router.get("/scope/conditions")
def scope_conditions(seg: Optional[str] = None, op: Optional[str] = None) -> dict[str, Any]:
    """全局的工况与根因：范围内的现象 / 工况与导致关系；导致关系两端挂在不同对象上的标「跨装置」。"""
    ctx = get_ctx()
    ops = set(_scope(seg, op))
    phen = [p for p in ctx.phen.phenomena.values() if ops & set(ctx.phenomenon_ops(p))]
    ids = {p["id"] for p in phen}
    links = [l for l in ctx.phen.links.values() if l["cause"] in ids or l["effect"] in ids]
    anchor = {pid: (p.get("anchor") or {}).get("id") for pid, p in ctx.phen.phenomena.items()}
    views = [{**tabs.link_view(ctx, l), "crossDevice": anchor.get(l["cause"]) != anchor.get(l["effect"])} for l in links]
    dcs = ctx.store.dcs
    anchors = [{"id": g, "name": dcs.equipment_groups[g]["name"], "kind": "group"}
               for o in sorted(ops) for g in ctx.hierarchy.op_groups.get(o, [])]
    seen: set[str] = set()
    anchors = [a for a in anchors if not (a["id"] in seen or seen.add(a["id"]))]
    return {"phenomena": [tabs.phenomenon_view(ctx, p) for p in phen], "links": views,
            "graph": tabs.graph_view(ctx, ids, links), "anchors": anchors,
            "crossCount": sum(1 for v in views if v["crossDevice"])}


@router.get("/scope/calculations")
def scope_calculations(seg: Optional[str] = None, op: Optional[str] = None) -> dict[str, Any]:
    ctx = get_ctx()
    ops = set(_scope(seg, op))
    items = [tabs.calc_view(ctx, c) for c in ctx.calcs.items.values()
             if ops & set(ctx.scope_ops((c.get("anchor") or {}).get("id") or ""))]
    return {"items": items, "total": len(items)}


@router.get("/scope/documents")
def scope_documents(seg: Optional[str] = None, op: Optional[str] = None) -> dict[str, Any]:
    return documents.for_scope(get_ctx(), _scope(seg, op))


@router.get("/algorithms")
def algorithms() -> dict[str, Any]:
    """算法库：算法的调用契约与被哪些计算组态引用。"""
    ctx = get_ctx()
    items = []
    for a in ctx.algos.items.values():
        used = [{"id": c["id"], "name": c["name"], "anchor": (c.get("anchor") or {}).get("name")}
                for c in ctx.calcs.items.values() if c.get("algorithmId") == a["id"]]
        items.append({**a, "usedBy": used})
    return {"items": items, "note": ctx.algos.note}


@router.get("/validation")
def validation_run() -> dict[str, Any]:
    """一致性校验（全量）：错误 / 警告 / 提示，每条带可跳转的目标对象。"""
    from backend.v2 import validation
    return validation.run(get_ctx())


# ------------------------------------------------------------------ 开发态（需求 4.2，只读）
@router.get("/dev/metamodel")
def dev_metamodel() -> dict[str, Any]:
    from backend.v2 import devtime
    return devtime.metamodel(get_ctx())


@router.get("/dev/hierarchy-types")
def dev_hierarchy_types() -> dict[str, Any]:
    from backend.v2 import devtime
    return devtime.hierarchy_types(get_ctx())


@router.get("/dev/class-tree")
def dev_class_tree() -> dict[str, Any]:
    from backend.v2 import devtime
    return devtime.class_tree(get_ctx())


@router.get("/dev/class")
def dev_class(id: str) -> dict[str, Any]:  # noqa: A002
    from backend.v2 import devtime
    try:
        return devtime.class_detail(get_ctx(), id)
    except LookupError:
        raise HTTPException(404, f"未找到类：{id}")


@router.get("/dev/relation-types")
def dev_relation_types() -> dict[str, Any]:
    from backend.v2 import devtime
    return devtime.relation_types(get_ctx())


@router.get("/dev/mapping-rules")
def dev_mapping_rules() -> dict[str, Any]:
    from backend.v2 import devtime
    return devtime.mapping_rules(get_ctx())


@router.get("/dev/parse-tag")
def dev_parse_tag(tag: str) -> dict[str, Any]:
    from backend.v2 import devtime
    return devtime.parse_tag(get_ctx(), tag)


# ------------------------------------------------------------------ 开发态类库（可编辑，需求 4.2）
def _cl():  # noqa: ANN202
    return get_ctx().classlib


def _cl_guard(fn, *args):  # noqa: ANN001, ANN202
    from backend.v2.classlib import ClassLibError
    try:
        return fn(*args)
    except ClassLibError as exc:
        raise HTTPException(400, str(exc))
    except LookupError as exc:
        raise HTTPException(404, f"未找到：{exc}")


def _cl_audit(op: str, name: str, target: str = "", note: str = "") -> None:
    get_ctx().audit.record(op, "类库", target, name, note=f"{_cl().current['version']}{'；' + note if note else ''}")


def _class_instances(ctx, cls: dict) -> list[dict]:  # noqa: ANN001
    """类的直接实例：设备类型类 → 该设备类型的设备组；元类根类 → 该元类的对象数（只计数）。"""
    if cls.get("abstract"):
        return []
    from backend.v2 import devtime
    h = ctx.hierarchy
    out = []
    for g in devtime._groups_of_type(ctx, cls["name"]):
        ops = h.ops_of_group.get(g) or []
        members = [e for e, x in ctx.store.dcs.equipment.items() if x.get("equipmentGroupId") == g]
        out.append({"id": g, "name": ctx.store.dcs.equipment_groups[g]["name"], "members": len(members), "inNav": bool(ops),
                    "opId": ops[0] if ops else None, "segmentId": h.ops[ops[0]]["segmentId"] if ops else None})
    return out


def _instance_counts(ctx) -> dict:  # noqa: ANN001
    from backend.v2 import devtime
    cnt = {}
    for c in _cl().data["classes"]:
        if not c.get("abstract"):
            gids = devtime._groups_of_type(ctx, c["name"])
            eq = sum(1 for e in ctx.store.dcs.equipment.values() if e.get("equipmentGroupId") in set(gids))
            cnt[c["id"]] = {"instances": eq + len(gids)}
    g = None
    for c in _cl().data["classes"]:
        if c.get("parent") is None and c["metaclass"] != "MC_EQUIP":
            if g is None:
                from backend.v2 import global_graph
                g = global_graph.build(ctx)["nodeCounts"]
            n = {"MC_EQGRP": len(ctx.store.dcs.equipment_groups), "MC_PARAM": g.get("工艺参数", 0), "MC_STREAM": g.get("物料流股", 0),
                 "MC_UTIL": g.get("公用介质", 0), "MC_QI": g.get("质量指标", 0)}.get(c["metaclass"], 0)
            cnt[c["id"]] = {"instances": n}
    return cnt


@router.get("/classlib")
def classlib_summary() -> dict[str, Any]:
    return _cl().summary()


@router.get("/classlib/tree")
def classlib_tree() -> dict[str, Any]:
    ctx = get_ctx()
    return {"items": _cl().tree(_instance_counts(ctx))}


@router.get("/classlib/class/{cid}")
def classlib_class(cid: str) -> dict[str, Any]:
    from backend.v2.classlib import PARTS
    ctx = get_ctx()
    cl = _cl()
    c = _cl_guard(cl.cls, cid)
    chain = cl.chain(cid)
    parts = {p: cl.effective(cid, p) for p in PARTS}
    inherited_caps = sorted({x for k in chain[:-1] for x in k.get("caps") or []})
    caps = [{**x, "_src": "本类" if x["code"] in (c.get("caps") or []) else "继承"} for x in cl.data["capabilities"]
            if x["code"] in set(c.get("caps") or []) | set(inherited_caps)]
    meta = next((m for m in cl.data["metaclasses"] if m["code"] == c["metaclass"]), {})
    prev = next((v["version"] for v in reversed(cl.data["versions"]) if v["status"] == "已发布"), None)
    changes = 0
    if prev and prev != cl.current["version"]:
        changes = sum(1 for r in cl.diff(prev, "current")["rows"] if r["id"] == cid or r["id"].startswith(cid + "/"))
    instances = _class_instances(ctx, c)
    base = {k: v for k, v in c.items() if k not in PARTS}
    return {**base, "path": [{"id": x["id"], "name": x["name"], "abstract": x.get("abstract")} for x in chain],
            "metaclassName": meta.get("name"), "tabsEffective": c.get("tabs") or meta.get("tabs") or [],
            "parts": parts, "caps": caps, "instances": instances,
            "summary": {p: {"own": sum(1 for x in v if x["_own"]), "inherited": sum(1 for x in v if not x["_own"])} for p, v in parts.items()},
            "version": {"current": cl.current["version"], "status": cl.current["status"], "since": prev, "changes": changes,
                        "updatedAt": c.get("updatedAt")}}


@router.post("/classlib/class")
def classlib_class_create(body: dict = Body(...)) -> dict[str, Any]:
    c = _cl_guard(_cl().upsert_class, None, body)
    _cl_audit("新建类", c["name"], c["id"])
    return c


@router.put("/classlib/class/{cid}")
def classlib_class_update(cid: str, body: dict = Body(...)) -> dict[str, Any]:
    c = _cl_guard(_cl().upsert_class, cid, body)
    _cl_audit("修改类", c["name"], cid)
    return c


@router.delete("/classlib/class/{cid}")
def classlib_class_delete(cid: str) -> dict[str, Any]:
    ctx = get_ctx()
    c = _cl_guard(_cl().cls, cid)
    n = sum(i["members"] + 1 for i in _class_instances(ctx, c))
    old = _cl_guard(_cl().delete_class, cid, n)
    _cl_audit("删除类", old["name"], cid)
    return {"deleted": cid}


@router.put("/classlib/class/{cid}/caps")
def classlib_caps(cid: str, body: dict = Body(...)) -> dict[str, Any]:
    caps = _cl_guard(_cl().set_caps, cid, list(body.get("caps") or []))
    _cl_audit("挂载能力", _cl().cls(cid)["name"], cid, "、".join(caps))
    return {"caps": caps}


@router.put("/classlib/class/{cid}/{part}/{code}")
def classlib_item_upsert(cid: str, part: str, code: str, body: dict = Body(...)) -> dict[str, Any]:
    from backend.v2.classlib import PARTS
    if part not in PARTS:
        raise HTTPException(404, part)
    item = _cl_guard(_cl().upsert_item, cid, part, code, body)
    _cl_audit(f"修改{PARTS[part]}", f"{_cl().cls(cid)['name']} › {item.get('name') or item['code']}", f"{cid}/{item['code']}")
    return item


@router.delete("/classlib/class/{cid}/{part}/{code}")
def classlib_item_delete(cid: str, part: str, code: str) -> dict[str, Any]:
    from backend.v2.classlib import PARTS
    old = _cl_guard(_cl().delete_item, cid, part, code)
    _cl_audit(f"删除{PARTS.get(part, part)}", f"{_cl().cls(cid)['name']} › {old.get('name') or code}", f"{cid}/{code}")
    return {"deleted": code}


@router.post("/classlib/class/{cid}/params/{code}/test")
def classlib_param_test(cid: str, code: str, body: dict = Body(...)) -> dict[str, Any]:
    """参数模板的位号匹配试验（需求 SW-005 第 3 条）：功能字母 + 描述关键字 + 位置维度。"""
    from backend.v2.classlib import tag_match
    ctx = get_ctx()
    tpl = next((x for x in _cl().effective(cid, "params") if x["code"] == code), None)
    if not tpl:
        raise HTTPException(404, code)
    tag = (body.get("tag") or "").strip()
    t = ctx.tag_by_name.get(tag.upper()) or ctx.tag_by_name.get(tag) or {}
    desc = body.get("desc") or t.get("rawDescription") or ""
    return {**tag_match(tpl, t.get("name") or tag, desc), "template": tpl["name"], "equipment": t.get("equipmentName")}


@router.get("/classlib/class/{cid}/phenomena/{code}/preview")
def classlib_phen_preview(cid: str, code: str) -> dict[str, Any]:
    """现象模板实例化预览：在本类第一个设备组的第一台设备上展开为具体位号。"""
    from backend.v2.phenomena import iter_conditions, rule_text
    ctx = get_ctx()
    tpl = next((x for x in _cl().effective(cid, "phenomena") if x["code"] == code), None)
    if not tpl:
        raise HTTPException(404, code)
    inst = _class_instances(ctx, _cl().cls(cid))
    if not inst:
        return {"instance": None, "lines": [], "note": "本类暂无实例"}
    gid = inst[0]["id"]
    names = [((c.get("subject") or {}).get("name") or "") for c in iter_conditions(tpl.get("rule")) if (c.get("subject") or {}).get("kind") == "parameter"]
    members = ctx.group_members(gid) or [gid]
    member = next((m for m in members if any(ctx.parameter_tags(m, n) for n in names)), members[0])
    lines = []
    for c in iter_conditions(tpl.get("rule")):
        s = c.get("subject") or {}
        if s.get("kind") == "parameter":
            tags = [t["name"] for t in ctx.parameter_tags(member, s.get("name") or "")]
            lines.append({"text": rule_text(c, ctx.limits, {}), "tags": tags or ["（本台未落到测点）"]})
        else:
            lines.append({"text": rule_text(c, ctx.limits, {k: v["name"] for k, v in ctx.calcs.items.items()}), "tags": []})
    return {"instance": inst[0]["name"], "member": ctx.object_name(member), "lines": lines,
            "ruleText": rule_text(tpl.get("rule"), ctx.limits, {k: v["name"] for k, v in ctx.calcs.items.items()}) if tpl.get("rule") else "（判定规则待定义）"}


@router.get("/classlib/section/{sec}")
def classlib_section(sec: str) -> dict[str, Any]:
    items = _cl_guard(_cl().section, sec)
    out = {"items": items}
    if sec == "metaclasses":
        out["usage"] = {m["code"]: sum(1 for c in _cl().data["classes"] if c.get("metaclass") == m["code"]) for m in items}
    if sec == "capabilities":
        names = {c["id"]: c["name"] for c in _cl().data["classes"]}
        out["classNames"] = names
    return out


@router.put("/classlib/section/{sec}/{code}")
def classlib_section_upsert(sec: str, code: str, body: dict = Body(...)) -> dict[str, Any]:
    from backend.v2.classlib import SECTIONS
    item = _cl_guard(_cl().upsert, sec, code, body)
    _cl_audit(f"修改{SECTIONS.get(sec, sec)}", item.get("name") or item["code"], item["code"])
    return item


@router.delete("/classlib/section/{sec}/{code}")
def classlib_section_delete(sec: str, code: str) -> dict[str, Any]:
    from backend.v2.classlib import SECTIONS
    old = _cl_guard(_cl().delete, sec, code)
    _cl_audit(f"删除{SECTIONS.get(sec, sec)}", old.get("name") or code, code)
    return {"deleted": code}


@router.get("/classlib/hierarchy-preview")
def classlib_hierarchy_preview() -> dict[str, Any]:
    """层级模板预览（取自已引用工程 105 车间）：车间 › 工艺段 › 工序，以及工序的子工序链。"""
    h = get_ctx().hierarchy
    op = next((o for o in h.ops.values() if o.get("subSteps")), next(iter(h.ops.values())))
    return {"path": [p["name"] for p in h.path(op["id"])], "subSteps": op.get("subSteps") or [],
            "levels": {"WORKSHOP": len(h.workshops), "SECTION": len(h.segments), "PROCESS": len(h.ops),
                       "SUBPROC": sum(len(o.get("subSteps") or []) for o in h.ops.values())}}


MAP_SAMPLES = {"位号解析": ["TI_1301C", "AT_1301C1", "FT_1302A", "P_1303C_RUN", "XV_1304C_VAL2", "SJGYW_C", "PT_1301", "HV_1301_AO"],
               "设备识别": ["水解罐C", "RB储罐A", "一级离心机A", "碳酸钾泵", "结晶罐A1"]}


@router.post("/classlib/mapping-test")
def classlib_mapping_test(body: dict = Body(...)) -> dict[str, Any]:
    """映射规则测试（需求 SW-011 第 5 条）：输入样例，显示解析结果、命中规则与置信度；同时给出点表中的实际归属作对照。"""
    from backend.v2.classlib import run_mapping
    ctx = get_ctx()
    rule = next((r for r in _cl().data["mappingRules"] if r["code"] == body.get("code")), None)
    if not rule:
        raise HTTPException(404, body.get("code"))
    raw = body.get("samples") or MAP_SAMPLES.get(rule["kind"]) or []
    samples = []
    for s in raw:
        t = ctx.tag_by_name.get(str(s).upper()) or {}
        samples.append({"tag": t.get("name") or s, "desc": t.get("rawDescription") or "", "equipment": t.get("equipmentName") or "",
                        "variable": t.get("variableCategory") or ""})
    res = _cl_guard(run_mapping, rule, samples, _cl().data["library"].get("funcMap") or {})
    hits = 0
    if rule.get("pattern") and rule["kind"] == "位号解析":
        import re as _re
        rx = _re.compile(rule["pattern"])
        hits = sum(1 for n in ctx.tag_by_name if rx.match(n))
    return {"rule": rule, "results": res, "hits": hits, "total": len(ctx.tag_by_name)}


@router.get("/classlib/algorithms")
def classlib_algorithms() -> dict[str, Any]:
    ctx = get_ctx()
    caps = _cl().data["capabilities"]
    items = []
    for a in ctx.algos.items.values():
        items.append({**a, "usedByCaps": [c["code"] for c in caps if c.get("algorithm") == a["id"]],
                      "usedByCalcs": [c["id"] for c in ctx.calcs.items.values() if c.get("algorithmId") == a["id"]],
                      "impl": "Python 包（本 Demo 内置实现）"})
    return {"items": items}


@router.post("/classlib/algorithms/{aid}/test")
def classlib_algorithm_test(aid: str, body: dict = Body(...)) -> dict[str, Any]:
    """算法测试（需求 SW-013 第 2 条）：输入测试数据（数组 / 常量），看输出与日志。内置实现代替隔离环境。"""
    import time
    import numpy as np
    ctx = get_ctx()
    algo = _guard(ctx.algos.get, aid)
    args = {}
    log = []
    for inp in algo.get("inputs") or []:
        v = (body.get("inputs") or {}).get(inp["name"])
        if v is None:
            if inp.get("default") is not None:
                v = inp["default"]
            elif inp.get("required"):
                raise HTTPException(400, f"缺少输入 {inp['name']}（{inp['label']}）")
            else:
                continue
        if isinstance(v, list) and v and isinstance(v[0], list):
            args[inp["name"]] = [np.asarray(x, dtype=float) for x in v]
        elif isinstance(v, list):
            args[inp["name"]] = [np.asarray(v, dtype=float)] if inp.get("multi") else np.asarray(v, dtype=float)
        else:
            args[inp["name"]] = v
        log.append(f"输入 {inp['name']} = {v}")
    t0 = time.time()
    try:
        out = ctx.algos.invoke(aid, args, float(body.get("stepMin") or 1))
        ok, err = True, ""
        values = [round(float(x), 4) for x in np.atleast_1d(out)][:200]
    except Exception as exc:  # noqa: BLE001
        ok, err, values = False, str(exc), []
    return {"ok": ok, "error": err, "output": {(algo.get("output") or {}).get("name") or "out": values},
            "ms": int((time.time() - t0) * 1000), "log": log + ["运行环境：本 Demo 内置实现（代替隔离环境）"]}


@router.post("/classlib/publish")
def classlib_publish(body: dict = Body(default={})) -> dict[str, Any]:
    v = _cl_guard(_cl().publish, body.get("note") or "")
    _cl_audit("发布类库", v["version"], v["version"], body.get("note") or "")
    return v


@router.post("/classlib/versions")
def classlib_new_version(body: dict = Body(default={})) -> dict[str, Any]:
    v = _cl_guard(_cl().new_version, body.get("base"))
    _cl_audit("新建类库版本", v["version"], v["version"], f"基于 {v['base']}")
    return v


@router.get("/classlib/diff")
def classlib_diff(a: str, b: str = "current") -> dict[str, Any]:
    return _cl_guard(_cl().diff, a, b)


@router.get("/classlib/export")
def classlib_export():  # noqa: ANN201
    """导出类库包（需求 SW-014 第 4 条）：当前版本的类库内容（JSON）。"""
    import json as _json
    cl = _cl()
    pkg = {"format": "6apa-classlib/1", "library": cl.data["library"], "version": cl.current["version"], "exportedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
           **cl._content()}
    _cl_audit("导出类库包", cl.current["version"], cl.current["version"])
    return _download(_json.dumps(pkg, ensure_ascii=False, indent=1).encode("utf-8"), f"类库包_{cl.current['version']}.json", "application/json")


@router.post("/classlib/import")
def classlib_import(body: dict = Body(...)) -> dict[str, Any]:
    """导入类库包：按编码检测冲突，strategy = merge（覆盖同编码）/ skip（跳过同编码）。"""
    cl = _cl()
    _cl_guard(cl.editable)
    pkg = body.get("package") or {}
    if pkg.get("format") != "6apa-classlib/1":
        raise HTTPException(400, "不是本系统导出的类库包")
    strategy = body.get("strategy") or "skip"
    stats = {"added": 0, "merged": 0, "skipped": 0}
    for sec in ("metaclasses", "hierarchyTypes", "hierarchyTemplates", "relationTypes", "mappingRules", "capabilities"):
        mine = {x["code"]: x for x in cl.data[sec]}
        for x in pkg.get(sec) or []:
            if x["code"] in mine:
                if strategy == "merge":
                    cl.data[sec][cl.data[sec].index(mine[x["code"]])] = x
                    stats["merged"] += 1
                else:
                    stats["skipped"] += 1
            else:
                cl.data[sec].append(x)
                stats["added"] += 1
    mine = {c["id"]: c for c in cl.data["classes"]}
    for c in pkg.get("classes") or []:
        if c["id"] in mine:
            if strategy == "merge":
                cl.data["classes"][cl.data["classes"].index(mine[c["id"]])] = c
                stats["merged"] += 1
            else:
                stats["skipped"] += 1
        else:
            cl.data["classes"].append(c)
            stats["added"] += 1
    cl.save()
    _cl_audit("导入类库包", f"{pkg.get('version')}（{strategy}）", "", str(stats))
    return stats


# ------------------------------------------------------------------ 运行态（需求 4.9）
@router.get("/runtime/status")
def runtime_status() -> dict[str, Any]:
    from backend.v2 import runtime
    return runtime.status(get_ctx())


@router.post("/runtime/evaluate")
def runtime_evaluate(body: dict = Body(default={})) -> dict[str, Any]:
    from backend.v2 import runtime
    ctx = get_ctx()
    seg = body.get("seg") or None
    if seg and seg not in ctx.hierarchy.segments:
        raise HTTPException(404, f"未找到工艺段：{seg}")
    return runtime.evaluate(ctx, "all" if body.get("scope") == "all" else "effective", seg)


@router.get("/runtime/causes/{pid}")
def runtime_causes(pid: str, target: Optional[str] = None) -> dict[str, Any]:
    from backend.v2 import runtime
    return _guard(runtime.cause_states, get_ctx(), pid, target)


@router.get("/runtime/bindings")
def runtime_bindings() -> dict[str, Any]:
    from backend.v2 import runtime
    return runtime.binding_summary(get_ctx())


@router.get("/knowledge")
def knowledge_list(status: str = "") -> dict[str, Any]:
    from backend.v2.userdata import KNOWLEDGE_TYPES
    items = [k for k in reversed(get_ctx().knowledge.items) if not status or k["status"] == status]
    return {"items": items, "types": KNOWLEDGE_TYPES, "pending": sum(1 for k in get_ctx().knowledge.items if k["status"] == "待审核")}


@router.post("/knowledge")
def knowledge_submit(body: dict = Body(...)) -> dict[str, Any]:
    """知识沉淀提交接口（需求 SW-075）：智能体或业务应用提交新知识，进入工程态候选审核队列。"""
    from backend.v2.userdata import UserDataError
    ctx = get_ctx()
    try:
        rec = ctx.knowledge.submit(body)
    except UserDataError as exc:
        raise HTTPException(400, str(exc))
    ctx.audit.record("提交知识", "知识沉淀", rec["id"], f"{rec['type']}：{rec['content'][:40]}", objects=rec["objectIds"], note=rec["submitter"])
    return rec


@router.post("/knowledge/{kid}/review")
def knowledge_review(kid: str, body: dict = Body(...)) -> dict[str, Any]:
    """审核知识沉淀：采纳后按类型落到本体（草案），经发布后生效；驳回只记录意见。"""
    from backend.v2.userdata import UserDataError
    ctx = get_ctx()
    rec = _guard(ctx.knowledge.get, kid)
    decision = body.get("decision")
    if decision not in ("采纳", "驳回"):
        raise HTTPException(400, "审核结论只能是 采纳 / 驳回")
    result = ""
    if decision == "采纳":
        pl = rec.get("payload") or {}
        if rec["type"] == "新的根因关系" and pl.get("cause") and pl.get("effect"):
            link = _guard(ctx.phen.create_link, {"cause": pl["cause"], "effect": pl["effect"], "confidence": pl.get("confidence") or "低",
                                                 "mechanism": rec["content"], "basis": f"知识沉淀 {kid}：{rec['basis']}"})
            link["source"] = {"kind": "知识沉淀", "ref": kid}
            ctx.phen._save("links")
            _audit("新增", "导致关系", None, tabs.link_view(ctx, link), _link_objects(ctx, link))
            result = f"已新增导致关系 {link['id']} （草案）"
        elif rec["type"] == "关系置信度修正" and pl.get("linkId") and pl.get("confidence"):
            import copy
            before = copy.deepcopy(_guard(ctx.phen.get_link, pl["linkId"]))
            after = _guard(ctx.phen.update_link, pl["linkId"], {"confidence": pl["confidence"]})
            _audit("修改", "导致关系", before, after, _link_objects(ctx, after))
            result = f"已把 {pl['linkId']} 的置信度改为 {pl['confidence']}"
        else:
            result = "已采纳，需工程人员按建议在本体详情中修改"
    try:
        out = ctx.knowledge.set_review(kid, decision, body.get("comment") or "", result)
    except UserDataError as exc:
        raise HTTPException(400, str(exc))
    ctx.audit.record(f"审核知识·{decision}", "知识沉淀", kid, f"{rec['type']}：{rec['content'][:40]}", note=result or (body.get("comment") or ""))
    return out


# ------------------------------------------------------------------ 发布与版本（需求 SW-060 / 061 / 062）
@router.get("/releases")
def releases() -> dict[str, Any]:
    from backend.v2 import release
    return release.list_releases()


@router.get("/releases/preview")
def release_preview() -> dict[str, Any]:
    """发布前预览：工程态当前各类数据的总数 / 生效数（只有生效的现象、导致关系、计算组态进入发布内容）。"""
    from backend.v2 import release
    return {"stats": release._stats(release.snapshot(get_ctx()))}


@router.post("/releases")
def release_publish(body: dict = Body(default={})) -> dict[str, Any]:
    from backend.v2 import release
    from backend.v2.userdata import UserDataError
    ctx = get_ctx()
    try:
        rec = release.publish(ctx, body.get("note") or "")
    except UserDataError as exc:
        raise HTTPException(400, str(exc))
    st = rec["stats"]
    ctx.audit.record("发布", "本体版本", rec["version"], rec["version"],
                     note=f"{rec['note']}；现象 生效 {st['phenomena']['published']}/{st['phenomena']['total']}，"
                          f"导致关系 生效 {st['links']['published']}/{st['links']['total']}")
    return rec


@router.get("/releases/compare")
def release_compare(a: str, b: str) -> dict[str, Any]:
    from backend.v2 import release
    try:
        return release.compare(get_ctx(), a, b)
    except LookupError as exc:
        raise HTTPException(404, f"未找到版本：{exc}")


@router.post("/releases/{version}/rollback")
def release_rollback(version: str, body: dict = Body(default={})) -> dict[str, Any]:
    from backend.v2 import release
    ctx = get_ctx()
    try:
        rec = release.rollback(ctx, version, bool(body.get("syncDraft")), body.get("note") or "")
    except LookupError:
        raise HTTPException(404, f"未找到版本：{version}")
    ctx.audit.record("回滚", "本体版本", rec["version"], rec["version"],
                     note=f"回滚到 {version}{'，工程态编辑数据同步回退' if rec['syncDraft'] else '，工程态编辑数据不变'}")
    return rec


@router.post("/status-batch")
def status_batch(body: dict = Body(...)) -> dict[str, Any]:
    from backend.v2 import release
    from backend.v2.userdata import UserDataError
    ctx = get_ctx()
    try:
        changed = release.batch_status(ctx, body.get("kind") or "", list(body.get("ids") or []), body.get("status") or "")
    except UserDataError as exc:
        raise HTTPException(400, str(exc))
    label = {"phenomena": "现象", "links": "导致关系", "calculations": "计算组态"}[body["kind"]]
    for c in changed:
        ctx.audit.record("批量变更状态", label, c["id"], c["name"],
                         changes=[{"field": "status", "before": c["before"], "after": c["after"]}])
    return {"changed": len(changed), "items": changed}


def _download(content: bytes, filename: str, media: str, extra: Optional[dict] = None):  # noqa: ANN202
    from urllib.parse import quote
    from fastapi.responses import Response
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
               "Access-Control-Expose-Headers": "X-Export-Info"}
    if extra:
        headers["X-Export-Info"] = quote(json_dumps(extra))
    return Response(content=content, media_type=media, headers=headers)


def json_dumps(v: Any) -> str:
    import json
    return json.dumps(v, ensure_ascii=False)


@router.get("/export/excel")
def export_excel(seg: Optional[str] = None):  # noqa: ANN201
    """导出本体数据为 Excel（需求 SW-067）：全量或按工艺段。"""
    from datetime import datetime
    from backend.v2 import export
    ctx = get_ctx()
    try:
        data, counts = export.excel(ctx, seg)
    except LookupError:
        raise HTTPException(404, f"未找到工艺段：{seg}")
    scope = ctx.hierarchy.segments[seg]["name"] if seg else "全车间"
    ctx.audit.record("导出", "Excel", seg or "all", f"本体数据 Excel（{scope}）", note="、".join(f"{k} {v}" for k, v in counts.items()))
    name = f"6APA本体_{scope}_{datetime.now().strftime('%Y%m%d%H%M')}.xlsx"
    return _download(data, name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", {"counts": counts})


@router.get("/export/ttl")
def export_ttl(seg: Optional[str] = None):  # noqa: ANN201
    """导出 TTL（需求 SW-069）：RDF 1.1 Turtle，导出后语法自检。"""
    from datetime import datetime
    from backend.v2 import export
    ctx = get_ctx()
    if seg and seg not in ctx.hierarchy.segments:
        raise HTTPException(404, f"未找到工艺段：{seg}")
    text, check = export.ttl(ctx, seg)
    scope = ctx.hierarchy.segments[seg]["name"] if seg else "全车间"
    ctx.audit.record("导出", "TTL", seg or "all", f"本体 TTL（{scope}）",
                     note=f"节点 {check['nodes']}、关系 {check['edges']}、导致关系 {check['causalLinks']}；语法自检：{check['syntax']}")
    name = f"6APA本体_{scope}_{datetime.now().strftime('%Y%m%d%H%M')}.ttl"
    return _download(text.encode("utf-8"), name, "text/turtle; charset=utf-8", check)


@router.get("/audit")
def audit_log(op: str = "", kind: str = "", keyword: str = "", limit: int = 300) -> dict[str, Any]:
    """操作日志（需求 SW-079）：编辑、导出、发布、回滚、删除等。"""
    items = [e for e in reversed(get_ctx().audit.data.get("items", []))
             if (not op or e["op"] == op) and (not kind or e["kind"] == kind)
             and (not keyword or keyword in f"{e['name']}{e.get('note') or ''}{e['targetId']}")]
    ops = sorted({e["op"] for e in get_ctx().audit.data.get("items", [])})
    return {"items": items[:limit], "total": len(items), "ops": ops}


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


@router.get("/objects/{object_id}/info")
def object_info(object_id: str, op: Optional[str] = None) -> dict[str, Any]:
    """对象基础信息与变更记录（需求 SW-041 第 4、5 条，SW-062）：ID、编码、类、状态、来源、所属位置、被谁引用、变更记录。"""
    ctx = get_ctx()
    head = _guard(tabs.header, ctx, object_id, op)
    prof = ctx.profile(object_id)
    dcs = ctx.store.dcs
    attrs = {a["name"]: a for a in prof.get("attributes") or [] if a.get("kind") == "固有"}
    is_group = object_id in dcs.equipment_groups
    raw = dcs.equipment_groups.get(object_id) if is_group else dcs.equipment.get(object_id) or {}
    my_tags = {t["name"] for t in ctx.tags_of_equipment.get(object_id, [])}
    if is_group:
        for m in ctx.group_members(object_id):
            my_tags |= {t["name"] for t in ctx.tags_of_equipment.get(m, [])}
    own_phen = [p for p, o in ctx.phenomena_for_object(object_id)]
    phen_ids = {p["id"] for p in own_phen}
    tag_refs = []
    from backend.v2.phenomena import iter_conditions
    for p in ctx.phen.phenomena.values():
        if p["id"] in phen_ids:
            continue
        if any((c.get("subject") or {}).get("tag") in my_tags for c in iter_conditions(p.get("rule"))):
            tag_refs.append({"id": p["id"], "name": p["name"], "anchor": (p.get("anchor") or {}).get("name")})
    calc_refs = [{"id": c["id"], "name": c["name"], "how": "作用对象" if (c.get("anchor") or {}).get("id") == object_id else "绑定位号"}
                 for c in ctx.calcs.items.values()
                 if (c.get("anchor") or {}).get("id") == object_id
                 or any((b or {}).get("tag") in my_tags for b in (c.get("bindings") or {}).values())
                 or any((b or {}).get("groupId") == object_id for b in (c.get("bindings") or {}).values())]
    rels = [{"id": r["id"], "text": f"{r['from']['name']} —{r['label']}→ {r['to']['name']}", "type": r["type"]}
            for r in ctx.relations.items if object_id in (r["from"]["id"], r["to"]["id"])]
    overrides = [{"kind": "现象", "id": v["phenomenonId"], "state": "已禁用" if v["disabled"] else "已覆盖", "note": v.get("note"), "at": v["updatedAt"]}
                 for v in ctx.overrides.data["phenomena"].values() if v["objectId"] == object_id] + \
                [{"kind": "限值", "id": v["limitId"], "state": "已禁用" if v["disabled"] else "已覆盖", "note": v.get("note"), "at": v["updatedAt"]}
                 for v in ctx.overrides.data["limits"].values() if v["objectId"] == object_id]
    h = ctx.hierarchy
    drawings = [{"opId": o, "name": h.ops[o]["name"], "hasImage": bool(__import__("backend.v2.drawing", fromlist=["image_path"]).image_path(o))}
                for o in head["opIds"]]
    return {
        "id": object_id, "name": head["name"], "kind": "设备组" if is_group else "设备",
        "code": (attrs.get("设备编码") or {}).get("value") or raw.get("owlSubject") or "",
        "className": head.get("className"), "classPath": head.get("classPath"),
        "status": "生效（来自点表与设备主数据）",
        "source": "DCS 点表 · 设备主数据" + ("（设备归并 / 拆分表）" if (attrs.get("点表中的其他写法") or {}).get("value") else ""),
        "confidence": (attrs.get("归属置信度") or {}).get("value"),
        "group": head.get("group"), "path": head["path"], "drawings": drawings,
        "assetPath": [x for x in [(attrs.get("资产大类") or {}).get("value"), (attrs.get("设备类型") or {}).get("value")] if x],
        "tagCount": len(my_tags), "phenomenonCount": len(own_phen),
        "referencedBy": {"phenomena": tag_refs, "calculations": calc_refs, "relations": rels},
        "overrides": overrides,
        "changes": ctx.audit.for_object({object_id} | phen_ids)[:200],
    }


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


# ------------------------------------------------------------------ 处置规程（需求 SW-051）
@router.get("/procedures/{cid}")
def procedure(cid: str) -> dict[str, Any]:
    from backend.v2 import procedures
    ctx = get_ctx()
    card = ctx.store.procedures.cards.get(cid)
    if not card:
        raise HTTPException(404, f"未找到处置卡：{cid}")
    return procedures.card_view(ctx, card)


@router.put("/procedures/{cid}")
def procedure_update(cid: str, body: dict = Body(...)) -> dict[str, Any]:
    from backend.v2 import procedures
    from backend.v2.userdata import UserDataError, diff
    ctx = get_ctx()
    card = ctx.store.procedures.cards.get(cid)
    if not card:
        raise HTTPException(404, f"未找到处置卡：{cid}")
    before = procedures.card_view(ctx, card)
    try:
        ctx.procedure_edits.put(cid, body)
    except UserDataError as exc:
        raise HTTPException(400, str(exc))
    after = procedures.card_view(ctx, card)
    keys = ("steps", "checks", "autoExecution", "authorization", "version", "status", "scope")
    ctx.audit.record("修改", "处置规程", cid, card["name"],
                     objects=[p["anchorId"] for p in after["alarmPhenomena"]] + [p["id"] for p in after["alarmPhenomena"]],
                     changes=diff({k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}))
    return after


@router.post("/procedures/{cid}/causes/{seq}/split")
def procedure_split(cid: str, seq: str, body: dict = Body(default={})) -> dict[str, Any]:
    """把处置卡的一条可能原因拆成「原因现象 + 导致关系」（4.4 d：处置卡分别对应为现象、根因影响关系和处置规程）。"""
    from backend.v2 import procedures
    ctx = get_ctx()
    try:
        r = procedures.split_cause(ctx, cid, seq, body.get("anchorId"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except LookupError as exc:
        raise HTTPException(404, f"未找到：{exc}")
    alarm = ctx.phen.phenomena[r["alarm"]]
    for x in r["created"]:
        if x in ctx.phen.phenomena:
            _audit("新增", "现象", None, ctx.phen.phenomena[x], _anchor_objects(ctx.phen.phenomena[x]))
        elif x in ctx.phen.links:
            _audit("新增", "导致关系", None, tabs.link_view(ctx, ctx.phen.links[x]), _link_objects(ctx, ctx.phen.links[x]))
    return {**r, "card": procedures.card_view(ctx, ctx.store.procedures.cards[cid]), "anchor": alarm.get("anchor")}


@router.post("/procedures/{cid}/split-all")
def procedure_split_all(cid: str, body: dict = Body(default={})) -> dict[str, Any]:
    ctx = get_ctx()
    card = ctx.store.procedures.cards.get(cid)
    if not card:
        raise HTTPException(404, f"未找到处置卡：{cid}")
    created: list[str] = []
    for c in card.get("causes") or []:
        created += procedure_split(cid, str(c.get("seq")), body)["created"]
    from backend.v2 import procedures
    return {"created": created, "card": procedures.card_view(ctx, card)}


# ------------------------------------------------------------------ 人工关系（拓扑 / 工艺影响，需求 SW-044 / 049）
@router.get("/relation-candidates")
def relation_candidates(type: str, end: str = "to", keyword: str = "", limit: int = 30) -> dict[str, Any]:
    """关系端点候选：按关系类型允许的端点类型过滤，名称 / 拼音首字母匹配。"""
    from backend.v2.search import initials
    from backend.v2.userdata import KIND_NAMES, RELATION_TYPES
    spec = RELATION_TYPES.get(type)
    if not spec:
        raise HTTPException(400, f"关系类型只能是：{'、'.join(RELATION_TYPES)}")
    allowed = spec["from" if end == "from" else "to"]
    kw = keyword.strip().lower()
    out = []
    for e in get_ctx().endpoint_index().values():
        if e["kind"] not in allowed:
            continue
        if kw and kw not in e["name"].lower() and not (kw.isascii() and kw in initials(e["name"])):
            continue
        out.append({**e, "kindName": KIND_NAMES[e["kind"]]})
        if len(out) >= limit:
            break
    return {"items": out, "allowed": [KIND_NAMES[k] for k in sorted(allowed)]}


@router.post("/relations")
def create_relation(body: dict = Body(...)) -> dict[str, Any]:
    from backend.v2.userdata import UserDataError
    ctx = get_ctx()
    idx = ctx.endpoint_index()

    def resolve_kind(end: dict) -> Optional[str]:
        e = idx.get(end.get("id") or "")
        if e:
            end["name"] = e["name"]
            return e["kind"]
        return None
    try:
        rel = ctx.relations.create(body, resolve_kind)
    except UserDataError as exc:
        raise HTTPException(400, str(exc))
    ctx.audit.record("新增", "关系", rel["id"], f"{rel['from']['name']} —{rel['label']}→ {rel['to']['name']}",
                     objects=[rel["from"]["id"], rel["to"]["id"]], note=rel["type"])
    return rel


@router.delete("/relations/{rid}")
def delete_relation(rid: str) -> dict[str, Any]:
    ctx = get_ctx()
    rel = _guard(ctx.relations.delete, rid)
    ctx.audit.record("删除", "关系", rid, f"{rel['from']['name']} —{rel['label']}→ {rel['to']['name']}",
                     objects=[rel["from"]["id"], rel["to"]["id"]], note=rel["type"])
    return {"deleted": rid}


# ------------------------------------------------------------------ 继承覆盖（设备上覆盖 / 禁用设备组的现象与限值）
def _check_inherited(ctx, object_id: str) -> str:  # noqa: ANN001
    e = ctx.store.dcs.equipment.get(object_id)
    if not e or not e.get("equipmentGroupId"):
        raise HTTPException(400, "只有属于设备组的设备才能覆盖继承来的定义")
    return e["equipmentGroupId"]


@router.put("/objects/{object_id}/overrides/phenomena/{pid}")
def override_phenomenon(object_id: str, pid: str, body: dict = Body(...)) -> dict[str, Any]:
    from backend.v2.phenomena import validate_rule
    from backend.v2.userdata import UserDataError, diff
    ctx = get_ctx()
    gid = _check_inherited(ctx, object_id)
    p = _guard(ctx.phen.get, pid)
    if (p.get("anchor") or {}).get("id") != gid:
        raise HTTPException(400, "该现象不是从本设备所属设备组继承来的")
    if body.get("rule"):
        _guard(validate_rule, body["rule"])
    before = ctx.overrides.phenomenon(object_id, pid)
    try:
        entry = ctx.overrides.set_phenomenon(object_id, pid, body)
    except UserDataError as exc:
        raise HTTPException(400, str(exc))
    ctx.audit.record("禁用继承" if entry["disabled"] else "覆盖继承", "现象", pid, p["name"], objects=[object_id],
                     changes=diff(_readable({"rule": (before or {}).get("rule") or p.get("rule"), "disabled": bool((before or {}).get("disabled"))}),
                                  _readable({"rule": entry.get("rule") or p.get("rule"), "disabled": entry["disabled"]})),
                     note=f"在 {ctx.object_name(object_id)} 上")
    return entry


@router.delete("/objects/{object_id}/overrides/phenomena/{pid}")
def restore_phenomenon(object_id: str, pid: str) -> dict[str, Any]:
    ctx = get_ctx()
    old = ctx.overrides.clear("phenomena", object_id, pid)
    if old:
        name = (ctx.phen.phenomena.get(pid) or {}).get("name", pid)
        ctx.audit.record("恢复继承", "现象", pid, name, objects=[object_id], note=f"在 {ctx.object_name(object_id)} 上")
    return {"restored": bool(old)}


@router.put("/objects/{object_id}/overrides/limits/{lid}")
def override_limit(object_id: str, lid: str, body: dict = Body(...)) -> dict[str, Any]:
    from backend.v2.userdata import UserDataError, diff
    ctx = get_ctx()
    _check_inherited(ctx, object_id)
    limit = ctx.limits.get(lid)
    if not limit:
        raise HTTPException(404, f"未找到限值：{lid}")
    before = ctx.overrides.limit(object_id, lid)
    try:
        entry = ctx.overrides.set_limit(object_id, lid, body)
    except UserDataError as exc:
        raise HTTPException(400, str(exc))
    base = {f: limit.get(f) for f in ("lowLow", "low", "normalLow", "normalHigh", "high", "highHigh")}
    ctx.audit.record("禁用继承" if entry["disabled"] else "覆盖继承", "参数约束", lid, f"{lid} {limit.get('appliesTo') or ''}",
                     objects=[object_id], note=f"在 {ctx.object_name(object_id)} 上",
                     changes=diff({**base, **((before or {}).get("values") or {}), "disabled": bool((before or {}).get("disabled"))},
                                  {**base, **(entry.get("values") or {}), "disabled": entry["disabled"]}))
    return entry


@router.delete("/objects/{object_id}/overrides/limits/{lid}")
def restore_limit(object_id: str, lid: str) -> dict[str, Any]:
    ctx = get_ctx()
    old = ctx.overrides.clear("limits", object_id, lid)
    if old:
        ctx.audit.record("恢复继承", "参数约束", lid, lid, objects=[object_id], note=f"在 {ctx.object_name(object_id)} 上")
    return {"restored": bool(old)}


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
    from backend.v2 import procedures
    view["procedures"] = procedures.cards_for_phenomenon(ctx, pid)  # 需求 SW-051：现象详情中直接查看关联规程
    return view


# 变更记录（需求 SW-062）：现象、导致关系、计算组态的增删改都记一条
def _readable(rec: Optional[dict]) -> Optional[dict]:
    """变更记录里判定规则显示为自然语言，锚点显示名称。"""
    if not rec:
        return rec
    from backend.v2.phenomena import rule_text
    ctx = get_ctx()
    out = dict(rec)
    if "rule" in out:
        out["rule"] = rule_text(out["rule"], ctx.limits, {k: v["name"] for k, v in ctx.calcs.items.items()}) if out["rule"] else "（待定义）"
    if isinstance(out.get("anchor"), dict):
        out["anchor"] = out["anchor"].get("name")
    return out


def _audit(op: str, kind: str, before: Optional[dict], after: Optional[dict], objects: list[str]) -> None:
    from backend.v2.userdata import diff
    before, after = _readable(before), _readable(after)
    rec = after or before or {}
    name = rec.get("name") or (f"{rec.get('causeName', rec.get('cause'))} → {rec.get('effectName', rec.get('effect'))}" if "cause" in rec else rec.get("id", ""))
    get_ctx().audit.record(op, kind, rec.get("id", ""), name, objects=objects,
                           changes=diff(before, after) if op == "修改" else [])


def _anchor_objects(rec: Optional[dict]) -> list[str]:
    return [((rec or {}).get("anchor") or {}).get("id") or ""]


def _link_objects(ctx, link: dict) -> list[str]:  # noqa: ANN001
    return [((ctx.phen.phenomena.get(link.get(k)) or {}).get("anchor") or {}).get("id") or "" for k in ("cause", "effect")] + \
        [link.get("cause") or "", link.get("effect") or ""]


@router.post("/phenomena")
def create_phenomenon(body: dict = Body(...)) -> dict[str, Any]:
    ctx = get_ctx()
    rec = _guard(ctx.phen.create_phenomenon, body)
    _audit("新增", "现象", None, rec, _anchor_objects(rec))
    return tabs.phenomenon_view(ctx, rec)


@router.put("/phenomena/{pid}")
def update_phenomenon(pid: str, body: dict = Body(...)) -> dict[str, Any]:
    import copy
    ctx = get_ctx()
    before = copy.deepcopy(_guard(ctx.phen.get, pid))
    rec = _guard(ctx.phen.update_phenomenon, pid, body)
    _audit("修改", "现象", before, rec, _anchor_objects(rec) + _anchor_objects(before))
    return tabs.phenomenon_view(ctx, rec)


@router.delete("/phenomena/{pid}")
def delete_phenomenon(pid: str) -> dict[str, Any]:
    import copy
    ctx = get_ctx()
    before = copy.deepcopy(_guard(ctx.phen.get, pid))
    out = _guard(ctx.phen.delete_phenomenon, pid)
    _audit("删除", "现象", before, None, _anchor_objects(before))
    return out


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
                  op_id=body.get("opId"), target_id=body.get("targetId"), phenomenon_id=pid)


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
    rec = _guard(ctx.phen.create_link, body)
    view = tabs.link_view(ctx, rec)
    _audit("新增", "导致关系", None, view, _link_objects(ctx, rec))
    return {**view, **({"warnings": rec["warnings"]} if rec.get("warnings") else {})}


@router.put("/causal-links/{lid}")
def update_link(lid: str, body: dict = Body(...)) -> dict[str, Any]:
    import copy
    ctx = get_ctx()
    before = copy.deepcopy(_guard(ctx.phen.get_link, lid))
    rec = _guard(ctx.phen.update_link, lid, body)
    _audit("修改", "导致关系", before, rec, _link_objects(ctx, rec))
    return tabs.link_view(ctx, rec)


@router.delete("/causal-links/{lid}")
def delete_link(lid: str) -> dict[str, Any]:
    import copy
    ctx = get_ctx()
    before = copy.deepcopy(_guard(ctx.phen.get_link, lid))
    objs = _link_objects(ctx, before)
    out = _guard(ctx.phen.delete_link, lid)
    _audit("删除", "导致关系", before, None, objs)
    return out


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


@router.get("/calc-meta")
def calc_meta() -> dict[str, Any]:
    from backend.v2.calculations import DEFAULT_EXECUTION, EXEC_MODES, FAILURE_MODES
    return {"modes": EXEC_MODES, "failureModes": FAILURE_MODES, "defaults": DEFAULT_EXECUTION,
            "bindingKinds": calculations.BINDING_KINDS}


def _check_calc_refs(body: dict) -> None:
    """保存前校验参数绑定指向的本体对象存在（需求 SW-050 第 3 条）。"""
    ctx = get_ctx()
    anchor = (body.get("anchor") or {}).get("id") or ""

    def names(oid: str) -> set[str]:
        out = set()
        for t in [oid] + (ctx.group_members(oid) if oid.startswith("egrp-") else []):
            try:
                out |= {p["name"] for p in ctx.parameter_names(t)}
            except Exception:  # noqa: BLE001
                pass
        return out
    for name, b in (body.get("bindings") or {}).items():
        k = (b or {}).get("kind")
        if k == "parameter" and anchor.startswith(("equip-", "egrp-")) and b.get("name") not in names(anchor):
            raise HTTPException(400, f"参数 {name} 绑定的「{b.get('name')}」不是作用对象上的参数")
        if k == "groupParameter":
            if b.get("groupId") not in ctx.store.dcs.equipment_groups:
                raise HTTPException(400, f"参数 {name} 绑定的设备组不存在")
            if b.get("name") not in names(b["groupId"]):
                raise HTTPException(400, f"参数 {name} 绑定的「{b.get('name')}」不是该设备组的参数")
        if k == "tag" and b.get("tag") not in ctx.tag_by_name:
            raise HTTPException(400, f"参数 {name} 绑定的位号 {b.get('tag')} 不在点表中")


@router.post("/calculations")
def calc_create(body: dict = Body(...)) -> dict[str, Any]:
    _check_calc_refs(body)
    rec = _guard(get_ctx().calcs.create, body)
    _audit("新增", "计算组态", None, rec, _anchor_objects(rec))
    return rec


@router.put("/calculations/{cid}")
def calc_update(cid: str, body: dict = Body(...)) -> dict[str, Any]:
    import copy
    before = copy.deepcopy(_guard(get_ctx().calcs.get, cid))
    _check_calc_refs({**before, **body})
    rec = _guard(get_ctx().calcs.update, cid, body)
    _audit("修改", "计算组态", before, rec, _anchor_objects(rec))
    return rec


@router.delete("/calculations/{cid}")
def calc_delete(cid: str) -> dict[str, Any]:
    import copy
    before = copy.deepcopy(_guard(get_ctx().calcs.get, cid))
    out = _guard(get_ctx().calcs.delete, cid)
    _audit("删除", "计算组态", before, None, _anchor_objects(before))
    return out


@router.post("/calculations/{cid}/run")
def calc_run(cid: str, body: dict = Body(default={})) -> dict[str, Any]:
    import time
    from datetime import datetime
    ctx = get_ctx()
    calc = _guard(ctx.calcs.get, cid)
    t0 = time.time()
    entry = {"kind": "试算", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "ok": False, "targets": 0, "ms": 0, "error": ""}
    try:
        r = _guard(rule_eval.run_calc, ctx, calc, hours=float(body.get("hours") or 6), op_id=body.get("opId"),
                   target_id=body.get("targetId"))
        entry.update(ok=all(x.get("values") is not None for x in r["results"]), targets=len(r["results"]),
                     error="；".join(f"{x['targetName']}：{'、'.join(x['unresolved'])}" for x in r["results"] if x.get("values") is None))
        return r
    except HTTPException as exc:
        entry["error"] = str(exc.detail)
        raise
    finally:
        entry["ms"] = int((time.time() - t0) * 1000)
        ctx.calcs.log_run(cid, entry)
