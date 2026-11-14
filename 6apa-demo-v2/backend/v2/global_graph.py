"""全局图谱：把层级、设备、工艺参数、物料、现象和它们之间的关系拍平成一张图，供前端按视图 / 布局 / 跳数筛选。

节点类型：车间、工艺段、工序、设备组、设备、工艺参数、质量指标、物料流股、公用介质、现象、工况
关系类型：
- 包含      车间 → 工艺段 → 工序 → 设备组 → 设备（未入组设备直接挂工序）
- 工序衔接  由设备组之间跨工序的物理拓扑推出（工艺流程布局用）
- 物理拓扑  设备组 ⇄ 设备组、物料 / 介质 → 设备组、设备组 → 产出物料（工业关系表）
- 具有属性  设备组 / 物料 → 工艺参数 / 质量指标（工业关系表）
- 工艺影响  工艺参数 / 质量指标之间的正向 / 负向影响（工业关系表影响关系、质量关系）
- 挂载      现象 → 设备组 / 设备
- 导致      现象 → 现象（根因影响关系，在线编辑实时生效）
每个节点带 opIndex（工序在全车间的顺序），前端按此做「工艺流程」从左到右的布局。
"""
from __future__ import annotations

from typing import Any

from backend.v2.context import AppContext

STREAM_TYPES = {"物料流股": "物料流股", "公用介质": "公用介质"}
ATTR_TYPES = {"工艺属性": "工艺参数", "质量指标": "质量指标"}
INFLUENCE_CATEGORIES = {"影响关系", "质量关系"}


