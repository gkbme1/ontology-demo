"""工序与阶段、罐批次 / 运行上下文 / 排班（经本体代调 EBR、MOM）自测。
需要本体服务（8700）与模拟 DCS 服务（8900，同时模拟 EBR 与 MOM）在运行。

    ONTOLOGY_URL=http://localhost:8700 python3 -m tests.test_process_context
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("ONTOLOGY_URL", "http://localhost:8700").rstrip("/") + "/api/ontology"
results: list[bool] = []
TANK_A = "equip-e2bde969"  # 水解罐A


def get(path: str, **query):
    url = BASE + urllib.parse.quote(path, safe="/-:") + ("?" + urllib.parse.urlencode(query) if query else "")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def check(ok, label):
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    now = int(time.time() * 1000)

    print("[工序与阶段定义]")
    s, d = get("/process-steps")
    check(s == 200 and d["available"] and len(d["steps"]) == 8, "8 道工序")
    check([x["name"] for x in d["steps"]][:5] == ["提取", "水洗", "脱色", "抽取", "水解"], "按调研顺序排列")
    hydro = next(x for x in d["steps"] if x["name"] == "水解")
    check([a["code"] for a in hydro["mainAreas"]] == ["S11"] and [a["code"] for a in hydro["auxAreas"]] == ["S10"], "水解：主工段 S11，辅助 S10")
    stages = [x for x in d["stages"] if x["stepId"] == hydro["id"]]
    check([x["name"] for x in stages] == ["进料", "反应", "终点判定", "出料", "空闲"], "水解 5 个阶段")
    react = next(x for x in stages if x["name"] == "反应")
    check(react["limitMode"] == "水解反应期" and len(react["dcsRules"]) == 2, "反应阶段：两条 DCS 条件，对应限值模式 水解反应期")
    check({c["type"] for c in d["contexts"]} == {"罐批次", "换酶后批次计数", "班次"}, "3 类运行上下文")

    print("[阶段识别规则]")
    s, d = get(f"/{TANK_A}/stage-rules")
    check(s == 200 and d["unitCode"] == "A", "水解罐A 罐号 A")
    rules = {x["name"]: x["rules"] for x in d["stages"]}
    check([r["tag"] for r in rules["反应"]] == ["P_1303A_RUN", "XV_1304A_VAL2"], "{x} 换成罐号得到具体位号")
    check(all(r["resolved"] for rs in rules.values() for r in rs), "识别位号都在点表里")
    s, _ = get("/equip-8170434d/stage-rules")
    check(s == 404, "没有定义阶段的设备返回 404")

    print("[罐批次（EBR）]")
    s, d = get(f"/{TANK_A}/batches", startTime=now - 3 * 86_400_000, endTime=now)
    items = d.get("items") or []
    check(s == 200 and 6 <= len(items) <= 15, f"3 天内 {len(items)} 批")
    check(d["scope"]["objectName"] == "水解罐A" and d["scope"]["step"] == "水解", "范围落到设备实例与工序")
    check(d["dataSource"]["sourceType"] == "EBR" and d["dataSource"]["simulated"] is True, "标明来源 EBR，模拟")
    done = [b for b in items if b["status"] == "已完成"]
    b = done[-1]
    check([p["phase"] for p in b["phases"]] == ["进料", "反应", "终点判定", "出料", "空闲"], "已完成批次 5 个阶段齐全")
    check(all(p["startTime"] < p["endTime"] for p in b["phases"]) and
          all(a["endTime"] == c["startTime"] for a, c in zip(b["phases"], b["phases"][1:])), "阶段首尾相接")
    react = next(p for p in b["phases"] if p["phase"] == "反应")
    check(react["stageId"] == "S-02" and react["limitMode"] == "水解反应期", "阶段标注本体阶段编号与限值模式")
    check(b["reactionStart"] == react["startTime"] and b["reactionEnd"] == react["endTime"], "反应起止与反应阶段一致")
    counts = [x["enzymeBatchCount"] for x in items]
    check(all(isinstance(c, int) and c >= 1 for c in counts), "每批有换酶后批次数")
    check(all(y in (x + 1, 1) for x, y in zip(counts, counts[1:])), "换酶后批次数逐批 +1（换酶时归 1）")
    s, d = get("/水解罐A/batches")
    check(s == 200 and d["scope"]["objectId"] == TANK_A, "可按设备名查询")
    s, _ = get("/equip-8170434d/batches")
    check(s == 404, "没有定义阶段的设备返回 404")

    print("[按批号查询]")
    s, d = get(f"/batches/{b['batchNo']}")
    check(s == 200 and d["batch"]["batchNo"] == b["batchNo"] and d["scope"]["objectId"] == TANK_A, "批号 → 批次与设备")
    s, _ = get("/batches/SJ-Z-0001")
    check(s == 404, "不存在的批号返回 404")

    print("[运行上下文]")
    at = (react["startTime"] + react["endTime"]) // 2
    s, d = get(f"/{TANK_A}/context", at=at)
    check(s == 200 and d["batch"]["batchNo"] == b["batchNo"], "某时刻所在批次")
    check(d["phase"]["phase"] == "反应" and d["phase"]["limitMode"] == "水解反应期", "所在阶段与限值模式")
    check(d["shift"] and d["shift"]["shift"] in ("夜班", "白班", "中班") and d["shift"]["team"], "所在班次与班组")
    s, d = get(f"/{TANK_A}/context")
    check(s == 200 and (d["batch"] or d["notice"]), "不给时刻 = 当前")

    print("[班次（MOM）]")
    s, d = get("/shifts", startTime=now - 86_400_000, endTime=now)
    check(s == 200 and 3 <= d["total"] <= 5, f"1 天 {d.get('total')} 个班次")
    check(all(x["endTime"] - x["startTime"] == 8 * 3600_000 for x in d["items"]), "每班 8 小时")
    check(d["dataSource"]["sourceType"] == "MOM", "标明来源 MOM")

    print("[DCS 开关量与 EBR 阶段一致]")
    def state_at(tag: str, t: int) -> int | None:
        _, h = get("/history", keyword=tag, startTime=b["startTime"], endTime=b["endTime"], sampleMode="raw")
        values = next(i for i in h["items"] if i["tagName"] == tag)["values"]
        last = None
        for p in values:
            if p["t"] > t:
                break
            last = p["v"]
        return last

    mid = {p["phase"]: (p["startTime"] + p["endTime"]) // 2 for p in b["phases"]}
    check(state_at("XV_1302A_VAL2", mid["进料"]) == 1 and state_at("XV_1302A_VAL2", mid["反应"]) == 0, "RB 进料阀：进料开、反应关")
    check(state_at("P_1303A_RUN", mid["反应"]) == 1 and state_at("XV_1304A_VAL2", mid["反应"]) == 1, "反应：搅拌运行且氨水阀开")
    check(state_at("P_1303A_RUN", mid["终点判定"]) == 1 and state_at("XV_1304A_VAL2", mid["终点判定"]) == 0, "终点判定：搅拌运行、氨水阀关")
    check(state_at("XV_1308A_FT", mid["出料"]) == 1 and state_at("P_1303A_RUN", mid["空闲"]) == 0, "出料流量有信号；空闲时搅拌停")

    print("[按设备筛选测点（unit）]")
    s, d = get("/history", keyword="液位", startTime=now - 3600_000, unit="水解罐A")
    names = sorted(i["tagName"] for i in d["items"])
    check(s == 200 and names == ["LT_1302A", "SJGYW_A"], f"unit=水解罐A 只留本台及同台号计量罐：{names}")
    check(any("按设备「水解罐A」筛选" in n for n in d["notes"]), "说明筛选口径")
    s, d = get("/history", keyword="液位", startTime=now - 3600_000, unit="不存在的罐")
    check(s == 404, "未知设备返回 404")

    print("[对象档案]")
    s, d = get(f"/asset-profile/{TANK_A}")
    proc = d.get("process") or {}
    check(proc.get("batchSupported") is True and proc["step"]["name"] == "水解", "水解罐A 档案：工序水解，可查批次")
    caps = {c["name"] for c in d["capabilities"]}
    check({"罐批次查询", "班次查询"} <= caps, "能力含 罐批次查询 / 班次查询")
    s, d = get("/asset-profile/equip-8170434d")
    check(not (d.get("process") or {}).get("batchSupported"), "未定义阶段的设备不支持批次")

    print(f"\n{sum(results)} / {len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
