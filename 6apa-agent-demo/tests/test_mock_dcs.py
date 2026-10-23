"""模拟 DCS 服务自测。

    MOCK_DCS_URL=http://localhost:8900 python3 -m tests.test_mock_dcs

检查四件事：
1. 响应格式与现场实时库接口示例逐字段一致；
2. 全点表 10680 个点的数值落在合理范围内（开关量只取 0/1、备用点坏质量……）；
3. 相关测点互相对得上（开/关反馈互补、阀位反馈跟随给定、停机时电流归零）；
4. 实时值与历史值出自同一条曲线，历史可复现；异常参数返回明确错误码。
"""

from __future__ import annotations

import os
import sys
import time
from collections import Counter, defaultdict

import httpx

BASE = os.environ.get("MOCK_DCS_URL", "http://localhost:8900").rstrip("/")
RT = f"{BASE}/api/hsm-db-rtserver/v1/rtdata/node/read"
HIS = f"{BASE}/api/timing-svc/v1/history/findAll"

client = httpx.Client(timeout=60.0, trust_env=False)
results: list[bool] = []


def check(ok: bool, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def post(url: str, body: dict) -> dict:
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def all_nodes() -> list[dict]:
    """通过调试接口分页拿全量点表（带画像）。"""
    items, offset = [], 0
    while True:
        data = client.get(f"{BASE}/api/mock/nodes", params={"limit": 500, "offset": offset}).json()["data"]
        items.extend(data["items"])
        offset += 500
        if offset >= data["total"]:
            return items


def read_rt(node_ids: list[str]) -> dict[str, dict]:
    out = {}
    for i in range(0, len(node_ids), 500):
        body = post(RT, {"nodeIds": node_ids[i : i + 500]})
        for item in body["data"]:
            out[item["nodeId"]] = item
    return out


def main() -> int:
    health = client.get(f"{BASE}/api/health").json()
    print(f"服务：{BASE}  点表已加载 {health['catalog']['tagCount']} 个点\n")

    # ------------------------------------------------------------ 1. 格式
    print("[1] 响应格式与现场接口示例一致")
    body = post(RT, {"nodeIds": ["100:AI001.PV", "100:EQ001.DI001.PV"]})
    check(set(body) == {"code", "message", "data"}, "顶层字段为 code / message / data")
    check(body["code"] == 0 and body["message"] == "success", "code=0, message=success")
    check(all(set(item) == {"nodeId", "st", "t", "q", "v"} for item in body["data"]), "每项字段为 nodeId/st/t/q/v")
    check([item["nodeId"] for item in body["data"]] == ["100:AI001.PV", "100:EQ001.DI001.PV"], "按请求顺序返回")
    check(isinstance(body["data"][0]["v"], float), "AI001 为模拟量（浮点）")
    check(body["data"][1]["v"] in (0, 1) and isinstance(body["data"][1]["v"], int), "DI001 为开关量（0/1 整数）")
    check(all(item["t"] <= item["st"] for item in body["data"]), "值时间戳 t 不晚于服务时间 st")

    # ------------------------------------------------------------ 2. 全点表合理性
    print("\n[2] 全点表数值合理性")
    nodes = all_nodes()
    values = read_rt([n["nodeId"] for n in nodes])
    check(len(values) >= 10000, f"覆盖 {len(values)} 个点")

    out_of_range, bad_discrete, spare_bad_q, non_spare_bad_q = [], [], 0, 0
    by_category: dict[str, list[float]] = defaultdict(list)
    for node in nodes:
        item = values[node["nodeId"]]
        profile = node["profile"]
        if profile.get("spare"):
            if profile["kind"] == "analog" and item["q"] == 0:
                spare_bad_q += 1
            continue
        if item["q"] != 1:
            non_spare_bad_q += 1
        if profile["kind"] == "discrete":
            if item["v"] not in (0, 1):
                bad_discrete.append(node["nodeId"])
            continue
        lo, hi = profile["range"]
        v = item["v"]
        if v != 0.0 or not profile.get("followsRunState"):
            if not (lo - 1e-9 <= v <= hi + 1e-9):
                out_of_range.append((node["nodeId"], v, lo, hi))
        by_category[f"{profile['category']}({profile['unit']})"].append(v)

    check(not out_of_range, f"模拟量全部落在画像范围内（越界 {len(out_of_range)}）")
    check(not bad_discrete, f"开关量只取 0/1（异常 {len(bad_discrete)}）")
    check(non_spare_bad_q == 0, "非备用点质量全部为 1")
    check(spare_bad_q > 0, f"备用模拟量返回坏质量 q=0（{spare_bad_q} 个）")

    print("\n  各类模拟量实时值分布（抽样）：")
    for category, vals in sorted(by_category.items(), key=lambda kv: -len(kv[1]))[:16]:
        running = [v for v in vals if v != 0.0] or [0.0]
        print(f"    {category:<16} n={len(vals):<5} min={min(running):<9} max={max(running):<9}")

    kinds = Counter(n["profile"]["category"] for n in nodes)
    print("\n  画像类别分布：", ", ".join(f"{k} {v}" for k, v in kinds.most_common(12)))

    # ------------------------------------------------------------ 3. 相关测点一致性
    print("\n[3] 相关测点互相对得上")
    by_device: dict[str, dict[str, dict]] = defaultdict(dict)
    for node in nodes:
        station, rest = node["nodeId"].split(":", 1)
        name = rest.rsplit(".", 1)[0]
        base, _, suffix = name.rpartition("_")
        if base:
            by_device[f"{station}:{base}"][suffix.upper()] = node

    pairs = [(dev, parts["OF"], parts["CF"]) for dev, parts in by_device.items() if "OF" in parts and "CF" in parts]
    complementary = sum(1 for _, of, cf in pairs if values[of["nodeId"]]["v"] + values[cf["nodeId"]]["v"] == 1)
    check(pairs and complementary == len(pairs), f"开反馈/关反馈互补：{complementary}/{len(pairs)} 组")

    valve_pairs = [
        (parts["AO"], parts["FB"])
        for parts in by_device.values()
        if "AO" in parts and "FB" in parts and parts["FB"]["profile"].get("feedbackOfSetpoint")
    ]
    close = sum(1 for ao, fb in valve_pairs if abs(values[ao["nodeId"]]["v"] - values[fb["nodeId"]]["v"]) <= 8)
    check(valve_pairs and close / len(valve_pairs) >= 0.9, f"阀位反馈跟随给定（差值≤8%）：{close}/{len(valve_pairs)} 组")

    run_current = [
        (parts["RUN"], parts["IB"]) for parts in by_device.values() if "RUN" in parts and "IB" in parts
    ]
    run_freq = [(parts["DO"], parts["FB"]) for parts in by_device.values()
                if "DO" in parts and "FB" in parts and parts["FB"]["profile"].get("followsRunState")]
    consistent = sum(
        1 for run, amp in run_current + run_freq
        if (values[run["nodeId"]]["v"] == 0) == (values[amp["nodeId"]]["v"] == 0.0)
    )
    total_pairs = len(run_current) + len(run_freq)
    check(total_pairs == 0 or consistent == total_pairs,
          f"运行状态与电流/频率一致（停机归零）：{consistent}/{total_pairs} 组")

    # ------------------------------------------------------------ 4. 历史值
    print("\n[4] 历史值")
    probe = ["10:PT_1003.PV", "13:AT_1301D1.PV", "10:P_PZ_DO.PV"]
    now = int(time.time() * 1000)
    one_hour_ago = now - 3_600_000
    his = post(HIS, {"nodeIds": probe, "startTime": one_hour_ago, "endTime": now, "interval": 60_000})
    check(his["code"] == 0, "findAll 返回 code=0")
    check(all(set(item) >= {"nodeId", "count", "values"} for item in his["data"]), "每项含 nodeId/count/values")
    counts = [item["count"] for item in his["data"]]
    check(all(c == 61 for c in counts), f"1 小时 / 60 s 间隔 → 每点 61 个样本（{counts}）")
    ts = [v["t"] for v in his["data"][0]["values"]]
    check(all(b - a == 60_000 for a, b in zip(ts, ts[1:])), "时间戳严格等间隔递增")

    again = post(HIS, {"nodeIds": probe, "startTime": one_hour_ago, "endTime": now, "interval": 60_000})
    check(again["data"] == his["data"], "同一段历史查两次结果完全一致（可复现）")

    rt = post(RT, {"nodeIds": ["10:PT_1003.PV"]})["data"][0]
    point = post(HIS, {"nodeIds": ["10:PT_1003.PV"], "startTime": rt["t"], "endTime": rt["t"] + 1000, "interval": 1000})
    check(point["data"][0]["values"][0]["v"] == rt["v"], f"实时值与同一时刻历史值一致（{rt['v']}）")

    raw = post(HIS, {"nodeIds": ["10:P_PZ_DO.PV"], "startTime": now - 24 * 3_600_000, "endTime": now,
                     "sampleMode": "raw"})["data"][0]["values"]
    alternating = all(a["v"] != b["v"] for a, b in zip(raw, raw[1:]))
    check(len(raw) >= 2 and alternating, f"开关量 raw 模式只返回变位点（24 h 内 {len(raw) - 1} 次变位，逐次交替）")

    agg = {mode: post(HIS, {"nodeIds": ["13:AT_1301D1.PV"], "startTime": one_hour_ago, "endTime": now,
                            "interval": 600_000, "sampleMode": mode})["data"][0]["values"]
           for mode in ("min", "avg", "max")}
    ordered = all(lo["v"] <= mid["v"] <= hi["v"] for lo, mid, hi in zip(agg["min"], agg["avg"], agg["max"]))
    check(ordered, "聚合模式 min ≤ avg ≤ max")

    future = post(HIS, {"nodeIds": ["10:PT_1003.PV"], "startTime": now - 60_000, "endTime": now + 3_600_000,
                        "interval": 10_000})["data"][0]["values"]
    check(future and max(v["t"] for v in future) <= int(time.time() * 1000), "结束时间在未来时截到当前时刻")

    auto = post(HIS, {"nodeIds": ["10:PT_1003.PV"], "startTime": "2026-09-01 00:00:00",
                      "endTime": "2026-09-02 00:00:00"})["data"][0]
    check(auto["count"] <= 400, f"未给 interval 时自动选步长（24 h → {auto['count']} 个样本）")

    # ------------------------------------------------------------ 5. 异常参数
    print("\n[5] 异常参数")
    cases = [
        (RT, {}, 40001, "缺 nodeIds"),
        (RT, {"nodeIds": "10:PT_1003.PV"}, 40001, "nodeIds 不是数组"),
        (RT, {"nodeIds": ["x"] * 501}, 40002, "超过单次点数上限"),
        (HIS, {"nodeIds": ["10:PT_1003.PV"]}, 40001, "缺 startTime"),
        (HIS, {"nodeIds": ["10:PT_1003.PV"], "startTime": now, "endTime": now - 1000}, 40003, "开始晚于结束"),
        (HIS, {"nodeIds": ["10:PT_1003.PV"], "startTime": now - 86_400_000 * 7, "endTime": now, "interval": 1000},
         40004, "样本数超限"),
        (HIS, {"nodeIds": ["10:PT_1003.PV"], "startTime": "昨天"}, 40001, "时间格式无法识别"),
        (HIS, {"nodeIds": ["10:PT_1003.PV"], "startTime": now - 60_000, "sampleMode": "foo"}, 40001, "未知 sampleMode"),
    ]
    for url, payload, code, label in cases:
        got = post(url, payload)
        check(got["code"] == code and got["data"] is None, f"{label} → code {got['code']}")
    bad = client.post(RT, content=b"not json", headers={"Content-Type": "application/json"}).json()
    check(bad["code"] == 40000, "请求体不是 JSON → code 40000")

    print(f"\n{sum(results)} / {len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
