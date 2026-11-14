"""v2 回归测试（不需要外部服务）。

    cd 6apa-demo-v2 && python3 -m unittest tests.test_v2 -v

运行时编辑写到临时目录（V2_STORE_DIR），不碰 data/store。
"""
from __future__ import annotations

import os
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="v2-store-")
os.environ["V2_STORE_DIR"] = _TMP

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.v2.context import get_ctx  # noqa: E402
from backend.v2.phenomena import ValidationError, rule_text, validate_rule  # noqa: E402

client = TestClient(app)
CTX = get_ctx()


def _equip(name: str) -> str:
    return next(e for e, x in CTX.store.dcs.equipment.items() if x["name"] == name)


def _group(prefix: str) -> str:
    return next(g for g, x in CTX.store.dcs.equipment_groups.items() if x["name"].startswith(prefix))


class HierarchyTest(unittest.TestCase):
    def test_first_screen_only_workshop_and_segments(self):
        r = client.get("/api/v2/nav/space").json()
        ws = r["items"][0]
        self.assertEqual(ws["label"], "105车间")
        self.assertEqual([s["label"] for s in ws["children"]],
                         ["6A_提取", "6A_脱色", "6A_抽提", "6A_水解", "6A_结晶", "6A_干燥",
                          "计算组态", "算法库", "工况与根因", "文档提取", "一致性校验", "发布与导出"])  # 全局节点挂在车间下、工艺段之后
        self.assertTrue(all("children" not in s for s in ws["children"]))  # 第一屏不出现工序 / 设备

    def test_segment_ops_list_devices_and_globals(self):
        r = client.get("/api/v2/nav/segment/SEG-04").json()
        self.assertEqual([o["label"] for o in r["items"]], ["水解A-F", "水解G-K", "水解配置", "萃取"])
        for op in r["items"]:  # 工序下直接是设备组 / 设备
            self.assertTrue(all(c["kind"] in ("group", "equipment") for c in op["children"]))
        g = client.get("/api/v2/nav/space").json()["globals"]
        self.assertEqual([x["label"] for x in g], ["计算组态", "算法库", "工况与根因", "文档提取", "一致性校验", "发布与导出"])
        r1 = client.get("/api/v2/nav/segment/SEG-01").json()
        self.assertEqual([o["label"] for o in r1["items"]], ["提取_RSE200", "提取_RSE300", "水洗", "稀硫酸配置", "破乳剂配置"])

    def test_hydrolysis_split_by_tank(self):
        h = CTX.hierarchy
        tank = _group("水解反应釜组")
        af = {CTX.store.dcs.equipment[e]["name"] for e in h.op_group_members[("OP-09", tank)]}
        gk = {CTX.store.dcs.equipment[e]["name"] for e in h.op_group_members[("OP-10", tank)]}
        self.assertTrue({"水解罐A", "水解罐F"} <= af)
        self.assertTrue({"水解罐G", "水解罐K"} <= gk)
        self.assertFalse(af & gk)

    def test_group_is_folder_in_both_ops(self):
        tank = _group("水解反应釜组")
        self.assertEqual(sorted(CTX.hierarchy.ops_of_group[tank]), ["OP-09", "OP-10"])


