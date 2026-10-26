"""确定性分析工具自测。

    ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.test_analysis_tools

分两部分：
1. 算法单元测试（不需要任何服务）：相关/滞后/判定口径、越限统计、因果上推的方向传播与环路、
   名称解析、Executor 对 async 本地工具与错误分类的处理；
2. 打真实本体服务（需本体服务 + 模拟 DCS 服务在跑）：测试对象从本体里动态挑，不写死业务值，
   验证路径方向、反向路径识别、工段计数与独立查询一致、返回体落在 local32k 预算内。
"""

from __future__ import annotations

import asyncio
import json
import sys

from backend.config import LLM_PROFILES, settings
from backend.tools import analysis_tools as at
from backend.tools.executor import ToolApiError, ToolExecutor
from backend.tools.ontology_tools import build_ontology_registry
from backend.tools.registry import INITIAL_GROUPS, ToolParameter, ToolRegistry, ToolSpec

results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


# ------------------------------------------------------------------ 伪本体


class FakeApi:
    """只实现分析工具用到的几个接口，数据是一张小因果图：

        C --负向--> B --正向--> A <--控制执行机构-- V
        A --正向--> B（制造环路，遍历不能死循环）
        A 反馈给 控制器 K
    """

    def __init__(self) -> None:
        def rel(subj, obj, category, predicate):
            return {
                "category": category,
                "predicate": predicate,
                "subject": {"id": subj, "entity": subj.upper(), "type": "工艺属性"},
                "object": {"id": obj, "entity": obj.upper()},
                "domainDescription": f"{subj}->{obj}",
                "source": {"file": "f.xlsx", "sheet": "s", "row": 1},
            }

        self.details = {
            "robj-a": {
                "id": "robj-a",
                "name": "ROBJ-A",
                "incomingRelations": [
                    rel("robj-b", "robj-a", "影响关系", "正向影响"),
                    rel("robj-v", "robj-a", "控制关系", "影响"),
                    rel("robj-x", "robj-a", "结构关系", "具有属性"),
                ],
                "outgoingRelations": [
                    rel("robj-a", "robj-b", "影响关系", "正向影响"),
                    {**rel("robj-a", "robj-k", "控制关系", "反馈给"), "object": {"id": "robj-k", "entity": "控制器K"}},
                ],
            },
            "robj-b": {
                "id": "robj-b",
                "incomingRelations": [rel("robj-c", "robj-b", "影响关系", "负向影响"), rel("robj-a", "robj-b", "影响关系", "正向影响")],
                "outgoingRelations": [],
            },
            "robj-c": {"id": "robj-c", "incomingRelations": [], "outgoingRelations": []},
            "robj-v": {"id": "robj-v", "incomingRelations": [rel("robj-c", "robj-v", "控制关系", "控制")], "outgoingRelations": []},
        }

    async def get_json(self, path, params=None):
        params = params or {}
        if path.startswith("/api/ontology/relation-entities/"):
            key = path.rsplit("/", 1)[1]
            if key not in self.details:
                raise ToolApiError("not_found", key)
            return self.details[key]
        if path == "/api/ontology/relation-entities":
            pool = [
                {"id": "robj-a", "name": "反应温度", "type": "工艺属性", "tagCount": 3, "relationCount": 9},
                {"id": "robj-b", "name": "进料温度", "type": "工艺属性", "tagCount": 1, "relationCount": 4},
            ]
            kw = params.get("keyword")
            items = [e for e in pool if not kw or kw in e["name"]]
            return {"items": items, "total": len(items)}
        if path == "/api/ontology/tags":
            return {"items": []}
        raise AssertionError(f"未预期的请求 {path}")


