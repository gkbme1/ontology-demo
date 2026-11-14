"""运行态（需求 4.9）：运行服务状态、现象与工况状态评估、原因链状态、绑定状态、知识沉淀。

- 运行服务加载「当前发布版本」：只评估版本里状态为「生效」的现象（可切到「全部（含草案，演示）」并按工艺段限定范围）；
  没有发布版本时加载工程态当前数据（演示）；
- 评估用模拟数据（最近 1 小时，最后一个采样点的状态）：发生 / 未发生 / 未知（条件无法判定）；
- 对活动现象，按根因关系逐层查原因现象及其当前状态（需求 SW-073 第 5 条）。
"""
from __future__ import annotations

import resource
import time
from datetime import datetime
from typing import Any

from backend.v2 import rule_eval
from backend.v2.context import AppContext

_cache: dict[str, Any] = {}


def _release_phenomena(ctx: AppContext) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from backend.v2 import release
    cur = release.list_releases()["current"]
    if cur:
        data = release.load(cur["version"])["data"]
        return data.get("phenomena") or {}, cur
    return ctx.phen.phenomena, None


def status(ctx: AppContext) -> dict[str, Any]:
    from backend.v2 import global_graph
    phen, cur = _release_phenomena(ctx)
    g = global_graph.build(ctx)
    modes: dict[str, int] = {}
    for c in ctx.calcs.items.values():
        m = (c.get("execution") or {}).get("mode", "按需")
        modes[m] = modes.get(m, 0) + 1
    return {
        "version": cur, "loadedAt": ctx.store.loaded_at,
        "versionNote": None if cur else "尚未发布：运行服务加载工程态当前数据（演示）",
        "objects": g["nodeCounts"], "relations": g["edgeCounts"],
        "objectTotal": sum(g["nodeCounts"].values()), "relationTotal": sum(g["edgeCounts"].values()),
        "phenomena": {"total": len(phen), "effective": sum(1 for p in phen.values() if p.get("status") == "生效"),
                      "withRule": sum(1 for p in phen.values() if p.get("rule"))},
        "memoryMB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "xbase": {"state": "模拟", "note": "XBase 未接入：实时 / 历史数据由内置模拟器生成（确定性模拟数据）"},
        "engine": {"tasks": len(ctx.calcs.items), "byMode": modes, "note": "本 Demo 无调度器，周期 / 事件触发任务只登记"},
        "evaluation": {k: _cache[k]["at"] for k in _cache},
        "api": {"openapi": "/docs", "note": "运行服务接口以 REST 提供，OpenAPI 说明见 /docs（FastAPI 自动生成）"},
    }


def evaluate(ctx: AppContext, scope: str = "effective", seg: str | None = None) -> dict[str, Any]:
    """评估现象状态。scope = effective（发布版本里生效的）| all（含草案，演示；建议限定工艺段）。"""
    phen, cur = _release_phenomena(ctx)
    h = ctx.hierarchy
    ops = set(h.segments[seg]["opIds"]) if seg else None
    t0 = time.time()
    items = []
    for p in phen.values():
        if not p.get("rule"):
            continue
        if scope == "effective" and p.get("status") != "生效":
            continue
        p_ops = ctx.phenomenon_ops(p)
        if ops is not None and not (set(p_ops) & ops):
            continue
        try:
            r = rule_eval.evaluate(ctx, p["rule"], p["anchor"]["id"], hours=1, phenomenon_id=p["id"])
        except Exception as exc:  # noqa: BLE001
            items.append({"id": p["id"], "name": p["name"], "category": p.get("category"), "severity": p.get("severity"),
                          "targetId": p["anchor"]["id"], "targetName": p["anchor"].get("name"), "state": "未知", "reason": str(exc)})
            continue
        for x in r["results"]:
            if x.get("disabled"):
                continue
            unknown = x["conditions"] and all(c.get("status") == "无法判定" for c in x["conditions"])
            state = "未知" if unknown else ("发生" if x["current"] else "未发生")
            since = x["events"][-1]["start"] if state == "发生" and x["events"] else None
            items.append({"id": p["id"], "name": p["name"], "category": p.get("category"), "severity": p.get("severity"),
                          "anchorId": p["anchor"]["id"], "targetId": x["targetId"], "targetName": x["targetName"], "state": state,
                          "since": since, "opId": (p_ops or [None])[0],
                          "reason": "；".join(c.get("reason") or "" for c in x["conditions"] if c.get("status") == "无法判定")[:200]})
    counts = {s: sum(1 for i in items if i["state"] == s) for s in ("发生", "未发生", "未知")}
    key = f"{scope}|{seg or ''}"
    res = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "scope": scope, "seg": seg, "version": cur["version"] if cur else None,
           "items": sorted(items, key=lambda i: ({"发生": 0, "未知": 1, "未发生": 2}[i["state"]], i["name"])),
           "counts": counts, "seconds": round(time.time() - t0, 1),
           "dataSource": {"simulated": True, "label": "模拟数据"}, "label": "本体评估结果（模拟数据，最近 1 小时最后一个采样点）"}
    _cache[key] = res
    return res


