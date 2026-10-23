"""局部语义图构建（需求文档第十一、二十章）。

默认只展开当前对象的一跳关系，支持继续展开到二跳、三跳，
避免一次性展开全部关系导致图谱过于复杂。
"""
from __future__ import annotations

from typing import Any

from backend.ontology.models import EDGE_CATEGORY_STYLES, NODE_TYPE_STYLES

_NODE_STYLE = {s["type"]: s for s in NODE_TYPE_STYLES}
_EDGE_STYLE = {s["category"]: s for s in EDGE_CATEGORY_STYLES}
_DEFAULT_NODE = _NODE_STYLE["外部对象"]
_UNMATCHED_EDGE = _EDGE_STYLE["未匹配关系"]

MAX_DEPTH = 3
MAX_NODES = 220


def node_style(node_type: str | None, matched: bool = True) -> dict[str, Any]:
    style = _NODE_STYLE.get(node_type or "", _DEFAULT_NODE)
    return {
        "color": style["color"] if matched else _DEFAULT_NODE["color"],
        "shape": style["shape"],
    }


def edge_style(category: str | None, matched: bool, weight: float | None) -> dict[str, Any]:
    style = _EDGE_STYLE.get(category or "", _EDGE_STYLE["结构关系"])
    if not matched:
        style = _UNMATCHED_EDGE
    w = weight if weight is not None else 1.0
    return {
        "color": style["color"],
        "lineStyle": style["lineStyle"],
        # 权重越高，边越粗（需求 11.3）
        "width": round(style["width"] * (0.7 + 0.45 * w), 2),
        "opacity": round(min(1.0, 0.55 + 0.22 * w), 2),
    }


def build_graph(
    store,
    root_id: str | None = None,
    root_type: str | None = None,
    depth: int = 1,
    area: str | None = None,
    category: str | None = None,
    predicate: str | None = None,
    scenario: str | None = None,
    subject_type: str | None = None,
    object_type: str | None = None,
    min_weight: float | None = None,
    max_weight: float | None = None,
    matched_only: bool | None = None,
    include_dcs: bool = False,
) -> dict[str, Any]:
    depth = max(1, min(MAX_DEPTH, int(depth or 1)))

    edges_pool = store.relations_query(
        area=area,
        category=category,
        predicate=predicate,
        scenario=scenario,
        subject_type=subject_type,
        object_type=object_type,
        min_weight=min_weight,
        max_weight=max_weight,
    )["items"]

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    truncated = False

    if root_type in (None, "relationEntity") and root_id and root_id.startswith("robj-"):
        truncated = _expand_relation_entity(store, root_id, depth, edges_pool, nodes, edges)
        if include_dcs:
            _attach_anchor_nodes(store, root_id, nodes, edges)
    elif root_type == "equipment" or (root_id or "").startswith("equip-"):
        truncated = _expand_equipment(store, root_id, nodes, edges, edges_pool, depth)
    elif root_type == "parameter" or (root_id or "").startswith("param-"):
        truncated = _expand_parameter(store, root_id, nodes, edges, edges_pool)
    elif root_type == "area" or (root_id or "").startswith("area-"):
        truncated = _expand_area(store, root_id, nodes, edges, edges_pool)
    else:
        # 无根对象：返回全部关系边（受筛选条件约束）
        for rel in edges_pool:
            _add_relation(store, rel, nodes, edges)
            if len(nodes) > MAX_NODES:
                truncated = True
                break

    if matched_only is not None:
        keep = {n["id"] for n in nodes.values() if (n.get("matchStatus") == "MATCHED") == matched_only}
        edges = {
            k: e for k, e in edges.items() if e["source"] in keep and e["target"] in keep
        }
        used = {e["source"] for e in edges.values()} | {e["target"] for e in edges.values()}
        nodes = {k: n for k, n in nodes.items() if k in used or n.get("isRoot")}

    return {
        "rootId": root_id,
        "rootType": root_type,
        "depth": depth,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
        "truncated": truncated,
        "maxNodes": MAX_NODES,
        "nodeStyles": NODE_TYPE_STYLES,
        "edgeStyles": EDGE_CATEGORY_STYLES,
    }


