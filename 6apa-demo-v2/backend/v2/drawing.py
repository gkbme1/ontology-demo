"""画面图纸（P&ID 示意）：按本画面的设备组 / 设备和物理拓扑关系自动排布。

仓库里没有 P&ID 原图，这里生成示意图的结构数据，前端画成 SVG：
- 节点：本画面的设备组（内含本画面认领的成员）+ 未入组设备（汇总成一个框）；
- 连线：工业关系表中「物理拓扑关系」里两端都在本画面的连接；
- 进出物料：指向本画面设备组的物料流股 / 公用介质画在左侧，产出画在右侧；
- 布局：按连线做最长路径分层（左 → 右），环路忽略回边。
子流程写在图纸顶部（不单独成层）。有了真图纸后可换成图片 + 热区，接口结构不变。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.v2.context import AppContext

STREAM_TYPES = {"物料流股", "公用介质"}
DRAWING_DIR = Path(__file__).resolve().parents[2] / "data" / "drawings"


def image_path(op_id: str) -> Path | None:
    cfg = _image_config(op_id)
    return DRAWING_DIR / cfg["image"] if cfg else None


def _image_config(op_id: str) -> dict[str, Any] | None:
    f = DRAWING_DIR / f"{op_id}.json"
    if not f.exists():
        return None
    cfg = json.loads(f.read_text("utf-8"))
    return cfg if (DRAWING_DIR / cfg["image"]).exists() else None


def _resolve_name(ctx: AppContext, op_id: str, name: str) -> tuple[str | None, str]:
    """热区名称 → 本体对象：优先本画面、其次同单元、再全厂；先设备后设备组。"""
    h = ctx.hierarchy
    dcs = ctx.store.dcs
    seg_ops = set(h.segment_of_op(op_id)["opIds"])
    cands = [e for e in dcs.equipment.values() if e["name"] == name]
    for scope in ({op_id}, seg_ops, None):
        hit = [e for e in cands if scope is None or h.op_of_equipment.get(e["id"]) in scope]
        if hit:
            return hit[0]["id"], "equipment"
    g = next((g for g in dcs.equipment_groups.values() if g["name"] == name), None)
    return (g["id"], "group") if g else (None, "")


def image_view(ctx: AppContext, op_id: str) -> dict[str, Any] | None:
    """现场图纸（P&ID 截图）+ 热区。热区按名称落到本体对象，落不到的标出来。"""
    cfg = _image_config(op_id)
    if not cfg:
        return None
    dcs = ctx.store.dcs
    spots = []
    for hs in cfg.get("hotspots") or []:
        oid, kind = _resolve_name(ctx, op_id, hs["name"])
        group = (dcs.equipment.get(oid) or {}).get("equipmentGroupId") if kind == "equipment" else None
        own_op = ctx.hierarchy.op_of_equipment.get(oid) if kind == "equipment" else (
            (ctx.hierarchy.ops_of_group.get(oid) or [None])[0] if oid else None)
        spots.append({**hs, "objectId": oid, "kind": kind, "groupId": group, "opId": own_op,
                      "otherOp": bool(own_op and own_op != op_id)})
    return {"url": f"/api/v2/drawings/{op_id}/image", "width": cfg["width"], "height": cfg["height"],
            "source": cfg.get("source", ""), "note": cfg.get("note", ""), "hotspots": spots,
            "unresolved": [s["name"] for s in spots if not s["objectId"]]}
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

    # 既流入又产出的是本画面内部物料，不画在两侧
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
        "image": image_view(ctx, op_id),
    }
