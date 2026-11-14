"""实例间连接：把工业关系表里「设备组 ↔ 设备组」的拓扑落到「实例 ↔ 实例」。

工业关系表按流程图粒度整理，物理拓扑写在设备组之间（水解反应釜组 ← RB储罐A/B），没有逐台画管线。
本体分三层：类（设备类型）、设备组（集合）、实例。组间关系是组层面的事实，不能原样当成实例的关系；
落到实例要先确定连接方式：

- 单台直连：两边各只有一台主体实例；
- 按台号：两组台号对得上（氨水计量罐A → 水解罐A）；
- 汇管：一对多或多对多经汇管 / 母管相连（RB储罐A、B → 水解罐A～K），每台都与对方每台相连；
- 指定：只有指定的几对相连，在「指定连接」列写 A→A；B→C；
- 不展开：只保留组间关系。
物料 / 公用介质与设备组的关系，落到组内每台主体实例。

连接方式写在 data/source/6APA_实例连接.xlsx 的「组连接方式」工作表（backend/tools/build_instance_links.py 生成，
可改「连接方式」「指定连接」两列）；表不存在时按规则自动判断。由此推出的实例关系都标「推导」，
汇管与对不全的按台号标「待确认」，和工业关系表里原本写好的实例关系区分开。

主体实例：设备组里真正属于这一组的设备。设备组成员清单里还挂着附属泵、阀等（如丁酯罐组里有丁酯泵），
优先取声明的实例（水解罐A～K），没有声明实例时取与组同名的那台，都没有则该组不展开。
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.services.equipment_merge import _norm, _split_instance

LINK_FILE_NAME = "6APA_实例连接.xlsx"
SHEET_MODES = "组连接方式"
SHEET_LINKS = "实例连接（推导结果）"
MODE_COLUMNS = ["关系编号", "关系类别", "主体", "谓词", "客体", "主体实例", "客体实例", "自动判断", "连接方式", "指定连接",
                "说明", "依据"]

MODE_DIRECT = "单台直连"
MODE_BY_NUMBER = "按台号"
MODE_HEADER = "汇管"
MODE_SPECIFIED = "指定"
MODE_NONE = "不展开"
MODE_MATERIAL = "物料到各台"
MODES = (MODE_DIRECT, MODE_BY_NUMBER, MODE_HEADER, MODE_SPECIFIED, MODE_NONE, MODE_MATERIAL)

STATUS_DERIVED = "推导"
STATUS_PENDING = "推导·待确认"

EQUIPMENT_TYPES = {"生产设备"}
MATERIAL_TYPES = {"物料流股", "公用介质"}
LINK_CATEGORIES = {"物理拓扑关系"}
CONTROL_PREDICATES = {"被控制"}


def principal_members(store: Any, group: dict[str, Any]) -> list[dict[str, Any]]:
    """设备组的主体实例（见模块说明）。"""
    dcs = store.dcs
    members = [dcs.equipment[e] for e in group["equipmentIds"]
               if e in dcs.equipment and dcs.equipment[e].get("equipmentGroupId") == group["id"]
               and dcs.equipment[e].get("nature", "实例") == "实例"]
    declared = [i for i in group.get("instances") or [] if i]
    picked = [m for m in members if m["name"] in declared]
    if picked:
        return sorted(picked, key=lambda m: m["name"])
    gname = _norm(group["name"])
    same = [m for m in members if _norm(m["name"]) == gname]
    if same:
        return same[:1]
    # 按设备类型的中心词取：储罐 → 名称含「罐」，碟片离心机 → 含「机」；类型不是泵时排除附属泵
    etype = group.get("equipmentType") or ""
    head = etype[-1] if etype else ""
    if not head:
        return []
    picked = [m for m in members if head in m["name"] and ("泵" in etype or not m["name"].endswith("泵"))]
    return sorted(picked, key=lambda m: m["name"])


def _letter(name: str) -> str | None:
    base, code = _split_instance(name)
    return code[-1].upper() if code and code[-1].isalpha() else None


def _auto_mode(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> tuple[str, str]:
    if not a or not b:
        side = "主体" if not a else "客体"
        return MODE_NONE, f"{side}设备组没有可确定的主体实例"
    if len(a) == 1 and len(b) == 1:
        return MODE_DIRECT, "两边各一台"
    if len(a) > 1 and len(b) > 1:
        la = {_letter(m["name"]) for m in a} - {None}
        lb = {_letter(m["name"]) for m in b} - {None}
        common = la & lb
        # 两边大部分台号都能对上才算按台号（RB储罐A/B 对水解罐A～K 只对上 A、B，是汇管）
        if len(common) >= 2 and len(common) >= 0.6 * max(len(a), len(b)):
            return MODE_BY_NUMBER, f"台号对得上 {len(common)} 对（{''.join(sorted(common))}）"
    return MODE_HEADER, f"{len(a)} 台对 {len(b)} 台，按汇管处理"


def _pairs(mode: str, a: list[dict[str, Any]], b: list[dict[str, Any]], specified: str) -> tuple[list[tuple], list[str]]:
    """按连接方式给出实例对，及对不上的说明。"""
    if mode in (MODE_DIRECT, MODE_HEADER, MODE_MATERIAL):
        return [(x, y) for x in a for y in b], []
    if mode == MODE_BY_NUMBER:
        by_b = {_letter(m["name"]): m for m in b}
        pairs, missing = [], []
        for x in a:
            y = by_b.get(_letter(x["name"]))
            if y:
                pairs.append((x, y))
            else:
                missing.append(x["name"])
        matched_b = {id(y) for _, y in pairs}
        missing += [y["name"] for y in b if id(y) not in matched_b]
        return pairs, missing
    if mode == MODE_SPECIFIED:
        name_a = {m["name"]: m for m in a}
        name_b = {m["name"]: m for m in b}
        pairs, bad = [], []
        for item in re.split(r"[；;，,\s]+", specified or ""):
            if "→" not in item:
                continue
            left, right = (s.strip() for s in item.split("→", 1))
            x = name_a.get(left) or next((m for m in a if _letter(m["name"]) == left.upper()), None)
            y = name_b.get(right) or next((m for m in b if _letter(m["name"]) == right.upper()), None)
            if x and y:
                pairs.append((x, y))
            else:
                bad.append(item)
        return pairs, bad
    return [], []


class InstanceLinks:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []          # 每条组间关系一行：连接方式与结果
        self.by_equipment: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.available = False
        self.file = LINK_FILE_NAME
        self.load_stats: dict[str, Any] = {"file": LINK_FILE_NAME, "sheets": []}


def _load_overrides(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    import pandas as pd

    try:
        df = pd.read_excel(path, sheet_name=SHEET_MODES, dtype=str).fillna("")
    except ValueError:
        return {}
    return {str(r["关系编号"]).strip(): {k: str(v).strip() for k, v in r.items()} for r in df.to_dict("records")
            if str(r.get("关系编号", "")).strip()}


def build(store: Any, path: Path | None = None) -> InstanceLinks:
    """按组间关系与连接方式推出实例间连接。path 给定时读取其中人工改过的连接方式。"""
    out = InstanceLinks()
    overrides = _load_overrides(path) if path else {}
    out.available = bool(path and path.exists())
    group_by_name = {g["name"]: g for g in store.dcs.equipment_groups.values()}
    principal_cache: dict[str, list[dict[str, Any]]] = {}

    def principal(name: str) -> list[dict[str, Any]] | None:
        group = group_by_name.get(name)
        if not group:
            return None
        if group["id"] not in principal_cache:
            principal_cache[group["id"]] = principal_members(store, group)
        return principal_cache[group["id"]]

    for rel in store.relations.relations:
        cat, pred = rel.get("category"), rel.get("predicate")
        st, ot = rel.get("subjectType"), rel.get("objectType")
        if not (cat in LINK_CATEGORIES or pred in CONTROL_PREDICATES):
            continue
        if st not in EQUIPMENT_TYPES and ot not in EQUIPMENT_TYPES:
            continue
        a_names = principal(rel["subjectEntity"]) if st in EQUIPMENT_TYPES else None
        b_names = principal(rel["objectEntity"]) if ot in EQUIPMENT_TYPES else None
        material_side = None
        if st in EQUIPMENT_TYPES and ot in EQUIPMENT_TYPES:
            auto, why = _auto_mode(a_names or [], b_names or [])
        else:
            material_side = "subject" if st not in EQUIPMENT_TYPES else "object"
            members = b_names if material_side == "subject" else a_names
            auto, why = (MODE_MATERIAL, "物料 / 介质落到组内每台") if members else (MODE_NONE, "设备组没有可确定的主体实例")
        code = rel.get("relationCode") or rel["id"]
        ov = overrides.get(code, {})
        mode = ov.get("连接方式") if ov.get("连接方式") in MODES else auto
        specified = ov.get("指定连接", "")

        links: list[dict[str, Any]] = []
        missing: list[str] = []
        if material_side is None:
            pairs, missing = _pairs(mode, a_names or [], b_names or [], specified)
            for x, y in pairs:
                links.append({"from": x, "to": y})
        elif mode == MODE_MATERIAL:
            members = b_names if material_side == "subject" else a_names
            other = {"id": (rel.get("subject") if material_side == "subject" else rel.get("object") or {}).get("id"),
                     "name": rel["subjectEntity"] if material_side == "subject" else rel["objectEntity"], "material": True}
            for m in members or []:
                links.append({"from": other, "to": m} if material_side == "subject" else {"from": m, "to": other})

        if mode in (MODE_HEADER, MODE_SPECIFIED) or (mode == MODE_BY_NUMBER and missing) or mode == MODE_NONE:
            status = STATUS_PENDING
        else:
            status = STATUS_DERIVED
        if ov.get("连接方式") in MODES and ov.get("连接方式") != auto:
            status = "人工指定"
        group_text = f"{rel['subjectEntity']} {pred} {rel['objectEntity']}"
        row = {
            "relationId": rel["id"], "relationCode": code, "category": cat, "predicate": pred,
            "subject": rel["subjectEntity"], "object": rel["objectEntity"],
            "subjectInstances": [m["name"] for m in a_names or []], "objectInstances": [m["name"] for m in b_names or []],
            "auto": auto, "autoReason": why, "mode": mode, "specified": specified, "status": status,
            "missing": missing, "mechanism": rel.get("domainDescription") or "", "linkCount": len(links),
        }
        out.rows.append(row)
        for link in links:
            view = {
                "relationId": rel["id"], "relationCode": code, "category": cat, "predicate": pred,
                "from": link["from"]["name"], "fromId": link["from"].get("id"),
                "to": link["to"]["name"], "toId": link["to"].get("id"),
                "mode": mode, "status": status, "groupRelation": group_text,
                "mechanism": rel.get("domainDescription") or "",
            }
            for side in ("from", "to"):
                if not link[side].get("material") and link[side].get("id"):
                    out.by_equipment[link[side]["id"]].append(view)
    out.load_stats = {
        "file": LINK_FILE_NAME,
        "sheets": [{"sheet": SHEET_MODES, "rows": len(overrides), "validRows": len(overrides)}],
        "groupRelationCount": len(out.rows),
        "instanceLinkCount": sum(r["linkCount"] for r in out.rows),
        "byMode": {m: sum(1 for r in out.rows if r["mode"] == m) for m in MODES},
        "pendingCount": sum(1 for r in out.rows if r["status"] == STATUS_PENDING),
    }
    return out