# ------------------------------------------------------------------ 节点构造


def _entity_node(store, entity_id: str, is_root: bool = False) -> dict[str, Any] | None:
    entity = store.relations.entities.get(entity_id)
    if not entity:
        return None
    brief = store.entity_brief(entity)
    matched = brief["matchStatus"] == "MATCHED"
    return {
        "id": entity_id,
        "label": entity["name"],
        "type": entity["type"],
        "nodeKind": "relationEntity",
        "matchStatus": brief["matchStatus"],
        "matchStatusLabel": brief["matchStatusLabel"],
        "matchCount": brief["matchCount"],
        "tagCount": brief["tagCount"],
        "relationCount": brief["relationCount"],
        "areas": entity["areas"],
        "isRoot": is_root,
        "sourceType": "RELATION_EXCEL",
        "style": node_style(entity["type"], matched),
    }


def _equipment_node(store, equipment_id: str, is_root: bool = False) -> dict[str, Any] | None:
    equip = store.dcs.equipment.get(equipment_id)
    if not equip:
        return None
    return {
        "id": equipment_id,
        "label": equip["name"],
        "type": "生产设备",
        "nodeKind": "equipment",
        "owlSubject": equip["owlSubject"],
        "areaName": equip["areaName"],
        "station": equip["station"],
        "tagCount": equip["tagCount"],
        "matchStatus": "MATCHED",
        "isRoot": is_root,
        "sourceType": "DCS_EXCEL",
        "style": node_style("生产设备", True),
    }


def _parameter_node(store, parameter_id: str, is_root: bool = False) -> dict[str, Any] | None:
    param = store.dcs.parameters.get(parameter_id)
    if not param:
        return None
    return {
        "id": parameter_id,
        "label": param["name"],
        "type": "参数",
        "nodeKind": "parameter",
        "equipmentName": param["equipmentName"],
        "categories": param["categories"],
        "units": param["units"],
        "tagCount": param["tagCount"],
        "matchStatus": "MATCHED",
        "isRoot": is_root,
        "sourceType": "DCS_EXCEL",
        "style": node_style("参数", True),
    }


def _tag_node(store, tag_id: str) -> dict[str, Any] | None:
    tag = store.dcs.tags.get(tag_id)
    if not tag:
        return None
    return {
        "id": tag_id,
        "label": tag["name"],
        "type": "DCS点",
        "nodeKind": "tag",
        "rawDescription": tag["rawDescription"],
        "blockType": tag["blockType"],
        "unit": tag["unit"],
        "station": tag["station"],
        "matchStatus": "MATCHED",
        "sourceType": "DCS_EXCEL",
        "style": node_style("DCS点", True),
    }


def _area_node(store, area_id: str, is_root: bool = False) -> dict[str, Any] | None:
    area = store.dcs.areas.get(area_id)
    if not area:
        return None
    return {
        "id": area_id,
        "label": area["nameZh"],
        "type": "生产工段",
        "nodeKind": "area",
        "fullName": area["name"],
        "tagCount": area["tagCount"],
        "matchStatus": "MATCHED",
        "isRoot": is_root,
        "sourceType": "DCS_EXCEL",
        "style": node_style("生产工段", True),
    }


def _add_relation(store, rel: dict[str, Any], nodes: dict, edges: dict) -> None:
    sid = rel["subject"].get("id")
    oid = rel["object"].get("id")
    if not sid or not oid:
        return
    for nid in (sid, oid):
        if nid not in nodes:
            n = _entity_node(store, nid)
            if n:
                nodes[nid] = n
    matched = rel["matchStatus"] == "MATCHED"
    edges[rel["id"]] = {
        "id": rel["id"],
        "source": sid,
        "target": oid,
        "label": rel["predicate"],
        "category": rel["category"],
        "area": rel["area"],
        "scenario": rel["scenario"],
        "weight": rel["weight"],
        "domainDescription": rel["domainDescription"],
        "matchStatus": rel["matchStatus"],
        "edgeKind": "relation",
        "sourceType": rel["sourceType"],
        # 注意：source/target 已用于图的端点，来源信息放在 provenance 字段
        "provenance": rel["source"],
        "style": edge_style(rel["category"], matched, rel["weight"]),
    }


