"""REST API 路由定义（需求文档第二十一章）。

路由以框架无关的方式声明：每个条目是 (path, handler(store, query) -> dict)。
main.py 将其装配为 FastAPI 应用；export_static.py 用同一份定义导出静态快照，
保证在线服务与静态演示返回完全一致的数据契约。
"""
from __future__ import annotations

from typing import Any, Callable

from backend.services import graph_builder


def _int(q: dict, key: str, default: int | None = None) -> int | None:
    v = q.get(key)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(q: dict, key: str) -> float | None:
    v = q.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bool(q: dict, key: str) -> bool | None:
    v = q.get(key)
    if v in (None, ""):
        return None
    return str(v).lower() in ("1", "true", "yes", "y")


def _str(q: dict, key: str) -> str | None:
    v = q.get(key)
    return v or None


# --------------------------------------------------------------- handlers


def h_overview(store, q):
    return store.overview()


def h_categories(store, q):
    return store.categories()


def h_process_areas(store, q):
    return {"items": store.areas(), "total": len(store.areas())}


def h_process_area_detail(store, q, area_id: str):
    # area-S01 / S01 / 工段全名 三种写法都接受
    return store.area_detail(store.resolve_area_id(area_id) or area_id)


def h_equipment(store, q):
    return store.equipment(
        station=_str(q, "sn"),
        area_id=_str(q, "areaId"),
        area_name=_str(q, "processArea"),
        keyword=_str(q, "keyword"),
        group_id=_str(q, "groupId") or _str(q, "equipmentGroup"),
        limit=_int(q, "limit"),
        offset=_int(q, "offset", 0),
    )


def h_equipment_detail(store, q, equipment_id: str):
    return store.equipment_detail(equipment_id)


def h_parameters(store, q):
    return store.parameters(
        equipment_id=_str(q, "equipmentId"),
        area_id=_str(q, "areaId"),
        keyword=_str(q, "keyword"),
        category=_str(q, "category"),
        limit=_int(q, "limit"),
        offset=_int(q, "offset", 0),
    )


def h_parameter_detail(store, q, parameter_id: str):
    return store.parameter_detail(parameter_id)


def h_tags(store, q):
    return store.tags(
        equipment_id=_str(q, "equipmentId"),
        parameter_id=_str(q, "parameter"),
        area_id=_str(q, "areaId"),
        parameter_type=_str(q, "type"),
        block_type=_str(q, "blockType"),
        keyword=_str(q, "keyword"),
        variable_category=_str(q, "variableCategory"),
        confidence=_str(q, "confidence"),
        group_id=_str(q, "groupId") or _str(q, "equipmentGroup"),
        limit=_int(q, "limit"),
        offset=_int(q, "offset", 0),
    )


def h_equipment_groups(store, q):
    return store.equipment_groups(
        area_id=_str(q, "areaId"),
        equipment_type=_str(q, "equipmentType"),
        keyword=_str(q, "keyword"),
        limit=_int(q, "limit"),
        offset=_int(q, "offset", 0),
    )


def h_equipment_group_detail(store, q, group_id: str):
    return store.equipment_group_detail(group_id)


def h_area_flow(store, q):
    return store.area_flow(_str(q, "areaId"))


def h_process_area_flow(store, q, area_id: str):
    return store.area_flow(area_id)


def h_classes(store, q):
    items = store.classes()
    return {"items": items, "total": len(items)}


def h_properties(store, q):
    items = store.properties()
    return {"items": items, "total": len(items)}


_COMPACT_RELATION_FIELDS = (
    "id", "relationCode", "area", "areaCode", "category", "predicate",
    "subjectType", "subjectEntity", "objectType", "objectEntity",
    "domainDescription", "scenario", "weight", "confidence", "basis",
    "isCausal", "matchStatus", "tagCount",
)


