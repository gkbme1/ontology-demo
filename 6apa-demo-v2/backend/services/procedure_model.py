"""报警处置规程：把自然语言的操作规程整理成本体里的「处置卡」，并锚定到本体对象。

现场排查与处置依据的是报警响应卡 / 操作规程（自然语言）。本体不内置规程原文的执行逻辑，
而是把每张卡拆成结构化的几部分，并把其中提到的位号、设备、工艺量对应到本体对象：

    处置卡（报警点）── 触发位号 / 触发对象 / 关联限值 / 关联联锁
      ├─ 可能原因：类别（仪表 / 工艺 / 设备 / 操作 / 公用工程）、验证方法、验证位号、判据
      ├─ 处置步骤：阶段、岗位、动作类型、关联对象 / 位号
      ├─ 禁止操作
      └─ 后果、解除条件、汇报要点、记录要求

数据源 data/source/处置规程.xlsx（四个工作表：处置卡 / 可能原因 / 处置步骤 / 禁止操作）。
提到的对象对应不上本体时标「待确认」，不猜。验证位号已对应的原因、动作为 确认 / 查询 / 对比 且位号
已对应的步骤，标为「可自动判断」——这部分以后可由固定程序直接用本体的实时 / 历史值执行，其余是给人的指引。
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.ontology import identifiers as ids
from backend.ontology.models import Provenance

PROCEDURE_FILE_NAME = "处置规程.xlsx"
SHEET_CARDS = "处置卡"
SHEET_CAUSES = "可能原因"
SHEET_STEPS = "处置步骤"
SHEET_FORBIDDEN = "禁止操作"

CARD_COLUMNS = ["卡片编号", "卡片名称", "报警名称", "触发对象", "触发位号", "报警级别", "设定值", "单位", "关联限值",
                "所属工段", "关联设备", "关联联锁", "优先级", "允许响应时间", "报警现象·DCS", "报警现象·现场",
                "未及时处置后果", "后果关联对象", "解除条件", "汇报要点", "记录要求", "状态", "依据"]
CAUSE_COLUMNS = ["卡片编号", "序号", "原因类别", "原因描述", "关联对象", "验证方法", "验证位号", "判据", "依据"]
STEP_COLUMNS = ["卡片编号", "序号", "阶段", "岗位", "动作类型", "步骤描述", "关联对象", "关联位号", "前置条件", "依据"]
FORBIDDEN_COLUMNS = ["卡片编号", "序号", "禁止内容", "关联对象", "依据"]

CAUSE_CATEGORIES = ("仪表", "工艺", "设备", "操作", "公用工程")
PHASES = ("确认判断", "假报警处置", "真实处置", "升级上报", "恢复确认")
ROLES = ("中控主操", "中控副操", "外操", "班长", "调度", "仪表", "车间")
ACTIONS = ("确认", "查询", "对比", "联系", "现场检查", "操作", "联锁", "上报", "记录")
AUTO_ACTIONS = ("确认", "查询", "对比")  # 有已对应位号时可由程序直接用本体数据完成

ANCHOR_OK = "已对应"
ANCHOR_PENDING = "待确认"

_SPLIT = re.compile(r"[、,，;；\s]+")


def _text(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() == "nan" else text


def _items(text: str) -> list[str]:
    return [t for t in _SPLIT.split(text or "") if t]


class ProcedureSet:
    def __init__(self, file_name: str) -> None:
        self.file = file_name
        self.available = False
        self.cards: dict[str, dict[str, Any]] = {}
        self.issues: list[dict[str, Any]] = []
        self.load_stats: dict[str, Any] = {"file": file_name, "sheets": []}
        # 对象 / 位号 → 卡片（触发 / 相关）
        self.by_tag: dict[str, set[str]] = defaultdict(set)
        self.by_object: dict[str, dict[str, str]] = defaultdict(dict)
        self.by_area: dict[str, set[str]] = defaultdict(set)


# ------------------------------------------------------------------ 锚定


class Anchorer:
    """把规程里的名称对应到本体对象：位号、工艺对象、设备、设备组、工段。"""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.entity_by_name: dict[str, dict[str, Any]] = {}
        for e in store.relations.entities.values():
            self.entity_by_name.setdefault(e["name"], e)
        self.group_by_name = {g["name"]: g for g in store.dcs.equipment_groups.values()}
        self.tag_names = sorted(t["name"] for t in store.dcs.tags.values())

    def tags(self, text: str) -> list[dict[str, Any]]:
        out = []
        for token in _items(text):
            if token.endswith("*"):
                hits = [n for n in self.tag_names if n.startswith(token[:-1])]
                if hits:
                    for n in hits:
                        tag = self.store.dcs.tag_by_name(n)
                        out.append({"text": n, "kind": "tag", "id": tag["id"], "objectId": tag.get("equipmentId"),
                                    "label": tag.get("rawDescription"), "status": ANCHOR_OK})
                    continue
            tag = self.store.dcs.tag_by_name(token)
            if tag:
                out.append({"text": token, "kind": "tag", "id": tag["id"], "objectId": tag.get("equipmentId"),
                            "label": tag.get("rawDescription"), "status": ANCHOR_OK})
            else:
                out.append({"text": token, "kind": "tag", "id": None, "status": ANCHOR_PENDING})
        return out

    def objects(self, text: str) -> list[dict[str, Any]]:
        return [self.object(token) for token in _items(text)]

    def object(self, name: str) -> dict[str, Any]:
        dcs = self.store.dcs
        entity = self.entity_by_name.get(name)
        if entity:
            return {"text": name, "kind": "entity", "id": entity["id"], "type": entity["type"], "status": ANCHOR_OK}
        equips = dcs.equipment_by_name(name)
        if len(equips) == 1:
            return {"text": name, "kind": "equipment", "id": equips[0]["id"], "type": "设备", "status": ANCHOR_OK}
        group = self.group_by_name.get(name)
        if group:
            return {"text": name, "kind": "group", "id": group["id"], "type": "标准设备组", "status": ANCHOR_OK}
        aid = dcs.resolve_area(name)
        if aid:
            return {"text": name, "kind": "area", "id": aid, "type": "工段", "status": ANCHOR_OK}
        if len(equips) > 1:
            return {"text": name, "kind": "equipment", "id": None, "status": ANCHOR_PENDING,
                    "note": f"同名设备 {len(equips)} 台，需指明控制站或工段"}
        return {"text": name, "kind": "unknown", "id": None, "status": ANCHOR_PENDING}


# ------------------------------------------------------------------ 加载


def load_procedures(path: Path, store: Any) -> ProcedureSet:
    ps = ProcedureSet(path.name)
    if not path.exists():
        return ps
    import pandas as pd

    ps.available = True
    sheets = {}
    for sheet in (SHEET_CARDS, SHEET_CAUSES, SHEET_STEPS, SHEET_FORBIDDEN):
        try:
            sheets[sheet] = pd.read_excel(path, sheet_name=sheet, dtype=str).fillna("").to_dict("records")
        except ValueError:
            sheets[sheet] = []
    anchor = Anchorer(store)
    limits = {l["id"]: l for l in _limit_items()}

    for i, rec in enumerate(sheets[SHEET_CARDS]):
        cid = _text(rec.get("卡片编号"))
        if not cid:
            continue
        r = {k: _text(rec.get(k)) for k in CARD_COLUMNS}
        aid = store.dcs.resolve_area(r["所属工段"]) if r["所属工段"] else None
        card = {
            "id": cid,
            "name": r["卡片名称"] or r["报警名称"] or cid,
            "alarmName": r["报警名称"],
            "trigger": {
                "objects": anchor.objects(r["触发对象"]),
                "tags": anchor.tags(r["触发位号"]),
                "level": r["报警级别"], "setpoint": r["设定值"], "unit": r["单位"],
                "limits": [{"id": x, "status": ANCHOR_OK if x in limits else ANCHOR_PENDING,
                            "appliesTo": (limits.get(x) or {}).get("appliesTo")} for x in _items(r["关联限值"])],
            },
            "area": {"text": r["所属工段"], "id": aid},
            "equipment": anchor.objects(r["关联设备"]),
            "interlocks": anchor.objects(r["关联联锁"]),
            "priority": r["优先级"],
            "responseTime": r["允许响应时间"],
            "phenomena": {"dcs": r["报警现象·DCS"], "field": r["报警现象·现场"]},
            "consequence": {"text": r["未及时处置后果"], "objects": anchor.objects(r["后果关联对象"])},
            "clearCondition": r["解除条件"],
            "reportPoints": r["汇报要点"],
            "recordRequirement": r["记录要求"],
            "status": r["状态"] or "草案",
            "basis": r["依据"],
            "causes": [], "steps": [], "forbidden": [],
            "source": Provenance(path.name, SHEET_CARDS, i + 2).to_dict(),
        }
        ps.cards[cid] = card

    def card_of(rec: dict[str, Any], sheet: str, row: int) -> dict[str, Any] | None:
        cid = _text(rec.get("卡片编号"))
        card = ps.cards.get(cid)
        if cid and not card:
            ps.issues.append({"severity": "warning", "check": "处置规程引用了不存在的卡片",
                              "detail": f"{sheet} 第 {row} 行：卡片 {cid} 不在「处置卡」工作表中",
                              "source": Provenance(path.name, sheet, row).to_dict()})
        return card

    for i, rec in enumerate(sheets[SHEET_CAUSES]):
        card = card_of(rec, SHEET_CAUSES, i + 2)
        if not card:
            continue
        verify_tags = anchor.tags(_text(rec.get("验证位号")))
        category = _text(rec.get("原因类别"))
        card["causes"].append({
            "seq": _text(rec.get("序号")) or str(len(card["causes"]) + 1),
            "category": category if category in CAUSE_CATEGORIES else (category or "工艺"),
            "description": _text(rec.get("原因描述")),
            "objects": anchor.objects(_text(rec.get("关联对象"))),
            "verifyMethod": _text(rec.get("验证方法")),
            "verifyTags": verify_tags,
            "criterion": _text(rec.get("判据")),
            "autoCheck": any(t["status"] == ANCHOR_OK for t in verify_tags),
            "basis": _text(rec.get("依据")),
        })
    for i, rec in enumerate(sheets[SHEET_STEPS]):
        card = card_of(rec, SHEET_STEPS, i + 2)
        if not card:
            continue
        tags = anchor.tags(_text(rec.get("关联位号")))
        action = _text(rec.get("动作类型"))
        card["steps"].append({
            "seq": _text(rec.get("序号")) or str(len(card["steps"]) + 1),
            "phase": _text(rec.get("阶段")) or "真实处置",
            "role": _text(rec.get("岗位")),
            "action": action,
            "description": _text(rec.get("步骤描述")),
            "objects": anchor.objects(_text(rec.get("关联对象"))),
            "tags": tags,
            "precondition": _text(rec.get("前置条件")),
            "auto": action in AUTO_ACTIONS and any(t["status"] == ANCHOR_OK for t in tags),
            "basis": _text(rec.get("依据")),
        })
    for i, rec in enumerate(sheets[SHEET_FORBIDDEN]):
        card = card_of(rec, SHEET_FORBIDDEN, i + 2)
        if card and _text(rec.get("禁止内容")):
            card["forbidden"].append({"seq": _text(rec.get("序号")), "text": _text(rec.get("禁止内容")),
                                      "objects": anchor.objects(_text(rec.get("关联对象"))), "basis": _text(rec.get("依据"))})

    for card in ps.cards.values():
        card["causes"].sort(key=lambda c: _seq(c["seq"]))
        card["steps"].sort(key=lambda s: (PHASES.index(s["phase"]) if s["phase"] in PHASES else 9, _seq(s["seq"])))
        card["summary"] = _summary(card)
        _index(ps, store, card)

    ps.load_stats = {
        "file": path.name,
        "sheets": [{"sheet": s, "rows": len(sheets[s]), "validRows": len(sheets[s])} for s in sheets],
        "cardCount": len(ps.cards),
        "anchors": _anchor_totals(ps),
    }
    return ps


def _seq(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 1e9


def _all_refs(card: dict[str, Any]) -> list[dict[str, Any]]:
    refs = card["trigger"]["objects"] + card["trigger"]["tags"] + card["equipment"] + card["interlocks"] \
        + card["consequence"]["objects"]
    for c in card["causes"]:
        refs += c["objects"] + c["verifyTags"]
    for s in card["steps"]:
        refs += s["objects"] + s["tags"]
    for f in card["forbidden"]:
        refs += f["objects"]
    return refs


def _summary(card: dict[str, Any]) -> dict[str, Any]:
    refs = _all_refs(card)
    return {
        "causeCount": len(card["causes"]),
        "autoCauseCount": sum(1 for c in card["causes"] if c["autoCheck"]),
        "stepCount": len(card["steps"]),
        "autoStepCount": sum(1 for s in card["steps"] if s["auto"]),
        "anchored": sum(1 for r in refs if r["status"] == ANCHOR_OK),
        "pending": sum(1 for r in refs if r["status"] == ANCHOR_PENDING),
    }


def _anchor_totals(ps: ProcedureSet) -> dict[str, int]:
    ok = sum(c["summary"]["anchored"] for c in ps.cards.values())
    pending = sum(c["summary"]["pending"] for c in ps.cards.values())
    return {"anchored": ok, "pending": pending}


def _index(ps: ProcedureSet, store: Any, card: dict[str, Any]) -> None:
    cid = card["id"]
    for t in card["trigger"]["tags"]:
        if t["id"]:
            ps.by_tag[t["id"]].add(cid)
    for ref in card["trigger"]["objects"] + card["equipment"] + card["interlocks"]:
        if ref["id"]:
            ps.by_object[ref["id"]][cid] = "触发"
    for ref in _all_refs(card):
        if ref.get("id") and ref["kind"] != "tag":
            ps.by_object[ref["id"]].setdefault(cid, "相关")
    area_id = card["area"]["id"]
    if not area_id:
        tags = [store.dcs.tags[t["id"]] for t in card["trigger"]["tags"] if t["id"] in store.dcs.tags]
        area_id = tags[0].get("areaId") if tags else None
        card["area"]["id"] = area_id
    if area_id:
        ps.by_area[area_id].add(cid)


def _limit_items() -> list[dict[str, Any]]:
    from backend.services import process_limits

    return process_limits._load()


# ------------------------------------------------------------------ 查询


def cards_for(ps: ProcedureSet, *, object_ids: set[str] = frozenset(), tag_ids: set[str] = frozenset(),
              area_id: str | None = None) -> list[dict[str, Any]]:
    """对象相关的处置卡：触发位号落在对象上、或卡片提到了对象。返回卡片并标出关系（触发 / 相关）。"""
    hits: dict[str, str] = {}
    for tid in tag_ids:
        for cid in ps.by_tag.get(tid, ()):
            hits[cid] = "触发"
    for oid in object_ids:
        for cid, role in ps.by_object.get(oid, {}).items():
            if hits.get(cid) != "触发":
                hits[cid] = role
    if area_id:
        for cid in ps.by_area.get(area_id, ()):
            hits.setdefault(cid, "本工段")
    order = {"触发": 0, "相关": 1, "本工段": 2}
    return [{**ps.cards[cid], "relation": role}
            for cid, role in sorted(hits.items(), key=lambda kv: (order.get(kv[1], 9), kv[0]))]


def search(ps: ProcedureSet, q: dict[str, Any]) -> dict[str, Any]:
    kw = _text(q.get("keyword"))
    area = _text(q.get("areaId"))
    items = []
    for card in ps.cards.values():
        if area and card["area"]["id"] != area:
            continue
        if kw and not any(kw in (x or "") for x in (card["id"], card["name"], card["alarmName"],
                                                     " ".join(t["text"] for t in card["trigger"]["tags"]),
                                                     " ".join(o["text"] for o in card["trigger"]["objects"]))):
            continue
        items.append({k: card[k] for k in ("id", "name", "alarmName", "priority", "responseTime", "status", "summary")}
                     | {"area": card["area"], "triggerTags": [t["text"] for t in card["trigger"]["tags"]][:8],
                        "level": card["trigger"]["level"], "setpoint": card["trigger"]["setpoint"]})
    items.sort(key=lambda c: c["id"])
    return {"items": items, "total": len(items)}
