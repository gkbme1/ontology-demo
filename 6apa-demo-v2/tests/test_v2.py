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
                         ["6A_提取", "6A_脱色", "6A_抽提", "6A_水解", "6A_结晶", "6A_干燥"])
        self.assertTrue(all("children" not in s for s in ws["children"]))  # 第一屏不出现工序 / 设备

    def test_segment_ops_list_devices_and_globals(self):
        r = client.get("/api/v2/nav/segment/SEG-04").json()
        self.assertEqual([o["label"] for o in r["items"]], ["水解A-F", "水解G-K", "水解配置", "萃取"])
        for op in r["items"]:  # 工序下直接是设备组 / 设备
            self.assertTrue(all(c["kind"] in ("group", "equipment") for c in op["children"]))
        g = client.get("/api/v2/nav/space").json()["globals"]
        self.assertEqual([x["label"] for x in g], ["计算组态", "算法库", "工况与根因", "文档提取"])
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
                         ["图纸位置与外观", "参数", "拓扑关系", "参数约束", "现象/工况定义", "根因影响关系",
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


class DocsAndSearchTest(unittest.TestCase):
    def test_docs(self):
        r = client.get("/api/v2/ops/OP-09/documents").json()
        self.assertEqual(r["documents"][0]["id"], "SOP-S11-ALARM-001")
        self.assertEqual(len(r["documents"][0]["extracted"]["procedures"]), 10)

    def test_search_tag(self):
        r = client.get("/api/v2/search", params={"keyword": "AT_1301C1"}).json()
        self.assertEqual(r["items"][0]["opId"], "OP-09")

    def test_pending_category(self):
        self.assertTrue(client.get("/api/v2/nav/domain/energy").json()["pending"])


if __name__ == "__main__":
    unittest.main()