def _compact_relation(rel: dict) -> dict:
    """精简视图：去掉 stableKey / URI / 来源 / 嵌套主客体这些追溯用字段，
    只留下"谁对谁、什么关系、什么机理、落在哪些位号"。
    v2 一条关系完整体约 1.8 KB，遍历因果链时很容易撑爆调用方的返回体预算。"""
    out = {k: rel.get(k) for k in _COMPACT_RELATION_FIELDS if k in rel}
    out["tags"] = [t.get("name") for t in (rel.get("tags") or [])]
    return out


def h_relations(store, q):
    result = store.relations_query(
        area=_str(q, "area"),
        category=_str(q, "category"),
        subject_type=_str(q, "subjectType"),
        object_type=_str(q, "objectType"),
        predicate=_str(q, "predicate"),
        scenario=_str(q, "scenario"),
        min_weight=_float(q, "minWeight"),
        max_weight=_float(q, "maxWeight"),
        matched=_bool(q, "matched"),
        entity_id=_str(q, "entityId"),
        keyword=_str(q, "keyword"),
        limit=_int(q, "limit"),
        offset=_int(q, "offset", 0),
    )
    if (_str(q, "view") or "").lower() == "compact":
        result = {**result, "items": [_compact_relation(r) for r in result["items"]], "view": "compact"}
    return result


def h_relation_detail(store, q, relation_id: str):
    return store.relation_detail(relation_id)


def h_relation_entities(store, q):
    items = [store.entity_brief(e) for e in store.relations.entities.values()]
    if _str(q, "type"):
        items = [e for e in items if e["type"] == q["type"]]
    if _str(q, "areaId"):
        resolved = store.resolve_area_id(q["areaId"]) or q["areaId"]
        items = [e for e in items if e.get("areaId") == resolved]
    if _str(q, "keyword"):
        kw = q["keyword"]
        items = [
            e for e in items
            if kw in (e["name"] or "") or kw in (e.get("belongsTo") or "") or kw in (e.get("uri") or "")
        ]
    matched = _bool(q, "matched")
    if matched is not None:
        want = "MATCHED" if matched else "UNMATCHED"
        items = [e for e in items if e["matchStatus"] == want]
    items.sort(key=lambda e: -e["relationCount"])
    total = len(items)
    # v2 起关系对象有 1174 个，不分页必然被裁剪
    limit = _int(q, "limit")
    offset = _int(q, "offset", 0) or 0
    window = items[offset : offset + limit] if limit else items[offset:]
    return {
        "items": window,
        "total": total,
        "offset": offset,
        "facets": {"type": sorted({e["type"] for e in items if e["type"]})},
    }


def h_relation_entity_detail(store, q, entity_id: str):
    return store.entity_detail(entity_id)


def h_graph(store, q):
    return graph_builder.build_graph(
        store,
        root_id=_str(q, "rootId"),
        root_type=_str(q, "rootType"),
        depth=_int(q, "depth", 1) or 1,
        area=_str(q, "area"),
        category=_str(q, "category"),
        predicate=_str(q, "predicate"),
        scenario=_str(q, "scenario"),
        subject_type=_str(q, "subjectType"),
        object_type=_str(q, "objectType"),
        min_weight=_float(q, "minWeight"),
        max_weight=_float(q, "maxWeight"),
        matched_only=_bool(q, "matched"),
        include_dcs=bool(_bool(q, "includeDcs")),
    )


def h_rules(store, q):
    return store.rules_query(
        area=_str(q, "area"),
        applies_to=_str(q, "appliesTo"),
        applies_to_type=_str(q, "appliesToType"),
        severity=_str(q, "severity"),
        keyword=_str(q, "keyword"),
    )


def h_capabilities(store, q):
    return store.capabilities()


def h_constraints(store, q):
    return store.constraints()


def h_model_registry(store, q):
    return store.model_registry()


def h_semantics(store, q):
    return store.semantics(limit=_int(q, "limit"), area_id=_str(q, "areaId"))


def h_measurement_anchors(store, q):
    anchors = store.measurement_anchors(area_id=_str(q, "areaId"), limit=_int(q, "limit"))
    return {
        "items": anchors,
        "total": len(anchors),
        "unanchoredEntities": store.unanchored_entities(),
    }


