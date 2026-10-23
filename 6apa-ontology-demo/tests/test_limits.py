"""工艺限值接口自测。需要本体服务（8700）在跑；越限判断还需要实时库（默认模拟 DCS 8900）。

    ONTOLOGY_URL=http://localhost:8700 python3 -m tests.test_limits
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
    url = BASE + urllib.parse.quote(path, safe="/-:*") + ("?" + urllib.parse.urlencode(query) if query else "")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def check(ok, label):
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    print("[限值清单]")
    status, data = get("/process-limits")
    check(status == 200 and data["available"], "限值数据源已加载")
    check(data["total"] > 0 and data["statusSummary"]["withValues"] > 0, f"共 {data['total']} 条，其中带数值 {data['statusSummary']['withValues']} 条")
    check(data["statusSummary"]["confirmed"] == 0, "没有任何条目被标成「已确认」——全部待现场核对")
    check(all(item["basis"] for item in data["items"]), "每条限值都写了依据")
    check(all(item["source"]["row"] for item in data["items"]), "每条限值都能追到 Excel 行号")

    temp = next(i for i in data["items"] if i["appliesTo"] == "釜内反应温度")
    check(temp["normalLow"] == 33.0 and temp["normalHigh"] == 35.0 and temp["high"] == 35.5,
          f"水解罐温度：正常 {temp['normalLow']}~{temp['normalHigh']} ℃，高限 {temp['high']} ℃")
    check(temp["targetCount"] == 11, f"该限值自动落到 {temp['targetCount']} 台水解罐的温度测点")

    ph = next(i for i in data["items"] if i["appliesTo"] == "反应体系pH")
    check(ph["unit"] == "pH" and ph["targetCount"] == 22, f"水解 pH 限值落到 {ph['targetCount']} 支 pH 计")

    status, only_blank = get("/process-limits", hasValues="false")
    check(only_blank["total"] > 0 and all(not i["hasValues"] for i in only_blank["items"]),
          f"{only_blank['total']} 条「待现场提供」空行构成工艺调查清单")

    print("[对象维度]")
    equips = json.load(urllib.request.urlopen(
        f"{BASE}/equipment?keyword={urllib.parse.quote('水解罐A')}&limit=1"))["items"]
    equip_id = equips[0]["id"]
    status, byobj = get(f"/{equip_id}/limits")
    check(status == 200 and byobj["total"] >= 1, f"按设备查到 {byobj['total']} 条适用限值")
    check(byobj["items"][0]["matchedTargetCount"] >= 1, "限值落到了该设备自己的测点上")

    print("[越限判断]")
    status, chk = get(f"/process-limits/{temp['id']}/check")
    if chk.get("available") is False:
        check(False, f"取当前值失败：{chk.get('emptyReason')}")
    else:
        check(chk["checked"] == 11, f"逐点比对 {chk['checked']} 个测点")
        check(all("statusLabel" in r for r in chk["results"]), "每个测点都有可读的判断结论")
        check(bool(chk.get("summary")), f"按状态汇总：{chk.get('summary')}")
        simulated = (chk.get("dataSource") or {}).get("simulated")
        check(simulated is not None, f"标明了数据来源是否为模拟（simulated={simulated}）")

    status, objchk = get(f"/{equip_id}/limit-check")
    check(status == 200 and objchk["checked"] >= 1, f"按对象做越限判断，检查了 {objchk.get('checked')} 个测点")

    print("[异常]")
    status, miss = get("/process-limits/PL999/check")
    check(miss.get("available") is False, "不存在的限值编号返回 available=false 与原因")

    print(f"\n{sum(results)} / {len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