def _structural_edge(eid, source, target, label, kind, color) -> dict[str, Any]:
    return {
        "id": eid,
        "source": source,
        "target": target,
        "label": label,
        "category": "本体结构",
        "edgeKind": kind,
        "weight": 1,
        "matchStatus": "MATCHED",
        "sourceType": "DCS_EXCEL",
        "style": {"color": color, "lineStyle": "solid", "width": 1.4, "opacity": 0.75},
    }


# ------------------------------------------------------------------ 展开策略


def _expand_relation_entity(store, root_id, depth, pool, nodes, edges) -> bool:
    root = _entity_node(store, root_id, is_root=True)
    if not root:
        return False
    nodes[root_id] = root
    frontier = {root_id}
    by_entity: dict[str, list[dict]] = {}
    for rel in pool:
        for side in ("subject", "object"):
            eid = rel[side].get("id")
            if eid:
                by_entity.setdefault(eid, []).append(rel)
    for _ in range(depth):
        nxt: set[str] = set()
        for eid in frontier:
            for rel in by_entity.get(eid, []):
                if rel["id"] in edges:
                    continue
                _add_relation(store, rel, nodes, edges)
                for side in ("subject", "object"):
                    other = rel[side].get("id")
                    if other and other != eid:
                        nxt.add(other)
                if len(nodes) > MAX_NODES:
                    return True
        frontier = nxt - set()
    return False


def _attach_anchor_nodes(store, entity_id, nodes, edges) -> None:
    """把关系对象匹配到的 DCS 实例与测量锚点挂到图上。"""
    entity = store.relations.entities.get(entity_id)
    if not entity:
        return
    for match in entity["match"]["matches"][:8]:
        if match["objectType"] == "equipment":
            n = _equipment_node(store, match["id"])
            if n:
                n["id"] = "dcs::" + n["id"]
                nodes[n["id"]] = n
                edges[f"map::{entity_id}::{n['id']}"] = _structural_edge(
                    f"map::{entity_id}::{n['id']}", entity_id, n["id"], "匹配本体实例", "mapping", "#6B7A90"
                )
        elif match["objectType"] == "parameter":
            n = _parameter_node(store, match["id"])
            if not n:
                continue
            n["id"] = "dcs::" + n["id"]
            nodes[n["id"]] = n
            edges[f"map::{entity_id}::{n['id']}"] = _structural_edge(
                f"map::{entity_id}::{n['id']}", entity_id, n["id"], "测量锚点", "anchor", "#F2C744"
            )
            for tid in match.get("tagIds", [])[:3]:
                t = _tag_node(store, tid)
                if t:
                    t["id"] = "dcs::" + t["id"]
                    nodes[t["id"]] = t
                    edges[f"tag::{n['id']}::{t['id']}"] = _structural_edge(
                        f"tag::{n['id']}::{t['id']}", n["id"], t["id"], "boundToTag", "tag", "#F2C744"
                    )


