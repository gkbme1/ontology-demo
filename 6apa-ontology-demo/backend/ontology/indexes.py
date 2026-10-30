"""本体服务的内存索引层。

数据访问全部经过本层，API 不直接触碰 Excel。
后续替换为 PostgreSQL / Neo4j / GraphDB / Jena 时只需替换本层实现，
前端 API 契约保持不变（需求文档第二十七章）。
"""
from __future__ import annotations

import datetime as _dt
import re as _re
from pathlib import Path
from typing import Any

from backend.ontology import identifiers as ids
from backend.ontology.models import (
    CAUSAL_CATEGORIES,
    CORE_CONTENTS,
    EDGE_CATEGORY_STYLES,
    NODE_TYPE_STYLES,
    ONTOLOGY_CATEGORIES,
    SOURCE_DCS,
    SOURCE_MAPPING,
    SOURCE_RELATION,
    SOURCE_RULE,
    SOURCE_TYPE_LABELS,
)
from backend.services import object_matcher
from backend.services.data_quality import build_quality_report
from backend.services.dcs_loader import load_dcs
from backend.services.mapping_loader import load_mapping
from backend.services.relation_excel_loader import load_relations
from backend.services.rule_loader import load_rules

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "data" / "source"

DCS_FILE = SOURCE_DIR / "6APA_DCS.xlsx"
RELATION_FILE = SOURCE_DIR / "6APA_工业关系.xlsx"
MAPPING_FILE = SOURCE_DIR / "6APA_对象映射.xlsx"
RULE_FILE = SOURCE_DIR / "6APA_规则.xlsx"
MERGE_FILE = SOURCE_DIR / "6APA_设备归并.xlsx"


