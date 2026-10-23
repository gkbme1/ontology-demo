"""示例问题自测。

    ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.test_examples

验两件事：
1. examples.json 结构合法，且里面提到的每个工具名都真实存在于 Tool Registry；
2. 「工艺调查」组的问题在本体里确实查得通——把参考工具链逐步打到真实本体上，
   看每一步是不是都有数据支撑。

注意：参考工具链只用于本测试与演示对照，运行时不会下发给模型，
Agent 仍然自己规划调用顺序。这里验证的是「本体里有料可查」，不是「Agent 必须这么查」。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys

from backend.agent.examples import all_questions, load_examples
from backend.config import settings
from backend.tools.executor import ToolExecutor
from backend.tools.ontology_tools import build_ontology_registry

TOOL_NAME = re.compile(r"query_[a-z_]+")
results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def dig(node, dotted: str):
    for part in dotted.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list):
            index = int(part)
            node = node[index] if index < len(node) else None
        else:
            return None
        if node is None:
            return None
    return node


async def main() -> int:
    registry = build_ontology_registry()
    known = {spec.name for spec in registry}
    catalog = load_examples()

    print("[结构]")
    check(catalog["available"] and catalog["groups"], f"示例问题已加载：{catalog['total']} 条 / {len(catalog['groups'])} 组")
    check(all(item.get("id") and item.get("question") for group in catalog["groups"] for item in group["items"]),
          "每条示例都有 id 与 question")
    questions = all_questions()
    check(len(set(questions)) == len(questions), "没有重复的问题文本")

    referenced: set[str] = set()
    for group in catalog["groups"]:
        for item in group["items"]:
            for line in item.get("referenceToolChain") or []:
                referenced.update(TOOL_NAME.findall(line))
    unknown = sorted(referenced - known)
    check(not unknown, f"参考工具链里提到的 {len(referenced)} 个工具名都存在" + (f"；未知：{unknown}" if unknown else ""))

    investigation = next((g for g in catalog["groups"] if g["key"] == "investigation"), None)
    check(investigation is not None and investigation["count"] >= 3,
          f"工艺调查组有 {investigation['count'] if investigation else 0} 条案例")

    print("\n[工艺调查案例在本体里查得通]")
    executor = ToolExecutor(
        settings.ontology_base_url,
        timeout=settings.ontology_timeout,
        max_result_chars=settings.max_tool_result_chars,
    )

    async def call(name: str, **args):
        return await executor.execute(registry.require(name), "case", json.dumps(args, ensure_ascii=False))

    # ① 异常参数 → 关系对象 ID
    entities = await call("query_relation_entities", keyword="釜内反应温度")
    items = dig(entities.result, "items") or []
    temp = next((i for i in items if i["name"] == "釜内反应温度"), None)
    check(temp is not None, f"按关键词找到工艺属性「釜内反应温度」（命中 {dig(entities.result, 'total')} 个）")
    if temp is None:
        await executor.aclose()
        return 1

    # ② 判异常的依据：工艺限值
    limits = await call("query_object_limits", object_id=temp["id"])
    limit_items = dig(limits.result, "items") or []
    check(limit_items and limit_items[0].get("hasValues"),
          f"该参数有工艺限值可作判据：{limit_items[0]['id']} 正常 {limit_items[0].get('normalLow')}~{limit_items[0].get('normalHigh')} "
          f"{limit_items[0].get('unit')}（状态 {limit_items[0].get('status')}）" if limit_items else "查不到限值")

    # ③ 异常本身：当前值逐点比对
    checked = await call("query_limit_check", object_id=temp["id"])
    check((dig(checked.result, "checked") or 0) > 0,
          f"逐点越限判断可用，检查 {dig(checked.result, 'checked')} 个测点，汇总 {dig(checked.result, 'summary')}")

    # ④ 候选原因：本体记载的影响因素。
    # 用 query_relations(entityId) 而不是 query_object_relations——后者把匹配实例与测量锚点一起带回来，
    # 返回体大、会触发裁剪；前者只回关系，7 条一条不少。Agent 看到 truncationNote 也应该这样换路。
    relations = await call("query_relations", entityId=temp["id"], limit=40, view="compact")
    check(not relations.truncated, f"关系查询未被裁剪，拿到完整的 {dig(relations.result, 'total')} 条关系")
    rels = dig(relations.result, "items") or []
    causes = [r for r in rels if r.get("objectEntity") == "釜内反应温度" and "影响" in (r.get("predicate") or "")]
    effects = [r for r in rels if r.get("subjectEntity") == "釜内反应温度" and "影响" in (r.get("predicate") or "")]
    check(causes, f"本体记载了 {len(causes)} 个影响该参数的因素：" + "、".join(r["subjectEntity"] for r in causes))
    check(effects, f"以及 {len(effects)} 条后果：" + "、".join(r["objectEntity"] for r in effects))
    check(all(r.get("domainDescription") for r in causes + effects), "每条因果关系都带工艺机理说明，可作为回答依据")

    # ⑤ 影响因素能不能用数据验证：有的有测点，有的没有——两种都要能查出来
    # v2 有 1174 个关系对象，不分页必被裁剪；这里按名字逐个精确取
    entity_by_name: dict[str, dict] = {}
    wanted = {r["subjectEntity"] for r in causes} | {r["objectEntity"] for r in effects} | {temp["name"]}
    for name in sorted(wanted):
        batch = await call("query_relation_entities", keyword=name, limit=5)
        for entity in dig(batch.result, "items") or []:
            if isinstance(entity, dict) and entity.get("name") == name:
                entity_by_name.setdefault(name, entity)
    check(len(entity_by_name) >= len(wanted) - 1, f"按名称精确取到 {len(entity_by_name)} / {len(wanted)} 个相关对象")
    anchored, unanchored = [], []
    for relation in causes:
        name = relation["subjectEntity"]
        entity = entity_by_name.get(name)
        if entity is None:
            unanchored.append(f"{name}（不在工艺属性清单内）")
        elif entity.get("matchStatus") == "MATCHED" and entity.get("tagCount"):
            anchored.append(f"{name}×{entity['tagCount']}点")
        else:
            unanchored.append(f"{name}（无测点）")
    check(anchored or unanchored, f"影响因素可落到测点的：{anchored or '无'}；无测点的：{unanchored or '无'}")
    check(
        True,
        f"影响因素可测 {len(anchored)} 个 / 不可测 {len(unanchored)} 个——两半都要在回答里说清楚",
    )

    # ⑥ 同期历史：能取到曲线做时间/方向/幅度比对
    import datetime as dt

    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    start = (now - dt.timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
    end = (now - dt.timedelta(days=1)).strftime("%Y-%m-%d 23:59:59")
    history = await call("query_history_values", object_id=temp["id"], startTime=start, endTime=end,
                         interval=1800000, limit=2)
    hist_items = dig(history.result, "items") or []
    check(hist_items and (hist_items[0].get("count") or 0) > 0,
          f"能取到「昨天」整天的历史曲线：{hist_items[0]['tagName']} {hist_items[0]['count']} 个采样点，"
          f"stats={hist_items[0].get('stats')}" if hist_items else "取不到历史值")
    simulated = dig(history.result, "dataSource.simulated")
    check(simulated is not None, f"历史值带模拟标记（simulated={simulated}），Agent 必须在回答中声明")

    print("\n[两端都有测点的因果路径——取历史值验证的闭环走得通]")
    # 直接用釜内反应温度这条链：v2 起它的四个原因全部有测点
    verifiable = []
    for relation in causes:
        entity = entity_by_name.get(relation["subjectEntity"])
        if entity and entity.get("tagCount"):
            verifiable.append(relation)
    check(verifiable, "存在两端都有测点的因果关系：" +
          "；".join(f"{r['subjectEntity']}--{r['predicate']}-->{r['objectEntity']}" for r in verifiable))

    for relation in verifiable[:2]:
        for role in ("subjectEntity", "objectEntity"):
            entity = entity_by_name.get(relation[role])
            if entity is None:
                continue
            series = await call("query_history_values", object_id=entity["id"], startTime=start,
                                endTime=end, interval=1800000, limit=1)
            first = (dig(series.result, "items") or [{}])[0]
            check((first.get("count") or 0) > 0,
                  f"  {entity['name']}：{first.get('tagName')} 取到 {first.get('count')} 个采样点 "
                  f"{first.get('stats', {}).get('min')}~{first.get('stats', {}).get('max')} {first.get('unit') or ''}")

    await executor.aclose()
    print(f"\n{sum(results)} / {len(results)} 通过")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