def run_unit_tests() -> None:
    print("[算法单元测试]")
    check(abs(at.pearson([1, 2, 3, 4, 5, 6, 7, 8], [2, 4, 6, 8, 10, 12, 14, 16]) - 1) < 1e-9, "pearson 完全正相关 = 1")
    check(abs(at.pearson([1, 2, 3, 4, 5, 6, 7, 8], [8, 7, 6, 5, 4, 3, 2, 1]) + 1) < 1e-9, "pearson 完全负相关 = -1")
    check(at.pearson([1] * 10, list(range(10))) is None, "常数序列不算相关")
    check(at.pearson([1, 2, 3], [1, 2, 3]) is None, f"样本少于 {at.MIN_SAMPLES} 不算相关")

    step = 900_000
    base = [((i * 37) % 11) - 5 + (i % 3) for i in range(60)]
    cause = {i * step: float(v) for i, v in enumerate(base)}
    lag = 2
    effect = {i * step: float(base[i - lag]) for i in range(lag, 60)}
    pos = at.lagged_correlation(cause, effect, 1)
    check(pos["leadMinutes"] == lag * 15 and pos["corr"] > 0.99, f"能找出原因领先 {lag * 15} 分钟：{pos}")
    neg = at.lagged_correlation(cause, {t: -v for t, v in effect.items()}, -1)
    check(neg["corr"] < -0.99 and at.verdict(-1, neg["corr"], neg["n"]) == "数据支持", "负向关系按方向判定为数据支持")
    check(at.verdict(1, -0.6, 50) == "与本体记载方向相反", "方向相反要明说")
    check(at.verdict(1, 0.35, 50) == "弱支持" and at.verdict(1, 0.1, 50) == "未发现支持证据", "弱支持与无证据的口径")
    check(at.verdict(0, -0.7, 50).startswith("同期强相关"), "本体未标方向时按绝对值判断")
    check(at.verdict(1, 0.9, 3) == "数据不足，无法判断", "样本不足不下结论")

    limit = {"normalLow": 33, "normalHigh": 35, "high": 35.5, "highHigh": 37, "low": 32, "lowLow": 30}
    series = {i * step: v for i, v in enumerate([34, 34.5, 35.2, 36, 37.5, 34, 32.5, 31])}
    stats = at.assess_tag(series, limit)
    check(
        stats.get("aboveNormal") == 3 and stats.get("aboveHigh") == 2 and stats.get("aboveHighHigh") == 1
        and stats.get("belowNormal") == 2 and stats.get("belowLow") == 1 and "belowLowLow" not in stats,
        f"逐档统计越限样本：{stats}",
    )
    check(at.anomaly_mask(series, limit, 1) == {2 * step, 3 * step, 4 * step}, "有限值时异常期 = 越出正常区间的时刻")
    check(len(at.anomaly_mask(series, None, -1)) == max(1, int(len(series) * at.ANOMALY_QUANTILE)), "无限值时异常期取最偏的分位")
    merged = at.zscore_average([{1: 10.0, 2: 20.0, 3: 30.0}, {1: 100.0, 2: 200.0, 3: 300.0, 4: 1.0}])
    check(set(merged) == {1, 2, 3} and abs(merged[1] + merged[3]) < 1e-9, "多测点按公共时刻标准化后平均")

    async def graph_checks() -> None:
        api = FakeApi()
        tree, controllers = await at._cause_tree(api, {"id": "robj-a", "name": "A"}, 3)
        by_id = {c["id"]: c for c in tree}
        check(set(by_id) == {"robj-b", "robj-v", "robj-c"}, f"只沿影响/控制执行机构上推，环路不重复：{sorted(by_id)}")
        check(by_id["robj-c"]["pathSign"] == -1 and by_id["robj-b"]["pathSign"] == 1, "路径方向按正负号相乘传播")
        check(by_id["robj-v"]["pathSign"] == 0 and by_id["robj-c"]["level"] == 2, "控制执行机构方向未标注，且不再往控制器上推")
        check("→负向→" in by_id["robj-c"]["path"] and by_id["robj-c"]["path"].endswith("A"), f"路径文本完整：{by_id['robj-c']['path']}")
        check(controllers == ["控制器K"], "识别出目标所在的控制回路")
        down, _ = await at._causal_walk(api, {"id": "robj-a", "name": "A"}, 2, "down")
        check([d["id"] for d in down] == ["robj-b"] and down[0]["path"].startswith("A →正向→"), "往下游找后果，不把'反馈给'控制器当后果")

        exact = await at._resolve_entity(api, "反应温度")
        check(exact["id"] == "robj-a", "名称精确命中")
        spaced = await at._resolve_entity(api, "反应 温度")
        check(spaced["id"] == "robj-a", "名称里多打的空格不影响命中")
        try:
            await at._resolve_entity(api, "温度")
            check(False, "多义名称应返回候选")
        except at.AnalysisInputError as exc:
            check({c["id"] for c in exc.candidates} == {"robj-a", "robj-b"}, "多义名称不自动挑，返回候选")

        # Executor：async 本地工具、ToolApiError 分类、返回体裁剪
        async def ok_handler(registry, arguments, api):
            return {"items": [{"n": i, "pad": "x" * 50} for i in range(200)], "total": 200}

        async def bad_handler(registry, arguments, api):
            raise ToolApiError("not_found", "没有这个对象")

        reg = ToolRegistry(
            [
                ToolSpec(name="t_ok", description="d", path="", handler=ok_handler, parameters=(ToolParameter("x"),)),
                ToolSpec(name="t_bad", description="d", path="", handler=bad_handler),
            ]
        )
        executor = ToolExecutor("http://127.0.0.1:9", max_result_chars=2000, registry=reg)
        good = await executor.execute(reg.require("t_ok"), "c1", "{}")
        bad = await executor.execute(reg.require("t_bad"), "c2", "{}")
        await executor.aclose()
        check(good.status == "ok" and good.truncated and len(good.to_llm_content()) < 2600, "async 本地工具的大返回体同样按预算裁剪")
        check(bad.status == "error" and bad.error_kind == "not_found", "本地工具访问本体失败时保留错误分类")

    # 越限统计：逐档判断与时长 / 连续时段
    check(at.classify(37.5, limit) == "高于高高限" and at.classify(35.2, limit) == "高于正常上沿", "取值分档按从严到宽判断")
    check(at.classify(31, limit) == "低于低限" and at.classify(34, limit) == "正常", "低侧分档与正常")
    minute = 60_000
    run_series = {i * 3 * minute: v for i, v in enumerate([34, 36, 36, 34, 36, 37.5, 36, 34, 32.5, 34])}
    prof = at.exceedance_profile(run_series, limit, 3 * minute)
    check(prof["minutes"] == {"aboveHighHigh": 3, "aboveHigh": 15, "aboveNormal": 15, "belowNormal": 3}, f"各档越限时长 = 样本数 × 间隔：{prof['minutes']}")
    check(prof["runCount"] == 3 and "（9分钟）" in prof["longestRuns"][0], f"连续越限时段按长度排序：{prof['longestRuns']}")
    check(prof["max"] == 37.5 and prof["worst"] == "高于高高限", "最值与最严重档位")
    low_only = at.exceedance_profile({i * minute: v for i, v in enumerate([34, 32.8, 31, 34])}, limit, minute)
    check(low_only["worst"] == "低于低限", f"低侧最严重档位取低限而不是正常下沿：{low_only['worst']}")

    asyncio.run(graph_checks())


