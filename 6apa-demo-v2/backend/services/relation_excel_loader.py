"""工业关系 Excel 导入层。

回答“工业对象之间是什么关系”。关系数据只来自 6APA_工业关系.xlsx，
不从设备名称、编号、DCS 点名或参数名称推断（需求文档第十二、二十四章）。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from backend.ontology import identifiers as ids
from backend.ontology.models import SOURCE_RELATION, Provenance
from backend.services.excel_utils import (
    find_header_row,
    norm_header,
    read_rows,
    read_sheet,
    split_tags,
)

SHEET_RELATIONS = "关系明细"
SHEET_OVERVIEW = "关系分类与统计(Overview)"
SHEET_TURTLE = "OWL_Turtle代码规范"
SHEET_ENTITY_DICT = "实体字典"
SHEET_AREA_FLOW = "全流程工段衔接"

# v2 的关系明细扩到 20 列。按表头取列，避免现场调列序时整体错位。
RELATION_SPEC: dict[str, tuple[str, ...]] = {
    "area": ("工段 (Area)", "工段"),
    "category": ("关系大类 (Category)", "关系大类"),
    "subjectType": ("起始对象类型 (Subject Type)", "起始对象类型"),
    "subjectEntity": ("起始对象语义名称 (Subject Entity)", "起始对象语义名称"),
    "predicate": ("关系谓词 / 边类型 (Predicate)", "关系谓词"),
    "objectType": ("目标对象类型 (Object Type)", "目标对象类型"),
    "objectEntity": ("目标对象语义名称 (Object Entity)", "目标对象语义名称"),
    "domainDescription": ("工艺机理与业务因果说明 (Domain Description)", "工艺机理与业务因果说明"),
    "scenario": ("子场景",),
    "weight": ("权重",),
    # v2 新增
    "areaCode": ("工段编号",),
    "relationCode": ("关系ID",),
    "subjectUri": ("主体URI",),
    "predicateUri": ("谓词URI",),
    "objectUri": ("客体URI",),
    "tagsRaw": ("关联DCS位号",),
    "basis": ("依据来源",),
    "confidence": ("置信度",),
    "processScreen": ("流程画面",),
    "changeFlag": ("变更标记",),
}

RELATION_COLUMNS = list(RELATION_SPEC)

REQUIRED_FIELDS = [
    "area",
    "category",
    "subjectType",
    "subjectEntity",
    "predicate",
    "objectType",
    "objectEntity",
]

FIELD_LABELS = {
    "area": "工段 (Area)",
    "category": "关系大类 (Category)",
    "subjectType": "起始对象类型 (Subject Type)",
    "subjectEntity": "起始对象语义名称 (Subject Entity)",
    "predicate": "关系谓词 / 边类型 (Predicate)",
    "objectType": "目标对象类型 (Object Type)",
    "objectEntity": "目标对象语义名称 (Object Entity)",
    "domainDescription": "工艺机理与业务因果说明 (Domain Description)",
    "scenario": "子场景",
    "weight": "权重",
}

# 客体类型为这些时，关系本身就是"工艺量 → 现场位号"的显式声明
TAG_OBJECT_TYPES = {"DCS测点"}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


class RelationDataset:
    def __init__(self, file_name: str) -> None:
        self.file = file_name
        self.relations: list[dict[str, Any]] = []
        self.entities: dict[str, dict[str, Any]] = {}
        self.overview_rows: list[dict[str, Any]] = []
        self.entity_dictionary: dict[str, dict[str, Any]] = {}
        self.area_flow: list[dict[str, Any]] = []
        self.turtle_lines: list[str] = []
        self.issues: list[dict[str, Any]] = []
        self.header_missing: list[str] = []
        self.load_stats: dict[str, Any] = {}

    def by_id(self, relation_id: str) -> dict[str, Any] | None:
        for rel in self.relations:
            if rel["id"] == relation_id:
                return rel
        return None


def load_relations(path: str | Path) -> RelationDataset:
    path = Path(path)
    ds = RelationDataset(path.name)

    hm, rows, start = read_rows(path, SHEET_RELATIONS, RELATION_SPEC)
    ds.header_missing = list(hm.missing)

    seen_keys: dict[str, int] = {}

    for offset, row in enumerate(rows):
        i = start + offset
        rec = {field: hm.text(row, field) for field in RELATION_SPEC}
        if not any(rec.values()):
            continue

        source = Provenance(ds.file, SHEET_RELATIONS, i).to_dict()
        missing = [FIELD_LABELS[f] for f in REQUIRED_FIELDS if not rec.get(f)]
        if missing:
            ds.issues.append(
                {
                    "severity": "error",
                    "check": "关系 Excel 必填字段为空",
                    "detail": "缺失字段：" + "、".join(missing),
                    "source": source,
                }
            )

        weight_raw = rec.get("weight")
        weight: float | None
        if weight_raw is None:
            weight = None
            ds.issues.append(
                {
                    "severity": "warning",
                    "check": "权重格式错误",
                    "detail": "权重为空",
                    "source": source,
                }
            )
        else:
            try:
                weight = float(weight_raw)
            except ValueError:
                weight = None
                ds.issues.append(
                    {
                        "severity": "warning",
                        "check": "权重格式错误",
                        "detail": f"权重不是数字：{weight_raw}",
                        "source": source,
                    }
                )

        key_parts = [
            rec.get("area") or "",
            rec.get("subjectType") or "",
            rec.get("subjectEntity") or "",
            rec.get("predicate") or "",
            rec.get("objectType") or "",
            rec.get("objectEntity") or "",
            rec.get("scenario") or "",
        ]
        stable_key = ids.stable_key(key_parts)
        # v2 的关系表自带全局唯一「关系ID」（R0001…），用它生成 ID 更稳：
        # 即便日后某条关系的描述或子场景被改写，ID 也不会漂移。
        rid = ids.relation_id([rec["relationCode"]] if rec.get("relationCode") else key_parts)

        if stable_key in seen_keys:
            ds.issues.append(
                {
                    "severity": "warning",
                    "check": "重复关系",
                    "detail": f"与第 {seen_keys[stable_key]} 行的关系键完全相同：{stable_key}",
                    "source": source,
                }
            )
        else:
            seen_keys[stable_key] = i

        # 关联 DCS 位号：顿号分隔；个别单元格被截断（值以省略号结尾），无法解析要报出来
        tag_names: list[str] = []
        truncated_tags: list[str] = []
        for candidate in split_tags(rec.get("tagsRaw")):
            if candidate.endswith(("…", "...", "．．．")):
                truncated_tags.append(candidate)
            else:
                tag_names.append(candidate)
        if truncated_tags:
            ds.issues.append({
                "severity": "warning",
                "check": "关联DCS位号被截断",
                "detail": "以下位号写不完整，无法解析：" + "、".join(truncated_tags),
                "source": source,
            })

        if rec.get("objectType") in TAG_OBJECT_TYPES and rec.get("objectEntity"):
            for candidate in split_tags(rec["objectEntity"]):
                if candidate not in tag_names and not candidate.endswith(("…", "...")):
                    tag_names.append(candidate)

        subject = _register_entity(ds, rec.get("subjectType"), rec.get("subjectEntity"), rec.get("area"))
        obj = _register_entity(ds, rec.get("objectType"), rec.get("objectEntity"), rec.get("area"))

        relation = {
            "id": rid,
            "seq": f"relation-{len(ds.relations) + 1:06d}",
            "stableKey": stable_key,
            "area": rec.get("area"),
            "category": rec.get("category"),
            "predicate": rec.get("predicate"),
            "subject": {
                "id": subject["id"] if subject else None,
                "type": rec.get("subjectType"),
                "entity": rec.get("subjectEntity"),
            },
            "object": {
                "id": obj["id"] if obj else None,
                "type": rec.get("objectType"),
                "entity": rec.get("objectEntity"),
            },
            "subjectType": rec.get("subjectType"),
            "subjectEntity": rec.get("subjectEntity"),
            "objectType": rec.get("objectType"),
            "objectEntity": rec.get("objectEntity"),
            "domainDescription": rec.get("domainDescription"),
            "scenario": rec.get("scenario"),
            "weight": weight,
            "weightRaw": weight_raw,
            # v2 新增
            "relationCode": rec.get("relationCode"),
            "areaCode": (rec.get("areaCode") or "").upper() or None,
            "subjectUri": rec.get("subjectUri"),
            "predicateUri": rec.get("predicateUri"),
            "objectUri": rec.get("objectUri"),
            "tagNames": tag_names,
            "tagNamesTruncated": truncated_tags,
            "basis": rec.get("basis"),
            "confidence": rec.get("confidence"),
            "processScreen": rec.get("processScreen"),
            "changeFlag": rec.get("changeFlag"),
            "bindsTag": rec.get("objectType") in TAG_OBJECT_TYPES,
            "sourceType": SOURCE_RELATION,
            "source": source,
        }
        ds.relations.append(relation)
        if subject:
            subject["outgoingRelationIds"].append(rid)
            subject["relationIds"].append(rid)
        if obj:
            obj["incomingRelationIds"].append(rid)
            obj["relationIds"].append(rid)

    _load_overview(ds, path)
    _load_entity_dictionary(ds, path)
    _load_area_flow(ds, path)
    _load_turtle(ds, path)
    _finalise(ds)
    return ds


def _register_entity(
    ds: RelationDataset, entity_type: str | None, entity_name: str | None, area: str | None
) -> dict[str, Any] | None:
    if not entity_name:
        return None
    if entity_type in TAG_OBJECT_TYPES:
        # 「绑定测点」关系的客体就是现场位号本身，本体里已经有 tag- 对象了，
        # 再登记一份 robj- 会把同一个东西数两遍。这里不登记，
        # 位号统一通过 relation["tagNames"] 解析到真实 tag- 对象。
        return None
    eid = ids.relation_entity_id(entity_type or "", entity_name)
    entity = ds.entities.get(eid)
    if entity is None:
        entity = {
            "id": eid,
            "name": entity_name,
            "type": entity_type,
            "areas": [],
            "relationIds": [],
            "outgoingRelationIds": [],
            "incomingRelationIds": [],
            "sourceType": SOURCE_RELATION,
        }
        ds.entities[eid] = entity
    if area and area not in entity["areas"]:
        entity["areas"].append(area)
    return entity


def _load_overview(ds: RelationDataset, path: Path) -> None:
    raw = read_sheet(path, SHEET_OVERVIEW, header=None)
    header_row = None
    for i in range(len(raw)):
        if _clean(raw.iloc[i, 0]) and "关系大类" in str(raw.iloc[i, 0]):
            header_row = i
            break
    if header_row is None:
        return
    cols = ["category", "predicate", "meaning", "typicalSubjectType", "typicalObjectType", "declaredCount"]
    for i in range(header_row + 1, len(raw)):
        row = raw.iloc[i]
        if not _clean(row.iloc[0]):
            continue
        item = {cols[j]: _clean(row.iloc[j]) for j in range(min(len(cols), len(row)))}
        item["sourceType"] = SOURCE_RELATION
        item["source"] = Provenance(ds.file, SHEET_OVERVIEW, i + 1).to_dict()
        ds.overview_rows.append(item)


# ---------------------------------------------------------------- 实体字典


_ENTITY_DICT_COLS = [
    "uri", "name", "type", "owlClass", "areaCode", "belongsTo",
    "description", "subjectCount", "objectCount",
]


def _load_entity_dictionary(ds: RelationDataset, path: Path) -> None:
    """实体字典：关系明细中出现的全部节点，带 URI / OWL 类 / 所属工段 / 所属设备。

    只用来**补充**已登记关系对象的属性，不新建对象——关系对象仍由关系明细决定，
    这样 /relation-entities 的条目集合与关系数据严格一致。
    """
    try:
        raw = read_sheet(path, SHEET_ENTITY_DICT, header=None)
    except ValueError:
        return
    header_row = find_header_row(raw, "实体URI", limit=12)
    if header_row is None:
        return
    for i in range(header_row + 1, len(raw)):
        row = raw.iloc[i]
        uri = _clean(row.iloc[0])
        if not uri:
            continue
        rec = {_ENTITY_DICT_COLS[j]: _clean(row.iloc[j]) for j in range(min(len(_ENTITY_DICT_COLS), len(row)))}
        name = rec.get("name")
        if not name:
            continue
        rec["source"] = Provenance(ds.file, SHEET_ENTITY_DICT, i + 1).to_dict()
        rec["sourceType"] = SOURCE_RELATION
        ds.entity_dictionary[f"{rec.get('type') or ''}|{name}"] = rec

    # 回填到已登记的关系对象上
    for entity in ds.entities.values():
        rec = ds.entity_dictionary.get(f"{entity.get('type') or ''}|{entity['name']}")
        if not rec:
            continue
        entity["uri"] = rec.get("uri")
        entity["owlClass"] = rec.get("owlClass")
        entity["areaCode"] = (rec.get("areaCode") or "").upper() or None
        entity["belongsTo"] = rec.get("belongsTo")
        entity["description"] = rec.get("description")
        entity["dictionarySource"] = rec.get("source")


# ------------------------------------------------------------ 全流程工段衔接


_FLOW_COLS = ["seq", "upstreamCode", "upstreamName", "material", "downstreamCode", "downstreamName", "note", "confidence"]


def _load_area_flow(ds: RelationDataset, path: Path) -> None:
    try:
        raw = read_sheet(path, SHEET_AREA_FLOW, header=None)
    except ValueError:
        return
    header_row = find_header_row(raw, "序号", limit=12)
    if header_row is None:
        return
    for i in range(header_row + 1, len(raw)):
        row = raw.iloc[i]
        if _clean(row.iloc[0]) is None:
            continue
        rec = {_FLOW_COLS[j]: _clean(row.iloc[j]) for j in range(min(len(_FLOW_COLS), len(row)))}
        if not rec.get("upstreamCode") or not rec.get("downstreamCode"):
            continue
        rec["upstreamCode"] = rec["upstreamCode"].upper()
        rec["downstreamCode"] = rec["downstreamCode"].upper()
        rec["sourceType"] = SOURCE_RELATION
        rec["source"] = Provenance(ds.file, SHEET_AREA_FLOW, i + 1).to_dict()
        ds.area_flow.append(rec)


def _load_turtle(ds: RelationDataset, path: Path) -> None:
    try:
        raw = read_sheet(path, SHEET_TURTLE, header=None)
    except ValueError:
        return
    for i in range(len(raw)):
        line = _clean(raw.iloc[i, 0])
        ds.turtle_lines.append(line or "")


def _finalise(ds: RelationDataset) -> None:
    for entity in ds.entities.values():
        entity["relationCount"] = len(entity["relationIds"])
    ds.load_stats = {
        "file": ds.file,
        "sheets": [
            {
                "sheet": SHEET_RELATIONS,
                "rows": len(ds.relations),
                "validRows": len(
                    [r for r in ds.relations if all(r.get(f) or r["subject"].get("entity") for f in ("area", "category"))]
                ),
                "errorRows": len({issue["source"].get("row") for issue in ds.issues if issue["severity"] == "error"}),
            },
            {"sheet": SHEET_OVERVIEW, "rows": len(ds.overview_rows), "validRows": len(ds.overview_rows)},
            {
                "sheet": SHEET_ENTITY_DICT,
                "rows": len(ds.entity_dictionary),
                "validRows": len(ds.entity_dictionary),
            },
            {"sheet": SHEET_AREA_FLOW, "rows": len(ds.area_flow), "validRows": len(ds.area_flow)},
            {
                "sheet": SHEET_TURTLE,
                "rows": len([l for l in ds.turtle_lines if l]),
                "validRows": len([l for l in ds.turtle_lines if l]),
            },
        ],
        "relationCount": len(ds.relations),
        "entityCount": len(ds.entities),
        "entityDictionaryCount": len(ds.entity_dictionary),
        "areaFlowCount": len(ds.area_flow),
        "tagBindingCount": len([r for r in ds.relations if r.get("bindsTag")]),
        "relationsWithTags": len([r for r in ds.relations if r.get("tagNames")]),
    }
