"""导出静态 API 快照。

用途：在没有后端进程的环境下（离线演示、静态托管）也能让前端
通过同一套 API 契约访问数据。

导出两类文件到 data/snapshot/：
  1. api/<name>.json      —— 与对应 REST 接口返回体完全一致的无筛选快照
  2. bulk/<name>.json     —— 设备 / 参数 / DCS 点全量紧凑表，
                             供静态 API 适配层在浏览器内合成带参数的接口
                             （/equipment/{id}、/parameters/{id}、/tags?... 等）

运行：python3 -m backend.export_static
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.api.routes import ROUTES
from backend.ontology.indexes import OntologyStore

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "snapshot"


def _write(path: Path, payload: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def _compact_tags(store: OntologyStore) -> list[dict[str, Any]]:
    return [
        {
            "id": t["id"],
            "n": t["name"],
            "d": t["rawDescription"],
            "sn": t["station"],
            "a": t["areaId"],
            "e": t["equipmentId"],
            "p": t["parameterId"],
            "pn": t["parameterName"],
            "pt": t["parameterType"],
            "u": t["unit"],
            "b": t["blockType"],
            "o": t["owlSubject"],
            "r": t["source"].get("row"),
        }
        for t in store.dcs.tags.values()
    ]


def _compact_parameters(store: OntologyStore) -> list[dict[str, Any]]:
    return [
        {
            "id": p["id"],
            "n": p["name"],
            "e": p["equipmentId"],
            "en": p["equipmentName"],
            "a": p["areaId"],
            "sn": p["station"],
            "o": p["owlSubject"],
            "c": p["categories"],
            "u": p["units"],
            "b": p["blockTypes"],
            "t": p["tagIds"],
            "r": p["source"].get("row"),
        }
        for p in store.dcs.parameters.values()
    ]


def _compact_equipment(store: OntologyStore) -> list[dict[str, Any]]:
    return [
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
        for e in store.dcs.equipment.values()
    ]


def main() -> int:
    store = OntologyStore()
    written: list[tuple[str, int]] = []

    for route in ROUTES:
        name = route.get("snapshot")
        if not name or route.get("param"):
            continue
        payload = route["handler"](store, {})
        size = _write(OUT_DIR / "api" / f"{name}.json", payload)
        written.append((f"api/{name}.json", size))

    # 关系对象详情逐个导出（71 个，体量小，保留完整匹配与锚点信息）
    entity_details = {eid: store.entity_detail(eid) for eid in store.relations.entities}
    written.append(
        ("api/relation-entity-details.json", _write(OUT_DIR / "api" / "relation-entity-details.json", entity_details))
    )
    relation_details = {r["id"]: store.relation_detail(r["id"]) for r in store.relations.relations}
    written.append(
        ("api/relation-details.json", _write(OUT_DIR / "api" / "relation-details.json", relation_details))
    )
    area_details = {
        a["id"]: {k: v for k, v in (store.area_detail(a["id"]) or {}).items() if k != "relations"}
        for a in store.areas()
    }
    written.append(("api/area-details.json", _write(OUT_DIR / "api" / "area-details.json", area_details)))

    written.append(("bulk/tags.json", _write(OUT_DIR / "bulk" / "tags.json", _compact_tags(store))))
    written.append(
        ("bulk/parameters.json", _write(OUT_DIR / "bulk" / "parameters.json", _compact_parameters(store)))
    )
    written.append(
        ("bulk/equipment.json", _write(OUT_DIR / "bulk" / "equipment.json", _compact_equipment(store)))
    )
    written.append(
        (
            "bulk/entity-matches.json",
            _write(
                OUT_DIR / "bulk" / "entity-matches.json",
                {eid: m for eid, m in store.matches.items()},
            ),
        )
    )

    manifest = {
        "generatedAt": store.loaded_at,
        "files": [{"path": p, "bytes": n} for p, n in written],
        "totalBytes": sum(n for _, n in written),
        "note": "静态快照与 REST API 返回体一一对应；bulk/* 为紧凑全量表，供静态 API 适配层合成带参数接口。",
    }
    _write(OUT_DIR / "manifest.json", manifest)

    total = manifest["totalBytes"]
    for p, n in written:
        print(f"  {p:<44} {n/1024:>9,.1f} KB")
    print(f"✓ 共 {len(written)} 个快照文件，合计 {total/1024/1024:.2f} MB → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
