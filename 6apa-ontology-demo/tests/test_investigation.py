"""调查知识（原因分类与权重、化验项目、判定规则、漂移口径）、限值版本、化验 / 操作记录代调自测。

    python3 -m tests.test_investigation

本体在进程内起（TestClient）；化验与操作记录要代调模拟 DCS 服务（8900，同时模拟 LIMS 与操作日志），需先启动它。
限值版本的写入测试在临时副本上进行，不改 data/source 下的文件。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app, get_store
from backend.services import limit_versions as lv
from backend.services.process_context import stage_rules, unit_scope

results: list[bool] = []


def check(ok, label):
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    store = get_store()
    c = TestClient(app)

    print("[调查知识]")
    kn = c.get("/api/ontology/investigation-knowledge").json()
    check(kn["available"] and [x["key"] for x in kn["categories"]] == ["人", "机", "料", "法", "环"], "原因分类：人机料法环")
    check(len(kn["weights"]) >= 5 and len(kn["labItems"]) == 2 and len(kn["rules"]) == 2 and len(kn["drift"]) == 3,
          "原因权重、化验项目、判定规则、漂移口径都已加载")
    rule = next(r for r in kn["rules"] if r["id"] == "J-S11-01")
    check(rule["object"] == "反应体系pH" and rule["constantThreshold"] == 0.1 and rule["phases"] == ["反应", "终点判定"],
          "pH 在线—化验规则：对象、阈值、适用阶段")
    check(all(r["status"].startswith("草案") for r in kn["rules"]), "预填条目全部标草案")

    print("[原因分类与权重]")
    ents = {e["name"]: e["id"] for e in store.relations.entities.values()}
    ids = ",".join(ents[n] for n in ("热水阀HV_1301", "氨水调节阀HV_1302", "硼酸溶液温度", "RB进料温度", "压缩空气总管压力", "釜内反应温度"))
    prof = {p["name"]: p for p in c.get("/api/ontology/cause-profile", params={"ids": ids, "names": "人为修改设定值"}).json()["items"]}
    check(prof["热水阀HV_1301"]["category"] == "机" and prof["热水阀HV_1301"]["weight"] == 1.2, "热水阀：机，权重表点名 1.2")
    check(prof["氨水调节阀HV_1302"]["category"] == "机" and "对象类型" in prof["氨水调节阀HV_1302"]["reason"], "执行机构按对象类型归「机」")
    check(prof["硼酸溶液温度"]["category"] == "料" and prof["RB进料温度"]["category"] == "料", "来料、辅料按关键词归「料」")
    check(prof["压缩空气总管压力"]["category"] == "环", "公用工程归「环」")
    check(prof["人为修改设定值"]["category"] == "人", "人为操作归「人」")
    check(prof["釜内反应温度"]["category"] == "法" and "未匹配" in prof["釜内反应温度"]["reason"], "未匹配的按「法」并说明")

    print("[台号对应：点表后缀跳过 I]")
    _, ids_k = unit_scope(store, "水解罐K")
    names = sorted(store.dcs.equipment[i]["name"] for i in ids_k)
    check(names == ["氨水计量罐L", "水解罐K"], f"水解罐K ↔ 氨水计量罐L：{names}")
    rules_k = c.get("/api/ontology/水解罐K/judgement-rules").json()
    r1 = next(r for r in rules_k["rules"] if r["id"] == "J-S11-01")
    check(r1["onlineTagResolved"]["tag"] == "AT_1301L1" and r1["onlineTagResolved"]["resolved"], "判定规则 {x} 按本台实际位号落到 AT_1301L1")
    sr = stage_rules(store, "水解罐K")
    tags = {r["tag"] for s in sr["stages"] for r in s["rules"]}
    check({"P_1303K_RUN", "XV_1304L_VAL2", "XV_1308K_FT"} <= tags, "阶段识别位号：搅拌 K、氨水阀 L、出料 K（与点表一致）")
    sr_i = stage_rules(store, "水解罐I")
    check(set(sr_i["unresolved"]) == {"P_1303{x}_RUN", "XV_1308{x}_FT"} and "缺少识别位号" in sr_i["note"],
          "水解罐I 点表缺搅拌运行与出料流量点：标为未落位")

    print("[化验（LIMS 代调）]")
    labs = c.get("/api/ontology/水解罐C/lab-results", params={"item": "PH"})
    d = labs.json()
    check(labs.status_code == 200 and d["total"] >= 6 and all(r["itemCode"] == "PH" for r in d["items"]), f"水解罐C pH 化验 {d.get('total')} 条")
    check(all(r["property"] == "反应体系pH" and "±2" in r["alignment"] for r in d["items"]), "化验项目对应到工艺属性与对齐方式")
    check(d["dataSource"]["sourceType"] == "LIMS" and d["dataSource"]["simulated"] is True, "标明来源 LIMS，模拟")
    r = c.post("/api/ontology/水解罐C/lab-results", json={"itemCode": "PH", "value": 7.83, "enteredBy": "自测", "note": "test_investigation"})
    check(r.status_code == 200 and r.json()["created"]["source"] == "人工录入" and r.json()["created"]["batchNo"], "人工录入写入 LIMS，并按取样时间落到批次")
    r = c.post("/api/ontology/水解罐C/lab-results", json={"itemCode": "PH", "value": 7.8})
    check(r.status_code == 400 and "录入人" in r.json()["detail"], "缺录入人 → 400")
    r = c.post("/api/ontology/水解罐C/lab-results", json={"itemCode": "XX", "value": 1, "enteredBy": "a"})
    check(r.status_code == 400 and "未在本体登记" in r.json()["detail"], "化验项目未登记 → 400")

    print("[操作记录（DCS 操作日志代调）]")
    found = None
    for unit in ("水解罐A", "水解罐B", "水解罐C", "水解罐D", "水解罐E", "水解罐K"):
        items = c.get(f"/api/ontology/{unit}/operations").json()["items"]
        found = next((o for o in items if o["kind"] == "设定值修改" and o["param"] == "温度设定值"), None) or found
        if found:
            break
    check(found is not None, "近 3 天能查到温度设定值修改")
    if found:
        check(found["shift"] and found["properties"] == ["釜内反应温度"] and found["station"], "操作记录附班次、对应工艺属性、操作站")

    print("[限值版本]")
    original = lv.VERSION_FILE
    before = original.read_bytes()
    tmp = Path(tempfile.mkdtemp()) / original.name
    shutil.copy(original, tmp)
    lv.VERSION_FILE = tmp
    try:
        v = c.get("/api/ontology/process-limits/PL002/versions").json()
        check([x["id"] for x in v["items"]] == ["PL002-V0", "PL002-V1", "PL002-V2"] and v["items"][0]["base"], "PL002：V0 + 两个条件版本")
        v2 = v["items"][2]
        check(v2["sourceType"] == "模型最优值±差值" and v2["normalLow"] == 7.75 and v2["normalHigh"] == 8.15, "模型最优值 ± 差值算出正常区间")

        def eff(limit, **q):
            return c.get(f"/api/ontology/process-limits/{limit}/effective", params=q).json()

        check(eff("PL002", at="2026-11-01 00:00:00", enzymeBatchCount=100)["version"]["id"] == "PL002-V2", "换酶后 100 批 → V2")
        check(eff("PL002", at="2026-11-01 00:00:00", enzymeBatchCount=900)["version"]["id"] == "PL002-V1", "换酶后 900 批 → V1")
        check(eff("PL002", at="2026-10-01 00:00:00", enzymeBatchCount=100)["version"]["id"] == "PL002-V0", "V2 生效之前 → V0")
        check(eff("PL002", at="2026-11-01 00:00:00")["version"]["id"] == "PL002-V0", "不知道换酶后批次数 → 带批次条件的版本不匹配")
        r = c.post("/api/ontology/process-limits/PL001/versions",
                   json={"normalLow": 33.2, "normalHigh": 35.2, "editor": "自测", "reason": "测试在线修改", "unit": "水解罐C",
                         "effectiveFrom": "2026-11-02 00:00:00"})
        check(r.status_code == 200 and r.json()["created"]["id"] == "PL001-V2", "在线修改 → 追加 PL001-V2")
        e = eff("PL001", at="2026-11-02 12:00:00", unit="水解罐C", enzymeBatchCount=300)
        check(e["version"]["id"] == "PL001-V2" and e["values"]["normalHigh"] == 35.2 and e["values"]["high"] == 35.5,
              "新版本对水解罐C 生效；留空档位沿用 V0")
        check(eff("PL001", at="2026-11-02 12:00:00", unit="水解罐A", enzymeBatchCount=300)["version"]["id"] == "PL001-V0", "其他罐不受影响")
        check(eff("PL001", at="2026-11-01 12:00:00", unit="水解罐C", enzymeBatchCount=300)["version"]["id"] == "PL001-V0",
              "生效时间之前的历史数据仍按旧版本")
        for body, word in (({"normalLow": 36, "normalHigh": 35, "editor": "a", "reason": "b"}, "满足"),
                           ({"normalLow": 33}, "修改人"),
                           ({"sourceType": "模型最优值±差值", "editor": "a", "reason": "b"}, "最优值"),
                           ({"normalLow": 33, "editor": "a", "reason": "b", "unit": "不存在的罐"}, "未找到设备")):
            r = c.post("/api/ontology/process-limits/PL001/versions", json=body)
            check(r.status_code == 400 and word in r.json()["detail"], f"校验：{word}")
        check(c.get("/api/ontology/process-limits/PLXXX/versions").status_code == 404, "不存在的限值 → 404")
    finally:
        lv.VERSION_FILE = original
        lv._cache["mtime"] = None
    check(original.read_bytes() == before, "data/source 下的限值版本表未被测试改动")

    print("[能力与数据源]")
    caps = c.get("/api/ontology/capabilities").json()
    check(caps["registeredCount"] == 7, "已登记能力 7 个（含化验查询 / 录入、操作记录）")
    srcs = {s["sourceType"]: s for s in c.get("/api/ontology/data-sources").json()["sources"]}
    check(srcs["INVESTIGATION_FILE"]["available"] and srcs["LIMIT_VERSION_FILE"]["available"], "数据源清单含调查知识、限值版本")
    prof = c.get("/api/ontology/asset-profile/equip-c0d9670e").json()
    pl1 = next(x for x in prof["constraints"]["operating"] if x["id"] == "PL001")
    check(pl1["versionCount"] == 2 and pl1["conditional"], "档案里的限值带版本数与是否有条件版本")

    print(f"\n{sum(results)} / {len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
