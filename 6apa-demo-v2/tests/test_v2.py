"""v2 回归测试（北I-2 深冷装置数据，不需要外部服务）。

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


def _group(name: str) -> str:
    return next(g for g, x in CTX.store.dcs.equipment_groups.items() if x["name"] == name)


class HierarchyTest(unittest.TestCase):
    def test_first_screen_only_plant_and_units(self):
        r = client.get("/api/v2/nav/space").json()
        ws = r["items"][0]
        self.assertEqual(ws["label"], "北I-2深冷装置")
        self.assertEqual([s["label"] for s in ws["children"]],
                         ["集配气单元", "压缩单元", "脱水单元", "冷冻分离单元", "轻烃储运单元", "辅助生产单元",
                          "计算组态", "算法库", "工况与根因", "文档提取"])  # 全局节点挂在装置下、单元之后
        self.assertTrue(all("children" not in s for s in ws["children"]))  # 第一屏不出现画面 / 设备

    def test_unit_screens_list_devices(self):
        r = client.get("/api/v2/nav/segment/SEG-04").json()
        self.assertEqual([o["label"] for o in r["items"]], ["冷冻单元", "1号膨胀机", "2号膨胀机", "丙烷机", "APC控制"])
        for op in r["items"]:  # 画面下直接是设备组 / 设备
            self.assertTrue(all(c["kind"] in ("group", "equipment") for c in op["children"]))
        r3 = client.get("/api/v2/nav/segment/SEG-03").json()
        self.assertEqual([o["label"] for o in r3["items"]], ["脱水单元", "三甘醇", "三甘醇尾气回收撬", "导热油炉"])

    def test_expanders_split_by_screen(self):
        """1号 / 2号膨胀机两张画面共用工段 S08，按名称 1# / 2# 认领；设备组是两张画面共用的文件夹。"""
        h, d = CTX.hierarchy, CTX.store.dcs
        grp = _group("膨胀压缩机组")
        one = {d.equipment[e]["name"] for e in h.op_group_members[("OP-08", grp)]}
        two = {d.equipment[e]["name"] for e in h.op_group_members[("OP-09", grp)]}
        self.assertEqual(one, {"1#膨胀压缩机"})
        self.assertEqual(two, {"2#膨胀压缩机"})
        self.assertEqual(sorted(h.ops_of_group[grp]), ["OP-08", "OP-09"])

    def test_screen_only_equipment_present(self):
        """画面上有、点表无测点的设备（4 台除尘器、丙烷机组换热器等）由设备统计声明建成 0 点设备。"""
        for name in ("1#除尘器", "4#除尘器", "丙烷冷凝器", "经济器", "活性炭过滤器"):
            self.assertEqual(CTX.store.dcs.equipment[_equip(name)]["tagCount"], 0, name)

    def test_tags_follow_point_table(self):
        d = CTX.store.dcs
        t = d.tag_by_name("104TT115")
        self.assertEqual((t["equipmentName"], t["parameterName"], t["areaCode"]), ("脱甲烷塔", "顶部温度", "S07"))
        self.assertEqual((t["rangeLow"], t["rangeHigh"]), (-150.0, 50.0))
        # 同组各台参数同名，组上的现象才能逐台判定
        for name in ("1#轻烃储罐", "2#轻烃储罐", "3#轻烃储罐"):
            params = {d.parameters[p]["name"] for p in d.equipment[_equip(name)]["parameterIds"]}
            self.assertIn("轻烃储罐压力", params)


