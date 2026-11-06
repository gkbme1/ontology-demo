"""文档提取：工序相关的文档，以及从文档中提取进本体的对象（留痕可追溯）。

两类文档：
- 规程类文档（docs/source-docs/*.md）：如 SOP-S11-ALARM-001（模拟规程），提取出处置卡、可能原因、处置步骤；
- 数据源文档（data/source/*.xlsx）：点表、工业关系、工艺限值、规则、处置规程，统计本工序从中提取了多少条。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.v2.context import AppContext

ROOT = Path(__file__).resolve().parents[2]
DOC_DIR = ROOT / "docs" / "source-docs"

# 文档登记：文档编号 → 适用工段、说明
REGISTRY = [
    {"id": "SOP-S11-ALARM-001", "file": "SOP-S11-ALARM-001.md", "title": "6-APA 酶法水解工段异常报警及处置操作规程",
     "type": "报警处置规程", "areaCodes": ["S11"], "status": "模拟规程·待企业SOP确认",
     "note": "依据 6-APA 本体编制的模拟规程，非企业正式 SOP"},
]


def _doc_meta(doc: dict[str, Any]) -> dict[str, Any]:
    path = DOC_DIR / doc["file"]
    text = path.read_text("utf-8") if path.exists() else ""
    headings = [{"level": len(m.group(1)), "text": m.group(2).strip()}
                for m in re.finditer(r"^(#{1,3})\s+(.+)$", text, re.M)]
    return {**doc, "exists": path.exists(), "headings": headings, "size": len(text)}


def for_op(ctx: AppContext, op_id: str) -> dict[str, Any]:
    return {**for_scope(ctx, [op_id]), "opId": op_id}


def for_scope(ctx: AppContext, op_ids: list[str]) -> dict[str, Any]:
    """一组工序（空 = 全车间）的文档与数据源提取统计。"""
    h = ctx.hierarchy
    op_ids = op_ids or list(h.ops)
    codes = {c for o in op_ids for c in h.ops[o]["areaCodes"]}
    equipment = {e for o in op_ids for e in h.op_equipment(o)}
    groups = {g for o in op_ids for g in h.op_groups.get(o, [])}
    docs = []
    for doc in REGISTRY:
        if not codes & set(doc["areaCodes"]):
            continue
        meta = _doc_meta(doc)
        cards = [c for c in ctx.store.procedures.cards.values() if (c.get("area") or {}).get("text") in doc["areaCodes"]]
        card_ids = {c["id"] for c in cards}
        phen = [p for p in ctx.phen.phenomena.values()
                if any(cid in str((p.get("source") or {}).get("ref", "")) for cid in card_ids)
                and ((p.get("anchor") or {}).get("id") in equipment | groups)]
        meta["extracted"] = {
            "procedures": [{"id": c["id"], "name": c["name"], "level": (c.get("trigger") or {}).get("level"),
                            "causes": len(c.get("causes") or []), "steps": len(c.get("steps") or [])} for c in cards],
            "phenomena": [{"id": p["id"], "name": p["name"], "anchor": (p.get("anchor") or {}).get("name")} for p in phen],
        }
        docs.append(meta)

    tags = [t for e in equipment for t in ctx.tags_of_equipment.get(e, [])]
    rel_rows = [r for r in ctx.store.relations.relations if r.get("area") and
                any(ctx.store.dcs.areas.get(f"area-{c}", {}).get("name") == r.get("area") for c in codes)]
    limits = [l for l in ctx.limits.values() if any(ctx.store.dcs.areas.get(f"area-{c}", {}).get("name") == l.get("area") for c in codes)]
    sources = [
        {"file": "6APA_DCS.xlsx", "sheet": "DCS点位明细", "what": "设备与测点", "count": len(tags),
         "detail": f"{len(equipment)} 台设备、{len(tags)} 个测点"},
        {"file": "6APA_工业关系.xlsx", "sheet": "关系明细", "what": "本体关系", "count": len(rel_rows),
         "detail": "按工段统计（同工段的其他工序共享）"},
        {"file": "6APA_工艺限值.xlsx", "sheet": "工艺限值", "what": "参数约束", "count": len(limits), "detail": "按工段统计"},
        {"file": "6APA_处置规程.xlsx", "sheet": "处置卡", "what": "处置卡",
         "count": sum(1 for c in ctx.store.procedures.cards.values() if (c.get("area") or {}).get("text") in codes),
         "detail": "按工段统计"},
    ]
    return {"opIds": op_ids, "documents": docs, "sources": sources}


def read(doc_id: str) -> dict[str, Any]:
    doc = next((d for d in REGISTRY if d["id"] == doc_id), None)
    if not doc:
        raise LookupError(doc_id)
    path = DOC_DIR / doc["file"]
    return {**_doc_meta(doc), "content": path.read_text("utf-8") if path.exists() else ""}
