"""设备名称统一与归并自测（不需要单独启动服务）。

    python3 -m tests.test_equipment_merge

1. 归并表：规则产出的每一行都在同一设备组内，兜底名称不参与，误并样例不出现；
2. 加载：水解罐A 的 6 种写法合并成一台，点位、参数一个不丢，同名参数合并；
3. 兼容：旧设备 ID / 旧 OWL Subject / 旧名称仍能查到合并后的设备，HTTP 接口照常；
4. 本体档案：继承自设备组的工艺属性只带本台设备的位号；
5. 归并表里「启用」改成 否 的行不归并。
"""
from __future__ import annotations

import sys

from backend.ontology import identifiers as ids
from backend.ontology.indexes import DCS_FILE, MERGE_FILE, OntologyStore
from backend.services import asset_model as am
from backend.services import equipment_merge as em
from backend.services.dcs_loader import load_dcs

results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    raw = load_dcs(DCS_FILE)
    rows = em.propose(raw)
    table = em.load_table(MERGE_FILE)

    print("[归并表]")
    check(MERGE_FILE.exists() and len(table) == len(rows), f"{MERGE_FILE.name} 与规则产出一致（{len(rows)} 行）")
    group_of = {e["owlSubject"]: e.get("equipmentGroupId") for e in raw.equipment.values()}
    check(all(group_of[r["原OWL Subject"]] == group_of[r["统一OWL Subject"]] for r in rows), "每一行都在同一标准设备组内")
    check(not any(r["原设备名"] in em.GENERIC_NAMES for r in rows), "公用测量管线 / 其他工艺单元 / 管网阀门系统 不参与归并")
    names = {r["原设备名"] for r in rows}
    check(not names & {"离心机A6", "离心机A10", "成品罐AB", "离心机B3BA"}, "同系列设备、A/B 双罐、含义不明的后缀不被误并")
    area_of = {e["owlSubject"]: e.get("areaCode") for e in raw.equipment.values()}
    cross = [r for r in rows if r["规则"] == "同名跨站"]
    check(all(area_of[r["原OWL Subject"]] == area_of[r["统一OWL Subject"]] for r in cross), f"同名跨站只并同工段的（{len(cross)} 行）")

    print("\n[加载]")
    store = OntologyStore()
    dcs = store.dcs
    merged = sum(1 for r in table if r["归并方式"] != em.KIND_RENAME)
    check(len(dcs.equipment) == len(raw.equipment) - merged, f"设备 {len(raw.equipment)} → {len(dcs.equipment)}")
    check(len(dcs.tags) == len(raw.tags) and sum(len(e["tagIds"]) for e in dcs.equipment.values())
          == sum(len(e["tagIds"]) for e in raw.equipment.values()), f"DCS 点一个不丢（{len(dcs.tags)}）")
    check(all(t["equipmentId"] is None or t["equipmentId"] in dict.keys(dcs.equipment) for t in dcs.tags.values())
          and all(t["parameterId"] is None or t["parameterId"] in dict.keys(dcs.parameters) for t in dcs.tags.values()),
          "点位都指向合并后的设备与参数，没有悬空引用")

    tank = dcs.equipment_by_owl(":Dev_13_水解罐A")
    alias_names = sorted(a["name"] for a in tank.get("aliases", []))
    check(alias_names == ["A罐", "A罐RB", "水解罐A", "水解罐A1", "水解罐A2"], f"水解罐A 合并了 {len(alias_names)} 种写法：{'、'.join(alias_names)}")
    tags = {dcs.tags[t]["name"] for t in tank["tagIds"]}
    check({"TI_1301A", "XV_1303A_DO", "XV_1302A_DO", "AT_1301A1", "AT_1301A2", "SJGYW_A"} <= tags,
          f"水解罐A 的点位齐全（{len(tags)} 个：搅拌、温度、进料阀、RB 进料阀、双 pH、液位）")
    check(sorted(tank["stations"]) == ["13", "20"], "控制站同时记 13 和 20")
    params = {dcs.parameters[p]["name"]: dcs.parameters[p] for p in tank["parameterIds"]}
    check(len(params["pH"]["tagIds"]) == 2, "两支 pH 电极合并为一个 pH 参数、保留两个位号")
    check("RB进料阀指令" in params and dcs.tag_by_name("XV_1302A_DO")["parameterName"] == "RB进料阀指令",
          "附属点位的参数加前缀区分（RB进料阀指令）")
    check(dcs.tag_by_name("XV_1303A_DO")["sourceEquipmentName"] == "A罐", "点位保留点表原写法，可追溯")

    print("\n[兼容]")
    old_id = ids.equipment_id(":Dev_13_A罐")
    check(dcs.equipment.get(old_id) is tank and dcs.equipment[old_id] is tank and old_id in dcs.equipment, "旧设备 ID 仍能取到合并后的设备")
    check(dcs.equipment_by_owl(":Dev_13_A罐") is tank, "旧 OWL Subject 仍能取到合并后的设备")
    check(tank in dcs.equipment_by_name("A罐"), "旧名称仍能按名称查到")
    check(old_id not in {e["id"] for e in dcs.equipment.values()}, "遍历设备时旧 ID 不再重复出现")
    old_param = ids.parameter_id(":Dev_13_A罐RB", "进料阀指令")
    check(dcs.parameters.get(old_param) is params["RB进料阀指令"], "旧参数 ID 仍能取到合并后的参数")
    renamed = dcs.equipment_by_owl(":Dev_30_A罐")
    check(renamed and renamed["name"] == "双锥干燥罐A", "只改名不合并的设备换成声明的实例名（S16 A罐 → 双锥干燥罐A）")

    print("\n[本体档案]")
    p = am.profile(store, old_id)
    check(p["objectId"] == tank["id"] and p["treePath"] and p["treePath"][-1].endswith(tank["id"]), "用旧 ID 打开档案得到合并后的设备，并能定位到树")
    check(len(p["header"]["aliases"]) == 5 and any("合并" in b for b in p["header"]["badges"]), "档案头部列出已归并的写法")
    inherited = [a for a in p["attributes"] if a.get("inheritedFrom")]
    temp = next(a for a in inherited if a["name"] == "釜内反应温度")
    check([l["tag"] for l in temp["dataLinks"]] == ["TI_1301A"] and temp["groupLinkTotal"] > 1,
          f"继承的「釜内反应温度」只带本台位号 TI_1301A（设备组共 {temp['groupLinkTotal']} 个）")
    check(all({l["tagId"] for l in a["dataLinks"]} <= set(tank["tagIds"]) for a in inherited), "所有继承属性的数据关联都是本台设备的位号")
    hits = am.search(store, "A罐")["items"]
    check(any(h["objectId"] == tank["id"] and "A罐" in h["hint"] for h in hits), "按旧写法搜索能找到合并后的设备")

    print("\n[启用开关]")
    disabled = [dict(r, 启用="否") if r["原设备名"] == "A罐" and r["工段"] == "S11" else r for r in table]
    again = load_dcs(DCS_FILE)
    stats = em.apply(again, disabled)
    check(stats["skipped"] == 1 and ids.equipment_id(":Dev_13_A罐") in dict.keys(again.equipment), "启用=否 的行不归并，A罐 仍是独立设备")

    print("\n[HTTP]")
    try:
        from fastapi.testclient import TestClient

        from backend import main as app_module
    except Exception as exc:  # pragma: no cover
        check(False, f"无法加载应用：{exc}")
        return 1
    app_module._store = store
    client = TestClient(app_module.app)
    r = client.get(f"/api/ontology/equipment/{old_id}")
    check(r.status_code == 200 and r.json().get("name") == "水解罐A", "原有设备接口用旧 ID 返回合并后的设备")
    r = client.get(f"/api/ontology/asset-profile/{old_id}")
    check(r.status_code == 200 and r.json()["objectId"] == tank["id"], "资产档案接口用旧 ID 返回合并后的设备")
    r = client.get("/api/ontology/equipment", params={"keyword": "水解罐A", "limit": 50})
    check(r.status_code == 200 and sum(1 for e in r.json()["items"] if e["name"] == "水解罐A") == 1, "设备列表里 水解罐A 只有一台")

    passed = sum(results)
    print(f"\n通过 {passed} / {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