class TabsTest(unittest.TestCase):
    def test_nine_tabs(self):
        eid = _equip("脱甲烷塔")
        head = client.get(f"/api/v2/objects/{eid}?op=OP-07").json()
        self.assertEqual([t["label"] for t in head["tabs"]],
                         ["图纸位置与外观", "参数", "拓扑关系", "参数约束", "现象/工况定义", "根因影响关系",
                          "工艺影响关系", "计算组态", "处置规程"])
        for t in head["tabs"]:
            r = client.get(f"/api/v2/objects/{eid}/tabs/{t['key']}?op=OP-07")
            self.assertEqual(r.status_code, 200, t["key"])

    def test_parameters_and_design(self):
        eid = _equip("脱甲烷塔")
        r = client.get(f"/api/v2/objects/{eid}/tabs/parameters").json()
        tags = {l["tag"] for x in r["items"] for l in x["links"]}
        self.assertTrue({"104TT115", "104PT111", "104LT102", "104PDT104"} <= tags)
        self.assertEqual(len(tags), len(CTX.tags_of_equipment[eid]))
        design = {x["name"]: x for x in r["items"] if x["group"] == "设计参数"}
        self.assertEqual(design["设备位号"]["value"], "T10401")  # 设备位号取画面编号
        self.assertTrue(design["塔径"]["pending"])  # 未填写的显示待补充，不编造

    def test_inherited_phenomena_on_member(self):
        phen = client.get(f"/api/v2/objects/{_equip('2#膨胀压缩机')}/tabs/phenomena").json()["items"]
        names = {p["name"]: p["origin"] for p in phen}
        self.assertEqual(names.get("膨胀机振动高"), "继承自设备组")

    def test_constraints_from_old_sop(self):
        r = client.get(f"/api/v2/objects/{_equip('脱甲烷塔')}/tabs/constraints").json()
        pl = {c["id"]: c for c in r["operating"]}
        lim = CTX.limits["PL-104TT115"]
        self.assertEqual((lim["normalLow"], lim["normalHigh"]), (-79.0, -75.0))
        self.assertIn("PL-104TT115", pl)
        self.assertEqual(CTX.limits["PL-104PT111"]["high"], 1.5)  # 附录二区间与附录四报警值合并成一条
        self.assertTrue(all(l["status"] == "草案·待工艺确认" for l in CTX.limits.values()))

    def test_inherit_flags_on_all_tabs(self):
        eid = _equip("1#膨胀压缩机")
        for key, field in (("parameters", "items"), ("topology", "items"), ("phenomena", "items"),
                           ("causal", "links"), ("calc", "items")):
            items = client.get(f"/api/v2/objects/{eid}/tabs/{key}").json()[field]
            self.assertTrue(items, key)
            self.assertTrue(all("inherited" in x for x in items), key)

    def test_group_drawing_members_filtered_by_op(self):
        r = client.get(f"/api/v2/objects/{_group('膨胀压缩机组')}/tabs/drawing?op=OP-09").json()
        self.assertEqual([m["name"] for m in r["members"]], ["2#膨胀压缩机"])

    def test_schematic(self):
        d = client.get("/api/v2/ops/OP-07/drawing").json()
        self.assertTrue(d["nodes"] and d["edges"])
        self.assertEqual(d["subSteps"][0], "冷箱Ⅰ/Ⅱ换热")


class ImageDrawingTest(unittest.TestCase):
    def test_every_screen_has_image_with_resolved_hotspots(self):
        for op in ("OP-01", "OP-02", "OP-03", "OP-04", "OP-05", "OP-06", "OP-07", "OP-08", "OP-09", "OP-10",
                   "OP-12", "OP-13", "OP-14", "OP-15"):
            img = client.get(f"/api/v2/ops/{op}/drawing").json()["image"]
            self.assertEqual(img["unresolved"], [], op)
            self.assertEqual(client.get(img["url"]).status_code, 200, op)

    def test_hotspots(self):
        img = client.get("/api/v2/ops/OP-07/drawing").json()["image"]
        self.assertEqual((img["width"], img["height"]), (1742, 909))
        spots = {h["name"]: h for h in img["hotspots"]}
        self.assertEqual(spots["脱甲烷塔"]["objectId"], _equip("脱甲烷塔"))
        self.assertEqual(spots["一级贫富气换热器"]["groupId"], _group("冷箱Ⅱ"))
        self.assertFalse(spots["冷冻甲醇罐"]["confirmed"])  # 画面标 D10502 与二次闪蒸罐同号，推断
        j = {h["name"]: h for h in client.get("/api/v2/ops/OP-08/drawing").json()["image"]["hotspots"]}
        self.assertTrue(j["J-T阀"]["otherOp"])  # 1号膨胀机画面上的 J-T 阀，点表归冷冻单元

    def test_screens_without_image_fall_back_to_schematic(self):
        self.assertIsNone(client.get("/api/v2/ops/OP-16/drawing").json()["image"])  # 循环水厂无截图
        self.assertEqual(client.get("/api/v2/drawings/OP-16/image").status_code, 404)