class OntologyStore:
    def __init__(self, source_dir: Path | None = None) -> None:
        base = Path(source_dir) if source_dir else SOURCE_DIR
        self.loaded_at = _dt.datetime.now().isoformat(timespec="seconds")
        self.dcs = load_dcs(base / DCS_FILE.name, base / MERGE_FILE.name)
        self.relations = load_relations(base / RELATION_FILE.name)
        self.mapping = load_mapping(base / MAPPING_FILE.name)
        self.rules = load_rules(base / RULE_FILE.name)
        self.matches = object_matcher.match_entities(self.relations, self.dcs, self.mapping)
        self._attach_matches()
        self._attach_area_relation_counts()
        self.quality = build_quality_report(self.dcs, self.relations, self.mapping, self.rules, self.matches)

    # ------------------------------------------------------------ 组装

    def _attach_matches(self) -> None:
        for entity in self.relations.entities.values():
            entity["match"] = self.matches[entity["id"]]
        for rel in self.relations.relations:
            for side in ("subject", "object"):
                eid = rel[side].get("id")
                if eid and eid in self.matches:
                    m = self.matches[eid]
                    rel[side]["matchStatus"] = m["matchStatus"]
                    rel[side]["matchStatusLabel"] = m["matchStatusLabel"]
                    rel[side]["matchCount"] = m["matchCount"]
            rel["matchStatus"] = (
                "MATCHED"
                if rel["subject"].get("matchStatus") == "MATCHED"
                and rel["object"].get("matchStatus") == "MATCHED"
                else "PARTIAL"
                if "MATCHED" in (rel["subject"].get("matchStatus"), rel["object"].get("matchStatus"))
                else "UNMATCHED"
            )
            rel["isCausal"] = rel["category"] in CAUSAL_CATEGORIES

    def _attach_area_relation_counts(self) -> None:
        """关系 Excel 的工段名与 DCS 工段名不同，通过映射表对齐后回填计数。"""
        # v2 起关系表自带「工段编号」，与点表同口径，直接对齐即可；
        # 编号缺失时再退回按工段名称匹配，最后才查人工映射表（兼容旧口径文件）。
        self.relation_area_to_dcs: dict[str, str | None] = {}
        for entry in self.mapping.entries:
            if entry.get("ontologyObjectType") == "工段":
                aid = self.dcs.resolve_area(entry.get("ontologyObjectUri")) or self.dcs.resolve_area(
                    entry.get("ontologyObjectName")
                )
                if aid:
                    self.relation_area_to_dcs.setdefault(entry["relationEntity"], aid)
        for area in self.dcs.areas.values():
            area["relationCount"] = 0
            area["relationAreaNames"] = []
        for rel in self.relations.relations:
            aid = (
                self.dcs.resolve_area(rel.get("areaCode"))
                or self.dcs.resolve_area(rel.get("area"))
                or self.relation_area_to_dcs.get(rel.get("area") or "")
            )
            rel["dcsAreaId"] = aid
            rel["areaId"] = aid
            if aid and aid in self.dcs.areas:
                area = self.dcs.areas[aid]
                area["relationCount"] += 1
                if rel["area"] not in area["relationAreaNames"]:
                    area["relationAreaNames"].append(rel["area"])
            # 关系自带位号 → 解析成真实 tag- 对象
            resolved = []
            for name in rel.get("tagNames") or []:
                tag = self.dcs.tag_by_name(name)
                if tag:
                    resolved.append({"id": tag["id"], "name": tag["name"],
                                     "rawDescription": tag.get("rawDescription"),
                                     "unit": tag.get("unit"), "blockType": tag.get("blockType")})
            rel["tags"] = resolved
            rel["tagCount"] = len(resolved)
            rel["unresolvedTagNames"] = [
                n for n in (rel.get("tagNames") or []) if not self.dcs.tag_by_name(n)
            ]

    # ------------------------------------------------------------ 概览

    def overview(self) -> dict[str, Any]:
        stats = {"pv": 0, "op": 0, "mot": 0, "val": 0, "dido": 0}
        for tag in self.dcs.tags.values():
            key = {
                "过程测量(PV)": "pv",
                "控制输出(OP)": "op",
                "电机控制(MOT)": "mot",
                "阀门控制(VAL)": "val",
                "状态反馈(DI)": "dido",
                "开关控制(DO)": "dido",
            }.get(tag["parameterType"] or "")
            if key:
                stats[key] += 1
        matched = len([m for m in self.matches.values() if m["matchStatus"] == "MATCHED"])
        return {
            "productionLine": "6-APA 生产线",
            "processAreaCount": len(self.dcs.areas),
            "controlStationCount": len(self.dcs.stations),
            "equipmentCount": len(self.dcs.equipment),
            "parameterCount": len(self.dcs.parameters),
            "tagCount": len(self.dcs.tags),
            "relationCount": len(self.relations.relations),
            "relationObjectCount": len(self.relations.entities),
            "relationObjectMatchedCount": matched,
            "relationObjectUnmatchedCount": len(self.relations.entities) - matched,
            "measurementAnchorCount": len(self.measurement_anchors()),
            "equipmentGroupCount": len(self.dcs.equipment_groups),
            "areaFlowCount": len(self.relations.area_flow),
            "multiAreaEquipmentCount": self.dcs.load_stats.get("multiAreaEquipmentCount", 0),
            "relationTagBindingCount": self.relations.load_stats.get("tagBindingCount", 0),
            "classCount": len(self.classes()),
            "categoryCount": len(ONTOLOGY_CATEGORIES),
            "coreContentCount": len(CORE_CONTENTS),
            "ruleCount": len(self.rules.rules),
            "constraintCount": 0,
            "capabilityCount": 0,
            "causalRelationCount": len([r for r in self.relations.relations if r["isCausal"]]),
            "mappingCount": len(self.mapping.entries),
            "tagStats": stats,
            "qualityIssueCount": len(self.quality["issues"]),
            "loadedAt": self.loaded_at,
        }

    # ------------------------------------------------------------ 工段 / 设备

    def areas(self) -> list[dict[str, Any]]:
        out = []
        for area in self.dcs.areas.values():
            out.append(
                {
                    "id": area["id"],
                    "code": area["code"],
                    "name": area["name"],
                    "nameZh": area["nameZh"],
                    "nameEn": area["nameEn"],
                    "uri": area.get("uri"),
                    "stations": area["stations"],
                    "processScreens": area.get("processScreens", []),
                    "positioning": area.get("positioning"),
                    "upstream": area.get("upstream", []),
                    "downstream": area.get("downstream", []),
                    "equipmentCount": area["equipmentCount"],
                    "parameterCount": area["parameterCount"],
                    "tagCount": area["tagCount"],
                    "equipmentGroupCount": area.get("equipmentGroupCount", 0),
                    "confidenceCounts": area.get("confidenceCounts", {}),
                    "declared": area.get("declared", {}),
                    "relationCount": area.get("relationCount", 0),
                    "relationAreaNames": area.get("relationAreaNames", []),
                    "sourceType": area["sourceType"],
                    "source": area["source"],
                }
            )
        out.sort(key=lambda a: a["code"])
        return out

    def area_detail(self, area_id: str) -> dict[str, Any] | None:
        area = self.dcs.areas.get(area_id)
        if not area:
            return None
        equipment = [self._equipment_brief(self.dcs.equipment[e]) for e in area["equipmentIds"]]
        equipment.sort(key=lambda e: -e["tagCount"])
        rels = [r for r in self.relations.relations if r.get("dcsAreaId") == area_id]
        by_category: dict[str, int] = {}
        for r in rels:
            by_category[r["category"] or "未标注"] = by_category.get(r["category"] or "未标注", 0) + 1
        return {
            **self.areas_by_id(area_id),
            "equipment": equipment,
            "equipmentGroups": [
                self._group_brief(self.dcs.equipment_groups[g]) for g in area["equipmentGroupIds"]
            ],
            "flow": self.area_flow(area_id),
            "relationCategoryCounts": by_category,
            "relations": rels,
        }

    def areas_by_id(self, area_id: str) -> dict[str, Any]:
        resolved = self.dcs.resolve_area(area_id) or area_id
        for a in self.areas():
            if a["id"] == resolved:
                return a
        return {}

    def resolve_area_id(self, value: Any) -> str | None:
        """area-S01 / S01 / 工段全名 → areaId。取不到返回 None。"""
        return self.dcs.resolve_area(value)

    def _equipment_brief(self, equip: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": equip["id"],
            "owlSubject": equip["owlSubject"],
            "name": equip["name"],
            "areaId": equip["areaId"],
            "areaName": equip["areaName"],
            "areaCode": equip.get("areaCode"),
            "areaIds": equip.get("areaIds", []),
            "areaCodes": equip.get("areaCodes", []),
            "areaNames": equip.get("areaNames", []),
            "areaSpan": equip.get("areaSpan", 1),
            "equipmentGroup": equip.get("equipmentGroup"),
            "equipmentGroupId": equip.get("equipmentGroupId"),
            "confidence": equip.get("confidence"),
            "station": equip["station"],
            "tagCount": equip["tagCount"],
            "parameterCount": equip["parameterCount"],
            "stats": equip["stats"],
            "statsFromSheet1": equip["statsFromSheet1"],
            "overview": equip["overview"],
            "sourceType": equip["sourceType"],
        }

    def equipment(
        self,
        station: str | None = None,
        area_id: str | None = None,
        area_name: str | None = None,
        keyword: str | None = None,
        group_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        items = list(self.dcs.equipment.values())
        if station:
            items = [e for e in items if e["station"] == str(station)]
        if area_id:
            # v2 起一台设备的点位可能落在多个工段，按任一命中过滤才符合直觉
            resolved = self.dcs.resolve_area(area_id) or area_id
            items = [e for e in items if resolved in (e.get("areaIds") or [e["areaId"]])]
        if area_name:
            items = [
                e for e in items
                if (e["areaName"] or "").find(area_name) >= 0
                or any(area_name in n for n in e.get("areaNames", []))
            ]
        if group_id:
            resolved_group = self.resolve_group_id(group_id)
            items = [e for e in items if e.get("equipmentGroupId") == resolved_group]
        if keyword:
            items = [e for e in items if keyword in (e["name"] or "") or keyword in (e["owlSubject"] or "")]
        items.sort(key=lambda e: -e["tagCount"])
        total = len(items)
        window = items[offset : offset + limit] if limit else items[offset:]
        return {"items": [self._equipment_brief(e) for e in window], "total": total, "offset": offset}

    def equipment_detail(self, equipment_id: str) -> dict[str, Any] | None:
        equip = self.dcs.equipment.get(equipment_id)
        if not equip:
            return None
        params = [self._parameter_brief(self.dcs.parameters[p]) for p in equip["parameterIds"]]
        rels = self.relations_for_ontology_object("equipment", equipment_id)
        return {
            **self._equipment_brief(equip),
            "area": self.areas_by_id(equip["areaId"]) if equip["areaId"] else None,
            "areas": [self.areas_by_id(a) for a in equip.get("areaIds", []) if a],
            "equipmentGroupDetail": (
                self._group_brief(self.dcs.equipment_groups[equip["equipmentGroupId"]])
                if equip.get("equipmentGroupId") in self.dcs.equipment_groups else None
            ),
            "parameters": params,
            "tags": [self.dcs.tags[t] for t in equip["tagIds"] if t in self.dcs.tags],
            "relations": rels["relations"],
            "relationEntities": rels["entities"],
            "rules": self.rules_for_object(equip["name"], equip.get("areaId")),
            "source": equip["source"],
            "statsSource": equip.get("statsSource"),
        }

    def _parameter_brief(self, param: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": param["id"],
            "name": param["name"],
            "equipmentId": param["equipmentId"],
            "equipmentName": param["equipmentName"],
            "owlSubject": param["owlSubject"],
            "areaId": param["areaId"],
            "areaName": param["areaName"],
            "areaCode": param.get("areaCode"),
            "station": param["station"],
            "categories": param["categories"],
            "units": param["units"],
            "blockTypes": param["blockTypes"],
            "tagCount": param["tagCount"],
            "tagIds": param["tagIds"],
            "sourceType": param["sourceType"],
        }

    def parameters(
        self,
        equipment_id: str | None = None,
        area_id: str | None = None,
        keyword: str | None = None,
        category: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        items = list(self.dcs.parameters.values())
        if equipment_id:
            items = [p for p in items if p["equipmentId"] == equipment_id]
        if area_id:
            items = [p for p in items if p["areaId"] == (self.dcs.resolve_area(area_id) or area_id)]
        if category:
            items = [p for p in items if category in p["categories"]]
        if keyword:
            items = [p for p in items if keyword in (p["name"] or "")]
        total = len(items)
        window = items[offset : offset + limit] if limit else items[offset:]
        return {"items": [self._parameter_brief(p) for p in window], "total": total, "offset": offset}

    def parameter_detail(self, parameter_id: str) -> dict[str, Any] | None:
        param = self.dcs.parameters.get(parameter_id)
        if not param:
            return None
        tags = [self.dcs.tags[t] for t in param["tagIds"] if t in self.dcs.tags]
        entities = [
            e
            for e in self.relations.entities.values()
            if any(m["objectType"] == "parameter" and m["id"] == parameter_id for m in e["match"]["matches"])
        ]
        rel_ids = {rid for e in entities for rid in e["relationIds"]}
        return {
            **self._parameter_brief(param),
            "equipment": self._equipment_brief(self.dcs.equipment[param["equipmentId"]])
            if param["equipmentId"] in self.dcs.equipment
            else None,
            "tags": tags,
            "measurementAnchors": [self._anchor_from_tag(param, t) for t in tags],
            "relationEntities": [self.entity_brief(e) for e in entities],
            "relations": [r for r in self.relations.relations if r["id"] in rel_ids],
            "rules": self.rules_for_object(param["name"]),
            "source": param["source"],
        }

    def tags(
        self,
        equipment_id: str | None = None,
        parameter_id: str | None = None,
        area_id: str | None = None,
        parameter_type: str | None = None,
        block_type: str | None = None,
        keyword: str | None = None,
        variable_category: str | None = None,
        confidence: str | None = None,
        group_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        items = list(self.dcs.tags.values())
        if equipment_id:
            items = [t for t in items if t["equipmentId"] == equipment_id]
        if parameter_id:
            items = [t for t in items if t["parameterId"] == parameter_id]
        if area_id:
            items = [t for t in items if t["areaId"] == (self.dcs.resolve_area(area_id) or area_id)]
        if variable_category:
            items = [t for t in items if t.get("variableCategory") == variable_category]
        if confidence:
            items = [t for t in items if t.get("confidence") == confidence]
        if group_id:
            resolved_group = self.resolve_group_id(group_id)
            items = [t for t in items if t.get("equipmentGroupId") == resolved_group]
        if parameter_type:
            items = [t for t in items if t["parameterType"] == parameter_type]
        if block_type:
            items = [t for t in items if t["blockType"] == block_type]
        if keyword:
            items = [
                t for t in items if keyword in (t["name"] or "") or keyword in (t["rawDescription"] or "")
            ]
        total = len(items)
        window = items[offset : offset + limit] if limit else items[offset:]
        return {"items": window, "total": total, "offset": offset}

    # ------------------------------------------------- 标准设备组（v2 新增）

    def _group_brief(self, group: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": group["id"],
            "uri": group["uri"],
            "name": group["name"],
            "areaId": group["areaId"],
            "areaCode": group["areaCode"],
            "areaName": group["areaName"],
            "equipmentType": group["equipmentType"],
            "instanceCountDeclared": group["instanceCountDeclared"],
            "instances": group["instances"],
            "components": group["components"],
            "keyTags": group["keyTags"],
            "properties": group["properties"],
            "tagCountDeclared": group["tagCountDeclared"],
            "tagCount": group["tagCount"],
            "equipmentCount": group["equipmentCount"],
            "sourceType": group["sourceType"],
            "source": group["source"],
        }

    def resolve_group_id(self, value: Any) -> str | None:
        """egrp-xxxxxxxx / :GroupUri / 设备组名称 → groupId。"""
        text = ids.normalize(value)
        if not text:
            return None
        if text in self.dcs.equipment_groups:
            return text
        for group in self.dcs.equipment_groups.values():
            if text in (group["uri"], group["name"]):
                return group["id"]
        return None

    def equipment_groups(
        self,
        area_id: str | None = None,
        equipment_type: str | None = None,
        keyword: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        items = list(self.dcs.equipment_groups.values())
        if area_id:
            resolved = self.dcs.resolve_area(area_id) or area_id
            items = [g for g in items if g["areaId"] == resolved]
        if equipment_type:
            items = [g for g in items if g["equipmentType"] == equipment_type]
        if keyword:
            items = [
                g for g in items
                if keyword in (g["name"] or "")
                or keyword in (g["uri"] or "")
                or any(keyword in inst for inst in g["instances"])
            ]
        items.sort(key=lambda g: (g["areaCode"] or "", -g["tagCount"]))
        total = len(items)
        window = items[offset : offset + limit] if limit else items[offset:]
        return {
            "items": [self._group_brief(g) for g in window],
            "total": total,
            "offset": offset,
            "facets": {
                "equipmentType": sorted({g["equipmentType"] for g in self.dcs.equipment_groups.values() if g["equipmentType"]}),
                "areaCode": sorted({g["areaCode"] for g in self.dcs.equipment_groups.values() if g["areaCode"]}),
            },
        }

    def equipment_group_detail(self, group_id: str) -> dict[str, Any] | None:
        resolved = self.resolve_group_id(group_id)
        group = self.dcs.equipment_groups.get(resolved) if resolved else None
        if not group:
            return None
        return {
            **self._group_brief(group),
            "area": self.areas_by_id(group["areaId"]) if group["areaId"] else None,
            "equipment": [
                self._equipment_brief(self.dcs.equipment[e])
                for e in group["equipmentIds"] if e in self.dcs.equipment
            ],
            "tags": [self.dcs.tags[t] for t in group["tagIds"] if t in self.dcs.tags][:200],
            "tagsTruncated": max(0, group["tagCount"] - 200),
        }

    # --------------------------------------------- 全流程工段衔接（v2 新增）

    def area_flow(self, area_id: str | None = None) -> dict[str, Any]:
        """工段之间的上下游衔接。传 area_id 时只看该工段的进出。"""
        rows = self.relations.area_flow
        resolved = self.dcs.resolve_area(area_id) if area_id else None
        code = self.dcs.areas[resolved]["code"] if resolved in self.dcs.areas else None

        def decorate(row: dict[str, Any]) -> dict[str, Any]:
            up = self.dcs.area_by_code.get(row["upstreamCode"])
            down = self.dcs.area_by_code.get(row["downstreamCode"])
            return {
                **row,
                "upstreamAreaId": up,
                "downstreamAreaId": down,
            }

        if code:
            upstream = [decorate(r) for r in rows if r["downstreamCode"] == code]
            downstream = [decorate(r) for r in rows if r["upstreamCode"] == code]
            return {
                "areaId": resolved,
                "areaCode": code,
                "upstream": upstream,
                "downstream": downstream,
                "total": len(upstream) + len(downstream),
                "sourceType": SOURCE_RELATION,
            }
        items = [decorate(r) for r in rows]
        return {"items": items, "total": len(items), "sourceType": SOURCE_RELATION}

    # ------------------------------------------------------------ 关系

    def entity_brief(self, entity: dict[str, Any]) -> dict[str, Any]:
        m = entity["match"]
        return {
            "id": entity["id"],
            "name": entity["name"],
            "type": entity["type"],
            "areas": entity["areas"],
            # v2 的「实体字典」Sheet 给出的权威属性
            "uri": entity.get("uri"),
            "owlClass": entity.get("owlClass"),
            "areaCode": entity.get("areaCode"),
            "areaId": ids.area_id(entity["areaCode"]) if entity.get("areaCode") else None,
            "belongsTo": entity.get("belongsTo"),
            "description": entity.get("description"),
            "relationCount": entity["relationCount"],
            "outgoingCount": len(entity["outgoingRelationIds"]),
            "incomingCount": len(entity["incomingRelationIds"]),
            "matchStatus": m["matchStatus"],
            "matchStatusLabel": m["matchStatusLabel"],
            "matchStrategy": m["matchStrategy"],
            "matchStrategyLabel": m["matchStrategyLabel"],
            "matchCount": m["matchCount"],
            "matchStrategies": m.get("matchStrategies", []),
            "tagCount": m["tagCount"],
            "pendingConfirmation": m["pendingConfirmation"],
            "sourceType": SOURCE_RELATION,
        }

    def entity_detail(self, entity_id: str) -> dict[str, Any] | None:
        entity = self.relations.entities.get(entity_id)
        if not entity:
            return None
        m = entity["match"]
        anchors: list[dict[str, Any]] = []
        for match in m["matches"]:
            if match["objectType"] != "parameter":
                continue
            param = self.dcs.parameters.get(match["id"])
            if not param:
                continue
            for tid in param["tagIds"]:
                tag = self.dcs.tags.get(tid)
                if tag:
                    anchors.append(self._anchor_from_tag(param, tag, entity))
        return {
            **self.entity_brief(entity),
            "matches": m["matches"],
            "matchStrategies": m["matchStrategies"],
            "measurementAnchors": anchors,
            "outgoingRelations": [r for r in self.relations.relations if r["id"] in entity["outgoingRelationIds"]],
            "incomingRelations": [r for r in self.relations.relations if r["id"] in entity["incomingRelationIds"]],
        }

    def relations_query(self, **f: Any) -> dict[str, Any]:
        items = list(self.relations.relations)
        if f.get("area"):
            items = [r for r in items if r["area"] == f["area"]]
        if f.get("category"):
            items = [r for r in items if r["category"] == f["category"]]
        if f.get("predicate"):
            items = [r for r in items if r["predicate"] == f["predicate"]]
        if f.get("subject_type"):
            items = [r for r in items if r["subjectType"] == f["subject_type"]]
        if f.get("object_type"):
            items = [r for r in items if r["objectType"] == f["object_type"]]
        if f.get("scenario"):
            items = [r for r in items if r["scenario"] == f["scenario"]]
        if f.get("entity_id"):
            items = [
                r
                for r in items
                if f["entity_id"] in (r["subject"].get("id"), r["object"].get("id"))
            ]
        if f.get("min_weight") is not None:
            items = [r for r in items if (r["weight"] is not None and r["weight"] >= f["min_weight"])]
        if f.get("max_weight") is not None:
            items = [r for r in items if (r["weight"] is not None and r["weight"] <= f["max_weight"])]
        if f.get("matched") is not None:
            want = "MATCHED" if f["matched"] else "UNMATCHED"
            items = [r for r in items if (r["matchStatus"] == "MATCHED") == (want == "MATCHED")]
        if f.get("causal"):
            items = [r for r in items if r["isCausal"]]
        if f.get("keyword"):
            k = f["keyword"]
            items = [
                r
                for r in items
                if k in (r["subjectEntity"] or "")
                or k in (r["objectEntity"] or "")
                or k in (r["predicate"] or "")
                or k in (r["domainDescription"] or "")
            ]
        total = len(items)
        offset = f.get("offset") or 0
        limit = f.get("limit")
        window = items[offset : offset + limit] if limit else items[offset:]
        return {"items": window, "total": total, "offset": offset}

    def relation_detail(self, relation_id: str) -> dict[str, Any] | None:
        rel = self.relations.by_id(relation_id)
        if not rel:
            return None
        subject = self.relations.entities.get(rel["subject"].get("id") or "")
        obj = self.relations.entities.get(rel["object"].get("id") or "")
        same_category = [
            r["id"] for r in self.relations.relations if r["category"] == rel["category"] and r["id"] != relation_id
        ]
        same_area = [r["id"] for r in self.relations.relations if r["area"] == rel["area"] and r["id"] != relation_id]
        return {
            **rel,
            "subjectDetail": self.entity_brief(subject) if subject else None,
            "objectDetail": self.entity_brief(obj) if obj else None,
            "sameCategoryRelationIds": same_category,
            "sameAreaRelationIds": same_area,
            "sourceTypeLabel": SOURCE_TYPE_LABELS[rel["sourceType"]],
        }

    def relations_for_ontology_object(self, object_type: str, object_id: str) -> dict[str, Any]:
        """反查某个 DCS 本体对象（设备/参数）参与的关系，经由匹配结果建立。"""
        entities = [
            e
            for e in self.relations.entities.values()
            if any(m["objectType"] == object_type and m["id"] == object_id for m in e["match"]["matches"])
        ]
        rel_ids = {rid for e in entities for rid in e["relationIds"]}
        return {
            "entities": [self.entity_brief(e) for e in entities],
            "relations": [r for r in self.relations.relations if r["id"] in rel_ids],
        }

    # ------------------------------------------------------------ 9 项核心内容

    def classes(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in self.dcs.schema_rows:
            if row.get("element", "").startswith("核心类"):
                out.append(
                    {
                        "uri": row["uri"],
                        "label": row["labelZh"],
                        "kind": "核心类 (Class)",
                        "domain": row["domain"],
                        "range": row["range"],
                        "example": row["example"],
                        "instanceCount": self._class_instance_count(row["uri"]),
                        "sourceType": row["sourceType"],
                        "source": row["source"],
                    }
                )
        seen = {c["label"] for c in out}
        # Excel 中实际出现的关系对象类型也是本体类
        type_counts: dict[str, int] = {}
        for e in self.relations.entities.values():
            if e["type"]:
                type_counts[e["type"]] = type_counts.get(e["type"], 0) + 1
        for t, n in sorted(type_counts.items(), key=lambda kv: -kv[1]):
            if t in seen:
                continue
            out.append(
                {
                    "uri": None,
                    "label": t,
                    "kind": "关系对象类型 (Relation Entity Type)",
                    "domain": None,
                    "range": None,
                    "example": None,
                    "instanceCount": n,
                    "sourceType": SOURCE_RELATION,
                    "source": {"file": self.relations.file, "sheet": "关系明细", "field": "对象类型"},
                }
            )
        return out

    def _class_instance_count(self, uri: str | None) -> int:
        return {
            ":ProductionArea": len(self.dcs.areas),
            ":ProductionEquipment": len(self.dcs.equipment),
            ":ProcessParameter": len(self.dcs.parameters),
            ":DcsTag": len(self.dcs.tags),
            ":EquipmentComponent": len(
                [e for e in self.relations.entities.values() if e["type"] == "设备部件"]
            ),
        }.get(uri or "", 0)

    def properties(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in self.dcs.schema_rows:
            el = row.get("element") or ""
            if el.startswith("对象属性") or el.startswith("数据属性"):
                out.append(
                    {
                        "name": row["uri"],
                        "label": row["labelZh"],
                        "kind": el,
                        "domain": row["domain"],
                        "range": row["range"],
                        "example": row["example"],
                        "sourceType": row["sourceType"],
                        "source": row["source"],
                    }
                )
        from backend.services.dcs_loader import STATS_SPEC, TAG_SPEC
        from backend.services.relation_excel_loader import FIELD_LABELS as REL_FIELDS
        from backend.services.relation_excel_loader import RELATION_SPEC

        # 字段清单直接取自各加载器的表头映射，Excel 加列时这里自动跟上
        dcs_fields = [candidates[0] for candidates in TAG_SPEC.values()]
        for f in dcs_fields:
            out.append(
                {
                    "name": f,
                    "label": "DCS 点表字段",
                    "kind": "数据属性 (Excel Field)",
                    "domain": "DCS点位明细",
                    "range": "xsd:string",
                    "example": None,
                    "sourceType": SOURCE_DCS,
                    "source": {"file": self.dcs.file, "sheet": "DCS点位明细", "field": f},
                }
            )
        for f in [candidates[0] for candidates in STATS_SPEC.values()]:
            out.append(
                {
                    "name": f,
                    "label": "DCS 设备统计字段",
                    "kind": "数据属性 (Excel Field)",
                    "domain": "设备统计",
                    "range": "xsd:string",
                    "example": None,
                    "sourceType": SOURCE_DCS,
                    "source": {"file": self.dcs.file, "sheet": "设备统计", "field": f},
                }
            )
        relation_fields = list(dict.fromkeys(
            [candidates[0] for candidates in RELATION_SPEC.values()] + list(REL_FIELDS.values())
        ))
        for f in relation_fields:
            out.append(
                {
                    "name": f,
                    "label": "工业关系字段",
                    "kind": "数据属性 (Excel Field)",
                    "domain": "关系明细",
                    "range": "xsd:string",
                    "example": None,
                    "sourceType": SOURCE_RELATION,
                    "source": {"file": self.relations.file, "sheet": "关系明细", "field": f},
                }
            )
        return out

    def relation_predicates(self) -> list[dict[str, Any]]:
        """关系谓词清单，含 Schema Sheet 的对象属性与关系 Excel 的实际谓词。"""
        out: list[dict[str, Any]] = []
        for row in self.dcs.schema_rows:
            if (row.get("element") or "").startswith("对象属性"):
                out.append(
                    {
                        "predicate": row["uri"],
                        "label": row["labelZh"],
                        "count": None,
                        "categories": [],
                        "sourceType": row["sourceType"],
                        "source": row["source"],
                    }
                )
        counts: dict[str, dict[str, Any]] = {}
        for r in self.relations.relations:
            p = r["predicate"] or "未标注"
            entry = counts.setdefault(p, {"predicate": p, "label": None, "count": 0, "categories": []})
            entry["count"] += 1
            if r["category"] and r["category"] not in entry["categories"]:
                entry["categories"].append(r["category"])
        for entry in sorted(counts.values(), key=lambda e: -e["count"]):
            entry["sourceType"] = SOURCE_RELATION
            entry["source"] = {"file": self.relations.file, "sheet": "关系明细", "field": "关系谓词 / 边类型 (Predicate)"}
            out.append(entry)
        return out

    def semantics(self, limit: int | None = None, area_id: str | None = None) -> dict[str, Any]:
        """DCS 原始描述 → 参数语义 → 工业对象 的语义提升链路。"""
        items: list[dict[str, Any]] = []
        for tag in self.dcs.tags.values():
            if area_id and tag["areaId"] != area_id:
                continue
            items.append(
                {
                    "id": tag["id"],
                    "rawDescription": tag["rawDescription"],
                    "parameterSemantic": tag["parameterName"],
                    "parameterId": tag["parameterId"],
                    "industrialObject": tag["equipmentName"],
                    "equipmentId": tag["equipmentId"],
                    "owlSubject": tag["owlSubject"],
                    "areaName": tag["areaName"],
                    "tagName": tag["name"],
                    "blockType": tag["blockType"],
                    "kind": "DCS语义提升",
                    "sourceType": SOURCE_DCS,
                    "source": tag["source"],
                }
            )
        total = len(items)
        rel_items = []
        for r in self.relations.relations:
            rel_items.append(
                {
                    "id": r["id"],
                    "subjectEntity": r["subjectEntity"],
                    "subjectType": r["subjectType"],
                    "predicate": r["predicate"],
                    "objectEntity": r["objectEntity"],
                    "objectType": r["objectType"],
                    "domainDescription": r["domainDescription"],
                    "kind": "关系语义",
                    "sourceType": SOURCE_RELATION,
                    "source": r["source"],
                }
            )
        return {
            "dcsSemantics": items[:limit] if limit else items,
            "dcsSemanticTotal": total,
            "relationSemantics": rel_items,
            "relationSemanticTotal": len(rel_items),
        }

    def _anchor_from_tag(
        self, param: dict[str, Any], tag: dict[str, Any], entity: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        anchor = {
            "id": f"anchor-{tag['id'][5:]}",
            "semanticName": param["name"],
            "parameterId": param["id"],
            "equipmentId": param["equipmentId"],
            "equipmentName": param["equipmentName"],
            "owlSubject": param["owlSubject"],
            "areaId": param["areaId"],
            "areaName": param["areaName"],
            "parameterType": tag["parameterType"],
            "tagId": tag["id"],
            "tagName": tag["name"],
            "rawDescription": tag["rawDescription"],
            "blockType": tag["blockType"],
            "unit": tag["unit"],
            "station": tag["station"],
            "sourceType": SOURCE_DCS,
            "source": tag["source"],
        }
        if entity is not None:
            anchor["relationEntityId"] = entity["id"]
            anchor["relationEntityName"] = entity["name"]
            anchor["relationEntityType"] = entity["type"]
            anchor["viaMappingFile"] = self.mapping.file
        return anchor

    def measurement_anchors(
        self, entity_only: bool = False, area_id: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entity in self.relations.entities.values():
            for match in entity["match"]["matches"]:
                if match["objectType"] != "parameter":
                    continue
                param = self.dcs.parameters.get(match["id"])
                if not param or (area_id and param["areaId"] != area_id):
                    continue
                for tid in param["tagIds"]:
                    tag = self.dcs.tags.get(tid)
                    if tag:
                        out.append(self._anchor_from_tag(param, tag, entity))
        if entity_only:
            return out[:limit] if limit else out
        return out[:limit] if limit else out

    def unanchored_entities(self) -> list[dict[str, Any]]:
        return [
            self.entity_brief(e)
            for e in self.relations.entities.values()
            if e["match"]["tagCount"] == 0
        ]

    def causal_relations(self) -> dict[str, Any]:
        items = [r for r in self.relations.relations if r["isCausal"]]
        return {"items": items, "total": len(items), "categories": sorted(CAUSAL_CATEGORIES)}

    def constraints(self) -> dict[str, Any]:
        return {
            "items": [],
            "total": 0,
            "emptyReason": "当前暂无项目约束数据。约束需由独立约束数据源提供，本 Demo 不虚构生产约束。",
            "expectedSource": "约束 Excel / 约束文件",
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "items": [],
            "total": 0,
            "emptyReason": "当前暂无项目能力数据。能力需由独立能力数据源提供，本 Demo 不使用 Mock 能力。",
            "expectedSource": "能力 Excel / 能力文件",
        }

    def model_registry(self) -> dict[str, Any]:
        return {
            "items": [],
            "total": 0,
            "emptyReason": "当前暂无模型注册数据。机理模型与时序模型注册信息需由独立模型注册数据源提供。",
            "expectedSource": "模型注册表",
        }

    _RULE_LIMIT_REF = _re.compile(r"PL\d{3}")

    def _rule_view(self, rule: dict[str, Any]) -> dict[str, Any]:
        """规则条目的对外视图：补上工段编号与它引用的限值编号。

        v2 的规则里 36 条把阈值写成「见 PLxxx」，直接引用工艺限值表——
        这里只做解析与回指，不替换原文，阈值仍以限值表为准。
        """
        area = rule.get("area")
        aid = self.dcs.resolve_area(area) if area else None
        refs = sorted(set(self._RULE_LIMIT_REF.findall(
            " ".join(str(rule.get(k) or "") for k in ("threshold", "condition", "description"))
        )))
        return {
            **rule,
            "areaId": aid,
            "areaCode": self.dcs.areas[aid]["code"] if aid in self.dcs.areas else None,
            "appliesToAllAreas": not area,
            "limitRefs": refs,
            "draft": str(rule.get("description") or "").startswith("【草案"),
        }

    def rules_query(
        self,
        area: str | None = None,
        applies_to: str | None = None,
        applies_to_type: str | None = None,
        severity: str | None = None,
        keyword: str | None = None,
    ) -> dict[str, Any]:
        items = [self._rule_view(r) for r in self.rules.rules]
        if area:
            # 同时接受工段名称、S11、area-S11；规则的 area 为空表示"全工段适用"
            resolved = self.dcs.resolve_area(area)
            items = [
                r for r in items
                if r.get("area") == area
                or (resolved and r.get("areaId") == resolved)
                or not r.get("area")
            ]
        if applies_to:
            items = [r for r in items if applies_to in (r.get("appliesTo") or "")]
        if applies_to_type:
            items = [r for r in items if r.get("appliesToType") == applies_to_type]
        if severity:
            items = [r for r in items if r.get("severity") == severity]
        if keyword:
            items = [
                r for r in items
                if keyword in (r.get("name") or "")
                or keyword in (r.get("condition") or "")
                or keyword in (r.get("conclusion") or "")
                or keyword in (r.get("appliesTo") or "")
            ]
        return {
            "items": items,
            "facets": {
                "appliesToType": sorted({r["appliesToType"] for r in self.rules.rules if r.get("appliesToType")}),
                "severity": sorted({r["severity"] for r in self.rules.rules if r.get("severity")}),
                "area": sorted({r["area"] for r in self.rules.rules if r.get("area")}),
            },
            "notice": (
                "规则来自独立规则数据源，条目以「【草案·待现场确认】」开头的尚未经现场确认，"
                "仅供工艺调查参考；阈值写「见 PLxxx」的以工艺限值表为准。"
            ),
            "total": len(items),
            "available": self.rules.available,
            "emptyReason": None
            if self.rules.available
            else (
                "当前暂无规则数据源。规则必须来自独立规则 Excel / 规则文件，"
                "不从参数名称自动生成。将 6APA_规则.xlsx 放入 data/source 后自动生效。"
            ),
            "expectedSource": RULE_FILE.name,
            "templateColumns": [
                "规则编号 (Rule ID)", "规则名称 (Rule Name)", "适用对象类型 (Applies To Type)",
                "适用对象 (Applies To)", "适用工段 (Area)", "条件 (Condition)", "逻辑 (Logic)",
                "阈值 (Threshold)", "推理结论 (Conclusion)", "严重程度 (Severity)", "规则说明 (Description)",
            ],
        }

    def rules_for_object(self, object_name: str | None, area_id: str | None = None) -> list[dict[str, Any]]:
        """某个对象适用哪些规则。

        名称命中优先；v2 的通用层规则（R-G-xx）适用对象写的是「全部泵、搅拌、离心机（MOT2块）」
        这类描述，名称对不上，所以额外把"未限定工段或同工段"的通用规则一并带出来，
        并用 matchedBy 标明是怎么命中的，避免使用者把泛化规则当成专属规则。
        """
        out: list[dict[str, Any]] = []
        for rule in self.rules.rules:
            view = self._rule_view(rule)
            applies = rule.get("appliesTo") or ""
            if object_name and object_name in applies:
                out.append({**view, "matchedBy": "适用对象名称"})
            elif view["appliesToAllAreas"] and rule.get("appliesToType") in ("设备", "参数"):
                out.append({**view, "matchedBy": "通用层规则（未限定工段）"})
            elif area_id and view.get("areaId") == area_id:
                out.append({**view, "matchedBy": "同工段规则"})
        return out

    # ------------------------------------------------------------ 元数据

    def categories(self) -> dict[str, Any]:
        cats = []
        counts = {
            "class": len(self.classes()),
            "instance": len(self.dcs.equipment),
            "property": len(self.properties()),
            "relation": len(self.relations.relations),
            "constraint": 0,
            "rule": len(self.rules.rules),
            "capability": 0,
            "semantic": len(self.dcs.tags),
            "measurementAnchor": len(self.measurement_anchors()),
            "causal": len([r for r in self.relations.relations if r["isCausal"]]),
            "modelRegistry": 0,
            "provenance": len(self.dcs.tags) + len(self.relations.relations) + len(self.mapping.entries),
        }
        for c in ONTOLOGY_CATEGORIES:
            cats.append({**c, "count": counts.get(c["key"], 0)})
        return {
            "categories": cats,
            "coreContents": [
                {**c, "count": counts.get(c["key"], 0)} for c in CORE_CONTENTS
            ],
            "nodeStyles": NODE_TYPE_STYLES,
            "edgeStyles": EDGE_CATEGORY_STYLES,
        }

    def data_sources(self) -> dict[str, Any]:
        def block(source_type, path: Path, stats, available, note=None):
            return {
                "sourceType": source_type,
                "sourceTypeLabel": SOURCE_TYPE_LABELS[source_type],
                "file": path.name,
                "status": "已加载" if available else "未提供",
                "available": available,
                "loadedAt": self.loaded_at if available else None,
                "sheets": stats.get("sheets", []) if available else [],
                "stats": {k: v for k, v in stats.items() if k not in ("sheets", "file")} if available else {},
                "note": note,
            }

        return {
            "loadedAt": self.loaded_at,
            "sources": [
                block(SOURCE_DCS, DCS_FILE, self.dcs.load_stats, True,
                      "现场基础事实：控制站 / 生产工段 / 设备 / 参数语义 / DCS 点"
                      + (f"；设备名称按 {MERGE_FILE.name} 统一（{self.dcs.merge_stats['applied']} 个写法归并）"
                         if (self.dcs.merge_stats or {}).get("available") else "")),
                block(SOURCE_RELATION, RELATION_FILE, self.relations.load_stats, True,
                      "工业关系事实：结构 / 控制 / 物理拓扑 / 影响 / 质量关系"),
                block(SOURCE_MAPPING, MAPPING_FILE, self.mapping.load_stats, self.mapping.available,
                      "关系对象 → DCS 本体对象的人工映射，全部条目需现场确认"),
                block(SOURCE_RULE, RULE_FILE, self.rules.load_stats, self.rules.available,
                      "推理规则数据源；未提供时规则页显示空状态，不生成任何规则"),
            ],
            "boundary": {
                "DCS_EXCEL": "现场有什么：工段 / 设备 / 参数 / DCS点",
                "RELATION_EXCEL": "它们如何关联：关系 / 部件 / 属性 / 因果",
                "MAPPING_FILE": "抽象对象与现场位号如何对齐",
                "RULE_FILE": "什么条件下可以得出什么判断",
            },
        }

    def turtle(self) -> dict[str, Any]:
        return {
            "lines": self.relations.turtle_lines,
            "sourceType": SOURCE_RELATION,
            "source": {"file": self.relations.file, "sheet": "OWL_Turtle代码规范"},
        }