class TabsTest(unittest.TestCase):
    def test_ten_tabs(self):
        eid = _equip("水解罐C")
        head = client.get(f"/api/v2/objects/{eid}?op=OP-09").json()
        self.assertEqual([t["label"] for t in head["tabs"]],
                         ["图纸位置与外观", "参数", "参数约束", "拓扑关系", "现象/工况定义", "根因影响关系",
                          "工艺影响关系", "计算组态", "处置规程"])
        for t in head["tabs"]:
            r = client.get(f"/api/v2/objects/{eid}/tabs/{t['key']}?op=OP-09")
            self.assertEqual(r.status_code, 200, t["key"])

    def test_instruments_and_inherited_phenomena(self):
        eid = _equip("水解罐C")
        r = client.get(f"/api/v2/objects/{eid}/tabs/parameters").json()
        tags = {l["tag"] for x in r["items"] for l in x["links"]}
        self.assertTrue({"AT_1301C1", "AT_1301C2", "TI_1301C"} <= tags)
        self.assertEqual(len(tags), len(CTX.tags_of_equipment[eid]))  # 仪表并入后一个测点都不少
        design = [x for x in r["items"] if x["group"] == "设计参数"]
        self.assertIn("材质", {x["name"] for x in design})
        self.assertTrue(all(x["pending"] for x in design))  # 未填写，显示待补充，不编造
        phen = client.get(f"/api/v2/objects/{eid}/tabs/phenomena").json()["items"]
        names = {p["name"]: p["origin"] for p in phen}
        self.assertEqual(names.get("水解罐pH偏高"), "继承自设备组")

    def test_constraints_link_to_condition_phenomena(self):
        r = client.get(f"/api/v2/objects/{_equip('水解罐C')}/tabs/constraints").json()
        self.assertNotIn("structure", r)  # 结构约束检查已去掉
        pl = {c["id"]: c for c in r["operating"]}
        self.assertEqual(pl["PL001"]["modePhenomenon"]["name"], "工况·水解反应期")
        conds = {v["id"]: (v["phenomenon"] or {}).get("name") for v in pl["PL001"]["versions"]}
        self.assertEqual(conds["PL001-V1"], "换酶后第 801～∞ 批")
        self.assertEqual(conds["PL001-V0"], "换酶后第 1～800 批")  # 基础版本覆盖其余批次
        self.assertTrue(pl["PL001"]["inherited"])
        # 引用的工况现象出现在本台的现象定义里（继承自设备组）
        phen = {p["id"]: p for p in client.get(f"/api/v2/objects/{_equip('水解罐C')}/tabs/phenomena").json()["items"]}
        self.assertIn(pl["PL001"]["modePhenomenon"]["id"], phen)
        self.assertTrue(phen[pl["PL001"]["modePhenomenon"]["id"]]["inherited"])

    def test_inherit_flags_on_all_tabs(self):
        eid = _equip("水解罐C")
        for key, field in (("parameters", "items"), ("constraints", "operating"), ("topology", "items"),
                           ("phenomena", "items"), ("causal", "links"), ("influence", "items"), ("calc", "items")):
            items = client.get(f"/api/v2/objects/{eid}/tabs/{key}").json()[field]
            self.assertTrue(items, key)
            self.assertTrue(all("inherited" in x for x in items), key)

    def test_group_drawing_members_filtered_by_op(self):
        gid = _group("水解反应釜组")
        r = client.get(f"/api/v2/objects/{gid}/tabs/drawing?op=OP-10").json()
        self.assertTrue(all(m["name"] not in ("水解罐A", "水解罐B") for m in r["members"]))

    def test_drawing(self):
        d = client.get("/api/v2/ops/OP-09/drawing").json()
        self.assertTrue(d["nodes"] and d["edges"])
        self.assertEqual(d["subSteps"][0], "RB进料")


class ImageDrawingTest(unittest.TestCase):
    def test_op09_has_image_with_resolved_hotspots(self):
        img = client.get("/api/v2/ops/OP-09/drawing").json()["image"]
        self.assertEqual((img["width"], img["height"]), (1733, 890))
        self.assertEqual(img["unresolved"], [])
        spots = {h["name"]: h for h in img["hotspots"]}
        self.assertEqual(spots["水解罐C"]["objectId"], _equip("水解罐C"))
        self.assertEqual(spots["水解罐C"]["groupId"], _group("水解反应釜组"))
        self.assertTrue(spots["硼酸罐A"]["otherOp"])  # 画面上有，点表归属 水解配置
        self.assertEqual(client.get(img["url"]).status_code, 200)

    def test_other_ops_fall_back_to_schematic(self):
        self.assertIsNone(client.get("/api/v2/ops/OP-10/drawing").json()["image"])
        self.assertEqual(client.get("/api/v2/drawings/OP-10/image").status_code, 404)