class RuleTest(unittest.TestCase):
    def test_validate(self):
        with self.assertRaises(ValidationError):
            validate_rule({"type": "group", "op": "XOR", "children": []})
        with self.assertRaises(ValidationError):
            validate_rule({"type": "condition", "subject": {"kind": "parameter", "name": "x"}, "operator": ">",
                           "threshold": {"kind": "limit", "limitId": "PL-104TT115"}})
        validate_rule({"type": "group", "op": "OR", "children": [
            {"type": "condition", "subject": {"kind": "tag", "tag": "104TT115"}, "operator": "<",
             "threshold": {"kind": "value", "value": -81}, "durationSec": 60},
            {"type": "group", "op": "AND", "children": [
                {"type": "condition", "subject": {"kind": "parameter", "name": "停机状态指示记录"}, "operator": "change",
                 "from": 0, "to": 1}]}]})

    def test_context_subject(self):
        rule = {"type": "condition", "subject": {"kind": "context", "name": "分子筛程序阶段"}, "operator": "=",
                "threshold": {"kind": "value", "value": 2}}
        validate_rule(rule)
        r = client.post("/api/v2/rules/evaluate", json={"anchorId": _group("分子筛吸附器组"), "rule": rule, "hours": 1}).json()
        self.assertEqual(r["results"][0]["conditions"][0]["status"], "无法判定")

    def test_rule_text(self):
        text = rule_text(CTX.phen.get("PH-24")["rule"], CTX.limits)
        self.assertIn("PL-104PT111 高限（1.5）", text)
        self.assertIn("持续 1 分钟", text)

    def test_evaluate_per_member(self):
        r = client.post("/api/v2/phenomena/PH-17/evaluate", json={"hours": 6}).json()
        self.assertTrue(r["dataSource"]["simulated"])
        self.assertEqual([x["targetName"] for x in r["results"]], ["1#膨胀压缩机", "2#膨胀压缩机"])
        tags = [c["tags"] for x in r["results"] for c in x["conditions"]]
        self.assertEqual(tags[0], ["104XE180AX"])  # 每台落到本台测点
        self.assertEqual(tags[4], ["104XE180BX"])

    def test_evaluate_is_deterministic(self):
        body = {"hours": 3}
        a = client.post("/api/v2/phenomena/PH-28/evaluate", json=body).json()
        b = client.post("/api/v2/phenomena/PH-28/evaluate", json=body).json()
        self.assertEqual([x["events"] for x in a["results"]], [x["events"] for x in b["results"]])

    def test_simulator_uses_range_when_no_limit(self):
        """没有限值的低温测点按量程取值，不会落在默认的 20～30 ℃。"""
        rule = {"type": "condition", "subject": {"kind": "tag", "tag": "104TT109"}, "operator": "<",
                "threshold": {"kind": "value", "value": 0}}
        r = client.post("/api/v2/rules/evaluate", json={"anchorId": _equip("脱甲烷塔"), "rule": rule, "hours": 1}).json()
        self.assertGreater(r["results"][0]["totalMinutes"], 50)

    def test_duration_hold(self):
        rule = {"type": "condition", "subject": {"kind": "tag", "tag": "104TT115"}, "operator": ">",
                "threshold": {"kind": "value", "value": -1000}, "durationSec": 600}
        r = client.post("/api/v2/rules/evaluate", json={"anchorId": _equip("脱甲烷塔"), "rule": rule, "hours": 1}).json()
        res = r["results"][0]
        self.assertEqual(res["eventCount"], 1)
        self.assertAlmostEqual(res["totalMinutes"], 61 - 9, delta=1)  # 前 9 分钟还没满 10 分钟

    def test_calc_reference_in_rule(self):
        r = client.post("/api/v2/phenomena/PH-06/evaluate", json={"hours": 2}).json()
        self.assertEqual([x["targetName"] for x in r["results"]], ["一级贫富气换热器", "二级贫富气换热器"])

    def test_no_rule_cannot_evaluate(self):
        self.assertEqual(client.post("/api/v2/phenomena/PH-10/evaluate", json={}).status_code, 400)


