"""罐批次 / 运行上下文工具与「按批次取时间窗」自测。

    ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.test_context_tools

1. 不需要服务：伪本体上验证 DCS 阶段推断、时间窗换算规则、EBR 不通时退回 DCS 推断；
2. 打真实本体服务（本体 8700 + 模拟 DCS 8900，后者同时模拟 EBR / MOM）：
   批次工具、分析工具带 batchNo / unit 后时间窗与测点范围、DCS 推断与 EBR 一致。
"""

from __future__ import annotations

import asyncio
import json
import sys

from backend.config import settings
from backend.tools import context_tools as ct
from backend.tools.executor import ToolApiError, ToolExecutor
from backend.tools.ontology_tools import build_ontology_registry

results: list[bool] = []
MIN = 60_000


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


# ------------------------------------------------------------------ 伪本体

T0 = 1_790_000_000_000  # 任意基准


def _phases(start: int, plan: list[tuple[str, int]]) -> list[dict]:
    out, t = [], start
    for name, minutes in plan:
        out.append({"phase": name, "startTime": t, "endTime": t + minutes * MIN, "startText": ct._fmt(t),
                    "endText": ct._fmt(t + minutes * MIN), "limitMode": "水解反应期" if name == "反应" else ""})
        t += minutes * MIN
    return out


PLAN = [("进料", 30), ("反应", 300), ("终点判定", 30), ("出料", 40), ("空闲", 60)]


def _batch(no: str, start: int, ongoing: bool = False) -> dict:
    phases = _phases(start, PLAN)
    if ongoing:
        phases = phases[:2]
        phases[-1]["endTime"] = phases[-1]["endText"] = None
    react = next(p for p in phases if p["phase"] == "反应")
    return {"batchNo": no, "status": "进行中" if ongoing else "已完成", "enzymeBatchCount": int(no[-2:]), "enzymeLot": "E-1",
            "startTime": start, "endTime": None if ongoing else phases[-1]["endTime"], "startText": ct._fmt(start),
            "endText": None if ongoing else phases[-1]["endText"], "reactionStart": react["startTime"],
            "reactionEnd": react["endTime"], "phases": phases}


BATCH_MIN = sum(m for _, m in PLAN)
BATCHES = [_batch("SJ-A-0010", T0), _batch("SJ-A-0011", T0 + BATCH_MIN * MIN),
           _batch("SJ-A-0012", T0 + 2 * BATCH_MIN * MIN, ongoing=True)]
NOW = T0 + 2 * BATCH_MIN * MIN + 100 * MIN

STAGE_RULES = {
    "scope": {"objectId": "equip-a", "objectName": "水解罐A"},
    "unitCode": "A",
    "stages": [
        {"id": "S-01", "name": "进料", "order": 1, "ebrPhase": "进料", "limitMode": "进料过程", "dcsCondition": "FEED=1",
         "rules": [{"tag": "FEED", "value": 1, "resolved": True}]},
        {"id": "S-02", "name": "反应", "order": 2, "ebrPhase": "反应", "limitMode": "水解反应期", "dcsCondition": "RUN=1；NH3=1",
         "rules": [{"tag": "RUN", "value": 1, "resolved": True}, {"tag": "NH3", "value": 1, "resolved": True}]},
        {"id": "S-03", "name": "终点判定", "order": 3, "ebrPhase": "终点判定", "limitMode": "水解反应期", "dcsCondition": "RUN=1；NH3=0",
         "rules": [{"tag": "RUN", "value": 1, "resolved": True}, {"tag": "NH3", "value": 0, "resolved": True}]},
        {"id": "S-04", "name": "出料", "order": 4, "ebrPhase": "出料", "limitMode": "出料过程", "dcsCondition": "OUT=1",
         "rules": [{"tag": "OUT", "value": 1, "resolved": True}]},
        {"id": "S-05", "name": "空闲", "order": 5, "ebrPhase": "空闲", "limitMode": "", "dcsCondition": "", "rules": []},
    ],
}


