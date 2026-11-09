"""调查知识：原因分类（人机料法环）与权重、化验项目、判定规则、漂移判定口径。

数据源 data/source/调查知识.xlsx（backend/tools/build_investigation_knowledge.py 生成预填版），五个工作表：
- 「原因分类」：人 / 机 / 料 / 法 / 环 各自按对象类型、名称关键词怎么归类，默认权重；
- 「原因权重」：具体原因对象的分类与权重（车间主任提出「各原因可设权重」）；
- 「化验项目」：化验项目对应哪个工艺属性、哪些罐、对比哪个在线位号、怎么对齐时间；
- 「判定规则」：如 BF-05「在线与化验 pH 差值恒定或扩大判异常」的对象、数据、判据、阈值、适用阶段；
- 「漂移口径」：限值以内缓慢偏离的判定方法与参数。

定义在本体，执行在 Agent：本体只登记分类、权重、规则与口径，取数、比对、统计都由 Agent 的固定程序完成。
全部预填条目标「草案·待工艺确认」。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.ontology.models import Provenance

KNOWLEDGE_FILE_NAME = "调查知识.xlsx"
SHEET_CATEGORIES = "原因分类"
SHEET_WEIGHTS = "原因权重"
SHEET_LAB = "化验项目"
SHEET_RULES = "判定规则"
SHEET_DRIFT = "漂移口径"

CATEGORY_COLUMNS = ["分类", "名称", "说明", "匹配对象类型", "匹配关键词", "默认权重", "示例", "状态"]
WEIGHT_COLUMNS = ["原因对象", "分类", "权重", "依据", "修改人", "状态"]
LAB_COLUMNS = ["项目编码", "项目名称", "对应工艺属性", "适用设备组", "采样点", "取样阶段", "单位", "对比在线位号",
               "对齐方式", "对齐窗口(分钟)", "来源系统", "说明", "状态"]
RULE_COLUMNS = ["规则编号", "规则名称", "对象", "适用设备组", "在线位号", "对比数据", "判据", "恒定偏差阈值",
                "扩大阈值(每天)", "最少样本数", "适用阶段", "原因分类", "依据", "状态"]
DRIFT_COLUMNS = ["口径编号", "适用对象", "方法", "基线", "参数", "说明", "状态"]

CATEGORY_ORDER = ("人", "机", "料", "法", "环")
DEFAULT_CATEGORY = "法"
_SPLIT = re.compile(r"[、,，;；\s]+")


def _text(v: Any) -> str:
    t = "" if v is None else str(v).strip()
    return "" if t.lower() == "nan" else t


def _num(v: Any, default: float | None = None) -> float | None:
    try:
        return float(_text(v)) if _text(v) else default
    except ValueError:
        return default


class InvestigationKnowledge:
    def __init__(self, file_name: str) -> None:
        self.file = file_name
        self.available = False
        self.categories: list[dict[str, Any]] = []
        self.weights: dict[str, dict[str, Any]] = {}
        self.lab_items: list[dict[str, Any]] = []
        self.rules: list[dict[str, Any]] = []
        self.drift: list[dict[str, Any]] = []
        self.load_stats: dict[str, Any] = {"file": file_name, "sheets": []}

    # ---------------------------------------------------------------- 原因分类
    def classify(self, name: str, entity_type: str | None = None) -> dict[str, Any]:
        """原因对象 → 人机料法环。顺序：原因权重表里点名的 → 对象类型 → 名称关键词 → 默认归「法」。"""
        override = self.weights.get(name)
        by_key = {c["key"]: c for c in self.categories}
        if override and override.get("category") in by_key:
            cat = by_key[override["category"]]
            return self._view(cat, "原因权重表点名", override)
        for cat in self.categories:
            if entity_type and entity_type in cat["types"]:
                return self._view(cat, f"对象类型「{entity_type}」", override)
        for cat in self.categories:
            hit = next((k for k in cat["keywords"] if k and k.lower() in (name or "").lower()), None)
            if hit:
                return self._view(cat, f"名称含「{hit}」", override)
        cat = by_key.get(DEFAULT_CATEGORY) or {"key": DEFAULT_CATEGORY, "name": "方法", "weight": 1.0}
        return self._view(cat, "未匹配到分类规则，按工艺方法（法）归类", override)

    @staticmethod
    def _view(cat: dict[str, Any], reason: str, override: dict[str, Any] | None) -> dict[str, Any]:
        weight = override["weight"] if override and override.get("weight") is not None else cat.get("weight", 1.0)
        out = {"category": cat["key"], "categoryName": cat.get("name"), "reason": reason, "weight": weight,
               "weightBasis": (override or {}).get("basis") or ("分类默认权重" if not override else "")}
        if override:
            out["weightStatus"] = override.get("status")
        return out

    def view(self) -> dict[str, Any]:
        return {"available": self.available, "source": self.file, "categories": self.categories,
                "weights": list(self.weights.values()), "labItems": self.lab_items, "rules": self.rules,
                "drift": self.drift}


def load_knowledge(path: Path, store: Any) -> InvestigationKnowledge:
    kn = InvestigationKnowledge(path.name)
    if not path.exists():
        return kn
    import pandas as pd

    kn.available = True
    sheets: dict[str, list[dict[str, Any]]] = {}
    for sheet in (SHEET_CATEGORIES, SHEET_WEIGHTS, SHEET_LAB, SHEET_RULES, SHEET_DRIFT):
        try:
            sheets[sheet] = pd.read_excel(path, sheet_name=sheet, dtype=str).fillna("").to_dict("records")
        except ValueError:
            sheets[sheet] = []

    def src(sheet: str, i: int) -> dict[str, Any]:
        return Provenance(path.name, sheet, i + 2).to_dict()

    for i, r in enumerate(sheets[SHEET_CATEGORIES]):
        if _text(r.get("分类")):
            kn.categories.append({
                "key": _text(r.get("分类")), "name": _text(r.get("名称")), "description": _text(r.get("说明")),
                "types": [t for t in _SPLIT.split(_text(r.get("匹配对象类型"))) if t],
                "keywords": [t for t in _SPLIT.split(_text(r.get("匹配关键词"))) if t],
                "weight": _num(r.get("默认权重"), 1.0), "examples": _text(r.get("示例")),
                "status": _text(r.get("状态")) or "草案", "source": src(SHEET_CATEGORIES, i),
            })
    order = {k: n for n, k in enumerate(CATEGORY_ORDER)}
    kn.categories.sort(key=lambda c: order.get(c["key"], 99))
    for i, r in enumerate(sheets[SHEET_WEIGHTS]):
        name = _text(r.get("原因对象"))
        if name:
            kn.weights[name] = {"name": name, "category": _text(r.get("分类")), "weight": _num(r.get("权重")),
                                "basis": _text(r.get("依据")), "editor": _text(r.get("修改人")),
                                "status": _text(r.get("状态")) or "草案", "source": src(SHEET_WEIGHTS, i)}
    for i, r in enumerate(sheets[SHEET_LAB]):
        if _text(r.get("项目编码")):
            kn.lab_items.append({
                "code": _text(r.get("项目编码")), "name": _text(r.get("项目名称")), "property": _text(r.get("对应工艺属性")),
                "group": _text(r.get("适用设备组")), "samplePoint": _text(r.get("采样点")), "stage": _text(r.get("取样阶段")),
                "unit": _text(r.get("单位")), "onlineTag": _text(r.get("对比在线位号")), "alignment": _text(r.get("对齐方式")),
                "alignMinutes": _num(r.get("对齐窗口(分钟)"), 2.0), "system": _text(r.get("来源系统")),
                "description": _text(r.get("说明")), "status": _text(r.get("状态")) or "草案", "source": src(SHEET_LAB, i),
            })
    for i, r in enumerate(sheets[SHEET_RULES]):
        if _text(r.get("规则编号")):
            kn.rules.append({
                "id": _text(r.get("规则编号")), "name": _text(r.get("规则名称")), "object": _text(r.get("对象")),
                "group": _text(r.get("适用设备组")), "onlineTag": _text(r.get("在线位号")), "compareWith": _text(r.get("对比数据")),
                "criterion": _text(r.get("判据")), "constantThreshold": _num(r.get("恒定偏差阈值")),
                "growthThresholdPerDay": _num(r.get("扩大阈值(每天)")), "minSamples": int(_num(r.get("最少样本数"), 4) or 4),
                "phases": [p for p in _SPLIT.split(_text(r.get("适用阶段"))) if p], "category": _text(r.get("原因分类")),
                "basis": _text(r.get("依据")), "status": _text(r.get("状态")) or "草案", "source": src(SHEET_RULES, i),
            })
    for i, r in enumerate(sheets[SHEET_DRIFT]):
        if _text(r.get("口径编号")):
            params = {}
            for part in _SPLIT.split(_text(r.get("参数"))):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k.strip()] = _num(v, None) if _num(v, None) is not None else v.strip()
            kn.drift.append({"id": _text(r.get("口径编号")), "object": _text(r.get("适用对象")), "method": _text(r.get("方法")),
                             "baseline": _text(r.get("基线")), "params": params, "description": _text(r.get("说明")),
                             "status": _text(r.get("状态")) or "草案", "source": src(SHEET_DRIFT, i)})
    kn.load_stats = {
        "file": path.name,
        "sheets": [{"sheet": s, "rows": len(rows), "validRows": len(rows)} for s, rows in sheets.items()],
        "categoryCount": len(kn.categories), "weightCount": len(kn.weights), "labItemCount": len(kn.lab_items),
        "ruleCount": len(kn.rules), "driftCount": len(kn.drift),
    }
    return kn


# ------------------------------------------------------------------ 接口


def cause_profile(store: Any, q: dict[str, Any]) -> dict[str, Any]:
    """一组候选原因的人机料法环分类与权重。ids= 关系对象 ID（逗号分隔），names= 名称（如「人为修改温度设定值」）。"""
    kn = store.investigation
    out = []
    for oid in [x for x in (q.get("ids") or "").split(",") if x.strip()]:
        entity = store.relations.entities.get(oid.strip())
        if not entity:
            out.append({"id": oid.strip(), "notFound": True})
            continue
        out.append({"id": entity["id"], "name": entity["name"], "type": entity.get("type"),
                    **kn.classify(entity["name"], entity.get("type"))})
    for name in [x for x in re.split(r"[,，]", q.get("names") or "") if x.strip()]:
        out.append({"id": None, "name": name.strip(), **kn.classify(name.strip(), q.get("type") or None)})
    return {"items": out, "categories": [{k: c[k] for k in ("key", "name", "weight", "description")} for c in kn.categories],
            "available": kn.available, "source": kn.file,
            "note": "分类与权重定义在本体（调查知识.xlsx），草案待工艺确认；候选方向的证据与排序由 Agent 计算。"}


def _resolve_tpl(tpl: str, code: str, names: list[str]) -> dict[str, Any] | None:
    from backend.services.process_context import resolve_template

    return resolve_template(names, tpl, code) if tpl else None


def object_rules(store: Any, object_id: str) -> dict[str, Any]:
    """设备实例（如水解罐C）适用的判定规则与化验项目，{x} 换成本台罐号；也可传工艺属性名称 / ID 查规则。"""
    from backend.services.process_context import _UNIT_CODE, _equipment, unit_tag_names

    kn = store.investigation
    entity = store.relations.entities.get(object_id)
    if entity or not object_id.startswith(("equip-", ":")) and not store.dcs.equipment_by_name(object_id):
        name = entity["name"] if entity else object_id
        rules = [r for r in kn.rules if r["object"] == name]
        labs = [x for x in kn.lab_items if x["property"] == name]
        return {"scope": {"objectId": entity["id"] if entity else None, "objectName": name, "kind": "property"},
                "rules": rules, "labItems": labs, "available": kn.available}
    equip = _equipment(store, object_id)
    group = store.dcs.equipment_groups[equip["equipmentGroupId"]]
    m = _UNIT_CODE.search(equip["name"])
    code = m.group(1) if m else ""
    names = unit_tag_names(store, equip)
    rules = []
    for r in kn.rules:
        if r["group"] and r["group"] != group["name"]:
            continue
        rules.append({**r, "onlineTagResolved": _resolve_tpl(r["onlineTag"], code, names),
                      "compareTagResolved": _resolve_tpl(r["compareWith"], code, names) if "{x}" in r["compareWith"] else None})
    labs = []
    for x in kn.lab_items:
        if x["group"] and x["group"] != group["name"]:
            continue
        labs.append({**x, "onlineTagResolved": _resolve_tpl(x["onlineTag"], code, names),
                     "samplePointResolved": x["samplePoint"].replace("{x}", code)})
    return {"scope": {"objectId": equip["id"], "objectName": equip["name"], "group": group["name"], "kind": "equipment"},
            "unitCode": code, "rules": rules, "labItems": labs, "available": kn.available}