def cause_states(ctx: AppContext, pid: str, target_id: str | None, depth: int = 3) -> dict[str, Any]:
    """活动现象的可能原因链，以及各原因现象在同一对象上的当前状态。"""
    chain = ctx.phen.chain(pid, "up", depth)
    out = []
    for cid, level in sorted(chain["levels"].items(), key=lambda kv: kv[1]):
        if cid == pid:
            continue
        p = ctx.phen.phenomena.get(cid)
        if not p:
            continue
        state, reason = "未知", "判定规则待定义"
        if p.get("rule"):
            tgt = target_id if target_id and _covers(ctx, p["anchor"]["id"], target_id) else None
            try:
                r = rule_eval.evaluate(ctx, p["rule"], p["anchor"]["id"], hours=1, target_id=tgt, phenomenon_id=p["id"])
                res = r["results"][0]
                unknown = res["conditions"] and all(c.get("status") == "无法判定" for c in res["conditions"])
                state = "未知" if unknown or res.get("disabled") else ("发生" if res["current"] else "未发生")
                reason = "" if state != "未知" else "条件无法判定"
            except Exception as exc:  # noqa: BLE001
                reason = str(exc)
        via = [l for l in chain["links"] if l["cause"] == cid]
        out.append({"id": cid, "name": p["name"], "level": level, "state": state, "reason": reason,
                    "anchor": (p.get("anchor") or {}).get("name"), "status": p.get("status"),
                    "to": [(ctx.phen.phenomena.get(l["effect"]) or {}).get("name") for l in via],
                    "confidence": [l.get("confidence") for l in via]})
    return {"root": pid, "name": (ctx.phen.phenomena.get(pid) or {}).get("name"), "targetId": target_id, "causes": out,
            "dataSource": {"simulated": True, "label": "模拟数据"}}


def _covers(ctx: AppContext, anchor: str, target: str) -> bool:
    if anchor == target:
        return True
    e = ctx.store.dcs.equipment.get(target)
    return bool(e and e.get("equipmentGroupId") == anchor)