def _dcs_changes(tag: str, start: int, end: int) -> list[dict]:
    """由 BATCHES 生成开关量变位，与 EBR 阶段一一对应。"""
    on_phases = {"FEED": {"进料"}, "RUN": {"反应", "终点判定"}, "NH3": {"反应"}, "OUT": {"出料"}}[tag]
    segs = []
    for b in BATCHES:
        for p in b["phases"]:
            segs.append((p["startTime"], p["endTime"] or NOW, 1 if p["phase"] in on_phases else 0))
    out, last = [], None
    first = next((v for a, e, v in segs if a <= start < e), 0)
    out.append({"t": start, "v": first, "q": 1})
    last = first
    for a, _, v in segs:
        if start < a < end and v != last:
            out.append({"t": a, "v": v, "q": 1})
            last = v
    return out


class FakeApi:
    def __init__(self, ebr_down: bool = False) -> None:
        self.ebr_down = ebr_down
        self.calls: list[tuple[str, dict]] = []

    async def get_json(self, path: str, params: dict | None = None):
        params = params or {}
        self.calls.append((path, params))
        if path.endswith("/batches") and path.startswith("/api/ontology/") and path.count("/") == 4:
            if self.ebr_down:
                raise ToolApiError("server_error", "本体服务返回 502：EBR 连不上")
            if "%E6%B3%B5" in path:  # 「泵」
                raise ToolApiError("not_found", "本体服务返回 404：未定义工艺阶段")
            s, e = params.get("startTime", 0), params.get("endTime", NOW)
            items = [b for b in BATCHES if b["startTime"] < e and (b["endTime"] or NOW) > s]
            return {"scope": {"objectName": "水解罐A"}, "items": items, "dataSource": {"simulated": True}}
        if path.startswith("/api/ontology/batches/"):
            no = path.rsplit("/", 1)[1]
            hit = next((b for b in BATCHES if b["batchNo"] == no), None)
            if not hit:
                raise ToolApiError("not_found", f"本体服务返回 404：没有批次 {no}")
            return {"scope": {"objectName": "水解罐A"}, "batch": hit, "dataSource": {"simulated": True}}
        if path.endswith("/stage-rules"):
            return STAGE_RULES
        if path == "/api/ontology/history":
            tag = params["keyword"]
            return {"items": [{"tagName": tag, "values": _dcs_changes(tag, params["startTime"], params["endTime"])}]}
        raise AssertionError(f"未预期的请求 {path}")


