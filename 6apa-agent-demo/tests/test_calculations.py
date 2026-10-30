"""派生量计算模块自测。

    ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.test_calculations

1. 算法单元测试（不需要服务）：液位死区跟踪、补液排除、抖动过滤、说法剥离、适用性判定；
2. 扩展性：新登记一个计算方法，入口工具不改就能分发到它；
3. 打真实本体（需本体服务 + 模拟 DCS 在跑）：派生量解析、合计与逐表一致、默认时间窗、
   算不了时返回 no_method、单表 focus、返回体落在 local32k 预算内。
"""

from __future__ import annotations

import asyncio
import json
import sys

from backend.config import LLM_PROFILES, settings
from backend.tools import calculations as calc
from backend.tools.calculations import level_consumption as lc
from backend.tools.calculations.base import CalcMethod, CalcSource
from backend.tools.executor import ToolExecutor
from backend.tools.ontology_tools import build_ontology_registry
from backend.tools.registry import INITIAL_GROUPS

results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def run_unit_tests() -> None:
    print("[算法单元测试]")
    moves = lc.level_movements([100, 90, 95, 80, 80.2, 85], deadband=1.0)
    check(
        moves["dropped"] == 25 and moves["risen"] == 10 and moves["refills"] == 2,
        f"只累计下降段为消耗，上升段单独记为补液：{moves}",
    )
    jitter = lc.level_movements([100, 100.3, 99.8, 100.2, 99.9, 90], deadband=1.0)
    check(jitter["dropped"] == 10 and jitter["risen"] == 0 and jitter["refills"] == 0, f"死区内的抖动不计：{jitter}")
    naive = 100 - 85
    check(moves["dropped"] != naive, f"补过液时消耗量（{moves['dropped']}）≠ 首末液位差（{naive}）")

    check(calc._strip_rate_words("氨水滴加速度") == "氨水", "剥掉'滴加速度'只剩核心词")
    check(calc._strip_rate_words("氨水计量罐A的消耗速度") == "氨水计量罐A", "剥掉'的消耗速度'")
    check(calc._strip_rate_words("氨水累计加量") == "氨水累计加量", "本体对象名本身不被剥")

    def rel(subject_name: str, predicate: str, mechanism: str) -> dict:
        return {
            "subject": {"id": "robj-level", "entity": subject_name},
            "predicate": predicate,
            "domainDescription": mechanism,
            "source": {"file": "f.xlsx", "sheet": "s", "row": 9},
        }

    async def detect_cases() -> None:
        own = await lc.detect(None, {"id": "robj-x", "name": "某罐液位", "tagCount": 2}, {})
        check(own is not None and own.derived is None and own.source["id"] == "robj-x", "液位量本身可算，取数对象就是它")
        derived = await lc.detect(
            None,
            {"id": "robj-y", "name": "某料累计加量"},
            {"description": "由计量罐液位差计算", "incomingRelations": [rel("某计量罐液位", "负向影响", "液位下降量即加料量")]},
        )
        check(derived is not None and derived.derived["id"] == "robj-y" and derived.source["id"] == "robj-level", "由液位负向影响、且写明液位差的派生量可算，从液位量取数")
        check("第9行" in derived.basis, "本体依据带来源行号")
        positive = await lc.detect(
            None, {"id": "robj-z", "name": "某量"}, {"description": "由液位计算", "incomingRelations": [rel("某罐液位", "正向影响", "")]}
        )
        check(positive is None, "正向影响不当作液位差消耗")
        unrelated = await lc.detect(
            None, {"id": "robj-w", "name": "某温度"}, {"description": "", "incomingRelations": [rel("某罐液位", "负向影响", "导热变化")]}
        )
        check(unrelated is None, "本体没写明与液位差有关的不算")

    asyncio.run(detect_cases())


