"""处置规程（需求 ONTO-SR-SW-051 与 4.4 d）。

处置卡原文（6APA_处置规程.xlsx）里「可能原因」与处置步骤写在一张卡上；按需求拆成三部分：
- 报警现象（卡片本身）：source.ref = 卡片 ID；
- 原因现象 + 「原因 导致 报警现象」：source.ref = 「卡片 ID 可能原因 n」（种子已拆了一部分，界面可逐条 / 一键补拆）；
- 处置规程：步骤（序号、阶段、角色、操作说明、前置条件、预期结果、注意事项、是否需人工确认）、处置前后检查的参数与限值、
  执行边界（禁止自动执行的操作、授权要求）、版本、状态。

原文只读；在线编辑保存在 data/store/procedure_edits.json，按卡片 ID 覆盖。
"""
from __future__ import annotations

import re
from typing import Any

from backend.v2.context import AppContext

_REF = re.compile(r"(ARP-[A-Za-z0-9-]+)(?:\s*(?:可能原因\s*|#)(\d+))?")
CAUSE_CATEGORY = {"仪表": "仪表", "设备": "设备", "操作": "操作", "工艺": "工艺", "物料": "物料", "公用工程": "公用工程", "环境": "环境"}


def _refs(text: str) -> list[tuple[str, str | None]]:
    return [(m.group(1), m.group(2)) for m in _REF.finditer(text or "")]


def phenomenon_index(ctx: AppContext) -> dict[tuple[str, str | None], list[str]]:
    """(卡片 ID, 原因序号 | None) → 现象 ID。依据现象的 source.ref。"""
    idx: dict[tuple[str, str | None], list[str]] = {}
    for p in ctx.phen.phenomena.values():
        for ref in _refs(str((p.get("source") or {}).get("ref") or "")):
            idx.setdefault(ref, []).append(p["id"])
    return idx


def link_index(ctx: AppContext) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """(卡片 ID, 原因序号) → 依据写着「卡片 可能原因 n」的导致关系（种子里原因现象可能复用了别的卡整理出的现象）。"""
    idx: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for l in ctx.phen.links.values():
        text = f"{l.get('basis') or ''} {(l.get('source') or {}).get('ref') or ''}"
        for card_id, seq in _refs(text):
            if seq:
                idx.setdefault((card_id, seq), []).append(l)
    return idx


def cards_for_phenomenon(ctx: AppContext, pid: str) -> list[dict[str, Any]]:
    """现象关联的处置卡（现象由该卡整理而来，或是该卡某条可能原因）。"""
    p = ctx.phen.phenomena.get(pid) or {}
    out = []
    for card_id, seq in _refs(str((p.get("source") or {}).get("ref") or "")):
        card = ctx.store.procedures.cards.get(card_id)
        if card:
            out.append({"id": card_id, "name": card["name"], "role": f"可能原因 {seq}" if seq else "报警现象",
                        "status": card_status(ctx, card)})
    return out


def card_status(ctx: AppContext, card: dict[str, Any]) -> str:
    edit = ctx.procedure_edits.get(card["id"]) or {}
    return edit.get("status") or card.get("status") or "草案·待工艺确认"