class CausalTest(unittest.TestCase):
    def test_chain_up(self):
        r = client.get("/api/v2/phenomena/PH-21/chain?direction=up").json()  # 膨胀机停机
        self.assertEqual(r["levels"]["PH-22"], 1)  # ← 压缩机停机
        self.assertEqual(r["levels"]["PH-14"], 2)  # ← 压缩机轴振动高

    def test_crud_roundtrip(self):
        gid = _group("轻烃储罐组")
        rule = {"type": "condition", "subject": {"kind": "parameter", "name": "轻烃储罐压力"}, "operator": ">",
                "threshold": {"kind": "value", "value": 2.4}, "durationSec": 60}
        p = client.post("/api/v2/phenomena", json={"name": "测试现象", "category": "工艺",
                                                    "anchor": {"kind": "group", "id": gid, "name": "x"}, "rule": rule}).json()
        self.assertTrue(p["id"].startswith("PH-U-"))
        link = client.post("/api/v2/causal-links", json={"cause": p["id"], "effect": "PH-28"}).json()
        self.assertEqual(client.post("/api/v2/causal-links", json={"cause": p["id"], "effect": "PH-28"}).status_code, 400)
        self.assertEqual(client.post("/api/v2/causal-links", json={"cause": p["id"], "effect": p["id"]}).status_code, 400)
        upd = client.put(f"/api/v2/phenomena/{p['id']}", json={"name": "测试现象2"}).json()
        self.assertEqual(upd["name"], "测试现象2")
        r = client.delete(f"/api/v2/phenomena/{p['id']}").json()
        self.assertEqual(r["removedLinks"], [link["id"]])
        self.assertTrue(os.path.exists(os.path.join(_TMP, "phenomena.json")))


class TroubleshootingTableTest(unittest.TestCase):
    """现场异常排查表：重烃收集罐烃室液位持续上涨 → 6 项排查（原因现象 + 验证位号）→ 处置卡。"""

    def test_causes_and_chain(self):
        r = client.get("/api/v2/phenomena/PH-36/chain?direction=up").json()
        self.assertEqual({k for k, v in r["levels"].items() if v == 1}, {"PH-37", "PH-38", "PH-39", "PH-40", "PH-41", "PH-42"})
        self.assertEqual(CTX.phen.get("PH-36")["source"]["kind"], "现场异常排查表")

    def test_every_check_is_judged_on_its_own_points(self):
        expect = {"PH-37": ["102_Z_101", "102_Z_102"], "PH-39": ["HZO_106", "HZO_111A"], "PH-40": ["105_LZO_104"],
                  "PH-42": ["102PT102"]}
        for pid, tags in expect.items():
            r = client.post(f"/api/v2/phenomena/{pid}/evaluate", json={"hours": 2}).json()
            got = [t for c in r["results"][0]["conditions"] for t in c["tags"]]
            self.assertEqual(got, tags, pid)
        r = client.post("/api/v2/phenomena/PH-38/evaluate", json={"hours": 2}).json()
        self.assertEqual([x["targetName"] for x in r["results"]], ["1#重烃泵", "2#重烃泵"])  # 逐台判定

    def test_card(self):
        card = CTX.store.procedures.cards["ARP-09"]
        self.assertEqual(len(card["causes"]), 6)
        self.assertEqual([s["phase"] for s in card["steps"]].count("排查"), 6)
        cards = client.get(f"/api/v2/objects/{_equip('重烃收集罐')}/tabs/procedures").json()
        self.assertIn("ARP-09", str(cards))


