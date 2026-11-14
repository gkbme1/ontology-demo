"""关系对象与 DCS 本体实例的匹配（需求文档 9.3）。

匹配优先级：
    0. 关系表自带位号   v2 的关系明细带「关联DCS位号」与 622 条「绑定测点」关系，
                        这是数据源里写死的显式声明，优先级最高，不需要任何猜测
    1. 精确匹配   关系对象名称 == DCS 设备名称 / DCS 参数语义名称
    2. 语义类型匹配 在精确同名的候选中按对象类型收敛
    3. 人工映射表 6APA_对象映射.xlsx

禁止仅根据模糊名称自动建立高置信度关系。无法匹配的对象保留为
“外部关系对象”，标记为“未匹配DCS实例”，不得丢弃。
"""
from __future__ import annotations

from typing import Any

from backend.ontology import identifiers as ids
from backend.ontology.models import (
    MATCH_STATUS_MATCHED,
    MATCH_STATUS_UNMATCHED,
    SOURCE_MAPPING,
)
from backend.services.dcs_loader import DcsDataset
from backend.services.mapping_loader import MappingDataset
from backend.services.relation_excel_loader import RelationDataset

STRATEGY_RELATION_TAG = "RELATION_TAG_BINDING"
STRATEGY_EXACT_EQUIPMENT = "EXACT_EQUIPMENT"
STRATEGY_EXACT_PARAMETER = "EXACT_PARAMETER"
STRATEGY_SEMANTIC_TYPE = "SEMANTIC_TYPE"
STRATEGY_MANUAL_MAPPING = "MANUAL_MAPPING"
STRATEGY_NONE = "NONE"

STRATEGY_LABELS = {
    STRATEGY_RELATION_TAG: "关系表位号绑定",
    STRATEGY_EXACT_EQUIPMENT: "精确匹配 · DCS 设备名称",
    STRATEGY_EXACT_PARAMETER: "精确匹配 · DCS 参数语义名称",
    STRATEGY_SEMANTIC_TYPE: "语义类型匹配",
    STRATEGY_MANUAL_MAPPING: "人工映射表",
    STRATEGY_NONE: "未匹配 DCS 实例",
}

# 关系对象类型 → 可接受的 DCS 本体对象类型（第二优先级：语义类型匹配）
TYPE_AFFINITY = {
    "生产设备": {"equipment"},
    "设备部件": {"equipment", "parameter"},
    "执行机构": {"equipment", "parameter"},
    "控制仪表": {"equipment", "parameter"},
    "控制系统": {"equipment"},
    "工艺属性": {"parameter"},
    "质量指标": {"parameter"},
    "业务指标": set(),
    "物料流股": set(),
    "工段": {"area"},
}


def collect_relation_tag_bindings(relations: RelationDataset) -> dict[str, list[str]]:
    """关系对象 → 关系表里声明的位号名。

    只认关系**主体**侧：`釜内反应温度 --绑定测点--> TI_1301A` 说的是主体由该位号测量。
    客体侧位号已并入 relation["tagNames"]，不会重复计入其它对象。
    """
    bindings: dict[str, list[str]] = {}
    for rel in relations.relations:
        names = rel.get("tagNames") or []
        if not names:
            continue
        sid = rel["subject"].get("id")
        if not sid:
            continue
        bucket = bindings.setdefault(sid, [])
        for name in names:
            if name not in bucket:
                bucket.append(name)
    return bindings


def match_entities(
    relations: RelationDataset, dcs: DcsDataset, mapping: MappingDataset
) -> dict[str, dict[str, Any]]:
    """为每个关系对象计算匹配结果，返回 entityId -> 匹配信息。"""
    bindings = collect_relation_tag_bindings(relations)
    results: dict[str, dict[str, Any]] = {}
    for entity in relations.entities.values():
        results[entity["id"]] = _match_one(entity, dcs, mapping, bindings.get(entity["id"], []))
    return results