def offline() -> None:
    print("[时间窗换算（伪本体）]")
    ct._now_ms = lambda: NOW  # type: ignore[assignment]

    async def resolve(args, api=None):
        return await ct.resolve_batch_window(api or FakeApi(), args)

    check(asyncio.run(resolve({"startTime": "2026-01-01"})) is None, "没给 unit / batchNo / phase：不改时间窗")
    w = asyncio.run(resolve({"batchNo": "SJ-A-0010"}))
    react = BATCHES[0]["phases"][1]
    check(w["start"] == ct._fmt(react["startTime"]) and w["end"] == ct._fmt(react["endTime"]), "batchNo：默认取反应阶段")
    check(w["basis"]["limitMode"] == "水解反应期" and w["basis"]["enzymeBatchCount"] == 10, "依据带限值模式与换酶后批次数")
    w = asyncio.run(resolve({"batchNo": "SJ-A-0010", "phase": "全批"}))
    check(w["start"] == ct._fmt(BATCHES[0]["startTime"]) and w["end"] == ct._fmt(BATCHES[0]["endTime"]), "phase=全批：整批起止")
    w = asyncio.run(resolve({"unit": "水解罐A"}))
    check(w["basis"]["batchNo"] == "SJ-A-0011", "只给 unit：取最近一个反应已结束的批次（进行中的不取）")
    w = asyncio.run(resolve({"unit": "水解罐A", "phase": "出料"}))
    check(w["basis"]["batchNo"] == "SJ-A-0011" and w["basis"]["phase"] == "出料", "unit + phase：该阶段已结束的最近一批")
    w = asyncio.run(resolve({"batchNo": "SJ-A-0012"}))
    check(w["basis"]["ongoing"] is True and w["end"] == ct._fmt(NOW), "进行中批次：截至当前，并标明进行中")
    w = asyncio.run(resolve({"unit": "水解罐A", "startTime": "2026-01-01 00:00:00", "endTime": "2026-01-02 00:00:00"}))
    check(w["start"] is None and w["unit"] == "水解罐A", "unit + 用户时间、没给 phase：时间窗按用户给的，只限定设备")
    for args, label in (({"phase": "反应"}, "只给 phase 没给设备"), ({"batchNo": "SJ-X-9"}, "批号不存在"),
                        ({"unit": "水解罐A", "phase": "保温"}, "phase 不在可选范围"),
                        ({"batchNo": "SJ-A-0012", "phase": "出料"}, "批次还没到该阶段"),
                        ({"unit": "某泵"}, "设备没有定义阶段")):
        try:
            asyncio.run(resolve(args))
            check(False, f"{label}：应要求澄清")
        except ct.BatchWindowError:
            check(True, f"{label}：要求澄清")

    print("[DCS 阶段推断（伪本体）]")
    inf = asyncio.run(ct.infer_batches_from_dcs(FakeApi(), "水解罐A", T0 - 30 * MIN, NOW))
    got = [[(p["phase"], p["startTime"], p["endTime"]) for p in b["phases"]] for b in inf["items"]]
    want = [[(p["phase"], p["startTime"], p["endTime"]) for p in b["phases"]] for b in BATCHES]
    check(got == want, f"推断出 {len(got)} 批，阶段与 EBR 完全一致（进行中批次末段无结束时间）")
    check([b["status"] for b in inf["items"]] == ["已完成", "已完成", "进行中"], "批次状态")
    check(all(b["batchNo"] is None and b["enzymeBatchCount"] is None for b in inf["items"]), "推断结果没有批号与换酶后批次数")
    check(inf["items"][0]["phases"][1]["limitMode"] == "水解反应期", "推断阶段带本体限值模式")
    inf = asyncio.run(ct.infer_batches_from_dcs(FakeApi(), "水解罐A", T0 + 100 * MIN, NOW))
    check(inf["items"][0]["partialStart"] is True and inf["items"][0]["phases"][0]["phase"] == "反应", "范围从批次中间开始：标明只看到后半段")

    print("[EBR 不通时退回 DCS 推断（伪本体）]")
    api = FakeApi(ebr_down=True)
    w = asyncio.run(resolve({"unit": "水解罐A"}, api))
    check(w["basis"]["source"] == ct.SOURCE_DCS and "EBR 暂时取不到" in w["basis"]["notice"], "来源标为 DCS推断，并说明原因")
    check(w["start"] == ct._fmt(BATCHES[1]["phases"][1]["startTime"]), "推断出的反应窗与 EBR 一致")
    check(any(p.endswith("/stage-rules") for p, _ in api.calls), "识别条件取自本体 stage-rules")

    print("[分析工具包装（伪本体）]")
    seen = {}

    async def fake_handler(registry, arguments, api):
        seen.update(arguments, unit_scope=ct.UNIT_SCOPE.get())
        return {"analysisType": "x"}

    wrapped = ct.with_batch_window(fake_handler)
    out = asyncio.run(wrapped(None, {"target": "温度", "batchNo": "SJ-A-0010"}, FakeApi()))
    check(seen["startTime"] == ct._fmt(react["startTime"]) and "batchNo" not in seen, "换算后的时间窗传给原工具")
    check(seen["unit_scope"] == "水解罐A" and ct.UNIT_SCOPE.get() is None, "调用期间限定设备，结束后复原")
    check(out["windowBasis"]["batchNo"] == "SJ-A-0010", "结果附 windowBasis")
    out = asyncio.run(wrapped(None, {"target": "温度", "phase": "反应"}, FakeApi()))
    check(out["status"] == "needs_clarification", "换算失败：返回 needs_clarification，不调原工具")


