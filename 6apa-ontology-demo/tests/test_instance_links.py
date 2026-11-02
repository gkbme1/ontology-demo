"""类 / 设备组 / 实例三层与实例连接自测（不需要单独启动服务）。

    python3 -m tests.test_instance_links

1. 实例连接：组间拓扑按连接方式落到实例；RB储罐A/B → 水解罐A～K 是汇管不是按台号，薄膜冷凝器A～D → 轻相罐A～D 按台号；
2. 实例档案：只有归属与实例间关系，不出现设备组作为对端；推导出的关系标连接方式与状态；所属设备组的关系另列为背景；
3. 设备组档案：组间关系与归属，属于哪个类；类档案：属性模板、由组间关系归纳的类间关系、设备组与实例；
4. 连接方式可人工改：在表里把汇管改成指定后，只连指定的几对并标「人工指定」。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

from backend.ontology.indexes import OntologyStore
from backend.services import asset_model as am
from backend.services import instance_links as il

results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    store = OntologyStore()
    links = store.instance_links
    rows = {(r["subject"], r["predicate"], r["object"]): r for r in links.rows}

    print("[实例连接]")
    rb = rows[("RB储罐A/B（水解进料）", "串联下游", "水解反应釜组(水解罐A–K)")]
    check(rb["mode"] == il.MODE_HEADER and rb["linkCount"] == 22 and rb["status"] == il.STATUS_PENDING,
          "RB储罐A/B → 水解罐A～K：汇管（2×11=22 条），标待确认")
    cond = rows[("薄膜冷凝器组", "串联下游", "薄膜轻相罐组(馏出液)")]
    check(cond["mode"] == il.MODE_BY_NUMBER and cond["linkCount"] == 4 and cond["status"] == il.STATUS_DERIVED,
          "薄膜冷凝器A～D → 轻相罐A～D：按台号 4 对")
    check(all(r["mode"] in il.MODES for r in links.rows) and links.load_stats["instanceLinkCount"] > 0,
          f"{len(links.rows)} 条组间关系推出 {links.load_stats['instanceLinkCount']} 条实例连接")

    print("\n[实例档案]")
    tank = store.dcs.equipment_by_owl(":Dev_13_水解罐A")
    p = am.profile(store, tank["id"])
    rels = p["relations"]["classRelations"]
    check({r["layer"] for r in rels} <= {"归属", "实例间"}, "关系只有归属与实例间两层")
    inst = [r for r in rels if r["layer"] == "实例间"]
    group_names = {g["name"] for g in store.dcs.equipment_groups.values()}
    check(inst and not any(r["target"] in group_names for r in inst), "实例间关系的对端是实例或物料，不是设备组")
    rb_links = [r for r in inst if r["target"] in ("RB储罐A", "RB储罐B")]
    check(len(rb_links) == 2 and all(r["linkMode"] == il.MODE_HEADER and r["linkStatus"] == il.STATUS_PENDING for r in rb_links),
          "水解罐A ← RB储罐A、RB储罐B（汇管，推导·待确认）")
    check(any(r["predicate"] == "属于类" and r["targetId"].startswith("class-") for r in rels), "归属里有「属于类」，可跳到类档案")
    gr = p["relations"]["groupRelations"]
    check(gr and all(r["layer"] == "所属组" for r in gr), f"所属设备组的 {len(gr)} 条关系另列为背景")

    print("\n[设备组与类]")
    g = am.profile(store, tank["equipmentGroupId"])
    check({r["layer"] for r in g["relations"]["classRelations"]} <= {"归属", "组间"} and g["header"]["className"].startswith("设备组"),
          "设备组档案：归属与组间关系，标明是设备组")
    index = am.asset_index(store)
    cid = index.class_of_type["固定化酶反应罐"]
    c = am.profile(store, cid)
    check(c["kind"] == "class" and c["treePath"] and c["treePath"][-1].endswith("type:固定化酶反应罐"), "类档案可打开，并定位到树上的设备类型节点")
    check(all(r["layer"] == "类间" for r in c["relations"]["classRelations"])
          and any(r["target"] == "储罐" and r["targetType"] == "类（设备类型）" for r in c["relations"]["classRelations"]),
          "类间关系由组间关系归纳：固定化酶反应罐 ← 储罐（类）")
    check(sum(1 for i in c["instances"] if i["nature"] == "实例") == 11 and any(a["valueType"] == "属性模板" for a in c["attributes"]),
          "类档案列出 11 台主体实例与属性模板")
    node = next(n for n in am.tree(store, c["treePath"][-2])["items"] if n["id"] == c["treePath"][-1])
    check(node["nature"] == "类" and node["objectId"] == cid, "树上设备类型节点是类")

    print("\n[人工改连接方式]")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / il.LINK_FILE_NAME
        df = pd.DataFrame([{"关系编号": rb["relationCode"], "连接方式": il.MODE_SPECIFIED, "指定连接": "A→A；B→B"}],
                          columns=il.MODE_COLUMNS)
        with pd.ExcelWriter(path, engine="openpyxl") as w:
            df.to_excel(w, sheet_name=il.SHEET_MODES, index=False)
        again = il.build(store, path)
        r2 = next(r for r in again.rows if r["relationCode"] == rb["relationCode"])
        check(r2["mode"] == il.MODE_SPECIFIED and r2["linkCount"] == 2 and r2["status"] == "人工指定", "改成「指定 A→A；B→B」后只连 2 对，标人工指定")

    try:
        from fastapi.testclient import TestClient

        from backend import main as app_module
    except Exception as exc:  # pragma: no cover
        check(False, f"无法加载应用：{exc}")
        return 1
    app_module._store = store
    client = TestClient(app_module.app)
    check(client.get(f"/api/ontology/asset-profile/{cid}").json()["kind"] == "class", "类档案接口可用")
    sources = client.get("/api/ontology/data-sources").json()["sources"]
    check(any(s["file"] == il.LINK_FILE_NAME and s["available"] for s in sources), "数据源清单里有实例连接表")

    passed = sum(results)
    print(f"\n通过 {passed} / {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