class CalcTest(unittest.TestCase):
    def test_run_rate(self):
        r = client.post("/api/v2/calculations/CALC-02/run", json={"hours": 2}).json()
        self.assertEqual([x["targetName"] for x in r["results"]], ["1#重烃储罐", "2#重烃储罐"])

    def test_calc_must_reference_registered_algorithm(self):
        bad = {"name": "x", "anchor": {"id": _group("膨胀压缩机组")}, "algorithmId": "ALG-NOT-EXIST", "bindings": {}}
        self.assertEqual(client.post("/api/v2/calculations", json=bad).status_code, 400)
        missing = {"name": "x", "anchor": {"id": _group("膨胀压缩机组")}, "algorithmId": "ALG-ABS-DIFF",
                   "bindings": {"a": {"kind": "parameter", "name": "膨胀端X轴震动"}}}
        self.assertEqual(client.post("/api/v2/calculations", json=missing).status_code, 400)  # b 未绑定

    def test_cross_device_calc(self):
        r = client.post("/api/v2/calculations/CALC-03/run", json={"hours": 2}).json()
        self.assertEqual(r["results"][0]["targetName"], "冷冻分离单元")
        self.assertEqual(sorted(r["results"][0]["inputs"][0]["tags"])[:2], ["104SI180A", "104SI180A1"])

    def test_scope_views(self):
        c = client.get("/api/v2/scope/conditions", params={"seg": "SEG-04"}).json()
        self.assertTrue(c["phenomena"] and c["links"])
        calcs = client.get("/api/v2/scope/calculations", params={"op": "OP-08"}).json()["items"]
        self.assertIn("CALC-03", {x["id"] for x in calcs})  # 单元级组态也出现在其画面的筛选里
        self.assertTrue(all(x["algorithm"]["id"] for x in calcs))
        algos = client.get("/api/v2/algorithms").json()["items"]
        self.assertTrue(any(a["usedBy"] for a in algos))


class DocsAndSearchTest(unittest.TestCase):
    def test_docs(self):
        r = client.get("/api/v2/ops/OP-07/documents").json()
        doc = r["documents"][0]
        self.assertEqual(doc["id"], "WJ-TRQ-03-09-04")
        self.assertEqual(doc["status"], "旧版规程·仅作参考")
        self.assertEqual({p["id"] for p in doc["extracted"]["procedures"]}, {"ARP-06", "ARP-07"})

    def test_procedure_cards(self):
        cards = client.get(f"/api/v2/objects/{_equip('脱甲烷塔')}/tabs/procedures").json()
        self.assertTrue(cards)

    def test_search_tag(self):
        r = client.get("/api/v2/search", params={"keyword": "104XE180BX"}).json()
        self.assertEqual(r["items"][0]["opId"], "OP-09")

    def test_meta_maps_screen_to_unit(self):
        """从图纸点到别的单元的设备时，前端按它切换左侧树。"""
        m = client.get("/api/v2/meta").json()["opSegment"]
        self.assertEqual((m["OP-07"], m["OP-12"]), ("SEG-04", "SEG-05"))
        j = {h["name"]: h for h in client.get("/api/v2/ops/OP-01/drawing").json()["image"]["hotspots"]}
        self.assertEqual(j["装置污水至采油厂管线阀"]["opId"], "OP-12")

    def test_pending_category(self):
        self.assertTrue(client.get("/api/v2/nav/domain/energy").json()["pending"])


if __name__ == "__main__":
    unittest.main()