# ------------------------------------------------------------------ 真实服务


async def live() -> None:
    print("[真实服务]")
    ct._now_ms = lambda: int(__import__("time").time() * 1000)  # type: ignore[assignment]
    reg = build_ontology_registry()
    ex = ToolExecutor(settings.ontology_base_url, registry=reg, max_result_chars=60000)

    async def run(name: str, args: dict) -> dict:
        r = await ex.execute(reg.get(name), "t", json.dumps(args, ensure_ascii=False))
        assert r.status != "error", r.error
        return r.result

    try:
        d = await run("get_batch_context", {"unit": "水解罐A"})
        check(d["source"] == "EBR" and 6 <= d["batchCount"] <= 15, f"get_batch_context：近 3 天 {d['batchCount']} 批，来源 EBR")
        check(d["current"] and d["current"]["phase"] and d["current"]["shift"], "当前批次、阶段与班次")
        done = [b for b in d["batches"] if b["status"] == "已完成"]
        last = done[-1]["batchNo"]
        d = await run("get_batch_context", {"batchNo": last})
        check(d["batch"]["batchNo"] == last and len(d["phases"]) == 5, "按批号查询：5 个阶段")
        react = next(p for p in d["phases"] if p["phase"] == "反应")

        d = await run("check_limit_exceedance", {"target": "釜内反应温度", "batchNo": last})
        check(d["window"]["start"] == react["startText"] and d["window"]["end"] == react["endText"], "越限统计：时间窗 = 该批反应阶段")
        names = [a["tag"] for a in d.get("abnormal") or []] + d.get("normalTags", [])
        check(names == ["TI_1301A"], f"越限统计：只取本台测点 {names}")
        check(d["windowBasis"]["source"] == "EBR" and last in d["windowBasis"]["text"], "结果写明时间窗依据")

        ctx = await run("get_batch_context", {"unit": "水解罐A"})
        react_done = [b["batchNo"] for b in ctx["batches"] if b.get("reaction") and "进行中" not in b["reaction"]]
        d = await run("investigate_process_anomaly", {"target": "釜内反应温度", "unit": "水解罐A"})
        check(d["windowBasis"]["batchNo"] == react_done[-1], "异常溯源：只给 unit 时取反应已结束的最近一批")
        check([t["tag"] for t in d["anomaly"]["tags"]] == ["TI_1301A"], "异常溯源：目标测点限定本台")

        d = await run("calculate_quantity", {"target": "氨水累计加量", "batchNo": last})
        check([r["tag"] for r in d["byTag"]] == ["LT_1302A"] and d["total"]["consumed"] > 0, "派生量计算：只算本台计量罐，反应期有消耗")

        d = await run("check_limit_exceedance", {"target": "釜内反应温度", "batchNo": "SJ-A-99999"})
        check(d["status"] == "needs_clarification", "批号不存在：要求澄清")

        end = ct._now_ms()
        ebr = await ct.unit_batches(ex, "水解罐A", end - 2 * 86_400_000, end)
        inf = await ct.infer_batches_from_dcs(ex, "水解罐A", end - 2 * 86_400_000, end)
        e = {(p["phase"], p["startTime"]) for b in ebr["items"] for p in b["phases"]}
        i = {(p["phase"], p["startTime"]) for b in inf["items"] if not b["partialStart"] for p in b["phases"]}
        check(i and i <= e, f"DCS 推断的 {len(i)} 个阶段起点都与 EBR 一致")
    finally:
        await ex.aclose()


def main() -> int:
    offline()
    try:
        asyncio.run(live())
    except Exception as exc:  # noqa: BLE001
        check(False, f"真实服务测试出错：{exc}")
    print(f"\n{sum(results)} / {len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
