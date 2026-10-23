"""人工对象映射表导入层（需求文档 9.3 第三优先级）。

关系 Excel 使用工艺抽象名称，DCS 点表使用现场位号命名。
当两者名称不一致时，通过独立的映射 Excel 维护对应关系，
而不是由系统进行模糊猜测。文件缺失时映射为空，不影响其余功能。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from backend.services.excel_utils import read_sheet

from backend.ontology.models import SOURCE_MAPPING, Provenance

SHEET_MAPPING = "对象映射"

MAPPING_COLUMNS = [
    "relationEntity",
    "relationEntityType",
    "relationArea",
    "ontologyObjectType",
    "ontologyObjectName",
    "ontologyObjectUri",
    "parameterName",
    "confidence",
    "status",
    "note",
]

MAPPING_FIELD_LABELS = [
    "关系对象语义名称 (Relation Entity)",
    "关系对象类型 (Relation Entity Type)",
    "关系所属工段 (Relation Area)",
    "标准本体对象类型 (Ontology Object Type)",
    "标准本体对象名称 (Ontology Object Name)",
    "本体对象标识 (OWL Subject URI / Area)",
    "本体参数语义名称 (Parameter Name)",
    "置信度 (Confidence)",
    "确认状态 (Status)",
    "映射说明 (Mapping Note)",
]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


class MappingDataset:
    def __init__(self, file_name: str | None) -> None:
        self.file = file_name
        self.available = file_name is not None
        self.entries: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.load_stats: dict[str, Any] = {}

    def for_entity(self, entity_type: str | None, entity_name: str) -> list[dict[str, Any]]:
        return [
            e
            for e in self.entries
            if e["relationEntity"] == entity_name
            and (e["relationEntityType"] in (None, entity_type) or entity_type is None)
        ]


def load_mapping(path: str | Path | None) -> MappingDataset:
    if path is None:
        return MappingDataset(None)
    path = Path(path)
    if not path.exists():
        return MappingDataset(None)

    ds = MappingDataset(path.name)
    raw = read_sheet(path, SHEET_MAPPING, header=0)
    raw.columns = MAPPING_COLUMNS[: len(raw.columns)]

    for i, row in enumerate(raw.itertuples(index=False), start=2):
        rec = {k: _clean(v) for k, v in zip(MAPPING_COLUMNS, row)}
        if not rec.get("relationEntity") or not rec.get("ontologyObjectType"):
            if any(rec.values()):
                ds.issues.append(
                    {
                        "severity": "error",
                        "check": "映射表必填字段为空",
                        "detail": "关系对象语义名称或标准本体对象类型为空",
                        "source": Provenance(ds.file, SHEET_MAPPING, i).to_dict(),
                    }
                )
            continue
        rec["sourceType"] = SOURCE_MAPPING
        rec["source"] = Provenance(ds.file, SHEET_MAPPING, i).to_dict()
        ds.entries.append(rec)

    ds.load_stats = {
        "file": ds.file,
        "sheets": [
            {
                "sheet": SHEET_MAPPING,
                "rows": len(raw),
                "validRows": len(ds.entries),
                "errorRows": len(ds.issues),
            }
        ],
        "mappingCount": len(ds.entries),
        "pendingCount": len([e for e in ds.entries if e.get("status") != "已确认"]),
    }
    return ds