async def run_live_tests() -> None:
    print("\n[真实本体]")
    registry = build_ontology_registry(compact_relations=True)
    budget = LLM_PROFILES["local32k"]["max_tool_result_chars"]
    executor = ToolExecutor(settings.ontology_base_url, timeout=settings.ontology_timeout, max_result_chars=budget, registry=registry)

    async def call(**args):
        return await executor.execute(registry.require("calculate_quantity"), "t", json.dumps(args, ensure_ascii=False))

    try:
        spec = registry.get("calculate_quantity")
        check(spec is not None and spec.group in INITIAL_GROUPS, "calculate_quantity 已注册且首批下发")
        check(all(m.key in spec.description for m in calc.CALC_METHODS.values()), "工具描述里自动列出全部已登记的计算方法")

        # 动态挑一个"由液位差算出的派生量"，用它的名称核心词 + "速度"来问
        quantities = (await executor.get_json("/api/ontology/relation-entities", {"type": "工艺属性", "limit": 2000})).get("items") or []
        derived_target = None
        for ent in quantities:
            detail = await executor.get_json(f"/api/ontology/relation-entities/{ent['id']}")
            source = await lc.detect(executor, ent, detail)
            if source and source.derived:
                derived_target = (ent, source)
                break
        check(derived_target is not None, "本体里能找到由液位差算出的派生量")
        if not derived_target:
            return
        ent, source = derived_target
        print(f"        动态选取：{ent['name']} ← {source.source['name']}")

        res = await call(target=ent["name"])
        data = res.result or {}
        check(data.get("source") == source.source["name"] and "basis" in data, "从本体写明的液位量取数，并给出本体依据")
        raw = await executor.get_json(
            f"/api/ontology/{source.source['id']}/history",
            {"startTime": data["window"]["start"], "endTime": data["window"]["end"], "limit": 50},
        )
        check(len(data.get("byTag") or []) == raw.get("total"), f"逐表结果覆盖全部测点（{len(data.get('byTag') or [])}/{raw.get('total')}）")
        if data.get("total"):
            summed = sum(row["consumed"] for row in data["byTag"])
            check(abs(summed - data["total"]["consumed"]) < 0.5, f"合计 = 逐表之和（{data['total']['consumed']} / {round(summed, 2)}）")
        check(data["window"]["minutes"] == lc.DEFAULT_WINDOW_MINUTES, "不给时间段时取默认时间窗")
        check("模拟数据" in data.get("conclusion", ""), "结论声明模拟数据")
        check(not res.truncated and len(res.to_llm_content()) <= budget, f"返回体在 local32k 预算内（{len(res.to_llm_content())} 字符）")

        core = calc._strip_rate_words(ent["name"])
        spoken = await call(target=f"{core}速度")
        sdata = spoken.result or {}
        if sdata.get("status") == "needs_clarification":
            check(any(c["id"] == ent["id"] for c in sdata.get("candidates") or []), f"'{core}速度'有多个可算对象时，候选里包含它")
        else:
            check((sdata.get("target") or {}).get("id") == ent["id"] and (sdata.get("target") or {}).get("matchedBy"), f"'{core}速度'推定到「{ent['name']}」并写明依据")

        windowed = await call(target=ent["name"], startTime="2026-10-25 00:00:00", endTime="2026-10-25 06:00:00")
        check(windowed.result["window"]["minutes"] == 360, "给了时间段就按时间段算")
        first_tag = data["byTag"][0]["tag"]
        focused = await call(target=ent["name"], focus=first_tag)
        check([r["tag"] for r in focused.result.get("byTag") or []] == [first_tag], "focus 只算指定的一支表")

        nope = await call(target="釜内反应温度")
        check(nope.result.get("status") == "no_method" and "byTag" not in nope.result, "没有适用算法时返回 no_method，不给任何数值")

        # 扩展性：临时登记一个方法，入口不改就能分发
        async def dummy_detect(api, entity, detail):
            return CalcSource(method="dummy_test", source={"id": entity["id"], "name": entity["name"]}, derived=None, basis="测试")

        async def dummy_run(ctx):
            return {"analysisType": "计算：测试方法", "conclusion": f"测试方法算了 {ctx.target['name']}"}

        calc.register(CalcMethod(key="dummy_test", title="测试方法", summary="测试", detect=dummy_detect, run=dummy_run))
        try:
            plugged = await calc.calculate_quantity(registry, {"target": "釜内反应温度", "method": "dummy_test"}, executor)
            check(plugged.get("conclusion") == "测试方法算了 釜内反应温度", "新登记的计算方法无需改入口即可被分发")
        finally:
            calc.CALC_METHODS.pop("dummy_test", None)
    finally:
        await executor.aclose()


def main() -> int:
    run_unit_tests()
    asyncio.run(run_live_tests())
    passed = sum(results)
    print(f"\n通过 {passed} / {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