def _match_one(
    entity: dict[str, Any],
    dcs: DcsDataset,
    mapping: MappingDataset,
    bound_tag_names: list[str] | None = None,
) -> dict[str, Any]:
    name = entity["name"]
    etype = entity["type"]
    matches: list[dict[str, Any]] = []
    strategies: list[str] = []

    # ---- 第零优先级：关系表自带位号 -------------------------------------
    bound_tags = [dcs.tag_by_name(t) for t in (bound_tag_names or [])]
    bound_tags = [t for t in bound_tags if t is not None]
    for tag in bound_tags:
        matches.append(_tag_match(tag))
    if bound_tags:
        strategies.append(STRATEGY_RELATION_TAG)

    # ---- 第一 / 第二优先级：精确匹配 + 语义类型收敛 -----------------------
    affinity = TYPE_AFFINITY.get(etype or "", {"equipment", "parameter"})

    equip_hits = dcs.equipment_by_name(name) if "equipment" in affinity else []
    param_hits = dcs.parameters_by_name(name) if "parameter" in affinity else []

    for equip in equip_hits:
        matches.append(_equipment_match(equip, STRATEGY_EXACT_EQUIPMENT))
    if equip_hits:
        strategies.append(STRATEGY_EXACT_EQUIPMENT)

    for param in param_hits:
        matches.append(_parameter_match(param, dcs, STRATEGY_EXACT_PARAMETER))
    if param_hits:
        strategies.append(STRATEGY_EXACT_PARAMETER)

    if matches and etype and TYPE_AFFINITY.get(etype) is not None:
        strategies.append(STRATEGY_SEMANTIC_TYPE)

    # ---- 第三优先级：人工映射表 -----------------------------------------
    for entry in mapping.for_entity(etype, name):
        resolved = _resolve_mapping(entry, dcs)
        if resolved is not None:
            matches.append(resolved)
    if any(m["strategy"] == STRATEGY_MANUAL_MAPPING for m in matches):
        strategies.append(STRATEGY_MANUAL_MAPPING)

    # 去重
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for m in matches:
        key = f"{m['objectType']}::{m['id']}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)

    anchors = [m for m in unique if m["objectType"] in ("parameter", "tag")]
    status = MATCH_STATUS_MATCHED if unique else MATCH_STATUS_UNMATCHED
    primary = strategies[0] if strategies else STRATEGY_NONE

    return {
        "entityId": entity["id"],
        "entityName": name,
        "entityType": etype,
        "matchStatus": status,
        "matchStatusLabel": "已匹配本体实例" if unique else "未匹配DCS实例",
        "matchStrategy": primary,
        "matchStrategyLabel": STRATEGY_LABELS[primary],
        "matchStrategies": sorted(set(strategies)),
        "matchCount": len(unique),
        "matches": unique,
        "anchorParameterIds": [m["id"] for m in anchors if m["objectType"] == "parameter"],
        "anchorTagIds": sorted({t for m in anchors for t in m.get("tagIds", [])}),
        "tagCount": len({t for m in anchors for t in m.get("tagIds", [])}),
        "pendingConfirmation": any(
            m["strategy"] == STRATEGY_MANUAL_MAPPING and m.get("status") != "已确认" for m in unique
        ),
    }


def _tag_match(tag: dict[str, Any]) -> dict[str, Any]:
    """位号级匹配项。objectType 用 "parameter" 之外的 "tag"，避免和参数语义混淆；
    但它同样算测量锚点，所以 anchors 的判定把它一起算进去。"""
    return {
        "objectType": "tag",
        "id": tag["id"],
        "name": tag["name"],
        "rawDescription": tag.get("rawDescription"),
        "equipmentId": tag.get("equipmentId"),
        "equipmentName": tag.get("equipmentName"),
        "parameterId": tag.get("parameterId"),
        "parameterName": tag.get("parameterName"),
        "areaId": tag.get("areaId"),
        "areaName": tag.get("areaName"),
        "areaCode": tag.get("areaCode"),
        "station": tag.get("station"),
        "blockType": tag.get("blockType"),
        "unit": tag.get("unit"),
        "parameterType": tag.get("parameterType"),
        "tagIds": [tag["id"]],
        "strategy": STRATEGY_RELATION_TAG,
        "strategyLabel": STRATEGY_LABELS[STRATEGY_RELATION_TAG],
        "sourceType": tag["sourceType"],
        "source": tag["source"],
    }