def binding_summary(ctx: AppContext) -> dict[str, Any]:
    """参数—位号绑定状态汇总与失效绑定列表（需求 SW-076 第 1 条）。首次计算较慢，结果缓存。"""
    if "binding" in _cache:
        return _cache["binding"]
    from backend.v2 import tabs
    h = ctx.hierarchy
    counts = {"已绑定": 0, "待确认": 0, "未绑定": 0, "失效": 0}
    by_seg: dict[str, dict[str, int]] = {}
    invalid = []
    for e, op in h.op_of_equipment.items():
        seg = h.segments[h.ops[op]["segmentId"]]["name"]
        try:
            items = tabs.tab(ctx, e, "parameters")["items"]
        except Exception:  # noqa: BLE001
            continue
        for x in items:
            b = x.get("binding")
            if not b:
                continue
            counts[b] += 1
            by_seg.setdefault(seg, {k: 0 for k in counts})[b] += 1
            if b == "失效":
                invalid.append({"objectId": e, "objectName": ctx.object_name(e), "parameter": x["name"], "note": x.get("bindingNote")})
    res = {"counts": counts, "bySegment": by_seg, "invalid": invalid, "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "note": "按导航中的设备逐台统计参数绑定状态；位号存在性以点表代替 XBase 位号目录"}
    _cache["binding"] = res
    return res


# ------------------------------------------------------------------ 运行态画面（需求 SW-088 第 3 条：同一套界面，只读，叠加实时值与现象状态）
ALARM_KEYS = (("highHigh", "HH", 1), ("high", "H", 1), ("lowLow", "LL", -1), ("low", "L", -1))


def alarm_of(v: float, limit: dict[str, Any] | None) -> str | None:
    """按位号的工艺限值判断报警级别：HH / H / LL / L；在报警限内但超出正常区间为「偏离」。"""
    if not limit:
        return None
    for key, label, sign in ALARM_KEYS:
        x = limit.get(key)
        if x is not None and (v >= x if sign > 0 else v <= x):
            return label
    lo, hi = limit.get("normalLow"), limit.get("normalHigh")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        return "偏离"
    return None


def live_values(ctx: AppContext, names: list[str]) -> dict[str, Any]:
    """位号实时值（模拟数据，当前时刻；与历史试算同一个确定性模拟器）。"""
    import numpy as np
    from backend.v2 import simulator
    now = int(time.time())
    out: dict[str, Any] = {}
    for n in names[:400]:
        tag = ctx.tag_by_name.get(n.upper()) or ctx.tag_by_name.get(n)
        if not tag:
            out[n] = {"v": None, "quality": "无此位号"}
            continue
        limit = ctx.limit_of_tag.get(tag["name"])
        v = float(simulator.series(tag, limit, np.array([now], dtype=np.int64))[0])
        digital = simulator.is_digital(tag)
        out[n] = {"v": round(v, 3), "digital": digital, "alarm": None if digital else alarm_of(v, limit),
                  "unit": tag.get("unit") or tag.get("standardUnit") or "", "limitId": (limit or {}).get("id")}
    return {"at": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"), "values": out, "dataSource": simulator.DATA_SOURCE}


_op_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def op_states(ctx: AppContext, op_id: str) -> dict[str, Any]:
    """一道工序内现象 / 工况的当前状态（逐台）：评估全部已定义判定规则的现象（含草案，演示），缓存 20 秒。
    objects：设备 / 设备组 → 当前发生的异常现象（active，图纸着色）与当前工况（conditions）。"""
    hit = _op_cache.get(op_id)
    if hit and time.time() - hit[0] < 20:
        return hit[1]
    if op_id not in ctx.hierarchy.ops:
        raise LookupError(op_id)
    items = []
    for p in ctx.phen.phenomena.values():
        if not p.get("rule") or op_id not in ctx.phenomenon_ops(p):
            continue
        try:
            r = rule_eval.evaluate(ctx, p["rule"], p["anchor"]["id"], hours=1, phenomenon_id=p["id"])
        except Exception as exc:  # noqa: BLE001
            items.append({"id": p["id"], "name": p["name"], "anchorId": p["anchor"]["id"], "targetId": p["anchor"]["id"],
                          "state": "未知", "reason": str(exc)[:120]})
            continue
        for x in r["results"]:
            if x.get("disabled"):
                continue
            unknown = x["conditions"] and all(c.get("status") == "无法判定" for c in x["conditions"])
            state = "未知" if unknown else ("发生" if x["current"] else "未发生")
            items.append({"id": p["id"], "name": p["name"], "category": p.get("category"), "severity": p.get("severity"),
                          "anchorId": p["anchor"]["id"], "targetId": x["targetId"], "targetName": x["targetName"], "state": state,
                          "since": x["events"][-1]["start"] if state == "发生" and x["events"] else None})
    res = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "opId": op_id, "items": items,
           "objects": _objects_of(ctx, items), "dataSource": {"simulated": True, "label": "模拟数据"},
           "basis": "评估全部已定义判定规则的现象（含草案，演示）：最近 1 小时模拟数据，最后一个采样点的状态"}
    _op_cache[op_id] = (time.time(), res)
    return res


def _objects_of(ctx: AppContext, items: list[dict[str, Any]]) -> dict[str, Any]:
    objs: dict[str, Any] = {}
    for i in items:
        if i["state"] != "发生":
            continue
        ids = {i["targetId"]}
        e = ctx.store.dcs.equipment.get(i["targetId"])
        if e and e.get("equipmentGroupId"):
            ids.add(e["equipmentGroupId"])
        cond = i.get("category") == "工况"
        for oid in ids:
            o = objs.setdefault(oid, {"active": [], "conditions": [], "severity": None})
            lst = o["conditions"] if cond else o["active"]
            if i["name"] not in lst:
                lst.append(i["name"])
            if not cond:
                o["severity"] = "严重" if i.get("severity") == "严重" or o["severity"] == "严重" else "警告"
    return objs
