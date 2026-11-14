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