class RuleTest(unittest.TestCase):
    def test_validate(self):
        with self.assertRaises(ValidationError):
            validate_rule({"type": "group", "op": "XOR", "children": []})
        with self.assertRaises(ValidationError):
            validate_rule({"type": "condition", "subject": {"kind": "parameter", "name": "x"}, "operator": ">",
                           "threshold": {"kind": "limit", "limitId": "PL001"}})
        validate_rule({"type": "group", "op": "OR", "children": [
            {"type": "condition", "subject": {"kind": "tag", "tag": "TI_1303"}, "operator": ">",
             "threshold": {"kind": "value", "value": 1}, "durationSec": 60},
            {"type": "group", "op": "AND", "children": [
                {"type": "condition", "subject": {"kind": "parameter", "name": "搅拌运行"}, "operator": "change",
                 "from": 1, "to": 0}]}]})

    def test_context_subject(self):
        rule = {"type": "condition", "subject": {"kind": "context", "name": "换酶后批次数"}, "operator": ">=",
                "threshold": {"kind": "value", "value": 801}}
        validate_rule(rule)
        r = client.post("/api/v2/rules/evaluate", json={"anchorId": _group("水解反应釜组"), "rule": rule, "hours": 1}).json()
        self.assertEqual(r["results"][0]["conditions"][0]["status"], "无法判定")

    def test_rule_text(self):
        text = rule_text(CTX.phen.get("PH-S11-03")["rule"], CTX.limits)
        self.assertIn("PL002 正常上限（8.2）", text)
        self.assertIn("持续 1 分钟", text)

    def test_evaluate_per_tank(self):
        r = client.post("/api/v2/phenomena/PH-S11-03/evaluate", json={"hours": 6, "opId": "OP-10"}).json()
        self.assertTrue(r["dataSource"]["simulated"])
        self.assertEqual([x["targetName"] for x in r["results"]], ["水解罐G", "水解罐H", "水解罐I", "水解罐J", "水解罐K"])
        self.assertTrue(all(c["tags"] for x in r["results"] for c in x["conditions"]))

    def test_evaluate_is_deterministic(self):
        body = {"hours": 3, "opId": "OP-09"}
        a = client.post("/api/v2/phenomena/PH-S11-06/evaluate", json=body).json()
        b = client.post("/api/v2/phenomena/PH-S11-06/evaluate", json=body).json()
        self.assertEqual([x["events"] for x in a["results"]], [x["events"] for x in b["results"]])

    def test_duration_hold(self):
        rule = {"type": "condition", "subject": {"kind": "tag", "tag": "TI_1303"}, "operator": ">",
                "threshold": {"kind": "value", "value": -1000}, "durationSec": 600}
        r = client.post("/api/v2/rules/evaluate", json={"anchorId": _equip("水解罐C"), "rule": rule, "hours": 1}).json()
        res = r["results"][0]
        self.assertEqual(res["eventCount"], 1)
        self.assertAlmostEqual(res["totalMinutes"], 61 - 9, delta=1)  # 前 9 分钟还没满 10 分钟

    def test_calc_reference_in_rule(self):
        r = client.post("/api/v2/phenomena/PH-S11-05/evaluate", json={"hours": 2, "opId": "OP-09"}).json()
        self.assertGreaterEqual(len(r["results"]), 6)

    def test_no_rule_cannot_evaluate(self):
        self.assertEqual(client.post("/api/v2/phenomena/PH-S11-23/evaluate", json={}).status_code, 400)


class CausalTest(unittest.TestCase):
    def test_chain_up(self):
        r = client.get("/api/v2/phenomena/PH-S11-23/chain?direction=up").json()
        self.assertIn("PH-S11-07", r["levels"])  # 搅拌非指令停机 → 反应期搅拌停止 → 终点异常
        self.assertEqual(r["levels"]["PH-S11-06"], 1)
        self.assertEqual(r["levels"]["PH-S11-07"], 2)

    def test_crud_roundtrip(self):
        gid = _group("水解反应釜组")
        rule = {"type": "condition", "subject": {"kind": "parameter", "name": "釜内反应温度"}, "operator": ">",
                "threshold": {"kind": "limit", "limitId": "PL001", "field": "normalHigh"}, "durationSec": 60}
        p = client.post("/api/v2/phenomena", json={"name": "测试现象", "category": "工艺",
                                                    "anchor": {"kind": "group", "id": gid, "name": "x"}, "rule": rule}).json()
        self.assertTrue(p["id"].startswith("PH-U-"))
        link = client.post("/api/v2/causal-links", json={"cause": p["id"], "effect": "PH-S11-23"}).json()
        self.assertEqual(client.post("/api/v2/causal-links", json={"cause": p["id"], "effect": "PH-S11-23"}).status_code, 400)
        self.assertEqual(client.post("/api/v2/causal-links", json={"cause": p["id"], "effect": p["id"]}).status_code, 400)
        upd = client.put(f"/api/v2/phenomena/{p['id']}", json={"name": "测试现象2"}).json()
        self.assertEqual(upd["name"], "测试现象2")
        r = client.delete(f"/api/v2/phenomena/{p['id']}").json()
        self.assertEqual(r["removedLinks"], [link["id"]])
        self.assertTrue(os.path.exists(os.path.join(_TMP, "phenomena.json")))