def _expand_equipment(store, equipment_id, nodes, edges, pool, depth) -> bool:
    equip = store.dcs.equipment.get(equipment_id)
    if not equip:
        return False
    nodes[equipment_id] = _equipment_node(store, equipment_id, is_root=True)
    if equip["areaId"]:
        a = _area_node(store, equip["areaId"])
        if a:
            nodes[a["id"]] = a
            edges[f"has::{a['id']}::{equipment_id}"] = _structural_edge(
                f"has::{a['id']}::{equipment_id}", a["id"], equipment_id, "hasEquipment", "structure", "#4C8DFF"
            )
    truncated = False
    for pid in equip["parameterIds"]:
        if len(nodes) > MAX_NODES:
            truncated = True
            break
        n = _parameter_node(store, pid)
        if not n:
            continue
        nodes[pid] = n
        edges[f"has::{equipment_id}::{pid}"] = _structural_edge(
            f"has::{equipment_id}::{pid}", equipment_id, pid, "hasParameter", "structure", "#35C4D7"
        )
        if depth >= 2:
            for tid in store.dcs.parameters[pid]["tagIds"]:
                if len(nodes) > MAX_NODES:
                    truncated = True
                    break
                t = _tag_node(store, tid)
                if t:
                    nodes[tid] = t
                    edges[f"tag::{pid}::{tid}"] = _structural_edge(
                        f"tag::{pid}::{tid}", pid, tid, "boundToTag", "tag", "#F2C744"
                    )
    linked = store.relations_for_ontology_object("equipment", equipment_id)
    for e in linked["entities"]:
        n = _entity_node(store, e["id"])
        if n:
            nodes[n["id"]] = n
            edges[f"map::{n['id']}::{equipment_id}"] = _structural_edge(
                f"map::{n['id']}::{equipment_id}", n["id"], equipment_id, "匹配本体实例", "mapping", "#6B7A90"
            )
    for rel in linked["relations"]:
        if any(rel["id"] == r["id"] for r in pool):
            _add_relation(store, rel, nodes, edges)
    return truncated


def _expand_parameter(store, parameter_id, nodes, edges, pool) -> bool:
    param = store.dcs.parameters.get(parameter_id)
    if not param:
        return False
    nodes[parameter_id] = _parameter_node(store, parameter_id, is_root=True)
    if param["equipmentId"]:
        e = _equipment_node(store, param["equipmentId"])
        if e:
            nodes[e["id"]] = e
            edges[f"has::{e['id']}::{parameter_id}"] = _structural_edge(
                f"has::{e['id']}::{parameter_id}", e["id"], parameter_id, "hasParameter", "structure", "#35C4D7"
            )
    for tid in param["tagIds"]:
        t = _tag_node(store, tid)
        if t:
            nodes[tid] = t
            edges[f"tag::{parameter_id}::{tid}"] = _structural_edge(
                f"tag::{parameter_id}::{tid}", parameter_id, tid, "boundToTag", "tag", "#F2C744"
            )
    linked = store.relations_for_ontology_object("parameter", parameter_id)
    for e in linked["entities"]:
        n = _entity_node(store, e["id"])
        if n:
            nodes[n["id"]] = n
            edges[f"map::{n['id']}::{parameter_id}"] = _structural_edge(
                f"map::{n['id']}::{parameter_id}", n["id"], parameter_id, "测量锚点", "anchor", "#F2C744"
            )
    for rel in linked["relations"]:
        if any(rel["id"] == r["id"] for r in pool):
            _add_relation(store, rel, nodes, edges)
    return False


def _expand_area(store, area_id, nodes, edges, pool) -> bool:
    area = store.dcs.areas.get(area_id)
    if not area:
        return False
    nodes[area_id] = _area_node(store, area_id, is_root=True)
    ranked = sorted(
        (store.dcs.equipment[e] for e in area["equipmentIds"]),
        key=lambda e: -e["tagCount"],
    )[:24]
    for equip in ranked:
        n = _equipment_node(store, equip["id"])
        if n:
            nodes[n["id"]] = n
            edges[f"has::{area_id}::{n['id']}"] = _structural_edge(
                f"has::{area_id}::{n['id']}", area_id, n["id"], "hasEquipment", "structure", "#4C8DFF"
            )
    for rel in pool:
        if rel.get("dcsAreaId") == area_id:
            _add_relation(store, rel, nodes, edges)
    return len(area["equipmentIds"]) > len(ranked)
