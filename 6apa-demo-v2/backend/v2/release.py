"""本体版本发布、对比、回滚（需求 ONTO-SR-SW-060 / 061）。

- 发布：先全量一致性校验，「生效」对象上有错误时不允许发布；生成版本号（V1、V2…）和发布说明，保存不可修改的快照；
  快照里保存工程态全部在线数据（现象、导致关系、计算组态、继承覆盖、人工关系、处置规程编辑），
  「发布内容」只计状态为「生效」的现象 / 导致关系 / 计算组态（草案不发布），覆盖与人工关系等随版本一起发布；
- 对比：任意两个版本（或「工程态当前」）按对象类型列出新增、修改、删除，可看字段级差异；
- 回滚：把历史版本重新发布为当前版本（生成新版本号）；可选同步回退工程态编辑数据。
本 Demo 的点表、工业关系、限值等 Excel 数据源不在版本快照内（只记录文件名与修改时间）。

保存在 data/store/releases/（索引 index.json + 每个版本一个 JSON），不进 git。
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from backend.v2.context import AppContext
from backend.v2.userdata import UserDataError, diff, now

ROOT = Path(__file__).resolve().parents[2]
KINDS = {"phenomena": "现象", "links": "导致关系", "calculations": "计算组态", "overrides": "继承覆盖",
         "relations": "人工关系", "procedureEdits": "处置规程编辑"}
CURRENT = "current"


def _dir() -> Path:
    d = Path(os.environ.get("V2_STORE_DIR") or ROOT / "data" / "store") / "releases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index() -> list[dict[str, Any]]:
    try:
        return json.loads((_dir() / "index.json").read_text("utf-8"))["items"]
    except (OSError, ValueError):
        return []


def _save_index(items: list[dict[str, Any]]) -> None:
    (_dir() / "index.json").write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1), "utf-8")


def snapshot(ctx: AppContext) -> dict[str, dict[str, Any]]:
    """工程态当前的在线数据，按类型 → {ID: 记录}。"""
    ov = ctx.overrides.data
    return {
        "phenomena": copy.deepcopy(ctx.phen.phenomena),
        "links": copy.deepcopy(ctx.phen.links),
        "calculations": copy.deepcopy(ctx.calcs.items),
        "overrides": copy.deepcopy({**{f"现象|{k}": v for k, v in ov["phenomena"].items()},
                                    **{f"限值|{k}": v for k, v in ov["limits"].items()}}),
        "relations": {r["id"]: copy.deepcopy(r) for r in ctx.relations.items},
        "procedureEdits": copy.deepcopy(ctx.procedure_edits.data["cards"]),
    }


def _stats(snap: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for k, label in KINDS.items():
        items = snap.get(k) or {}
        effective = sum(1 for x in items.values() if x.get("status") == "生效") if k in ("phenomena", "links", "calculations") else len(items)
        out[k] = {"label": label, "total": len(items), "published": effective}
    return out


def _sources(ctx: AppContext) -> list[dict[str, Any]]:
    src = []
    for d in ("data/source", "data/config"):
        for f in sorted((ROOT / d).glob("*.*")):
            if f.suffix in (".xlsx", ".json", ".ttl"):
                src.append({"file": f"{d}/{f.name}", "modified": int(f.stat().st_mtime)})
    return src


def list_releases() -> dict[str, Any]:
    items = list(reversed(_index()))
    return {"items": items, "current": items[0] if items else None}


def load(version: str, ctx: AppContext | None = None) -> dict[str, Any]:
    if version == CURRENT:
        if ctx is None:
            raise LookupError(version)
        return {"version": CURRENT, "label": "工程态当前（未发布）", "data": snapshot(ctx)}
    p = _dir() / f"{version}.json"
    if not p.exists():
        raise LookupError(version)
    return json.loads(p.read_text("utf-8"))


def publish(ctx: AppContext, note: str, *, user: str = "演示用户", data: dict | None = None, rollback_of: str | None = None) -> dict[str, Any]:
    from backend.v2 import validation
    if data is None:
        check = validation.run(ctx)
        if not check["publishable"]:
            raise UserDataError(f"一致性校验有 {check['blocking']} 个阻止发布的错误（生效对象上的错误），请先处理")
        warn = check["counts"]
    else:
        warn = None
    items = _index()
    version = f"V{len(items) + 1}"
    snap = data if data is not None else snapshot(ctx)
    rec = {"version": version, "note": note.strip() or ("回滚自 " + rollback_of if rollback_of else ""), "user": user,
           "time": now(), "stats": _stats(snap), "check": warn, "rollbackOf": rollback_of,
           "previous": items[-1]["version"] if items else None}
    (_dir() / f"{version}.json").write_text(json.dumps({**rec, "data": snap, "sources": _sources(ctx)}, ensure_ascii=False), "utf-8")
    items.append(rec)
    _save_index(items)
    return rec


def compare(ctx: AppContext, a: str, b: str) -> dict[str, Any]:
    """a → b 的变化（a 为旧版本）。"""
    da, db = load(a, ctx)["data"], load(b, ctx)["data"]
    groups = []
    for k, label in KINDS.items():
        x, y = da.get(k) or {}, db.get(k) or {}
        added = [_brief(k, i, y[i]) for i in y if i not in x]
        removed = [_brief(k, i, x[i]) for i in x if i not in y]
        modified = []
        for i in x:
            if i in y and x[i] != y[i]:
                ch = diff(x[i], y[i], skip=("updatedAt", "updatedBy", "createdAt"))
                if ch:
                    modified.append({**_brief(k, i, y[i]), "changes": ch})
        groups.append({"kind": k, "label": label, "added": added, "removed": removed, "modified": modified})
    return {"from": a, "to": b, "groups": groups,
            "total": sum(len(g["added"]) + len(g["removed"]) + len(g["modified"]) for g in groups)}


def _brief(kind: str, rid: str, rec: dict[str, Any]) -> dict[str, Any]:
    name = rec.get("name")
    if kind == "links":
        name = f"{rec.get('cause')} → {rec.get('effect')}"
    if kind == "relations":
        name = f"{(rec.get('from') or {}).get('name')} —{rec.get('label')}→ {(rec.get('to') or {}).get('name')}"
    if kind == "overrides":
        name = rid.split("|", 1)[0] + " " + (rec.get("phenomenonId") or rec.get("limitId") or "") + (" 禁用" if rec.get("disabled") else " 覆盖")
    if kind == "procedureEdits":
        name = rid
    return {"id": rid, "name": name or rid, "status": rec.get("status")}


def restore(ctx: AppContext, data: dict[str, dict[str, Any]]) -> None:
    """把工程态编辑数据回退到快照（回滚时可选）。"""
    ctx.phen.phenomena = copy.deepcopy(data.get("phenomena") or {})
    ctx.phen.links = copy.deepcopy(data.get("links") or {})
    ctx.phen._save("phenomena")
    ctx.phen._save("links")
    ctx.calcs.items = copy.deepcopy(data.get("calculations") or {})
    ctx.calcs._save()
    ov = {"phenomena": {}, "limits": {}}
    for k, v in (data.get("overrides") or {}).items():
        kind, key = k.split("|", 1)
        ov["phenomena" if kind == "现象" else "limits"][key] = v
    ctx.overrides.data = ov
    ctx.overrides.save()
    ctx.relations.data = {"items": list(copy.deepcopy(data.get("relations") or {}).values())}
    ctx.relations.save()
    ctx.procedure_edits.data = {"cards": copy.deepcopy(data.get("procedureEdits") or {})}
    ctx.procedure_edits.save()


def rollback(ctx: AppContext, version: str, sync_draft: bool, note: str = "") -> dict[str, Any]:
    old = load(version)
    rec = publish(ctx, note or f"回滚到 {version}", data=old["data"], rollback_of=version)
    if sync_draft:
        restore(ctx, old["data"])
    return {**rec, "syncDraft": sync_draft}


def batch_status(ctx: AppContext, kind: str, ids: list[str], status: str) -> list[dict[str, Any]]:
    """批量变更状态（需求 SW-062 第 2 条）：现象 / 导致关系 / 计算组态。返回 (记录前, 记录后) 列表用于留痕。"""
    from backend.v2.phenomena import STATUSES
    if status not in STATUSES:
        raise UserDataError(f"状态只能是：{'、'.join(STATUSES)}")
    store = {"phenomena": ctx.phen.phenomena, "links": ctx.phen.links, "calculations": ctx.calcs.items}.get(kind)
    if store is None:
        raise UserDataError("只能批量变更 现象 / 导致关系 / 计算组态 的状态")
    changed = []
    for i in ids:
        if i in store and store[i].get("status") != status:
            before = store[i].get("status")
            store[i]["status"] = status
            store[i]["updatedAt"] = now()
            changed.append({"id": i, "name": store[i].get("name") or i, "before": before, "after": status})
    if kind == "calculations":
        ctx.calcs._save()
    else:
        ctx.phen._save(kind)
    return changed