class CalcTest(unittest.TestCase):
    def test_run_level_consumption(self):
        r = client.post("/api/v2/calculations/CALC-S11-02/run", json={"hours": 2, "opId": "OP-09"}).json()
        self.assertEqual(len(r["results"]), 6)
        self.assertTrue(all(x["min"] >= 0 for x in r["results"]))  # 只计下降量，速率不为负

    def test_calc_must_reference_registered_algorithm(self):
        bad = {"name": "x", "anchor": {"id": _group("水解反应釜组")}, "algorithmId": "ALG-NOT-EXIST", "bindings": {}}
        self.assertEqual(client.post("/api/v2/calculations", json=bad).status_code, 400)
        missing = {"name": "x", "anchor": {"id": _group("水解反应釜组")}, "algorithmId": "ALG-ABS-DIFF",
                   "bindings": {"a": {"kind": "parameter", "name": "反应体系pH", "index": 0}}}
        self.assertEqual(client.post("/api/v2/calculations", json=missing).status_code, 400)  # b 未绑定

    def test_cross_device_calc(self):
        r = client.post("/api/v2/calculations/CALC-G-02/run", json={"hours": 2}).json()
        self.assertEqual(r["results"][0]["targetName"], "6A_水解")
        self.assertEqual(len(r["results"][0]["inputs"][0]["tags"]), 11)  # 11 台水解罐的罐温

    def test_scope_views(self):
        c = client.get("/api/v2/scope/conditions", params={"seg": "SEG-04"}).json()
        self.assertTrue(c["phenomena"] and c["links"])
        calcs = client.get("/api/v2/scope/calculations", params={"op": "OP-09"}).json()["items"]
        self.assertIn("CALC-G-01", {x["id"] for x in calcs})  # 工艺段级组态也出现在其工序的筛选里
        self.assertTrue(all(x["algorithm"]["id"] for x in calcs))
        algos = client.get("/api/v2/algorithms").json()["items"]
        self.assertTrue(any(a["usedBy"] for a in algos))


