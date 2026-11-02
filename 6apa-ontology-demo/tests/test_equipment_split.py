"""设备拆分与类 / 实例标注自测（不需要单独启动服务）。

    python3 -m tests.test_equipment_split

1. 拆分表：只拆名字是实例通名的合集，台号覆盖全部实例才拆，误拆样例不出现；
2. 加载：滤液泵 拆成 滤液泵A～F 各 5 个点，参数名去掉台号；拆不开的点留作「…·公共点位」；
3. 兼容：原合集的旧 ID 打开档案转到所属设备组，旧参数 ID 转到拆出的参数，按旧名称能查到拆出的实例；
4. 导航树：设备组标「类」，叶子标出性质，实例在前；工业关系里的「滤液泵A」能匹配到 DCS 实例。
"""
from __future__ import annotations

import sys

from backend.ontology import identifiers as ids
from backend.ontology.indexes import MERGE_FILE, OntologyStore
from backend.services import asset_model as am
from backend.services import equipment_merge as em
from backend.services import equipment_split as es

results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    rows = em.load_table(MERGE_FILE, es.SPLIT_SHEET)
    store = OntologyStore()
    dcs = store.dcs

    print("[拆分表]")
    check(rows and all(r["规则"] in ("描述台号", "序号对应") for r in rows), f"「设备拆分」工作表 {len(rows)} 行，规则只有 描述台号 / 序号对应")
    sources = {r["原设备名"] for r in rows}
    check(not sources & {"丁酯泵", "脱色BA泵", "公用测量管线", "其他工艺单元", "管网阀门系统"}, "只拆实例通名的合集，泵、兜底名称不会被拆给罐")
    descs = {r["位号描述"] for r in rows}
    check(not any("出料泵" in d and d.startswith("脱色罐") for d in descs), "「脱色罐出料泵a/b」两台泵对六台罐，不拆")
    check(not any(d.startswith("冷凝器冷盐水分阀") for d in descs), "「冷凝器冷盐水分阀a～e」与四台冷凝器对不上，不拆")
    check(not any(d.startswith("丁酯罐泵后") for d in descs) and {"丁酯罐液位A", "丁酯罐液位B"} <= descs,
          "两台实例时挂在泵上的 A/B 不拆，丁酯罐液位A/B 照拆")

    print("\n[加载]")
    group = next(g for g in dcs.equipment_groups.values() if g["name"] == "滤液泵组")
    members = [dcs.equipment[e] for e in group["equipmentIds"]]
    check(sorted(e["name"] for e in members) == [f"滤液泵{c}" for c in "ABCDEF"], "滤液泵组下是 滤液泵A～F 六台实例")
    check(all(e["tagCount"] == 5 and e["nature"] == "实例" for e in members), "每台 5 个点，性质都是实例")
    pump_a = next(e for e in members if e["name"] == "滤液泵A")
    names = sorted(dcs.parameters[p]["name"] for p in pump_a["parameterIds"])
    check(names == sorted(["启停指令", "故障", "远控", "运行", "电机控制"]), f"参数名去掉台号：{'、'.join(names)}")
    check({dcs.tags[t]["sourceEquipmentName"] for t in pump_a["tagIds"]} == {"滤液泵"}, "点位保留点表原写法「滤液泵」")
    residual = [e for e in dcs.equipment.values() if e.get("nature") == es.NATURE_SHARED]
    check(residual and all(e["name"].endswith(es.RESIDUAL_SUFFIX) for e in residual),
          f"拆不开的点留作公共点位：{'、'.join(e['name'] for e in residual)}")
    check(all(t["equipmentId"] in dict.keys(dcs.equipment) for t in dcs.tags.values() if t["equipmentId"])
          and all(p["tagIds"] for p in dcs.parameters.values()), "没有悬空的点位，也没有空参数")

    print("\n[兼容]")
    old_id = ids.equipment_id(":Dev_10_滤液泵")
    check(old_id in dcs.equipment_splits and old_id not in dict.keys(dcs.equipment), "原合集「滤液泵」整台拆完后删除，旧 ID 记录在拆分表里")
    p = am.profile(store, old_id)
    check(p["kind"] == "group" and p["objectId"] == group["id"] and p["splitFrom"]["name"] == "滤液泵",
          "用原合集的旧 ID 打开档案，转到所属设备组（类）并说明已拆分")
    old_param = ids.parameter_id(":Dev_10_滤液泵", "a启停指令")
    check(dcs.parameters.get(old_param, {}).get("equipmentId") == pump_a["id"], "旧参数 ID 转到 滤液泵A 的「启停指令」")
    check(pump_a in dcs.equipment_by_name("滤液泵"), "按旧名称「滤液泵」能查到拆出的实例")
    entity = next(e for e in store.relations.entities.values() if e["name"] == "滤液泵A")
    check(entity["match"]["matchStatusLabel"] == "已匹配本体实例", "工业关系里的「滤液泵A」匹配到 DCS 实例")

    print("\n[导航树与档案]")
    index = am.asset_index(store)
    path = index.path_of(pump_a["id"])
    group_node = next(n for n in am.tree(store, path[-3])["items"] if n["id"] == path[-2])
    check(group_node["nature"] == "类" and "类" in group_node["hint"], "设备组节点标为「类」")
    leaves = am.tree(store, path[-2])["items"]
    check(all(n["nature"] == "实例" for n in leaves), "滤液泵组下的叶子都是实例")
    shared = residual[0]
    spath = index.path_of(shared["id"])
    leaves = am.tree(store, spath[-2])["items"]
    natures = [n["nature"] for n in leaves]
    check(es.NATURE_SHARED in natures and natures == sorted(natures, key=lambda n: n != "实例"),
          f"公共点位标出性质并排在实例之后（{shared['name']}）")
    sp = am.profile(store, shared["id"])
    check(sp["header"]["nature"] == es.NATURE_SHARED and not any(r["role"] == "同组实例" for r in sp["relations"]["classRelations"]),
          "公共点位档案标明不是单台设备，不把实例称作「同组实例」")
    gp = am.profile(store, group["id"])
    check(len(gp["instances"]) == 6 and all(i["nature"] == "实例" for i in gp["instances"]), "类档案列出 6 台实例")
    counts = dcs.nature_counts
    check(sum(counts.values()) == len(dcs.equipment), f"每个设备都有性质：{counts}")

    passed = sum(results)
    print(f"\n通过 {passed} / {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
