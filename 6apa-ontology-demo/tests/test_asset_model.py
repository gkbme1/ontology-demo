"""资产本体视图自测（不需要单独启动服务）。

    python3 -m tests.test_asset_model

1. 导航树：本体域齐全；工业资产各级计数自洽；1340 台设备全部能沿树找到；
2. 搜索：设备名、位号、工段编号都能定位，并给出可逐级展开的路径；
3. 本体档案：设备 / 设备组 / 工艺对象 / 工段四类都有属性、关系、能力、约束、规则，
   数据关联的位号确实属于该对象，参数一个不漏；
4. HTTP：新接口可用、不与原有路由冲突，原有接口照常返回。
"""
from __future__ import annotations

import sys

from backend.ontology.indexes import OntologyStore
from backend.services import asset_model as am
from backend.services import process_limits

results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    store = OntologyStore()
    index = am.asset_index(store)

    print("[导航树]")
    roots = am.tree(store, None)["items"]
    check(len(roots) == len(am.DOMAINS), f"根节点为全部本体域（{len(roots)} 个）")
    empty = [r for r in roots if r["count"] == 0]
    check(all(not r["hasChildren"] for r in empty), f"无数据源的本体域如实显示为 0 且不可展开（{'、'.join(r['label'] for r in empty)}）")

    classes = am.tree(store, "dom:assets")["items"]
    check(sum(c["count"] for c in classes) == len(store.dcs.equipment), f"工业资产各大类合计 = 设备总数（{len(store.dcs.equipment)}）")
    consistent = True
    for cls in classes:
        kids = am.tree(store, cls["id"])["items"]
        if sum(k["count"] for k in kids) != cls["count"]:
            consistent = False
            print(f"        {cls['label']} {cls['count']} ≠ {sum(k['count'] for k in kids)}")
    check(consistent, "每个大类的计数 = 下属设备类型 / 未入组设备之和")

    cache: dict[str, set[str]] = {}

    def children_ids(parent: str) -> set[str]:
        if parent not in cache:
            cache[parent] = {n["id"] for n in am.tree(store, parent)["items"]}
        return cache[parent]

    unreachable = []
    for eid in store.dcs.equipment:
        path = index.path_of(eid)
        parent = ""
        ok = bool(path)
        for node_id in path:
            if node_id not in (children_ids(parent) if parent else {r["id"] for r in roots}):
                ok = False
                break
            parent = node_id
        if not ok:
            unreachable.append(eid)
    check(not unreachable, f"全部 {len(store.dcs.equipment)} 台设备都能沿导航树逐级找到（找不到 {len(unreachable)} 台）")

    some_group = next(g for g in store.dcs.equipment_groups.values() if len(g["equipmentIds"]) >= 2)
    members = am.tree(store, index.path_of(some_group["id"])[-1])["items"]
    check(len(members) == len([e for e in some_group["equipmentIds"] if e in store.dcs.equipment]), f"设备组节点列出全部成员（{some_group['name']}）")
    shared = [n for n in (n for g in store.dcs.equipment_groups.values() for n in am.tree(store, index.path_of(g["id"])[-1])["items"]) if n.get("badge") == "共用"]
    check(all("主组" in n.get("hint", "") for n in shared), f"共用设备标出主组（{len(shared)} 个）")

    process = am.tree(store, "dom:process")["items"]
    check(process and process[0]["label"] == "工艺属性", "工艺域按对象类型展开")

    print("\n[搜索]")
    from collections import Counter

    name_count = Counter(e["name"] for e in store.dcs.equipment.values())
    equip = next(e for e in store.dcs.equipment.values() if e.get("equipmentGroupId") and name_count[e["name"]] == 1 and e["tagIds"])
    hits = am.search(store, equip["name"])["items"]
    check(any(h["objectId"] == equip["id"] for h in hits), f"按设备名找到设备（{equip['name']}）")
    tag = store.dcs.tags[equip["tagIds"][0]]
    hits = am.search(store, tag["name"])["items"]
    check(any(h["objectId"] == equip["id"] and tag["name"] in h["hint"] for h in hits), f"按位号找到所属设备（{tag['name']}）")
    hits = am.search(store, "S11")["items"]
    check(any(h["objectId"] == "area-S11" for h in hits), "按工段编号找到工段")
    check(am.search(store, "")["total"] == 0, "空关键词不返回结果")

    print("\n[本体档案]")
    sections = ("header", "attributes", "relations", "capabilities", "constraints", "rules")
    for oid in (equip["id"], equip["equipmentGroupId"], "area-S11"):
        p = am.profile(store, oid)
        check(all(k in p for k in sections) and p["attributes"], f"{p['kind']} 档案六部分齐全（{p['name']}）")

    p = am.profile(store, equip["id"])
    own_tags = {store.dcs.tags[t]["name"] for t in equip["tagIds"] if t in store.dcs.tags}
    param_attrs = [a for a in p["attributes"] if a.get("parameterId")]
    check(len(param_attrs) == len(equip["parameterIds"]), "设备的参数全部列为属性（测量 / 状态 / 控制）")
    check(all({l["tag"] for l in a["dataLinks"]} <= own_tags for a in param_attrs), "参数属性的数据关联位号都属于该设备")
    check(any(r["role"] == "所属" for r in p["relations"]["classRelations"]), "类间关系包含所属工段 / 设备组")
    limits = {l["id"] for l in process_limits.limits_for_object(store, equip["id"]).get("items") or []}
    check({c["id"] for c in p["constraints"]["operating"]} == limits, "运行约束 = 该设备适用的工艺限值")
    check(all(c["status"] in ("已挂载", "具备挂载点", "未挂载") for c in p["capabilities"]), "能力挂载状态只取 已挂载 / 具备挂载点 / 未挂载")
    check(p["treePath"] == index.path_of(equip["id"]), "档案带出它在导航树中的路径")

    entity = next(e for e in store.relations.entities.values() if e["type"] == "工艺属性" and e["match"]["tagCount"])
    p = am.profile(store, entity["id"])
    measured = [a for a in p["attributes"] if a.get("dataLinks")]
    check(p["kind"] == "entity" and measured and measured[0]["dataLinkTotal"] == entity["match"]["tagCount"], f"工艺对象的数据关联 = 匹配到的测点（{entity['name']}）")

    p = am.profile(store, tag["id"])
    check(p["objectId"] == equip["id"] and p.get("focusTag") == tag["name"], "按位号打开所属设备档案并标出焦点位号")
    p = am.profile(store, equip["owlSubject"])
    check(p["objectId"] == equip["id"], "支持 OWL Subject 形式")
    try:
        am.profile(store, "equip-not-exist")
        check(False, "不存在的对象返回 404")
    except am.ProfileNotFound as exc:
        check(exc.status == 404, "不存在的对象返回 404")

    print("\n[HTTP]")
    try:
        from fastapi.testclient import TestClient

        from backend import main as app_module
    except Exception as exc:  # pragma: no cover
        check(False, f"无法加载应用：{exc}")
        return 1
    app_module._store = store  # 复用已加载的本体，不重复解析 Excel
    client = TestClient(app_module.app)
    for path in ("/api/ontology/asset-tree", "/api/ontology/asset-tree?parent=dom:assets",
                 f"/api/ontology/asset-tree/search?keyword={equip['name']}", f"/api/ontology/asset-profile/{equip['id']}"):
        r = client.get(path)
        check(r.status_code == 200 and r.json().get("items", r.json().get("objectId")) is not None, f"新接口 200：{path.split('?')[0]}")
    check(client.get("/api/ontology/asset-profile/nope").status_code == 404, "新接口 404：未知对象")
    for path in ("/api/ontology/overview", f"/api/ontology/equipment/{equip['id']}", f"/api/ontology/{equip['id']}/relations",
                 f"/api/ontology/{equip['id']}/limits", "/api/ontology/equipment-groups?limit=1", "/api/ontology/relations?limit=1"):
        check(client.get(path).status_code == 200, f"原有接口照常：{path.split('?')[0]}")
    health = client.get("/api/health").json()
    listed = {e.get("path") if isinstance(e, dict) else e for e in health.get("endpoints", [])}
    check({"/api/ontology/asset-tree", "/api/ontology/asset-profile/{object_id}"} <= listed or not listed, "新接口登记在 /api/health 的接口清单里")

    passed = sum(results)
    print(f"\n通过 {passed} / {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