def build(ctx: AppContext, include_user: bool = True) -> dict[str, Any]:
    h = ctx.hierarchy
    dcs = ctx.store.dcs
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def node(nid: str, name: str, ntype: str, **kw: Any) -> None:
        if nid not in nodes:
            nodes[nid] = {"id": nid, "name": name, "type": ntype, **kw}

    def edge(s: str, t: str, etype: str, label: str = "", **kw: Any) -> None:
        if s == t or s not in nodes or t not in nodes or (s, t, etype) in seen_edges:
            return
        seen_edges.add((s, t, etype))
        edges.append({"s": s, "t": t, "type": etype, "label": label, **kw})

    # ---------------- 层级与设备
    op_index: dict[str, int] = {}
    for ws in h.workshops:
        node(ws["id"], ws["name"], "车间", opIndex=-1)
    for seg in h.segments.values():
        first = len(op_index)
        for op_id in seg["opIds"]:
            op_index[op_id] = len(op_index)
        node(seg["id"], seg["name"], "工艺段", segId=seg["id"], opIndex=first, order=seg["order"])
        edge(seg["workshopId"], seg["id"], "包含")
        for op_id in seg["opIds"]:
            op = h.ops[op_id]
            node(op_id, op["name"], "工序", segId=seg["id"], opId=op_id, opIndex=op_index[op_id], screen=op["screen"])
            edge(seg["id"], op_id, "包含")
    group_by_name: dict[str, str] = {}
    for op_id, gids in h.op_groups.items():
        for gid in gids:
            g = dcs.equipment_groups[gid]
            node(gid, g["name"], "设备组", segId=h.ops[op_id]["segmentId"], opId=op_id, opIndex=op_index[op_id],
                 objectId=gid, etype=g.get("equipmentType") or "")
            group_by_name.setdefault(g["name"], gid)
            edge(op_id, gid, "包含")
            for eid in h.op_group_members.get((op_id, gid), []):
                e = dcs.equipment[eid]
                node(eid, e["name"], "设备", segId=h.ops[op_id]["segmentId"], opId=op_id, opIndex=op_index[op_id],
                     objectId=eid, groupId=gid)
                edge(gid, eid, "包含")
    for op_id, eids in h.op_ungrouped.items():
        for eid in eids:
            e = dcs.equipment[eid]
            node(eid, e["name"], "设备", segId=h.ops[op_id]["segmentId"], opId=op_id, opIndex=op_index[op_id], objectId=eid)
            edge(op_id, eid, "包含")

    # ---------------- 工业关系表：物理拓扑、具有属性、工艺影响
    ent_node: dict[str, str] = {}  # 关系实体 id → 图节点 id

    def resolve(ent: dict[str, Any], create_kind: str | None = None, near: dict[str, Any] | None = None) -> str | None:
        rid = ent["id"]
        if rid in ent_node:
            return ent_node[rid]
        if ent["type"] == "生产设备" and ent["entity"] in group_by_name:
            ent_node[rid] = group_by_name[ent["entity"]]
            return ent_node[rid]
        kind = create_kind
        if kind and near is not None:
            node(rid, ent["entity"], kind, segId=near.get("segId"), opId=near.get("opId"), opIndex=near.get("opIndex", 0))
            ent_node[rid] = rid
            return rid
        return None

    rels = ctx.store.relations.relations
    # 先建流股与属性节点（需要一个已在图中的邻居来确定所在工序）
    for r in rels:
        cat, s, o = r["category"], r["subject"], r["object"]
        if cat == "物理拓扑关系":
            g_s, g_o = resolve(s), resolve(o)
            if g_s and o["type"] in STREAM_TYPES:
                resolve(o, STREAM_TYPES[o["type"]], nodes[g_s])
            if g_o and s["type"] in STREAM_TYPES:
                resolve(s, STREAM_TYPES[s["type"]], nodes[g_o])
        elif cat == "结构关系" and r["predicate"] == "具有属性" and o["type"] in ATTR_TYPES:
            owner = resolve(s)
            if owner:
                resolve(o, ATTR_TYPES[o["type"]], nodes[owner])
    for r in rels:
        cat, s, o = r["category"], r["subject"], r["object"]
        a, b = ent_node.get(s["id"]) or resolve(s), ent_node.get(o["id"]) or resolve(o)
        if not a or not b:
            continue
        if cat == "物理拓扑关系":
            edge(a, b, "物理拓扑", r["predicate"], mechanism=r.get("domainDescription") or "")
        elif cat == "结构关系" and r["predicate"] == "具有属性":
            edge(a, b, "具有属性", "具有属性")
        elif cat in INFLUENCE_CATEGORIES and s["type"] in ATTR_TYPES and o["type"] in ATTR_TYPES:
            edge(a, b, "工艺影响", r["predicate"], mechanism=r.get("domainDescription") or "")

    # 人工新增的关系（需求 SW-044 / 049：保存后全局图谱同步更新）
    if include_user:
        for r in ctx.relations.items:
            a, b = r["from"]["id"], r["to"]["id"]
            etype = "工艺影响" if r["type"] == "工艺影响" else "物理拓扑"
            edge(a, b, etype, r.get("label") or r["type"], mechanism=r.get("mechanism") or "", userRelation=True)

    # 工序衔接：设备组之间跨工序的物理拓扑
    for e in list(edges):
        if e["type"] != "物理拓扑":
            continue
        sa, sb = nodes[e["s"]], nodes[e["t"]]
        if sa["type"] == "设备组" and sb["type"] == "设备组" and sa.get("opId") != sb.get("opId"):
            edge(sa["opId"], sb["opId"], "工序衔接", f"{sa['name']} → {sb['name']}")

    # ---------------- 现象与导致关系
    for p in ctx.phen.phenomena.values():
        anchor = (p.get("anchor") or {}).get("id")
        if anchor not in nodes:
            continue
        an = nodes[anchor]
        node(p["id"], p["name"], "工况" if p.get("category") == "工况" else "现象", segId=an.get("segId"),
             opId=an.get("opId"), opIndex=an.get("opIndex", 0), anchorId=anchor, hasRule=bool(p.get("rule")),
             category=p.get("category") or "")
        edge(p["id"], anchor, "挂载", "挂在")
    for l in ctx.phen.links.values():
        edge(l["cause"], l["effect"], "导致", "导致", mechanism=l.get("mechanism") or "", confidence=l.get("confidence"))

    # 度数
    deg: dict[str, int] = {}
    for e in edges:
        deg[e["s"]] = deg.get(e["s"], 0) + 1
        deg[e["t"]] = deg.get(e["t"], 0) + 1
    for n in nodes.values():
        n["degree"] = deg.get(n["id"], 0)
    counts: dict[str, int] = {}
    for n in nodes.values():
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    ecounts: dict[str, int] = {}
    for e in edges:
        ecounts[e["type"]] = ecounts.get(e["type"], 0) + 1
    return {
        "nodes": list(nodes.values()), "edges": edges, "nodeCounts": counts, "edgeCounts": ecounts,
        "segments": [{"id": s["id"], "name": s["name"]} for s in h.segments.values()],
        "ops": [{"id": o, "name": h.ops[o]["name"], "segId": h.ops[o]["segmentId"], "index": i} for o, i in op_index.items()],
        "note": "关系全部来自本体（层级、点表设备、工业关系表、现象与根因影响关系），不按名称推断",
    }