def h_causal_relations(store, q):
    return store.causal_relations()


def h_object_relations(store, q, object_id: str):
    """通用对象关系查询：支持 OWL Subject URI、设备 ID、参数 ID、关系对象 ID。"""
    from backend.ontology import identifiers as ids

    if object_id.startswith(":"):
        equip = store.dcs.equipment_by_owl(object_id)
        object_id = equip["id"] if equip else object_id
    if object_id.startswith("equip-"):
        detail = store.equipment_detail(object_id)
        if not detail:
            return None
        return {
            "objectId": object_id,
            "objectKind": "equipment",
            "objectName": detail["name"],
            "owlSubject": detail["owlSubject"],
            "area": detail["area"],
            "parameters": detail["parameters"],
            "tags": detail["tags"],
            "relationEntities": detail["relationEntities"],
            "relations": detail["relations"],
            "rules": detail["rules"],
            "causalRelations": [r for r in detail["relations"] if r["isCausal"]],
        }
    if object_id.startswith("param-"):
        detail = store.parameter_detail(object_id)
        if not detail:
            return None
        return {
            "objectId": object_id,
            "objectKind": "parameter",
            "objectName": detail["name"],
            "equipment": detail["equipment"],
            "tags": detail["tags"],
            "measurementAnchors": detail["measurementAnchors"],
            "relationEntities": detail["relationEntities"],
            "relations": detail["relations"],
            "rules": detail["rules"],
            "causalRelations": [r for r in detail["relations"] if r["isCausal"]],
        }
    if object_id.startswith("robj-"):
        detail = store.entity_detail(object_id)
        if not detail:
            return None
        return {
            "objectId": object_id,
            "objectKind": "relationEntity",
            "objectName": detail["name"],
            "matches": detail["matches"],
            "measurementAnchors": detail["measurementAnchors"],
            "relations": detail["outgoingRelations"] + detail["incomingRelations"],
            "causalRelations": [
                r for r in detail["outgoingRelations"] + detail["incomingRelations"] if r["isCausal"]
            ],
        }
    if object_id.startswith("egrp-"):
        return store.equipment_group_detail(object_id)
    resolved_area = store.resolve_area_id(object_id)
    if resolved_area:
        return store.area_detail(resolved_area)
    _ = ids
    return None


def h_data_sources(store, q):
    return store.data_sources()


def h_data_quality(store, q):
    return store.quality


def h_turtle(store, q):
    return store.turtle()


# --------------------------------------------------------------- 路由表

Route = dict[str, Any]