def _default_steps(card: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for s in card.get("steps") or []:
        out.append({"seq": str(s.get("seq") or len(out) + 1), "phase": s.get("phase") or "", "role": s.get("role") or "",
                    "description": s.get("description") or "", "precondition": s.get("precondition") or "",
                    "expected": "", "caution": "",
                    # 原文 auto=true 的是确认 / 对比类步骤，可由系统辅助；其余需人工确认
                    "manualConfirm": not s.get("auto"),
                    "tags": [t.get("text") for t in s.get("tags") or []]})
    return out


def _default_checks(ctx: AppContext, card: dict[str, Any]) -> list[dict[str, Any]]:
    trig = card.get("trigger") or {}
    out = []
    for lim in trig.get("limits") or []:
        l = ctx.limits.get(lim.get("id") or "") or {}
        band = f"{l.get('normalLow', '')}~{l.get('normalHigh', '')}" if l else ""
        out.append({"when": "处置前", "parameter": lim.get("appliesTo") or l.get("appliesTo") or "", "limitId": lim.get("id"),
                    "requirement": f"确认是否超出 {trig.get('setpoint') or ''}".strip()})
        out.append({"when": "处置后", "parameter": lim.get("appliesTo") or l.get("appliesTo") or "", "limitId": lim.get("id"),
                    "requirement": f"恢复到正常区间 {band} {l.get('unit') or ''}".strip()})
    if card.get("clearCondition"):
        out.append({"when": "处置后", "parameter": "解除条件", "limitId": None, "requirement": card["clearCondition"]})
    return out


def card_view(ctx: AppContext, card: dict[str, Any], pindex: dict | None = None) -> dict[str, Any]:
    pindex = pindex if pindex is not None else phenomenon_index(ctx)
    edit = ctx.procedure_edits.get(card["id"]) or {}
    alarm = [ctx.phen.phenomena[x] for x in pindex.get((card["id"], None), []) if x in ctx.phen.phenomena]
    alarm_ids = {p["id"] for p in alarm}
    lindex = link_index(ctx)
    causes = []
    for c in card.get("causes") or []:
        seq = str(c.get("seq"))
        pids = pindex.get((card["id"], seq), [])
        phen = ctx.phen.phenomena.get(pids[0]) if pids else None
        link = None
        if phen:
            link = next((l for l in ctx.phen.links.values() if l["cause"] == phen["id"] and l["effect"] in alarm_ids), None)
        if not link:
            link = next(iter(lindex.get((card["id"], seq), [])), None)
            if link:
                phen = ctx.phen.phenomena.get(link["cause"]) or phen
        state = "已拆分" if phen and link else ("缺导致关系" if phen else "未拆分")
        causes.append({**{k: c.get(k) for k in ("seq", "category", "description", "verifyMethod", "criterion", "autoCheck")},
                       "verifyTags": [t.get("text") for t in c.get("verifyTags") or []],
                       "phenomenon": {"id": phen["id"], "name": phen["name"], "hasRule": bool(phen.get("rule"))} if phen else None,
                       "linkId": link["id"] if link else None, "splitState": state})
    forbidden = [f.get("text") for f in card.get("forbidden") or [] if f.get("text")]
    return {
        **{k: card.get(k) for k in ("id", "name", "alarmName", "trigger", "priority", "responseTime", "phenomena", "consequence",
                                    "clearCondition", "reportPoints", "recordRequirement", "basis", "source")},
        "scope": edit.get("scope") or "、".join(e.get("text") for e in card.get("equipment") or []),
        "version": edit.get("version") or "V1（导入版）",
        "status": card_status(ctx, card),
        "alarmPhenomena": [{"id": p["id"], "name": p["name"], "anchorId": (p.get("anchor") or {}).get("id"),
                            "anchorName": (p.get("anchor") or {}).get("name")} for p in alarm],
        "causes": causes,
        "splitCount": sum(1 for c in causes if c["splitState"] == "已拆分"),
        "steps": edit.get("steps") if edit.get("steps") is not None else _default_steps(card),
        "checks": edit.get("checks") if edit.get("checks") is not None else _default_checks(ctx, card),
        "forbidden": forbidden,
        "autoExecution": edit.get("autoExecution") or "禁止自动执行：本卡操作均由人工执行，系统只提供判断与提示",
        "authorization": edit.get("authorization") or "待企业 SOP 确认",
        "edited": bool(edit), "editedAt": edit.get("updatedAt"),
    }


def split_cause(ctx: AppContext, card_id: str, seq: str, anchor_id: str | None) -> dict[str, Any]:
    """把一条可能原因拆成「原因现象 + 导致关系」；报警现象不存在时先建报警现象（判定规则待定义）。"""
    card = ctx.store.procedures.cards.get(card_id)
    if not card:
        raise LookupError(card_id)
    cause = next((c for c in card.get("causes") or [] if str(c.get("seq")) == str(seq)), None)
    if not cause:
        raise LookupError(f"{card_id} 可能原因 {seq}")
    pindex = phenomenon_index(ctx)
    created: list[str] = []
    alarm_ids = pindex.get((card_id, None), [])
    if alarm_ids:
        alarm = ctx.phen.phenomena[alarm_ids[0]]
    else:
        if not anchor_id:
            raise ValueError("该卡还没有报警现象，需要指定挂载对象")
        alarm = ctx.phen.create_phenomenon({
            "name": card["name"], "category": "工艺", "severity": "警告", "anchor": _anchor(ctx, anchor_id), "rule": None,
            "description": (card.get("phenomena") or {}).get("dcs") or "", "note": "由处置卡拆分生成，判定规则待定义"})
        alarm["source"] = {"kind": "处置卡", "ref": card_id}
        ctx.phen._save("phenomena")
        created.append(alarm["id"])
    pids = pindex.get((card_id, str(seq)), [])
    existing = link_index(ctx).get((card_id, str(seq)))
    if existing:
        return {"alarm": existing[0]["effect"], "phenomenon": existing[0]["cause"], "link": existing[0]["id"], "created": []}
    if pids:
        phen = ctx.phen.phenomena[pids[0]]
    else:
        phen = ctx.phen.create_phenomenon({
            "name": cause.get("description") or f"{card['name']} 原因 {seq}",
            "category": CAUSE_CATEGORY.get(cause.get("category") or "", "工艺"), "severity": "提示",
            "anchor": alarm["anchor"], "rule": None,
            "description": f"核实方法：{cause.get('verifyMethod') or '—'}；判据：{cause.get('criterion') or '—'}",
            "note": "由处置卡可能原因拆分生成，判定规则待定义（可按核实方法 / 判据补写）"})
        phen["source"] = {"kind": "处置卡·可能原因", "ref": f"{card_id} 可能原因 {seq}"}
        ctx.phen._save("phenomena")
        created.append(phen["id"])
    link = next((l for l in ctx.phen.links.values() if l["cause"] == phen["id"] and l["effect"] == alarm["id"]), None)
    if not link:
        link = ctx.phen.create_link({"cause": phen["id"], "effect": alarm["id"], "confidence": "中",
                                     "mechanism": cause.get("description") or "", "basis": f"{card_id} 可能原因 {seq}"})
        created.append(link["id"])
    return {"alarm": alarm["id"], "phenomenon": phen["id"], "link": link["id"], "created": created}


def _anchor(ctx: AppContext, oid: str) -> dict[str, Any]:
    dcs = ctx.store.dcs
    if oid in dcs.equipment_groups:
        return {"kind": "group", "id": oid, "name": dcs.equipment_groups[oid]["name"]}
    if oid in dcs.equipment:
        return {"kind": "equipment", "id": oid, "name": dcs.equipment[oid]["name"]}
    raise ValueError(f"挂载对象不存在：{oid}")
