"""本体实时值 / 历史值接口自测。需要本体服务（8700）与实时库 / 历史库（默认模拟 DCS 服务 8900）在运行。

    ONTOLOGY_URL=http://localhost:8700 python3 -m tests.test_timeseries
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

    print("[实时值]")
    s, d = get("/equip-8170434d/realtime")
    check(s == 200 and d["scope"]["objectKind"] == "equipment", "按设备 ID 查询")
    check(d["total"] == 5 and all(i["nodeId"] and i["timeText"] for i in d["items"]), "每个点带 nodeId / 值 / 时间")
    check(all(i["equipmentName"] == "一层排渣泵" and i["description"] for i in d["items"]), "值上附带本体语义（设备、现场描述）")
    check(d["dataSource"]["sourceType"] == "RTDB", "标明数据来自实时库")
    s2, d2 = get("/:Dev_10_一层排渣泵/realtime")
    check(s2 == 200 and d2["total"] == d["total"], "按 OWL Subject 查询与按 ID 一致")
    s, d = get("/equip-ecc06748/realtime", limit=5)
    check(d["returned"] == 5 and d["total"] > 5 and d["notes"], "点多时分页并给出提示")
    check(not d["items"][0]["description"].startswith("备用"), "备用点排在最后")
    s, d = get("/realtime", keyword="水解罐I温度")
    check(s == 200 and d["items"] and d["items"][0]["unit"] == "℃", "集合接口按关键词查询")

    print("[历史值]")
    s, d = get("/param-5fc7af33/history", startTime=now - 6 * 3600_000, interval=1800000)
    item = d["items"][0]
    check(s == 200 and item["count"] == 13 and item["stats"], "参数 6 小时 / 30 分钟间隔 → 13 个样本，附统计")
    check(d["dataSource"]["sourceType"] == "HISTORIAN", "标明数据来自历史库")
    s, d = get("/equip-8170434d/history", startTime=now - 24 * 3600_000, sampleMode="raw", keyword="启停")
    values = d["items"][0]["values"]
    check(len(values) >= 2 and all(a["v"] != b["v"] for a, b in zip(values, values[1:])), "raw 模式返回启停变位")

    rt = get("/equip-8170434d/realtime", keyword="运行")[1]["items"][0]
    his = get("/equip-8170434d/history", keyword="运行", startTime=now - 60_000, sampleMode="interpolated",
              interval=1000)[1]["items"][0]["values"][-1]
    check(rt["value"] == his["v"], "实时值与最新历史值一致")

    print("[关系对象 / 异常]")
    matched = get("/relation-entities", matched="true")[1]["items"][0]
    s, d = get(f"/{matched['id']}/realtime", limit=3)
    check(s == 200 and d["total"] > 0 and any("待现场确认" in n for n in d["notes"]), "关系对象经映射查到测点，并提示映射待确认")
    unmatched = get("/relation-entities", matched="false")[1]["items"][0]
    s, d = get(f"/{unmatched['id']}/realtime")
    check(s == 200 and d["total"] == 0 and d["notes"], "未匹配关系对象返回空并说明原因")
    for label, path, query, code in [
        ("缺 startTime", "/equip-8170434d/history", {}, 400),
        ("时间格式错误", "/equip-8170434d/history", {"startTime": "昨天"}, 400),
        ("对象不存在", "/equip-xxxx/realtime", {}, 404),
        ("集合接口无过滤条件", "/realtime", {}, 400),
    ]:
        s, d = get(path, **query)
        check(s == code and d.get("detail"), f"{label} → HTTP {s}")

    s, d = get("/timeseries/status")
    check(s == 200 and d["upstreams"]["RTDB"]["reachable"], "实时库 / 历史库连接状态")
    health = json.load(urllib.request.urlopen(BASE.replace("/api/ontology", "/api/health"), timeout=30))
    check(any(e["path"] == "/api/ontology/{object_id}/realtime" for e in health["endpoints"]), "/api/health 接口清单包含新接口")
    s, d = get("/equip-8170434d/relations")
    check(s == 200, "原有接口不受影响")

    print(f"\n{sum(results)} / {len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
