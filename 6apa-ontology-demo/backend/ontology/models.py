"""本体数据模型与可配置分类定义。

分类名称集中在此处定义，前端通过 /api/ontology/categories 获取，
不在页面中硬编码（需求文档第四章）。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------- 数据来源类型

SOURCE_DCS = "DCS_EXCEL"
SOURCE_RELATION = "RELATION_EXCEL"
SOURCE_RULE = "RULE_FILE"
SOURCE_MAPPING = "MAPPING_FILE"
SOURCE_SCHEMA = "DCS_EXCEL_SCHEMA"

SOURCE_TYPE_LABELS = {
    SOURCE_DCS: "DCS 点表 Excel",
    SOURCE_RELATION: "工业关系 Excel",
    SOURCE_RULE: "规则 Excel / 规则文件",
    SOURCE_MAPPING: "对象映射 Excel",
    SOURCE_SCHEMA: "DCS 点表 Excel · 本体架构与设计规范 Sheet",
}


@dataclass
class Provenance:
    """数据来源追溯（需求文档第二十二章）。"""

    file: str
    sheet: str
    row: int | None = None
    field: str | None = None
    value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ------------------------------------------------------------ 12 个本体分类

ONTOLOGY_CATEGORIES: list[dict[str, Any]] = [
    {
        "key": "class",
        "index": 1,
        "name": "类",
        "nameEn": "Class",
        "core": True,
        "coreIndex": 1,
        "group": "描述工业对象及其结构",
        "description": "本体中的概念类型定义，来自 DCS 点表 Schema Sheet 与 Excel 中实际出现的对象类型。",
        "endpoint": "/api/ontology/classes",
    },
    {
        "key": "instance",
        "index": 2,
        "name": "实例",
        "nameEn": "Instance",
        "core": False,
        "group": "描述工业对象及其结构",
        "description": "由 DCS 点表实际加载的工段、设备、参数、DCS 点实例。",
        "endpoint": "/api/ontology/equipment",
    },
    {
        "key": "property",
        "index": 3,
        "name": "属性",
        "nameEn": "Property",
        "core": True,
        "coreIndex": 2,
        "group": "描述工业对象及其结构",
        "description": "对象属性与数据属性定义，含 DCS 点表与关系 Excel 的全部字段。",
        "endpoint": "/api/ontology/properties",
    },
    {
        "key": "relation",
        "index": 4,
        "name": "关系",
        "nameEn": "Relation",
        "core": True,
        "coreIndex": 3,
        "group": "描述工业对象及其结构",
        "description": "全部关系边，来自工业关系 Excel，不从名称推断。",
        "endpoint": "/api/ontology/relations",
    },
    {
        "key": "constraint",
        "index": 5,
        "name": "约束",
        "nameEn": "Constraint",
        "core": True,
        "coreIndex": 4,
        "group": "描述工业对象及其结构",
        "description": "生产约束与阈值，需由独立约束数据源提供。",
        "endpoint": "/api/ontology/constraints",
    },
    {
        "key": "rule",
        "index": 6,
        "name": "规则",
        "nameEn": "Rule",
        "core": True,
        "coreIndex": 6,
        "group": "描述工业对象能做什么、如何理解",
        "description": "推理规则，来自独立规则 Excel / 规则文件，不从参数名称自动生成。",
        "endpoint": "/api/ontology/rules",
    },
    {
        "key": "capability",
        "index": 7,
        "name": "能力",
        "nameEn": "Capability",
        "core": True,
        "coreIndex": 5,
        "group": "描述工业对象能做什么、如何理解",
        "description": "对象可提供的判断与计算能力，需由独立能力数据源提供。",
        "endpoint": "/api/ontology/capabilities",
    },
    {
        "key": "semantic",
        "index": 8,
        "name": "语义",
        "nameEn": "Semantic",
        "core": True,
        "coreIndex": 7,
        "group": "描述工业对象能做什么、如何理解",
        "description": "DCS 原始描述 → 参数语义 → 工业对象的语义提升链路。",
        "endpoint": "/api/ontology/semantics",
    },
    {
        "key": "measurementAnchor",
        "index": 9,
        "name": "测量锚点",
        "nameEn": "Measurement Anchor",
        "core": True,
        "coreIndex": 8,
        "group": "建立工业语义与 DCS 点之间的映射",
        "description": "工业语义与 DCS Tag / DCS 块之间的绑定关系。",
        "endpoint": "/api/ontology/measurement-anchors",
    },
    {
        "key": "causal",
        "index": 10,
        "name": "因果关系",
        "nameEn": "Causal Relationship",
        "core": True,
        "coreIndex": 9,
        "group": "描述参数、设备、状态之间的影响关系",
        "description": "影响关系与质量关系边，直接来自工业关系 Excel，不重新推断。",
        "endpoint": "/api/ontology/causal-relations",
    },
    {
        "key": "modelRegistry",
        "index": 11,
        "name": "模型注册",
        "nameEn": "Model Registry",
        "core": False,
        "group": "上层应用接入",
        "description": "机理模型、时序模型注册信息，需由独立模型注册数据源提供。",
        "endpoint": "/api/ontology/model-registry",
    },
    {
        "key": "provenance",
        "index": 12,
        "name": "知识/来源",
        "nameEn": "Knowledge & Provenance",
        "core": False,
        "group": "上层应用接入",
        "description": "每一条本体数据的文件、Sheet、行号级来源追溯。",
        "endpoint": "/api/ontology/data-sources",
    },
]

CORE_CONTENTS = sorted(
    [c for c in ONTOLOGY_CATEGORIES if c.get("core")],
    key=lambda c: c["coreIndex"],
)

# --------------------------------------------- 关系图节点 / 边样式（需求 11.2 / 11.3）

NODE_TYPE_STYLES: list[dict[str, str]] = [
    {"type": "生产工段", "color": "#4C8DFF", "shape": "roundRect"},
    {"type": "生产设备", "color": "#FF9F45", "shape": "circle"},
    {"type": "设备部件", "color": "#B07CFF", "shape": "circle"},
    {"type": "工艺属性", "color": "#3FCF8E", "shape": "circle"},
    {"type": "参数", "color": "#35C4D7", "shape": "circle"},
    {"type": "DCS点", "color": "#F2C744", "shape": "diamond"},
    {"type": "规则", "color": "#F2557A", "shape": "roundRect"},
    {"type": "物料流股", "color": "#5FD0A8", "shape": "circle"},
    {"type": "控制仪表", "color": "#7CA9FF", "shape": "circle"},
    {"type": "执行机构", "color": "#FFB86B", "shape": "circle"},
    {"type": "控制系统", "color": "#8FA6C4", "shape": "roundRect"},
    {"type": "质量指标", "color": "#E77CC0", "shape": "circle"},
    {"type": "业务指标", "color": "#D9534F", "shape": "roundRect"},
    # v2 新增的节点类型
    {"type": "设备实例", "color": "#FFC08A", "shape": "circle"},
    {"type": "DCS测点", "color": "#F2C744", "shape": "diamond"},
    {"type": "报警事件", "color": "#F2557A", "shape": "diamond"},
    {"type": "公用介质", "color": "#6FD3E8", "shape": "circle"},
    {"type": "外部对象", "color": "#6B7A90", "shape": "circle"},
]

EDGE_CATEGORY_STYLES: list[dict[str, Any]] = [
    {"category": "结构关系", "lineStyle": "solid", "width": 1.6, "color": "#8FA6C4"},
    {"category": "工艺关系", "lineStyle": "solid", "width": 2.6, "color": "#5FD0A8"},
    {"category": "物理拓扑关系", "lineStyle": "solid", "width": 2.4, "color": "#4C8DFF"},
    {"category": "属性关系", "lineStyle": "dashed", "width": 1.4, "color": "#3FCF8E"},
    {"category": "控制关系", "lineStyle": "solid", "width": 2.0, "color": "#FFB86B"},
    {"category": "因果关系", "lineStyle": "solid", "width": 2.0, "color": "#F2557A"},
    {"category": "影响关系", "lineStyle": "solid", "width": 2.0, "color": "#F2557A"},
    {"category": "质量关系", "lineStyle": "solid", "width": 2.2, "color": "#E77CC0"},
    {"category": "空间关系", "lineStyle": "dotted", "width": 1.4, "color": "#8FA6C4"},
    {"category": "物料关系", "lineStyle": "solid", "width": 2.0, "color": "#5FD0A8"},
    {"category": "能量关系", "lineStyle": "solid", "width": 2.0, "color": "#F2C744"},
    # v2 新增的关系大类
    {"category": "测点绑定关系", "lineStyle": "dotted", "width": 1.6, "color": "#F2C744"},
    {"category": "报警联锁关系", "lineStyle": "dashed", "width": 2.2, "color": "#F2557A"},
    {"category": "工段衔接", "lineStyle": "solid", "width": 3.0, "color": "#4C8DFF"},
    {"category": "未匹配关系", "lineStyle": "dashed", "width": 1.2, "color": "#6B7A90"},
]

# 被视为“因果关系”的关系大类（需求 19.9）。原始值不修改，仅用于前端归组。
CAUSAL_CATEGORIES = {"因果关系", "影响关系", "质量关系"}

MATCH_STATUS_MATCHED = "MATCHED"
MATCH_STATUS_UNMATCHED = "UNMATCHED"
