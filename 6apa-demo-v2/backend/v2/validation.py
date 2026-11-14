"""一致性校验（需求 ONTO-SR-SW-059）。

对当前本体执行全量校验，结果分「错误 / 警告 / 提示」，每条可跳转到问题对象：
1. 判定规则：引用的参数、位号、计算组态、限值是否存在；限值字段是否有值；
2. 现象：判定规则待定义的统计；
3. 根因关系：端点存在、因果环路；
4. 计算组态：算法存在、必填输入已绑定、绑定的参数 / 设备组 / 位号 / 计算组态存在；
5. 位号映射：参数关联的位号在点表（XBase 位号目录的替身）中存在；
6. 参数约束：适用工况有对应的「工况」现象；
7. 层级与图纸：设备组在导航中无成员、图纸热区未对应到本体对象 / 对应待确认。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.v2.context import AppContext

LEVELS = ["错误", "警告", "提示"]


def _rule_conditions(rule: Any) -> list[dict[str, Any]]:
    if not rule:
        return []
    if rule.get("type") == "group":
        return [c for ch in rule.get("children") or [] for c in _rule_conditions(ch)]
    return [rule]


def run(ctx: AppContext) -> dict[str, Any]:
    h = ctx.hierarchy
    dcs = ctx.store.dcs
    items: list[dict[str, Any]] = []

    def add(level: str, rule: str, message: str, target: dict[str, Any] | None = None) -> None:
        items.append({"level": level, "rule": rule, "message": message, "target": target})

    def obj_target(oid: str, tab: str | None = None) -> dict[str, Any] | None:
        ops = h.ops_of_object(ctx.store, oid)
        if not ops:
            return None
        return {"kind": "object", "id": oid, "name": ctx.object_name(oid), "opId": ops[0],
                "segmentId": h.ops[ops[0]]["segmentId"], "tab": tab}

    param_cache: dict[str, set[str]] = {}

    def params_of(oid: str) -> set[str]:
        if oid not in param_cache:
            names = set()
            targets = [oid] + (ctx.group_members(oid) if oid.startswith("egrp-") else [])
            for t in targets:
                try:
                    names |= {p["name"] for p in ctx.parameter_names(t)}
                except Exception:  # noqa: BLE001
                    pass
            param_cache[oid] = names
        return param_cache[oid]

    # 1 / 2 现象与判定规则
    pending = []
    for p in ctx.phen.phenomena.values():
        aid = (p.get("anchor") or {}).get("id") or ""
        tgt = obj_target(aid, "phenomena")
        where = f"现象「{p['name']}」（{p['id']}）"
        if aid not in dcs.equipment and aid not in dcs.equipment_groups:
            add("错误", "现象挂载", f"{where} 挂载的对象不存在：{aid}", None)
            continue
        if not p.get("rule"):
            pending.append(p)
            continue
        for c in _rule_conditions(p.get("rule")):
            s = c.get("subject") or {}
            if s.get("kind") == "parameter" and s.get("name") not in params_of(aid):
                add("错误", "判定规则引用", f"{where} 引用的参数「{s.get('name')}」不在挂载对象上", tgt)
            elif s.get("kind") == "tag" and s.get("tag") not in ctx.tag_by_name:
                add("错误", "判定规则引用", f"{where} 引用的位号 {s.get('tag')} 在点表中不存在", tgt)
            elif s.get("kind") == "calc" and s.get("calcId") not in ctx.calcs.items:
                add("错误", "判定规则引用", f"{where} 引用的计算组态 {s.get('calcId')} 不存在", tgt)
            elif s.get("kind") == "context":
                add("提示", "运行上下文", f"{where} 条件主体是运行上下文「{s.get('name')}」（EBR / MOM），本 Demo 未接入，试算显示无法判定", tgt)
            t = c.get("threshold") or {}
            if t.get("kind") == "limit":
                lim = ctx.limits.get(t.get("limitId") or "")
                if not lim:
                    add("错误", "判定规则引用", f"{where} 引用的限值 {t.get('limitId')} 不存在", tgt)
                elif lim.get(t.get("field")) in (None, ""):
                    add("警告", "限值待补", f"{where} 引用 {t.get('limitId')} 的「{t.get('field')}」暂无数值（待现场提供），规则无法判定", tgt)
    for p in pending:
        add("提示", "判定规则待定义", f"现象「{p['name']}」（{p['id']}）判定规则待定义，只能作为图谱节点，不能试算",
            obj_target((p.get("anchor") or {}).get("id") or "", "phenomena"))

    # 3 根因关系
    cyc = ctx.phen.cyclic_links()
    for lid, l in ctx.phen.links.items():
        c, e = ctx.phen.phenomena.get(l["cause"]), ctx.phen.phenomena.get(l["effect"])
        if not c or not e:
            add("错误", "关系有效性", f"导致关系 {lid} 的端点现象不存在", None)
        elif lid in cyc:
            add("警告", "因果环路", f"导致关系 {lid}「{c['name']} → {e['name']}」处在因果环路上，请确认是正反馈 / 控制回路还是方向登记错误",
                obj_target((e.get("anchor") or {}).get("id") or "", "causal"))

    # 4 计算组态
    for cid, calc in ctx.calcs.items.items():
        aid = (calc.get("anchor") or {}).get("id") or ""
        tgt = obj_target(aid, "calc") if (aid.startswith(("equip-", "egrp-"))) else {"kind": "global:calc", "name": "计算组态"}
        where = f"计算组态「{calc['name']}」（{cid}）"
        algo = ctx.algos.items.get(calc.get("algorithmId") or "")
        if not algo:
            add("错误", "计算组态", f"{where} 引用的算法 {calc.get('algorithmId')} 不在算法库中", tgt)
            continue
        bindings = calc.get("bindings") or {}
        for inp in algo.get("inputs") or []:
            b = bindings.get(inp["name"])
            if not b:
                if inp.get("required") and inp.get("default") is None:
                    add("错误", "计算组态", f"{where} 必填输入「{inp['label']}」未绑定", tgt)
                continue
            k = b.get("kind")
            if k == "parameter" and aid.startswith(("equip-", "egrp-")) and b.get("name") not in params_of(aid):
                add("错误", "计算组态", f"{where} 输入「{inp['label']}」绑定的参数「{b.get('name')}」不在作用对象上", tgt)
            elif k == "groupParameter" and b.get("groupId") not in dcs.equipment_groups:
                add("错误", "计算组态", f"{where} 输入「{inp['label']}」绑定的设备组不存在", tgt)
            elif k == "groupParameter" and b.get("name") not in params_of(b.get("groupId")):
                add("错误", "计算组态", f"{where} 输入「{inp['label']}」绑定的参数「{b.get('name')}」不在设备组上", tgt)
            elif k == "tag" and b.get("tag") not in ctx.tag_by_name:
                add("错误", "计算组态", f"{where} 输入「{inp['label']}」绑定的位号 {b.get('tag')} 不存在", tgt)
            elif k == "calc" and b.get("calcId") not in ctx.calcs.items:
                add("错误", "计算组态", f"{where} 输入「{inp['label']}」引用的计算组态 {b.get('calcId')} 不存在", tgt)

    # 5 位号映射 / 6 参数约束的适用工况（逐个设备组 / 设备）
    cond_keys = {p.get("conditionKey") for p in ctx.phen.phenomena.values() if p.get("conditionKey")}
    cond_modes = {(k.split(":")[1], k.split(":")[2]) for k in cond_keys if k.startswith("mode:") and k.count(":") >= 2}
    seen_tags: set[str] = set()
    seen_limits: set[str] = set()
    objects = list(h.ops_of_group) + list(h.op_of_equipment)
    for oid in objects:
        try:
            prof = ctx.profile(oid)
        except Exception:  # noqa: BLE001
            continue
        for a in prof.get("attributes") or []:
            for link in a.get("dataLinks") or []:
                tag = link.get("tag")
                if tag and tag not in ctx.tag_by_name and tag not in seen_tags:
                    seen_tags.add(tag)
                    add("错误", "位号映射", f"「{ctx.object_name(oid)}」的参数「{a['name']}」绑定的位号 {tag} 在点表中不存在（失效绑定）",
                        obj_target(oid, "parameters"))
        for c in (prof.get("constraints") or {}).get("operating") or []:
            mode = c.get("operatingMode")
            if not mode or c["id"] in seen_limits:
                continue
            seen_limits.add(c["id"])
            lim = ctx.limits.get(c["id"]) or {}
            area = (lim.get("area") or "").strip().lower().replace("（", "(").replace("）", ")")
            code = (dcs.area_by_name.get(area) or "")[5:]
            if (code, mode) not in cond_modes:
                add("提示", "工况引用", f"限值 {c['id']}（{c.get('appliesTo')}）的适用工况「{mode}」还没有对应的工况现象", obj_target(oid, "constraints"))

    # 7 层级与图纸
    for gid, g in dcs.equipment_groups.items():
        if gid in h.ops_of_group and not ctx.group_members(gid):
            add("警告", "层级完整性", f"设备组「{g['name']}」在导航中没有成员设备", obj_target(gid, "drawing"))
    from backend.v2 import drawing
    for op_id, op in h.ops.items():
        img = drawing.image_view(ctx, op_id)
        if not img:
            continue
        tgt = {"kind": "drawing", "id": op_id, "name": op["name"], "segmentId": op["segmentId"]}
        for s in img["hotspots"]:
            if not s.get("objectId"):
                add("警告", "图纸映射", f"图纸「{op['name']}」上的「{s['name']}」未对应到本体对象", tgt)
            elif not s.get("confirmed", True):
                add("提示", "图纸映射", f"图纸「{op['name']}」上的「{s['name']}」对应关系待确认（{s.get('note') or '按位置 / 文字推断'}）", tgt)

    counts = {lv: sum(1 for i in items if i["level"] == lv) for lv in LEVELS}
    rules: dict[str, int] = {}
    for i in items:
        rules[i["rule"]] = rules.get(i["rule"], 0) + 1
    items.sort(key=lambda i: LEVELS.index(i["level"]))
    return {"checkedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "counts": counts, "rules": rules, "items": items,
            "publishable": counts["错误"] == 0,
            "scope": {"phenomena": len(ctx.phen.phenomena), "links": len(ctx.phen.links), "calculations": len(ctx.calcs.items),
                      "objects": len(objects), "limits": len(seen_limits)},
            "note": "位号以点表代替 XBase 位号目录校验；错误需处理后才能发布（发布功能后续实现）"}
