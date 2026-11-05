"""工序图纸（P&ID 示意）：按本工序的设备组 / 设备和物理拓扑关系自动排布。

仓库里没有 P&ID 原图，这里生成示意图的结构数据，前端画成 SVG：
- 节点：本工序的设备组（内含本工序认领的成员）+ 未入组设备（汇总成一个框）；
- 连线：工业关系表中「物理拓扑关系」里两端都在本工序的连接；
- 进出物料：指向本工序设备组的物料流股 / 公用介质画在左侧，产出画在右侧；
- 布局：按连线做最长路径分层（左 → 右），环路忽略回边。
子工序写在图纸顶部（不单独成层）。有了真图纸后可换成图片 + 热区，接口结构不变。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.v2.context import AppContext

STREAM_TYPES = {"物料流股", "公用介质"}
MAX_STREAMS = 10


def _layers(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    out_edges: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        out_edges[a].append(b)
    # DFS 去环
    state: dict[str, int] = {}
    order: list[str] = []
    dag: list[tuple[str, str]] = []

    def visit(n: str) -> None:
        state[n] = 1
        for m in out_edges[n]:
            if state.get(m) == 1:
                continue  # 回边
            dag.append((n, m))
            if m not in state:
                visit(m)
        state[n] = 2
        order.append(n)

    for n in nodes:
        if n not in state:
            visit(n)
    layer = {n: 0 for n in nodes}
    for n in reversed(order):
        for a, b in dag:
            if a == n:
                layer[b] = max(layer[b], layer[a] + 1)
    return layer


def build(ctx: AppContext, op_id: str) -> dict[str, Any]:
    h = ctx.hierarchy
    op = h.ops[op_id]
    dcs = ctx.store.dcs
    nodes: list[dict[str, Any]] = []
    name_to_node: dict[str, str] = {}
    for gid in h.op_groups.get(op_id, []):
        group = dcs.equipment_groups[gid]
        members = h.op_group_members.get((op_id, gid), [])
        nodes.append({
            "id": gid, "kind": "group", "name": group["name"], "type": group.get("equipmentType") or "",
            "members": [{"id": e, "name": dcs.equipment[e]["name"], "tagCount": len(dcs.equipment[e].get("tagIds") or [])}
                        for e in members],
        })
        name_to_node[group["name"]] = gid
    ungrouped = h.op_ungrouped.get(op_id, [])
    if ungrouped:
        nodes.append({
            "id": f"{op_id}|ungrouped", "kind": "ungrouped", "name": "未入组设备", "type": "",
            "members": [{"id": e, "name": dcs.equipment[e]["name"], "tagCount": len(dcs.equipment[e].get("tagIds") or [])}
                        for e in ungrouped],
        })
        for e in ungrouped:
            name_to_node.setdefault(dcs.equipment[e]["name"], f"{op_id}|ungrouped")

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    inlets: dict[str, dict[str, Any]] = {}
    outlets: dict[str, dict[str, Any]] = {}
    for rel in ctx.store.relations.relations:
        if rel.get("category") != "物理拓扑关系":
            continue
        subj, obj = rel["subject"], rel["object"]
        a, b = name_to_node.get(subj["entity"]), name_to_node.get(obj["entity"])
        if a and b and a != b:
            if (a, b) not in seen:
                seen.add((a, b))
                edges.append({"from": a, "to": b, "predicate": rel["predicate"],
                              "label": rel.get("domainDescription") or "", "relationId": rel["id"]})
        elif b and not a and subj.get("type") in STREAM_TYPES:
            s = inlets.setdefault(subj["entity"], {"name": subj["entity"], "type": subj["type"], "to": []})
            if b not in s["to"]:
                s["to"].append(b)
        elif a and not b and obj.get("type") in STREAM_TYPES:
            s = outlets.setdefault(obj["entity"], {"name": obj["entity"], "type": obj["type"], "from": []})
            if a not in s["from"]:
                s["from"].append(a)

    # 既流入又产出的是本工序内部物料，不画在两侧
    internal = set(inlets) & set(outlets)
    for name in internal:
        inlets.pop(name)
        outlets.pop(name)

    layer = _layers([n["id"] for n in nodes], [(e["from"], e["to"]) for e in edges])
    for n in nodes:
        n["layer"] = layer.get(n["id"], 0)
    # 同层按名称排，未入组设备放最后一层
    max_layer = max([n["layer"] for n in nodes], default=0)
    for n in nodes:
        if n["kind"] == "ungrouped" and not any(n["id"] in (e["from"], e["to"]) for e in edges):
            n["layer"] = max_layer
    per_layer: dict[int, int] = defaultdict(int)
    for n in sorted(nodes, key=lambda n: (n["layer"], n["kind"] == "ungrouped", n["name"])):
        n["row"] = per_layer[n["layer"]]
        per_layer[n["layer"]] += 1

    return {
        "opId": op_id, "name": op["name"], "screen": op["screen"], "subSteps": op["subSteps"],
        "path": h.path(op_id), "nodes": nodes, "edges": edges,
        "inlets": list(inlets.values())[:MAX_STREAMS], "outlets": list(outlets.values())[:MAX_STREAMS],
        "internalStreams": sorted(internal),
        "kind": "schematic",
        "note": "示意图：按本体中的设备组与物理拓扑关系自动排布，不是现场 P&ID 原图",
    }
