"""全局搜索（需求 ONTO-SR-SW-078）。

- 范围：工艺段、工序（画面）、设备组、设备、位号、现象 / 工况，以及工艺参数、物料流股、公用介质、质量指标（在全局图谱中定位）；
- 匹配：名称 / 编码包含关键字，位号前缀匹配，拼音首字母匹配（如 sjg → 水解罐）；
- 结果带类型与所属位置，前端按类型分组显示。

search_index() 不含现象（现象可在线编辑，单文件版在浏览器里现算），单文件版导出同一份索引。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from backend.v2.context import AppContext

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:  # 未安装时只按中文匹配
    lazy_pinyin = None  # type: ignore[assignment]

KIND_ORDER = ["segment", "op", "group", "equipment", "tag", "phenomenon", "condition", "parameter", "stream", "utility", "quality"]
GRAPH_KINDS = {"工艺参数": "parameter", "物料流股": "stream", "公用介质": "utility", "质量指标": "quality"}


@lru_cache(maxsize=20000)
def initials(text: str) -> str:
    """拼音首字母（小写）；非汉字字符原样保留（小写）。"""
    if not text or lazy_pinyin is None:
        return ""
    return "".join(s[0] for s in lazy_pinyin(text, style=Style.FIRST_LETTER, errors=lambda x: list(x)) if s).lower()


def _entry(kind: str, oid: str, label: str, hint: str, **kw: Any) -> dict[str, Any]:
    return {"kind": kind, "id": oid, "label": label, "hint": hint, "py": initials(label), **kw}


def search_index(ctx: AppContext) -> list[dict[str, Any]]:
    h = ctx.hierarchy
    dcs = ctx.store.dcs
    out: list[dict[str, Any]] = []
    for seg in h.segments.values():
        out.append(_entry("segment", seg["id"], seg["name"], "工艺段", segmentId=seg["id"]))
    for op in h.ops.values():
        out.append(_entry("op", op["id"], op["name"], " / ".join(p["name"] for p in h.path(op["id"])[:2]),
                          code=op.get("screen") or "", segmentId=op["segmentId"], opId=op["id"]))
    for gid, ops in h.ops_of_group.items():
        if ops:
            out.append(_entry("group", gid, dcs.equipment_groups[gid]["name"], h.ops[ops[0]]["name"],
                              segmentId=h.ops[ops[0]]["segmentId"], opId=ops[0]))
    for eid, op_id in h.op_of_equipment.items():
        out.append(_entry("equipment", eid, dcs.equipment[eid]["name"], h.ops[op_id]["name"],
                          segmentId=h.ops[op_id]["segmentId"], opId=op_id))
    for t in dcs.tags.values():
        eid = t.get("equipmentId")
        if eid in h.op_of_equipment:
            op_id = h.op_of_equipment[eid]
            out.append({"kind": "tag", "id": eid, "label": f"{t['name']}（{t.get('rawDescription') or ''}）", "code": t["name"],
                        "hint": f"{t.get('equipmentName')} · {h.ops[op_id]['name']}", "py": "",
                        "segmentId": h.ops[op_id]["segmentId"], "opId": op_id})
    from backend.v2 import global_graph
    seen: set[str] = set()
    for n in global_graph.build(ctx)["nodes"]:
        kind = GRAPH_KINDS.get(n["type"])
        if not kind or n["id"] in seen:
            continue
        seen.add(n["id"])
        where = h.ops[n["opId"]]["name"] if n.get("opId") in h.ops else ""
        out.append(_entry(kind, n["id"], n["name"], f"{n['type']}{' · ' + where if where else ''} · 在全局图谱中定位", graph=True))
    return out


def score(entry: dict[str, Any], kw: str) -> int:
    """匹配度：0 不匹配；越大越靠前（完全相同 > 名称 / 编码包含 > 拼音首字母开头 > 拼音首字母包含）。"""
    low = kw.lower()
    label, code = entry["label"], (entry.get("code") or "").lower()
    if kw.upper() in (label.upper(), code.upper()):
        return 5
    if entry["kind"] == "tag":
        return 4 if code.startswith(low) else (3 if len(kw) >= 2 and kw in label else 0)
    if kw in label or (low and low in code) or low == entry["id"].lower():
        return 4
    if kw.isascii() and kw.isalpha() and len(kw) >= 2:
        py = entry.get("py") or ""
        if py.startswith(low):
            return 2
        if low in py:
            return 1
    return 0


def matches(entry: dict[str, Any], kw: str) -> bool:
    return score(entry, kw) > 0


def search(ctx: AppContext, keyword: str, limit: int = 80) -> dict[str, Any]:
    kw = keyword.strip()
    if not kw:
        return {"items": [], "total": 0}
    items = [{**e, "score": score(e, kw)} for e in ctx.search_index()]
    items = [e for e in items if e["score"]]
    for p in ctx.phen.phenomena.values():
        ops = ctx.phenomenon_ops(p)
        if not ops:
            continue
        e = _entry("condition" if p.get("category") == "工况" else "phenomenon", p["id"], p["name"],
                   (p.get("anchor") or {}).get("name") or "", segmentId=ctx.hierarchy.ops[ops[0]]["segmentId"], opId=ops[0],
                   anchorId=(p.get("anchor") or {}).get("id"))
        if (sc := score(e, kw)):
            items.append({**e, "score": sc})
    # 按类型分组（前端分组显示），组内按匹配度
    items.sort(key=lambda e: (KIND_ORDER.index(e["kind"]), -e["score"]))
    total = len(items)
    # 每类最多 12 条
    per: dict[str, int] = {}
    shown = []
    for e in items:
        per[e["kind"]] = per.get(e["kind"], 0) + 1
        if per[e["kind"]] <= 12:
            shown.append({k: v for k, v in e.items() if k not in ("py", "score")})
    return {"items": shown[:limit], "total": total, "counts": per}