# --------------------------------------------------------------- 真实本体


async def run_live_tests() -> None:
    print("\n[真实本体]")
    registry = build_ontology_registry(compact_relations=True)
    budget = LLM_PROFILES["local32k"]["max_tool_result_chars"]
    executor = ToolExecutor(settings.ontology_base_url, timeout=settings.ontology_timeout, max_result_chars=budget, registry=registry)

    async def call(name: str, **args):
        execution = await executor.execute(registry.require(name), "t", json.dumps(args, ensure_ascii=False))
        return execution

    try:
        for name in (
            "investigate_process_anomaly",
            "verify_process_influence",
            "summarize_area_relations",
            "check_limit_exceedance",
            "map_causal_neighborhood",
            "audit_data_gaps",
            "describe_equipment_links",
        ):
            spec = registry.get(name)
            check(spec is not None and spec.group in INITIAL_GROUPS, f"{name} 已注册且首批下发")

        # 动态挑一条两端都有测点、方向明确的影响关系
        rels = await executor.get_json(
            "/api/ontology/relations", {"category": "影响关系", "predicate": "负向影响", "matched": "true", "limit": 200}
        )
        chosen = None
        for rel in rels.get("items") or []:
            subj, obj = rel["subject"]["id"], rel["object"]["id"]
            if not (subj.startswith("robj-") and obj.startswith("robj-")):
                continue
            hs = await executor.get_json(f"/api/ontology/{subj}/history", {"startTime": "2026-01-01 00:00:00", "endTime": "2026-01-01 01:00:00", "limit": 1})
            ho = await executor.get_json(f"/api/ontology/{obj}/history", {"startTime": "2026-01-01 00:00:00", "endTime": "2026-01-01 01:00:00", "limit": 1})
            if hs.get("total") and ho.get("total"):
                chosen = rel
                break
        check(chosen is not None, "本体里能找到两端都有测点的负向影响关系")
        if chosen is None:
            return
        cause, effect = chosen["subject"], chosen["object"]
        print(f"        动态选取：{cause['entity']} --负向影响--> {effect['entity']}")

        ver = await call("verify_process_influence", cause=cause["id"], effect=effect["id"])
        data = ver.result or {}
        check(ver.status == "ok" and data["ontology"]["recorded"] and data["ontology"]["direction"] == "负向", "影响验证读出本体路径与负向")
        check(data["evidence"]["verdict"] in at._VERDICT_RANK and data["evidence"].get("corr") is not None, f"两端有测点时给出统计判断：{data['evidence']['verdict']}")
        check("模拟数据" in data["method"], "模拟数据会在 method 里声明")

        rev = await call("verify_process_influence", cause=effect["id"], effect=cause["id"])
        check(not rev.result["ontology"]["recorded"] and "反方向" in rev.result["ontology"]["note"], "反着问时识别出本体记载的是反方向")
        check(rev.result["evidence"]["verdict"].startswith("仅统计参考"), "本体没有记载的路径只给统计参考")

        inv = await call("investigate_process_anomaly", target=effect["id"], symptom="偏高")
        idata = inv.result or {}
        mine = next((c for c in idata.get("candidates", []) if c["id"] == cause["id"]), None)
        check(mine is not None and mine["level"] == 1 and mine["expected"] == "同期应偏低", "异常溯源把负向原因列为第一层，且预期方向取反")
        lim = idata.get("limit")
        if lim:
            raw = await executor.get_json(f"/api/ontology/{effect['id']}/limits")
            owner = next((x for x in raw["items"] if x["id"] == lim["id"]), {})
            check(owner.get("appliesTo") == effect["entity"], "只采用 appliesTo 为该对象本身的限值")
        check(not inv.truncated and len(inv.to_llm_content()) <= budget + 200, f"异常溯源返回体在 local32k 预算内（{len(inv.to_llm_content())} 字符）")

        clarify = await call("investigate_process_anomaly", target="温度")
        check(clarify.result.get("status") == "needs_clarification" and clarify.result.get("candidates"), "名称多义时返回候选而不是乱挑")

        areas = await executor.get_json("/api/ontology/process-areas")
        area = max(areas["items"], key=lambda a: a.get("relationCount") or 0)
        summ = await call("summarize_area_relations", area=area["code"])
        sdata = summ.result or {}
        independent = await executor.get_json("/api/ontology/relations", {"area": area["name"], "limit": 1})
        check(sdata.get("total") == independent.get("total"), f"工段关系总数与独立查询一致（{area['name']}：{sdata.get('total')}）")
        check(sum(row["count"] for row in sdata["byCategory"]) == sdata["total"], "各类别计数之和等于总数（不漏类别）")
        check(not summ.truncated, "工段统计返回体未被裁剪")

        # 越限统计：动态挑一个已填数值、且有测点的工艺量限值
        limits = await executor.get_json("/api/ontology/process-limits", {"hasValues": "true", "appliesToType": "工艺属性"})
        picked = next((x for x in limits.get("items") or [] if (x.get("matchedTargetCount") or x.get("targetCount"))), None)
        check(picked is not None, "本体里能找到已填数值、有测点的工艺量限值")
        if picked:
            print(f"        动态选取：{picked['appliesTo']}（{picked['id']}）")
            win = await call("check_limit_exceedance", target=picked["appliesTo"], startTime="2026-10-25 00:00:00", endTime="2026-10-26 00:00:00")
            w = win.result or {}
            check(w.get("limit", {}).get("id") == picked["id"], "越限统计用的是该工艺量本身的限值")
            check(w.get("abnormalTagCount", 0) + len(w.get("normalTags") or []) == w.get("tagCount"), "越限测点 + 正常测点 = 全部测点（不漏表）")
            longest = max((sum((r.get("minutes") or {}).values()) for r in w.get("abnormal") or []), default=0)
            check(all(m <= 24 * 60 + w["window"]["intervalMinutes"] for r in w.get("abnormal") or [] for m in (r.get("minutes") or {}).values()), f"单档越限时长不超过时间窗（最大合计 {longest} 分钟）")
            check(not win.truncated and len(win.to_llm_content()) <= budget + 200, f"越限统计返回体在 local32k 预算内（{len(win.to_llm_content())} 字符）")
            now = await call("check_limit_exceedance", target=picked["appliesTo"])
            check(now.result.get("mode") == "当前值" and now.result.get("tagCount"), "不给时间窗时核对当前值")

        # 影响因素与后果：用前面动态选出的关系，两端互相能找到对方
        down = await call("map_causal_neighborhood", target=cause["id"], scope="后果")
        up = await call("map_causal_neighborhood", target=effect["id"], scope="原因", withValues=True)
        check(any(r["id"] == effect["id"] and r["direction"] == "负向" for r in down.result["consequences"]), "从原因往下游能找到结果，方向为负向")
        mine_up = next((r for r in up.result["causes"] if r["id"] == cause["id"]), None)
        check(mine_up is not None and mine_up["measurable"] and mine_up.get("current"), "从结果往上游能找到原因，并带出当前值")
        hist = await executor.get_json(f"/api/ontology/{effect['id']}/realtime", {"limit": 1})
        check(up.result["target"]["measurable"] == bool(hist.get("total")), "有无测点与本体实时值接口一致")
        check(not up.truncated and len(up.to_llm_content()) <= budget + 200, f"梳理结果在 local32k 预算内（{len(up.to_llm_content())} 字符）")

        # 数据缺口盘点：数量与本体自己的统计一致，清单完整且不被裁剪
        raw_limits = await executor.get_json("/api/ontology/process-limits")
        stat = raw_limits.get("statusSummary") or {}
        overview = await call("audit_data_gaps")
        summary = overview.result["summary"]
        check(
            summary["limitTotal"] == stat.get("total") and summary["limitConfirmed"] == stat.get("confirmed")
            and summary["limitMissingValues"] == stat.get("total", 0) - stat.get("withValues", 0),
            f"限值计数与本体 statusSummary 一致：{summary}",
        )
        for kind, key, expected in (
            ("缺限值", "missingLimits", summary["limitMissingValues"]),
            ("推断限值", "inferredLimits", summary["limitInferredUnconfirmed"]),
            ("无测点", "unmeasured", summary["unmeasuredQuantities"]),
        ):
            listed = await call("audit_data_gaps", kind=kind)
            rows = sum(len(v) for v in (listed.result.get(key) or {}).values())
            check(rows == expected and not listed.truncated, f"{kind}清单完整列出 {rows}/{expected} 条且未被裁剪（{len(listed.to_llm_content())} 字符）")
        unmatched = await executor.get_json("/api/ontology/relation-entities", {"matched": "false", "type": "工艺属性"})
        check(summary["unmeasuredByType"].get("工艺属性") == unmatched.get("total"), "无测点工艺属性数与独立查询一致")

        # 设备关联：动态挑一台没有关联本体对象的设备、一台有的
        equipment = (await executor.get_json("/api/ontology/equipment", {"limit": 60})).get("items") or []
        bare = linked = None
        for item in equipment:
            rel = await executor.get_json(f"/api/ontology/{item['id']}/relations")
            if not rel.get("relationEntities") and not rel.get("relations") and bare is None:
                bare = item
            if rel.get("relationEntities") and linked is None:
                linked = item
            if bare and linked:
                break
        check(bare is not None and linked is not None, "能找到无关联与有关联的设备各一台")
        if bare:
            res = await call("describe_equipment_links", equipment=bare["id"])
            check(res.result["deviceLevelRecorded"] is False and "没有登记" in res.result["conclusion"], f"无设备级关系时明说并退到工段层面（{bare['name']}）")
            check(bool(res.result["area"].get("code")), "无设备级关系时仍给出所在工段")
        if linked:
            res = await call("describe_equipment_links", equipment=linked["id"])
            check(res.result["deviceLevelRecorded"] and res.result["device"].get("ontologyObjects"), f"有关联时列出对应本体对象（{linked['name']}）")
            check(not res.truncated and len(res.to_llm_content()) <= budget + 200, f"设备关联返回体在预算内（{len(res.to_llm_content())} 字符）")
        same_area: dict = {}
        by_name: dict = {}
        for item in (await executor.get_json("/api/ontology/equipment", {"limit": 2000})).get("items") or []:
            same_area.setdefault((item["name"], item.get("areaId")), []).append(item["id"])
            by_name.setdefault(item["name"], set()).add(item.get("areaId"))
        twin = next((k for k, ids in same_area.items() if len(ids) > 1 and len(by_name[k[0]]) == 1), None)
        if twin:
            res = await call("describe_equipment_links", equipment=twin[0])
            check(len(res.result["device"].get("ids") or []) == len(same_area[twin]), f"同工段同名的多站点设备合并看待（{twin[0]}：{len(same_area[twin])} 条）")
        spread = next((n for n, areas_ in by_name.items() if len(areas_) > 1), None)
        if spread:
            res = await call("describe_equipment_links", equipment=spread)
            check(res.result.get("status") == "needs_clarification", f"跨工段同名设备不合并，返回候选（{spread}）")
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
