"""v2 口径切换与新增数据源的回归自测。

    ONTOLOGY_URL=http://localhost:8700 python3 -m tests.test_v2_refactor

验四件事：
1. 工段口径换成流程图口径后，条目、ID、上下游、控制站归属都对；
2. 既有接口的字段名没变（只多不少），areaId 三种写法等价；
3. 新增数据源（规则 71 条、设备组 120 个、工段衔接 40 条、关系自带位号）确实加载进来了；
4. 数据问题被如实报告，而不是被悄悄抹平。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("ONTOLOGY_URL", "http://localhost:8700").rstrip("/") + "/api/ontology"
results: list[bool] = []


def get(path: str, **query):
    url = BASE + urllib.parse.quote(path, safe="/-:*{}") + (
        "?" + urllib.parse.urlencode(query) if query else ""
    )
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, {}


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    print("[一、工段口径]")
    status, areas = get("/process-areas")
    items = areas["items"]
    check(status == 200 and areas["total"] == 24, f"工段 {areas['total']} 个（流程图口径 S01–S23 + S99）")
    check(all(a["id"] == f"area-{a['code']}" for a in items), "ID 形如 area-S01，与工段编号一一对应")
    check([a["code"] for a in items] == sorted(a["code"] for a in items), "按编号排序")
    codes = {a["code"] for a in items}
    check({"S01", "S11", "S13", "S99"} <= codes, "关键工段都在：S01 提取 / S11 水解 / S13 结晶 / S99 备用")

    s11 = next(a for a in items if a["code"] == "S11")
    check(s11["name"] == "酶法水解" and s11["nameEn"] == "EnzymaticHydrolysis", f"S11 = {s11['name']}（{s11['nameEn']}）")
    check(sorted(s11["stations"]) == ["13", "20"], f"S11 跨控制站 {s11['stations']}——控制站已降级为属性")
    check(s11["tagCount"] == s11["declared"].get("tagCount"),
          f"实际点位 {s11['tagCount']} 与工段划分表声明一致")
    check(bool(s11["positioning"]) and bool(s11["uri"]), "带工艺定位与本体 URI")

    # 旧口径不该再出现
    legacy = [a for a in items if "工段 (" in (a["name"] or "") or "Enzymatic Hydrolysis" in (a["name"] or "")]
    check(not legacy, "旧的控制站口径工段名已不再作为工段条目出现")

    print("\n[二、areaId 三种写法等价]")
    by_id = get("/process-areas/area-S11")[1]
    by_code = get("/process-areas/S11")[1]
    by_name = get("/process-areas/酶法水解")[1]
    check(by_id.get("id") == by_code.get("id") == by_name.get("id") == "area-S11",
          "area-S11 / S11 / 酶法水解 三种写法查到同一个工段")
    for label, value in (("area-S11", "area-S11"), ("S11", "S11")):
        _, eq = get("/equipment", areaId=value, limit=1)
        _, tg = get("/tags", areaId=value, limit=1)
        check(eq["total"] > 0 and tg["total"] > 0, f"equipment / tags 的 areaId 也接受 {label}")

    print("\n[三、设备可以跨工段]")
    _, overview = get("/overview")
    check(overview["multiAreaEquipmentCount"] > 0,
          f"{overview['multiAreaEquipmentCount']} 台设备的点位落在多个工段（控制站口径下不会出现）")
    _, wide = get("/equipment", limit=300)
    multi = [e for e in wide["items"] if e["areaSpan"] > 1]
    check(multi, f"设备条目带 areaSpan / areaCodes，例：{multi[0]['name']} → {multi[0]['areaCodes']}" if multi else "未取到跨工段设备样本")
    if multi:
        target = multi[0]
        _, hit = get("/equipment", areaId=target["areaCodes"][-1], limit=500)
        check(any(e["id"] == target["id"] for e in hit["items"]),
              "按非主工段过滤也能查到该设备（任一命中）")

    print("\n[四、既有字段没丢]")
    _, eq_list = get("/equipment", keyword="水解罐A", limit=1)
    equip = eq_list["items"][0]
    for field in ("id", "owlSubject", "name", "areaId", "areaName", "station", "tagCount",
                  "parameterCount", "stats", "statsFromSheet1", "overview", "sourceType"):
        if field not in equip:
            check(False, f"设备列表缺字段 {field}")
            break
    else:
        check(True, "设备列表的既有字段一个没少")
    for field in ("areaCode", "areaCodes", "areaSpan", "equipmentGroup", "confidence"):
        if field not in equip:
            check(False, f"设备列表缺新增字段 {field}")
            break
    else:
        check(True, "并补上了 areaCode / areaCodes / areaSpan / equipmentGroup / confidence")

    _, detail = get(f"/equipment/{equip['id']}")
    check(all(k in detail for k in ("area", "parameters", "tags", "relations", "relationEntities", "rules", "source")),
          "设备详情结构不变")

    _, tags = get("/tags", equipmentId=equip["id"], limit=1)
    tag = tags["items"][0]
    for field in ("areaCode", "variableCategory", "confidence", "attributionBasis", "equipmentGroup"):
        if field not in tag:
            check(False, f"点位缺新增字段 {field}")
            break
    else:
        check(True, "点位补上了 areaCode / 变量类别 / 归属依据 / 置信度 / 设备组")

    print("\n[五、新增数据源]")
    _, rules = get("/rules")
    check(rules["available"] and rules["total"] == 71, f"规则从「暂无」变成 {rules['total']} 条")
    with_refs = [r for r in rules["items"] if r["limitRefs"]]
    check(len(with_refs) > 30, f"{len(with_refs)} 条规则的阈值引用工艺限值（见 PLxxx），规则与限值联动")
    check(all(r.get("draft") is not None for r in rules["items"]), "每条规则标明是否为待现场确认的草案")

    _, groups = get("/equipment-groups")
    check(groups["total"] == 120, f"标准设备组 {groups['total']} 个")
    group = groups["items"][0]
    check(all(k in group for k in ("uri", "instances", "components", "properties", "tagCount")),
          "设备组带实例清单、主要部件、本体属性、关联点位数")
    _, gdetail = get(f"/equipment-groups/{group['id']}")
    check(gdetail and gdetail["id"] == group["id"], "设备组详情可查")

    _, flow = get("/area-flow")
    check(flow["total"] == 40, f"全流程工段衔接 {flow['total']} 条")
    check(all(r["upstreamAreaId"] and r["downstreamAreaId"] for r in flow["items"]),
          "每条衔接的上下游都能落到真实工段")
    _, s11flow = get("/process-areas/area-S11/flow")
    check(s11flow["upstream"] and s11flow["downstream"],
          f"S11 上游 {len(s11flow['upstream'])} 条 / 下游 {len(s11flow['downstream'])} 条，带衔接物料")

    print("\n[六、关系表自带位号]")
    _, rels = get("/relations", limit=1)
    check(rels["total"] == 2252, f"关系 {rels['total']} 条（v1 是 71 条）")
    _, bind = get("/relations", category="测点绑定关系", limit=1)
    check(bind["total"] == 622, f"其中「测点绑定关系」{bind['total']} 条，是工艺量到位号的显式声明")
    rel = bind["items"][0]
    check(rel.get("tags") and rel["tags"][0].get("id", "").startswith("tag-"),
          f"关系自带位号已解析成真实 tag- 对象：{rel['subjectEntity']} → {[t['name'] for t in rel['tags']][:3]}")
    check(all(k in rel for k in ("relationCode", "subjectUri", "basis", "confidence")),
          "关系带 关系ID / URI / 依据来源 / 置信度")

    _, entities = get("/relation-entities")
    check(entities["total"] == 1174, f"关系对象 {entities['total']} 个，与实体字典条目数一致（位号不再重复登记成关系对象）")
    ent = entities["items"][0]
    check(all(k in ent for k in ("uri", "owlClass", "areaCode")), "关系对象带 URI / OWL 类 / 所属工段编号")

    # 釜内反应温度：这次重构后应该由关系表直接给出位号，而不是只靠人工映射
    _, temp = get("/relation-entities", type="工艺属性")
    hit = next((e for e in temp["items"] if e["name"] == "釜内反应温度"), None)
    if hit:
        strategies = hit.get("matchStrategies") or []
        check("RELATION_TAG_BINDING" in strategies,
              f"釜内反应温度的测点来自关系表位号绑定（策略 {strategies}）")
    else:
        check(False, "未找到「釜内反应温度」")

    print("\n[七、数据问题如实报告]")
    _, quality = get("/data-quality")
    names = {c["check"] for c in quality["checks"]}
    for expected in ("工段编号含义冲突", "设备跨工段", "关联DCS位号完整性", "标准设备组已登记",
                     "流程画面与点表差异", "画面可见但点表未收录"):
        if expected not in names:
            check(False, f"缺少检查项「{expected}」")
            break
    else:
        check(True, "v2 新增的 6 项检查都在")
    conflict = next((c for c in quality["checks"] if c["check"] == "工段编号含义冲突"), None)
    check(conflict and not conflict["passed"],
          "S99 在点表里是「备用/未定义点」、在限值与规则里是「跨工段协同」——冲突已报出，未被悄悄合并")
    check(quality["summary"]["errorCount"] == 0,
          f"没有 error 级问题（warning {quality['summary']['warningCount']} / info {quality['summary']['infoCount']}）")

    print("\n[八、限值与工段对齐]")
    _, limits = get("/process-limits")
    check(limits["total"] == 68, f"工艺限值 {limits['total']} 条")
    unresolved = sorted({i["area"] for i in limits["items"] if i["area"] and not i.get("areaCode")})
    check(unresolved == ["跨工段协同"],
          f"除「跨工段协同」外，限值的适用工段都对上了 v2 编号（未对上：{unresolved}）")
    pl001 = next(i for i in limits["items"] if i["id"] == "PL001")
    check(pl001["areaCode"] == "S11" and pl001["targetCount"] == 11,
          f"PL001 落在 {pl001['areaCode']}，覆盖 {pl001['targetCount']} 个测点")

    print(f"\n{sum(results)} / {len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
