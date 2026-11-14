"""导出单文件版：一个 HTML 文件，双击就能在浏览器里看，不需要 Python / 后端。

    python3 -m backend.tools.export_static            # 用已构建的 frontend/dist-single
    python3 -m backend.tools.export_static --build    # 先 npm run build:single（需要 Node.js）

输出 release/6APA本体Demo_v2.html。做法：
- 用种子数据（不含 data/store 里的在线编辑）跑一遍后端，把前端会请求的只读接口应答全部收集起来；
- 现象 / 根因关系只导出原始记录，由前端在浏览器里现算（src/api/static.ts），因此单文件版里也能增删改；
- 判定规则与计算组态的试算结果预先算好（模拟数据，时间窗截至导出时刻）；
- 现场图纸转成 data URL 内嵌；整个快照 JSON → gzip → base64，放进 <script id="v2-data">。
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / "frontend"
SINGLE = FRONT / "dist-single" / "index.html"
OUT = ROOT / "release" / "6APA本体Demo_v2.html"

# 用种子数据导出，避免把本机的在线编辑带进去
os.environ["V2_STORE_DIR"] = tempfile.mkdtemp(prefix="v2-export-")

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.v2.context import get_ctx  # noqa: E402
from backend.v2 import drawing as drawing_mod, nav, procedures  # noqa: E402

STATIC_TABS = ["constraints", "topology", "influence", "calc", "procedures"]
OP_TABS = ["drawing", "parameters"]  # 设备组在不同工序下内容不同


def key(path: str, query: dict[str, Any] | None = None) -> str:
    """与前端 static.ts 的 key() 一致：参数按名排序、跳过空值、不做 URL 编码。"""
    parts = sorted((k, v) for k, v in (query or {}).items() if v not in (None, ""))
    return f"{path}?{'&'.join(f'{k}={v}' for k, v in parts)}" if parts else path


class Collector:
    def __init__(self) -> None:
        self.client = TestClient(app)
        self.get: dict[str, Any] = {}
        self.failed: list[str] = []

    def fetch(self, path: str, query: dict[str, Any] | None = None) -> Any:
        k = key(path, query)
        if k in self.get:
            return self.get[k]
        r = self.client.get("/api/v2" + path, params={a: b for a, b in (query or {}).items() if b not in (None, "")})
        if r.status_code != 200:
            self.failed.append(f"{r.status_code} {k}")
            return None
        self.get[k] = r.json()
        return self.get[k]

    def post(self, path: str, body: dict[str, Any]) -> Any:
        r = self.client.post("/api/v2" + path, json=body)
        return r.json() if r.status_code == 200 else None


REL_KEYS = ("category", "from", "to", "direction", "target", "predicate", "mechanism")
ATTR_KEYS = ("kind", "name", "value", "valueType", "description", "note")


def slim_profile(p: dict[str, Any]) -> dict[str, Any]:
    """其他分类里的对象档案只展示属性与关系（GenericProfile.vue），其余字段不导出。"""
    rel = p.get("relations") or {}
    return {
        "objectId": p.get("objectId"), "kind": p.get("kind"), "name": p.get("name"),
        "header": {k: (p.get("header") or {}).get(k) for k in ("className", "classPath")},
        "attributes": [{k: a.get(k) for k in ATTR_KEYS if a.get(k) not in (None, "")} for a in p.get("attributes") or []],
        "relations": {g: [{k: r.get(k) for k in REL_KEYS if r.get(k) not in (None, "")} for r in rel.get(g) or []]
                      for g in ("classRelations", "attributeRelations", "groupRelations")},
    }


def domain_nodes(col: Collector, cat: str) -> list[dict[str, Any]]:
    """逐层展开某个分类的树，返回全部节点。"""
    out: list[dict[str, Any]] = []
    root = col.fetch(f"/nav/domain/{cat}") or {}
    stack = list(root.get("items") or [])
    while stack:
        n = stack.pop()
        out.append(n)
        if n.get("hasChildren"):
            sub = col.fetch(f"/nav/domain/{cat}", {"parent": n["id"]}) or {}
            stack += sub.get("items") or []
    return out


def build_front() -> None:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    if subprocess.call([npm, "run", "build:single"], cwd=FRONT) != 0:
        sys.exit("前端单文件构建失败")


def main() -> None:
    if "--build" in sys.argv or not SINGLE.exists():
        build_front()
    t0 = time.time()
    ctx = get_ctx()
    h = ctx.hierarchy
    dcs = ctx.store.dcs
    col = Collector()

    print("收集导航 / 工艺段 / 工序 …")
    col.fetch("/meta")
    col.fetch("/global-graph")
    col.fetch("/nav/space")
    for seg in h.segments:
        col.fetch(f"/nav/segment/{seg}")
        col.fetch(f"/segments/{seg}")
    image_b64: dict[str, str] = {}
    for op in h.ops:
        col.fetch(f"/ops/{op}")
        d = col.fetch(f"/ops/{op}/drawing")
        if d and d.get("image"):
            path = drawing_mod.image_path(op)
            image_b64[op] = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
            d["image"]["url"] = image_b64[op]
        col.fetch(f"/ops/{op}/calculations")
        docs = col.fetch(f"/ops/{op}/documents") or {}
        for doc in docs.get("documents") or []:
            col.fetch(f"/documents/{doc['id']}")

    print("收集设备 / 设备组的页签 …")
    objects = {e: [op] for e, op in h.op_of_equipment.items()}
    objects.update({g: list(ops) for g, ops in h.ops_of_group.items()})
    for oid, ops in objects.items():
        for op in [None, *ops]:
            col.fetch(f"/objects/{oid}", {"op": op})
            for tab in OP_TABS:
                col.fetch(f"/objects/{oid}/tabs/{tab}", {"op": op})
        for tab in STATIC_TABS:
            col.fetch(f"/objects/{oid}/tabs/{tab}")
        col.fetch(f"/objects/{oid}/parameters")
        col.fetch(f"/objects/{oid}/info")

    print("收集其他分类 …")
    for cat in nav.CATEGORIES:
        if cat["key"] == "space":
            continue
        for n in domain_nodes(col, cat["key"]):
            raw = str(n["id"]).split("|")[-1]
            if raw.startswith(("equip-", "egrp-", "robj-", "area-")):
                prof = col.fetch(f"/objects/{raw}/profile")
                if prof:
                    col.get[key(f"/objects/{raw}/profile")] = slim_profile(prof)
                if raw.startswith(("equip-", "egrp-")):
                    col.fetch(f"/objects/{raw}")

    print("收集全局视图（计算组态 / 算法库 / 工况与根因 / 文档提取）…")
    col.fetch("/algorithms")
    col.fetch("/validation")
    for cid in ctx.store.procedures.cards:
        col.fetch(f"/procedures/{cid}")
    for q in [{}] + [{"seg": s} for s in h.segments] + [{"op": o} for o in h.ops]:
        for path in ("/scope/calculations", "/scope/documents", "/scope/conditions"):
            col.fetch(path, q)

    col.fetch("/limits")
    calcs = (col.fetch("/calculations") or {}).get("items") or []
    for c in calcs:
        col.fetch(f"/calculations/{c['id']}")

    print("预算试算结果（模拟数据）…")
    evals: dict[str, Any] = {}
    for p in ctx.phen.phenomena.values():
        if not p.get("rule"):
            continue
        for op in ctx.phenomenon_ops(p) or [""]:
            r = col.post(f"/phenomena/{p['id']}/evaluate", {"hours": 24, "opId": op or None})
            if r:
                evals[f"{p['id']}|{op}"] = r
    calc_runs: dict[str, Any] = {}
    for c in calcs:
        anchor = c["anchor"]["id"]
        ops = h.ops_of_object(ctx.store, anchor) or [""]
        for op in ops:
            r = col.post(f"/calculations/{c['id']}/run", {"hours": 6, "opId": op or None})
            if r:
                calc_runs[f"{c['id']}|{op}|"] = r
            members = ctx.group_members(anchor, op) if anchor.startswith("egrp-") else [anchor]
            for m in members:
                r = col.post(f"/calculations/{c['id']}/run", {"hours": 6, "opId": op or None, "targetId": m})
                if r and any(x.get("values") for x in r["results"]):
                    calc_runs[f"{c['id']}|{op}|{m}"] = r

    print("整理现象 / 根因关系与搜索索引 …")
    anchor_ops = {}
    for p in ctx.phen.phenomena.values():
        aid = (p.get("anchor") or {}).get("id")
        if aid:
            anchor_ops[aid] = ctx.phenomenon_ops(p)
    for oid in objects:  # 新增现象可挂到任意设备 / 设备组
        anchor_ops.setdefault(oid, h.ops_of_object(ctx.store, oid))
    equip_group = {e: x["equipmentGroupId"] for e, x in dcs.equipment.items() if x.get("equipmentGroupId")}

    from backend.v2.search import initials
    search = {
        "index": ctx.search_index(),  # 与完整版同一份搜索索引（不含现象，现象在浏览器里现算）
        "phenPy": {pid: initials(p["name"]) for pid, p in ctx.phen.phenomena.items()},
        "opSegment": {o: x["segmentId"] for o, x in h.ops.items()},
    }
    limits = {lid: {k: l.get(k) for k in ("lowLow", "low", "normalLow", "normalHigh", "high", "highHigh")}
              for lid, l in ctx.limits.items()}
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    snapshot = {
        "info": {"generatedAt": generated, "note": "单文件版数据快照（种子数据 + 模拟数据试算结果）"},
        "get": col.get,
        "base": {"phenomena": list(ctx.phen.phenomena.values()), "links": list(ctx.phen.links.values()),
                 "anchorOps": anchor_ops, "equipGroup": equip_group, "limits": limits,
                 "calcNames": {k: v["name"] for k, v in ctx.calcs.items.items()}, "search": search,
                 "phenProcedures": {pid: procedures.cards_for_phenomenon(ctx, pid) for pid in ctx.phen.phenomena}},
        "evals": evals,
        "calcRuns": calc_runs,
    }
    raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    packed = base64.b64encode(gzip.compress(raw, 9)).decode("ascii")

    html = SINGLE.read_text("utf-8")
    html = html.replace("<title>6APA 本体 v2</title>", "<title>6APA 本体 v2（单文件版）</title>")
    inject = f'<script id="v2-data" type="application/octet-stream">{packed}</script>'
    html = html.replace("<div id=\"app\"></div>", f"<div id=\"app\"></div>\n    {inject}", 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, "utf-8")
    print(f"接口应答 {len(col.get)} 条，试算 {len(evals)} 条，计算 {len(calc_runs)} 条；"
          f"数据 {len(raw) / 1e6:.1f} MB → 压缩后 {len(packed) / 1e6:.1f} MB")
    if col.failed:
        print(f"有 {len(col.failed)} 个接口未取到（前 5 个）：", col.failed[:5])
    print(f"已生成：{OUT}（{OUT.stat().st_size / 1e6:.1f} MB，用时 {time.time() - t0:.0f} 秒）")


if __name__ == "__main__":
    main()
