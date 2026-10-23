"""为离线静态演示构建紧凑数据包。

输出 demo/data/*.js —— 每个文件把一份 API 快照赋值给 window.__ONTO__ 的一个键。
静态演示的 API 适配层（demo/src/api.js）在浏览器内用这些表合成
与 REST 接口完全一致的响应体，因此前端代码路径与连后端时保持一致。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.ontology.indexes import OntologyStore

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "demo" / "data"


def _js(name: str, payload: Any) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    text = f"window.__ONTO__=window.__ONTO__||{{}};window.__ONTO__.{name}={body};\n"
    path = OUT / f"{name}.js"
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def main() -> int:
    s = OntologyStore()
    sizes: list[tuple[str, int]] = []

    # --- 元数据与小表（与 REST 响应体一致） ---
    sizes.append(("overview", _js("overview", s.overview())))
    sizes.append(("categories", _js("categories", s.categories())))
    sizes.append(("areas", _js("areas", s.areas())))
    sizes.append(("classes", _js("classes", s.classes())))
    sizes.append(("properties", _js("properties", s.properties())))
    sizes.append(("predicates", _js("predicates", s.relation_predicates())))
    sizes.append(("relations", _js("relations", s.relations.relations)))
    sizes.append(
        ("relationEntities", _js("relationEntities", [s.entity_brief(e) for e in s.relations.entities.values()]))
    )
    sizes.append(
        (
            "entityDetails",
            _js("entityDetails", {eid: s.entity_detail(eid) for eid in s.relations.entities}),
        )
    )
    sizes.append(("dataSources", _js("dataSources", s.data_sources())))
    sizes.append(("dataQuality", _js("dataQuality", s.quality)))
    sizes.append(("rules", _js("rules", s.rules_query())))
    sizes.append(
        (
            "emptySets",
            _js(
                "emptySets",
                {
                    "constraints": s.constraints(),
                    "capabilities": s.capabilities(),
                    "modelRegistry": s.model_registry(),
                },
            ),
        )
    )
    sizes.append(("turtle", _js("turtle", s.turtle())))
    sizes.append(("relationOverview", _js("relationOverview", s.relations.overview_rows)))

    # --- 全量紧凑表（去掉可由上级对象推导的冗余字段） ---
    equipment = [
        {
            "id": e["id"],
            "n": e["name"],
            "o": e["owlSubject"],
            "a": e["areaId"],
            "sn": e["station"],
            "tc": e["tagCount"],
            "pc": e["parameterCount"],
            "s": e["stats"],
            "s1": e["statsFromSheet1"],
            "ov": e["overview"],
            "p": e["parameterIds"],
            "r": e["source"].get("row"),
            "r1": (e.get("statsSource") or {}).get("row"),
        }
        for e in s.dcs.equipment.values()
    ]
    parameters = [
        {
            "id": p["id"],
            "n": p["name"],
            "e": p["equipmentId"],
            "c": p["categories"],
            "u": p["units"],
            "b": p["blockTypes"],
            "t": p["tagIds"],
            "r": p["source"].get("row"),
        }
        for p in s.dcs.parameters.values()
    ]
    tags = [
        {
            "id": t["id"],
            "n": t["name"],
            "d": t["rawDescription"],
            "e": t["equipmentId"],
            "p": t["parameterId"],
            "pt": t["parameterType"],
            "u": t["unit"],
            "b": t["blockType"],
            "r": t["source"].get("row"),
        }
        for t in s.dcs.tags.values()
    ]
    sizes.append(("equipment", _js("equipment", equipment)))
    sizes.append(("parameters", _js("parameters", parameters)))
    sizes.append(("tags", _js("tags", tags)))

    # 关系对象 → DCS 实例的匹配索引（供反查：某设备/参数参与了哪些关系）
    match_index: dict[str, list[str]] = {}
    for eid, m in s.matches.items():
        for match in m["matches"]:
            match_index.setdefault(match["id"], []).append(eid)
    sizes.append(("matchIndex", _js("matchIndex", match_index)))

    meta = {
        "generatedAt": s.loaded_at,
        "files": [{"name": n, "bytes": b} for n, b in sizes],
        "totalBytes": sum(b for _, b in sizes),
        "sourceFiles": [src["file"] for src in s.data_sources()["sources"] if src["available"]],
    }
    sizes.append(("meta", _js("meta", meta)))

    for n, b in sizes:
        print(f"  {n:<20} {b/1024:>9,.1f} KB")
    print(f"✓ {len(sizes)} 个数据包，合计 {sum(b for _, b in sizes)/1024/1024:.2f} MB → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