class StatusAndCycleTest(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(client.get("/api/v2/meta").json()["statuses"], ["草案·待工艺确认", "生效", "停用"])

    def test_cycle_warning(self):
        ctx = get_ctx()
        link = next(iter(ctx.phen.links.values()))
        r = client.post("/api/v2/causal-links", json={"cause": link["effect"], "effect": link["cause"], "confidence": "低"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["inCycle"])
        self.assertTrue(body["warnings"][0].startswith("形成因果环路"))
        chain = client.get(f"/api/v2/phenomena/{link['cause']}/chain").json()
        self.assertTrue(any(l["inCycle"] for l in chain["graph"]["links"]))
        client.delete(f"/api/v2/causal-links/{body['id']}")
        self.assertFalse(any(l["inCycle"] for l in client.get("/api/v2/causal-links").json()["items"]))


class Batch2Test(unittest.TestCase):
    """第 2 批：参数类别与绑定状态、继承覆盖、人工关系、基础信息与变更记录。"""

    def test_parameter_categories_and_binding(self):
        r = client.get(f"/api/v2/objects/{_equip('水解罐C')}/tabs/parameters").json()
        self.assertEqual(r["attrGroups"], ["基本信息", "设计参数"])
        self.assertTrue(set(r["paramGroups"]) <= {"测量值", "设定值", "阀位", "控制指令", "状态", "计算值"})
        params = [x for x in r["items"] if x["section"] == "参数"]
        self.assertTrue(all(x["binding"] in ("已绑定", "待确认", "未绑定", "失效") for x in params))
        temp = next(x for x in params if x["name"] == "釜内反应温度")
        self.assertEqual((temp["category"], temp["binding"]), ("测量值", "待确认"))
        self.assertTrue(all(x["binding"] is None for x in r["items"] if x["section"] == "属性"))

    def test_override_phenomenon_and_limit(self):
        import copy
        eid = _equip("水解罐C")
        rule = copy.deepcopy(get_ctx().phen.get("PH-S11-01")["rule"])
        rule["children"][0]["threshold"] = {"kind": "value", "value": 33.5}
        self.assertEqual(client.put(f"/api/v2/objects/{eid}/overrides/phenomena/PH-S11-01", json={"rule": rule}).status_code, 200)
        row = next(x for x in client.get(f"/api/v2/objects/{eid}/tabs/phenomena").json()["items"] if x["id"] == "PH-S11-01")
        self.assertEqual(row["inheritState"], "已覆盖")
        self.assertIn("33.5", row["ruleText"])
        ev = client.post("/api/v2/phenomena/PH-S11-01/evaluate", json={"opId": "OP-09"}).json()
        mine = next(x for x in ev["results"] if x["targetId"] == eid)
        self.assertIn("覆盖", mine["overrideNote"])
        # 禁用 → 本台不判定；恢复继承
        client.put(f"/api/v2/objects/{eid}/overrides/phenomena/PH-S11-01", json={"disabled": True})
        ev = client.post("/api/v2/phenomena/PH-S11-01/evaluate", json={"opId": "OP-09"}).json()
        self.assertTrue(next(x for x in ev["results"] if x["targetId"] == eid)["disabled"])
        client.delete(f"/api/v2/objects/{eid}/overrides/phenomena/PH-S11-01")
        row = next(x for x in client.get(f"/api/v2/objects/{eid}/tabs/phenomena").json()["items"] if x["id"] == "PH-S11-01")
        self.assertNotIn("inheritState", row)
        # 限值：顺序校验、覆盖后显示模板值
        bad = client.put(f"/api/v2/objects/{eid}/overrides/limits/PL001", json={"values": {"normalHigh": 40, "high": 35}})
        self.assertEqual(bad.status_code, 400)
        client.put(f"/api/v2/objects/{eid}/overrides/limits/PL001", json={"values": {"normalHigh": 34}})
        lim = next(x for x in client.get(f"/api/v2/objects/{eid}/tabs/constraints").json()["operating"] if x["id"] == "PL001")
        self.assertEqual(lim["inheritState"], "已覆盖")
        self.assertTrue(lim["template"]["normal"].endswith("35.0"))
        client.delete(f"/api/v2/objects/{eid}/overrides/limits/PL001")
        # 不属于设备组的对象不能覆盖
        self.assertEqual(client.put(f"/api/v2/objects/{_group('水解反应釜组')}/overrides/limits/PL001", json={"disabled": True}).status_code, 400)

    def test_user_relations(self):
        gid, eid = _group("水解反应釜组"), _equip("水解罐C")
        util = client.get("/api/v2/relation-candidates", params={"type": "供应", "end": "from", "keyword": "蒸汽"}).json()["items"][0]
        self.assertEqual(util["kind"], "utility")
        bad = client.post("/api/v2/relations", json={"type": "供应", "from": {"id": gid}, "to": {"id": eid}})
        self.assertEqual(bad.status_code, 400)  # 供应的起点只能是公用介质
        rel = client.post("/api/v2/relations", json={"type": "供应", "from": {"id": util["id"]}, "to": {"id": gid}}).json()
        topo = client.get(f"/api/v2/objects/{eid}/tabs/topology").json()["items"]
        mine = [x for x in topo if x.get("relationId") == rel["id"]]
        self.assertTrue(mine and mine[0]["inherited"])  # 挂在设备组上，设备上显示为继承
        info = client.get(f"/api/v2/objects/{gid}/info").json()
        self.assertTrue(any(r["id"] == rel["id"] for r in info["referencedBy"]["relations"]))
        self.assertEqual(client.delete(f"/api/v2/relations/{rel['id']}").status_code, 200)

    def test_info_and_audit(self):
        eid = _equip("水解罐C")
        client.put(f"/api/v2/objects/{eid}/overrides/phenomena/PH-S11-02", json={"disabled": True})
        client.delete(f"/api/v2/objects/{eid}/overrides/phenomena/PH-S11-02")
        info = client.get(f"/api/v2/objects/{eid}/info").json()
        self.assertEqual(info["kind"], "设备")
        self.assertEqual(info["group"]["id"], _group("水解反应釜组"))
        ops = [c["op"] for c in info["changes"][:2]]
        self.assertEqual(ops, ["恢复继承", "禁用继承"])


class Batch3Test(unittest.TestCase):
    """第 3 批：处置规程拆分与编辑、计算组态执行设置与编辑。"""

    def test_procedure_view_and_split(self):
        gid = _group("水解反应釜组")
        cards = client.get(f"/api/v2/objects/{gid}/tabs/procedures").json()["items"]
        card = next(c for c in cards if c["id"] == "ARP-S11-01")
        states = {c["seq"]: c["splitState"] for c in card["causes"]}
        self.assertEqual(states["6"], "已拆分")  # 种子：反应期搅拌停止 → 水解罐温度偏高（依据 ARP-S11-01 可能原因 6）
        self.assertTrue(all(k in card["steps"][0] for k in ("precondition", "expected", "caution", "manualConfirm")))
        self.assertTrue(any(k["when"] == "处置后" for k in card["checks"]))
        seq = next(c["seq"] for c in card["causes"] if c["splitState"] == "未拆分")
        r = client.post(f"/api/v2/procedures/ARP-S11-01/causes/{seq}/split", json={"anchorId": gid}).json()
        self.assertEqual(next(c for c in r["card"]["causes"] if c["seq"] == seq)["splitState"], "已拆分")
        link = get_ctx().phen.links[r["link"]]
        self.assertEqual(link["effect"], r["alarm"])
        again = client.post(f"/api/v2/procedures/ARP-S11-01/causes/{seq}/split", json={"anchorId": gid}).json()
        self.assertEqual(again["created"], [])  # 已拆分的不重复建
        procs = client.get(f"/api/v2/phenomena/{r['phenomenon']}").json()["procedures"]
        self.assertEqual(procs[0]["id"], "ARP-S11-01")

    def test_procedure_edit(self):
        card = client.get("/api/v2/procedures/ARP-S11-02").json()
        steps = card["steps"]
        steps[0]["expected"] = "确认真实低温或测点故障"
        r = client.put("/api/v2/procedures/ARP-S11-02", json={"steps": steps, "version": "V1.1"}).json()
        self.assertEqual((r["steps"][0]["expected"], r["version"], r["edited"]), ("确认真实低温或测点故障", "V1.1", True))
        bad = client.put("/api/v2/procedures/ARP-S11-02", json={"steps": [{"description": ""}]})
        self.assertEqual(bad.status_code, 400)

    def test_calc_execution_and_validation(self):
        gid = _group("水解反应釜组")
        base = {"name": "罐温均值（周期）", "anchor": {"kind": "group", "id": gid}, "algorithmId": "ALG-MEAN",
                "bindings": {"series": {"kind": "parameter", "name": "釜内反应温度"}}}
        self.assertEqual(client.post("/api/v2/calculations", json={**base, "bindings": {"series": {"kind": "const", "value": 1}}}).status_code, 400)
        self.assertEqual(client.post("/api/v2/calculations", json={**base, "bindings": {"series": {"kind": "parameter", "name": "不存在的参数"}}}).status_code, 400)
        self.assertEqual(client.post("/api/v2/calculations", json={**base, "execution": {"mode": "事件触发"}}).status_code, 400)
        c = client.post("/api/v2/calculations", json={**base, "execution": {"mode": "周期", "periodSec": 60},
                                                      "output": {"tag": "CALC_T1301_AVG", "writeBack": True}}).json()
        self.assertEqual(c["execution"]["mode"], "周期")
        client.post(f"/api/v2/calculations/{c['id']}/run", json={"opId": "OP-09"})
        view = next(x for x in client.get(f"/api/v2/objects/{gid}/tabs/calc?op=OP-09").json()["items"] if x["id"] == c["id"])
        self.assertIn("成功", view["runState"])
        client.delete(f"/api/v2/calculations/{c['id']}")


class Batch4Test(unittest.TestCase):
    """第 4 批：发布、对比、回滚、批量状态、Excel / TTL 导出、操作日志。"""

    def test_publish_compare_rollback(self):
        r = client.post("/api/v2/status-batch", json={"kind": "phenomena", "ids": ["PH-S11-05"], "status": "生效"}).json()
        self.assertEqual(r["changed"], 1)
        v1 = client.post("/api/v2/releases", json={"note": "测试发布"}).json()
        self.assertGreaterEqual(v1["stats"]["phenomena"]["published"], 1)
        client.post("/api/v2/status-batch", json={"kind": "phenomena", "ids": ["PH-S11-05"], "status": "停用"})
        cmp = client.get("/api/v2/releases/compare", params={"a": v1["version"], "b": "current"}).json()
        phen = next(g for g in cmp["groups"] if g["kind"] == "phenomena")
        self.assertTrue(any(m["id"] == "PH-S11-05" and any(c["field"] == "status" for c in m["changes"]) for m in phen["modified"]))
        rb = client.post(f"/api/v2/releases/{v1['version']}/rollback", json={"syncDraft": True}).json()
        self.assertEqual(rb["rollbackOf"], v1["version"])
        self.assertEqual(client.get("/api/v2/phenomena/PH-S11-05").json()["status"], "生效")  # 工程态同步回退
        self.assertEqual(client.get("/api/v2/releases").json()["current"]["version"], rb["version"])
        ops = client.get("/api/v2/audit").json()["ops"]
        self.assertTrue({"发布", "回滚", "批量变更状态"} <= set(ops))
        self.assertEqual(client.post("/api/v2/status-batch", json={"kind": "phenomena", "ids": ["PH-S11-05"], "status": "已确认"}).status_code, 400)

    def test_blocking_only_for_effective(self):
        r = client.get("/api/v2/validation").json()
        self.assertTrue(all(not i["blocking"] for i in r["items"] if i["draft"]))
        self.assertEqual(r["publishable"], r["blocking"] == 0)

    def test_export_excel_and_ttl(self):
        from io import BytesIO
        from urllib.parse import unquote
        from openpyxl import load_workbook
        r = client.get("/api/v2/export/excel", params={"seg": "SEG-04"})
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(BytesIO(r.content), read_only=True)
        self.assertTrue({"空间层级", "设备", "参数", "现象", "导致关系", "处置步骤"} <= set(wb.sheetnames))
        t = client.get("/api/v2/export/ttl", params={"seg": "SEG-04"})
        self.assertIn("owl:TransitiveProperty", t.text)
        self.assertIn("@zh", t.text)
        info = __import__("json").loads(unquote(t.headers["x-export-info"]))
        self.assertTrue(info["syntax"].startswith("通过") or info["syntax"].startswith("未自检"))
        self.assertIn("导出", client.get("/api/v2/audit").json()["ops"])


class DocsAndSearchTest(unittest.TestCase):
    def test_docs(self):
        r = client.get("/api/v2/ops/OP-09/documents").json()
        self.assertEqual(r["documents"][0]["id"], "SOP-S11-ALARM-001")
        self.assertEqual(len(r["documents"][0]["extracted"]["procedures"]), 10)

    def test_search_tag(self):
        r = client.get("/api/v2/search", params={"keyword": "AT_1301C1"}).json()
        self.assertEqual(r["items"][0]["opId"], "OP-09")

    def test_search_grouped_and_pinyin(self):
        r = client.get("/api/v2/search", params={"keyword": "sjg"}).json()  # 拼音首字母：水解罐
        labels = [i["label"] for i in r["items"]]
        self.assertIn("水解罐A", labels)
        kinds = [i["kind"] for i in r["items"]]
        self.assertEqual(kinds, sorted(kinds, key=["segment", "op", "group", "equipment", "tag", "phenomenon", "condition",
                                                    "parameter", "stream", "utility", "quality"].index))  # 按类型分组
        r = client.get("/api/v2/search", params={"keyword": "6A_水解"}).json()
        self.assertEqual(r["items"][0]["kind"], "segment")

    def test_validation(self):
        r = client.get("/api/v2/validation").json()
        self.assertEqual(set(r["counts"]), {"错误", "警告", "提示"})
        self.assertEqual(r["publishable"], r["blocking"] == 0)  # 只有生效对象上的错误阻止发布
        self.assertIn("判定规则待定义", r["rules"])
        self.assertTrue(all(i["level"] in ("错误", "警告", "提示") for i in r["items"]))

    def test_tab_counts(self):
        head = client.get(f"/api/v2/objects/{_group('水解反应釜组')}?op=OP-09").json()
        for k in ("parameters", "constraints", "topology", "phenomena", "causal"):
            self.assertGreater(head["counts"].get(k, 0), 0, k)

    def test_pending_category(self):
        self.assertTrue(client.get("/api/v2/nav/domain/energy").json()["pending"])


if __name__ == "__main__":
    unittest.main()