ROUTES: list[Route] = [
    {"path": "/api/ontology/overview", "handler": h_overview, "name": "本体概览", "snapshot": "overview"},
    {"path": "/api/ontology/categories", "handler": h_categories, "name": "本体分类（12 项）", "snapshot": "categories"},
    {"path": "/api/ontology/process-areas", "handler": h_process_areas, "name": "生产工段", "snapshot": "process-areas"},
    {
        "path": "/api/ontology/process-areas/{area_id}",
        "handler": h_process_area_detail,
        "name": "工段详情",
        "param": "area_id",
        "snapshot": "process-areas/{id}",
        "ids": lambda s: [a["id"] for a in s.areas()],
    },
    {"path": "/api/ontology/equipment", "handler": h_equipment, "name": "设备列表", "snapshot": "equipment"},
    {
        "path": "/api/ontology/equipment/{equipment_id}",
        "handler": h_equipment_detail,
        "name": "设备详情",
        "param": "equipment_id",
        "snapshot": "equipment/{id}",
        "ids": lambda s: list(s.dcs.equipment.keys()),
        "bulky": True,
    },
    {"path": "/api/ontology/parameters", "handler": h_parameters, "name": "参数语义", "snapshot": "parameters"},
    {
        "path": "/api/ontology/parameters/{parameter_id}",
        "handler": h_parameter_detail,
        "name": "参数详情",
        "param": "parameter_id",
        "snapshot": "parameters/{id}",
        "ids": lambda s: list(s.dcs.parameters.keys()),
        "bulky": True,
    },
    {"path": "/api/ontology/tags", "handler": h_tags, "name": "DCS 点", "snapshot": "tags"},
    {
        "path": "/api/ontology/equipment-groups",
        "handler": h_equipment_groups,
        "name": "标准设备组",
        "snapshot": "equipment-groups",
    },
    {
        "path": "/api/ontology/equipment-groups/{group_id}",
        "handler": h_equipment_group_detail,
        "name": "设备组详情",
        "param": "group_id",
        "snapshot": None,
    },
    {"path": "/api/ontology/area-flow", "handler": h_area_flow, "name": "全流程工段衔接", "snapshot": "area-flow"},
    {
        "path": "/api/ontology/process-areas/{area_id}/flow",
        "handler": h_process_area_flow,
        "name": "工段上下游",
        "param": "area_id",
        "snapshot": None,
    },
    {"path": "/api/ontology/classes", "handler": h_classes, "name": "类", "snapshot": "classes"},
    {"path": "/api/ontology/properties", "handler": h_properties, "name": "属性", "snapshot": "properties"},
    {"path": "/api/ontology/relations", "handler": h_relations, "name": "关系", "snapshot": "relations"},
    {
        "path": "/api/ontology/relations/{relation_id}",
        "handler": h_relation_detail,
        "name": "关系详情",
        "param": "relation_id",
        "snapshot": "relations/{id}",
        "ids": lambda s: [r["id"] for r in s.relations.relations],
    },
    {
        "path": "/api/ontology/relation-entities",
        "handler": h_relation_entities,
        "name": "关系对象",
        "snapshot": "relation-entities",
    },
    {
        "path": "/api/ontology/relation-entities/{entity_id}",
        "handler": h_relation_entity_detail,
        "name": "关系对象详情",
        "param": "entity_id",
        "snapshot": "relation-entities/{id}",
        "ids": lambda s: list(s.relations.entities.keys()),
    },
    {"path": "/api/ontology/graph", "handler": h_graph, "name": "关系图数据", "snapshot": "graph"},
    {"path": "/api/ontology/rules", "handler": h_rules, "name": "规则", "snapshot": "rules"},
    {"path": "/api/ontology/capabilities", "handler": h_capabilities, "name": "能力", "snapshot": "capabilities"},
    {"path": "/api/ontology/constraints", "handler": h_constraints, "name": "约束", "snapshot": "constraints"},
    {"path": "/api/ontology/model-registry", "handler": h_model_registry, "name": "模型注册", "snapshot": "model-registry"},
    {"path": "/api/ontology/semantics", "handler": h_semantics, "name": "语义", "snapshot": "semantics"},
    {
        "path": "/api/ontology/measurement-anchors",
        "handler": h_measurement_anchors,
        "name": "测量锚点",
        "snapshot": "measurement-anchors",
    },
    {
        "path": "/api/ontology/causal-relations",
        "handler": h_causal_relations,
        "name": "因果关系",
        "snapshot": "causal-relations",
    },
    {
        "path": "/api/ontology/{object_id}/relations",
        "handler": h_object_relations,
        "name": "对象关系查询",
        "param": "object_id",
        "snapshot": None,
    },
    {"path": "/api/ontology/data-sources", "handler": h_data_sources, "name": "数据源管理", "snapshot": "data-sources"},
    {"path": "/api/ontology/data-quality", "handler": h_data_quality, "name": "数据质量报告", "snapshot": "data-quality"},
    {"path": "/api/ontology/turtle", "handler": h_turtle, "name": "OWL Turtle 规范", "snapshot": "turtle"},
]


def route_index() -> list[dict[str, str]]:
    return [{"path": r["path"], "name": r["name"]} for r in ROUTES]


__all__ = ["ROUTES", "route_index", "Callable"]
