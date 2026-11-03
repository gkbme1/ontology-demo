"""能力登记与挂载自测（不需要单独启动服务）。

    python3 -m tests.test_capabilities

1. 能力表：只登记外部系统提供的能力；已登记的给出真实端点，待登记的不虚构端点；不含 Agent 工具；
2. 挂载：对象上的能力 = 能力描述 + 调用契约 + 参数绑定；位号绑定只取本对象的点，必填参数绑不上的能力不显示；
3. 越限判断归入约束（按当前值校验），不再出现在能力里；
4. HTTP：/api/ontology/capabilities 返回登记表，数据源清单里有能力表。
"""
from __future__ import annotations

import sys

from backend.ontology.indexes import OntologyStore
from backend.services import asset_model as am
from backend.services import capability_loader as cl
from backend.services.timeseries import node_id_for

results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    store = OntologyStore()
    caps = store.capability_set

    print("[能力表]")
    check(caps.available and len(caps.items) >= 6 and not caps.issues, f"{cl.CAPABILITY_FILE_NAME} 加载 {len(caps.items)} 项能力，无绑定错误")
    registered = [c for c in caps.items if c["registration"] == cl.STATUS_REGISTERED]
    check({c["name"] for c in registered} == {"实时值查询", "历史值查询", "罐批次查询", "班次查询"},
          "已登记的是实时库 / 历史库 / EBR / MOM 四个接口")
    check(all(c["endpoint"] for c in registered) and not any(c["endpoint"] for c in caps.items if c not in registered),
          "已登记的有端点，待登记的不虚构端点")
    names = {c["name"] for c in caps.items}
    check(not names & {"异常溯源", "越限判断", "计算"} and not any("investigate" in c["endpoint"] for c in caps.items),
          "不登记 Agent 分析工具 / 计算模块，越限判断不作为能力")

    print("\n[挂载]")
    tank = store.dcs.equipment_by_owl(":Dev_13_水解罐A")
    p = am.profile(store, tank["id"])
    by_name = {c["name"]: c for c in p["capabilities"]}
    rt = by_name.get("实时值查询")
    node_ids = rt and rt["parameters"][0]["bound"]
    own = {node_id_for(store.dcs.tags[t]) for t in tank["tagIds"]}
    check(rt and rt["status"] == cl.MOUNT_CALLABLE and node_ids["total"] == len(tank["tagIds"]) and set(node_ids["values"]) <= own,
          f"水解罐A 实时值查询可调用，nodeIds 绑定本台 {node_ids and node_ids['total']} 个位号")
    check(rt["endpoint"].endswith("/api/hsm-db-rtserver/v1/rtdata/node/read") and rt["gateway"] == f"GET /api/ontology/{tank['id']}/realtime",
          "给出提供方端点与本体代调入口")
    hist = by_name["历史值查询"]
    start = next(x for x in hist["parameters"] if x["name"] == "startTime")
    check(start["required"] and start["bound"]["bound"] is None, "时间窗参数标为调用方提供")
    onoff = by_name.get("启停 / 开关")
    onoff_tags = onoff and onoff["parameters"][0]["bound"]["values"]
    check(onoff and onoff["status"] == cl.MOUNT_PENDING and onoff["preconditions"] and "P_1303A_DO" in onoff_tags,
          "启停：提供方待登记，写明前置条件，target 绑定到本台启停点")
    check("调节" not in by_name, "水解罐A 没有调节输出点，调节能力不适用、不显示")
    check("越限判断" not in by_name and p["constraints"]["check"]["available"]
          and p["constraints"]["check"]["endpoint"] == f"/api/ontology/{tank['id']}/limit-check",
          "越限判断在约束里（按当前值校验），不在能力里")
    rules = by_name["规则诊断"]["parameters"][1]["bound"]
    check(rules["total"] == len(p["rules"]), f"规则诊断的 ruleIds 绑定本对象适用的 {rules['total']} 条规则")
    pump = next(e for e in store.dcs.equipment.values() if e["name"] == "滤液泵A")
    pump_caps = {c["name"] for c in am.profile(store, pump["id"])["capabilities"]}
    check("机理 / 时序模型预测" not in pump_caps, "滤液泵A 没有过程测量点，模型预测能力不适用")
    area = am.profile(store, "area-S11")
    check({c["name"] for c in area["capabilities"]} == {"实时值查询", "历史值查询", "班次查询", "规则诊断"}, "工段只挂适用于工段的能力（含班次）")

    print("\n[HTTP]")
    try:
        from fastapi.testclient import TestClient

        from backend import main as app_module
    except Exception as exc:  # pragma: no cover
        check(False, f"无法加载应用：{exc}")
        return 1
    app_module._store = store
    client = TestClient(app_module.app)
    r = client.get("/api/ontology/capabilities").json()
    check(r["total"] == len(caps.items) and r["registeredCount"] == 4, "/api/ontology/capabilities 返回能力登记表")
    sources = client.get("/api/ontology/data-sources").json()["sources"]
    check(any(s["file"] == cl.CAPABILITY_FILE_NAME and s["available"] for s in sources), "数据源清单里有能力登记表")
    check(client.get("/api/ontology/overview").json()["capabilityCount"] == len(caps.items), "概览的能力数取自登记表")

    passed = sum(results)
    print(f"\n通过 {passed} / {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