def _equipment_match(equip: dict[str, Any], strategy: str, entry: dict | None = None) -> dict[str, Any]:
    out = {
        "objectType": "equipment",
        "id": equip["id"],
        "name": equip["name"],
        "owlSubject": equip["owlSubject"],
        "areaId": equip["areaId"],
        "areaName": equip["areaName"],
        "station": equip["station"],
        "tagCount": equip["tagCount"],
        "parameterCount": equip["parameterCount"],
        "strategy": strategy,
        "strategyLabel": STRATEGY_LABELS[strategy],
        "sourceType": equip["sourceType"],
        "source": equip["source"],
    }
    if entry:
        out.update(_mapping_meta(entry))
    return out


def _parameter_match(
    param: dict[str, Any], dcs: DcsDataset, strategy: str, entry: dict | None = None
) -> dict[str, Any]:
    tags = [dcs.tags[t] for t in param["tagIds"] if t in dcs.tags]
    out = {
        "objectType": "parameter",
        "id": param["id"],
        "name": param["name"],
        "equipmentId": param["equipmentId"],
        "equipmentName": param["equipmentName"],
        "owlSubject": param["owlSubject"],
        "areaId": param["areaId"],
        "areaName": param["areaName"],
        "categories": param["categories"],
        "units": param["units"],
        "blockTypes": param["blockTypes"],
        "tagIds": param["tagIds"],
        "tags": [
            {
                "id": t["id"],
                "name": t["name"],
                "rawDescription": t["rawDescription"],
                "blockType": t["blockType"],
                "unit": t["unit"],
                "station": t["station"],
                "parameterType": t["parameterType"],
            }
            for t in tags
        ],
        "strategy": strategy,
        "strategyLabel": STRATEGY_LABELS[strategy],
        "sourceType": param["sourceType"],
        "source": param["source"],
    }
    if entry:
        out.update(_mapping_meta(entry))
    return out


def _area_match(area: dict[str, Any], entry: dict) -> dict[str, Any]:
    out = {
        "objectType": "area",
        "id": area["id"],
        "name": area["name"],
        "nameZh": area["nameZh"],
        "stations": area["stations"],
        "equipmentCount": area["equipmentCount"],
        "tagCount": area["tagCount"],
        "strategy": STRATEGY_MANUAL_MAPPING,
        "strategyLabel": STRATEGY_LABELS[STRATEGY_MANUAL_MAPPING],
        "sourceType": area["sourceType"],
        "source": area["source"],
    }
    out.update(_mapping_meta(entry))
    return out


def _mapping_meta(entry: dict) -> dict[str, Any]:
    return {
        "confidence": entry.get("confidence"),
        "status": entry.get("status"),
        "note": entry.get("note"),
        "mappingSourceType": SOURCE_MAPPING,
        "mappingSource": entry.get("source"),
    }


def _resolve_mapping(entry: dict, dcs: DcsDataset) -> dict[str, Any] | None:
    otype = entry.get("ontologyObjectType")
    uri = entry.get("ontologyObjectUri")
    pname = entry.get("parameterName")
    if not uri:
        return None
    if otype == "设备":
        equip = dcs.equipment_by_owl(uri)
        return _equipment_match(equip, STRATEGY_MANUAL_MAPPING, entry) if equip else None
    if otype == "参数" and pname:
        param = dcs.parameters.get(ids.parameter_id(uri, pname))
        return _parameter_match(param, dcs, STRATEGY_MANUAL_MAPPING, entry) if param else None
    if otype == "工段":
        # v2 的映射表里这一列写的是工段名称；旧版写的是控制站工段名。
        # 统一走 resolve_area（同时认 area-S01 / S01 / 工段全名）。
        aid = dcs.resolve_area(uri) or dcs.resolve_area(entry.get("ontologyObjectName"))
        area = dcs.areas.get(aid) if aid else None
        return _area_match(area, entry) if area else None
    return None
