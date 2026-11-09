"""设备设计参数（材质、容积、高度等固定参数）：读 data/config/设备设计参数.xlsx。

设备先按设备名称、再按设备组声明的设备类型命中第一个模板；值按 设备 > 所属设备组 取，未填显示「待补充」。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / "data" / "config" / "设备设计参数.xlsx"


class DesignParams:
    def __init__(self, path: Path = FILE) -> None:
        self.templates: list[dict[str, Any]] = []
        self.values: dict[tuple[str, str], dict[str, Any]] = {}
        self.available = path.exists()
        if not self.available:
            return
        wb = load_workbook(path, read_only=True, data_only=True)
        order: dict[str, dict[str, Any]] = {}
        for row in list(wb["参数模板"].iter_rows(min_row=2, values_only=True)):
            name, kw, param, unit, note = (list(row) + [None] * 5)[:5]
            if not name or not param:
                continue
            t = order.setdefault(name, {"name": name, "keywords": [k.strip() for k in str(kw or "").split("、") if k.strip()],
                                        "params": []})
            t["params"].append({"name": param, "unit": unit or "", "note": note or ""})
        self.templates = list(order.values())
        for row in wb["参数值"].iter_rows(min_row=2, values_only=True):
            obj, param, value, basis, status = (list(row) + [None] * 5)[:5]
            if obj and param and value not in (None, ""):
                self.values[(str(obj).strip(), str(param).strip())] = {"value": value, "basis": basis or "", "status": status or ""}

    def template_for(self, etype: str, name: str) -> dict[str, Any] | None:
        for text in (name, etype):  # 先看设备名称（组里混有泵、罐），再看设备组声明的类型
            if not text:
                continue
            for t in self.templates:
                if any(k in text for k in t["keywords"]):
                    return t
        return None

    def for_object(self, name: str, etype: str, group_name: str | None = None) -> list[dict[str, Any]]:
        t = self.template_for(etype, name)
        if not t:
            return []
        out = []
        for p in t["params"]:
            v = self.values.get((name, p["name"])) or (self.values.get((group_name, p["name"])) if group_name else None)
            out.append({
                "group": "设计参数", "name": p["name"], "valueType": p["unit"] or "文本", "links": [],
                "value": v["value"] if v else None, "pending": not v,
                "description": p["note"],
                "note": (f"{v['basis']}（{v['status']}）" if v and (v["basis"] or v["status"]) else "") +
                        ("" if not v or (name, p["name"]) in self.values else f" 取自设备组 {group_name}"),
                "source": f"设备设计参数.xlsx · 模板「{t['name']}」",
            })
        return out
