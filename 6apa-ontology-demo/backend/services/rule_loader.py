"""规则数据导入层（需求文档第十三章）。

规则来自独立规则 Excel / 规则文件，绝不从参数名称自动生成。
规则文件不存在时返回空集合，前端显示空状态，不得出现虚构规则。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from backend.services.excel_utils import read_sheet

from backend.ontology import identifiers as ids
from backend.ontology.models import SOURCE_RULE, Provenance

SHEET_RULES = "规则明细"

RULE_COLUMNS = [
    "ruleId",
    "name",
    "appliesToType",
    "appliesTo",
    "area",
    "condition",
    "logic",
    "threshold",
    "conclusion",
    "severity",
    "description",
]

RULE_FIELD_LABELS = [
    "规则编号 (Rule ID)",
    "规则名称 (Rule Name)",
    "适用对象类型 (Applies To Type)",
    "适用对象 (Applies To)",
    "适用工段 (Area)",
    "条件 (Condition)",
    "逻辑 (Logic)",
    "阈值 (Threshold)",
    "推理结论 (Conclusion)",
    "严重程度 (Severity)",
    "规则说明 (Description)",
]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


class RuleDataset:
    def __init__(self, file_name: str | None) -> None:
        self.file = file_name
        self.available = file_name is not None
        self.rules: list[dict[str, Any]] = []
        self.issues: list[dict[str, Any]] = []
        self.load_stats: dict[str, Any] = {}


def load_rules(path: str | Path | None) -> RuleDataset:
    if path is None:
        return RuleDataset(None)
    path = Path(path)
    if not path.exists():
        return RuleDataset(None)

    ds = RuleDataset(path.name)
    try:
        raw = read_sheet(path, SHEET_RULES, header=0)
    except ValueError:
        ds.issues.append(
            {
                "severity": "error",
                "check": "规则文件 Sheet 缺失",
                "detail": f"未找到 Sheet「{SHEET_RULES}」",
                "source": {"file": ds.file},
            }
        )
        return ds

    raw.columns = RULE_COLUMNS[: len(raw.columns)]
    for i, row in enumerate(raw.itertuples(index=False), start=2):
        rec = {k: _clean(v) for k, v in zip(RULE_COLUMNS, row)}
        if not rec.get("ruleId") and not rec.get("name"):
            continue
        rec["id"] = ids.rule_id(rec.get("ruleId") or "", rec.get("name") or "")
        rec["sourceType"] = SOURCE_RULE
        rec["source"] = Provenance(ds.file, SHEET_RULES, i).to_dict()
        ds.rules.append(rec)

    ds.load_stats = {
        "file": ds.file,
        "sheets": [{"sheet": SHEET_RULES, "rows": len(raw), "validRows": len(ds.rules)}],
        "ruleCount": len(ds.rules),
    }
    return ds
