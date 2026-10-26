"""Agent Loop 自测（不需要 LLM Key，需要本体服务在跑）。

    ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.test_agent_loop

用一个"按脚本出牌"的假 LLM 替换真实模型，验证 Runtime 本身的正确性：
多步 Tool 调用、结果回灌、实体上下文、工具预算、异常不崩溃。
真实 DeepSeek 的行为不在本测试范围内——这里测的是 Agent 骨架，不是模型智力。
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Sequence

from backend.agent.context import ConversationStore
from backend.agent.events import ANSWER, DONE, TOOL_RESULT
from backend.agent.runtime import AgentRuntime
from backend.config import settings
from backend.llm.base import LLMResponse, ToolCall
from backend.tools.executor import ToolExecutor
from backend.tools.ontology_tools import build_ontology_registry


class ScriptedLLM:
    """按预置脚本依次返回 tool_calls / 最终回答的假 LLM。

    每个脚本项要么是 [(tool_name, args), ...]，要么是一段最终回答文本。
    还会把每次收到的 messages 记下来，供断言检查"工具结果确实回灌给了模型"。
    """

    model = "scripted-stub"

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.seen_messages: list[list[dict[str, Any]]] = []
        self.calls = 0

    async def chat(self, messages: Sequence[dict[str, Any]], tools=None, *, on_text_delta=None, stream=None):
        self.calls += 1
        self.seen_messages.append([dict(message) for message in messages])
        step = self.script.pop(0) if self.script else "（脚本耗尽，直接作答）"

        if isinstance(step, str):
            if on_text_delta:
                for piece in (step[i : i + 8] for i in range(0, len(step), 8)):
                    await on_text_delta(piece)
            return LLMResponse(content=step, finish_reason="stop")

        if tools is None:
            # 工具预算耗尽时 Runtime 不再传 tools，此时必须收口作答
            return LLMResponse(content="（工具预算用尽后的收口回答）", finish_reason="stop")

        return LLMResponse(
            content="",
            tool_calls=[
                ToolCall(id=f"call_{self.calls}_{i}", name=name, arguments=json.dumps(args, ensure_ascii=False))
                for i, (name, args) in enumerate(step)
            ],
            finish_reason="tool_calls",
        )

    async def aclose(self) -> None:
        return None


def build_runtime(script: list[Any], executor: ToolExecutor, **kwargs) -> tuple[AgentRuntime, ScriptedLLM]:
    llm = ScriptedLLM(script)
    runtime = AgentRuntime(llm, build_ontology_registry(), executor, **kwargs)
    return runtime, llm


async def collect(runtime: AgentRuntime, conversation, question: str) -> list:
    return [event async for event in runtime.run_turn(conversation, question)]


def check(condition: bool, label: str) -> bool:
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


async def main() -> int:
    executor = ToolExecutor(settings.ontology_base_url, timeout=settings.ontology_timeout, max_result_chars=6000)
    store = ConversationStore()
    ok = True

    # ---------------------------------------------------------------- 用例 1
    print("\n[1] 多步 Tool 链路：检索设备 → 查详情 → 查关系 → 作答")
    runtime, llm = build_runtime(
        [
            [("query_equipment_list", {"keyword": "一层排渣泵", "limit": 3})],
            [("query_equipment_detail", {"equipment_id": "__FROM_PREVIOUS__"})],
            [("query_object_relations", {"object_id": "__FROM_PREVIOUS__"})],
            "一层排渣泵位于提取水洗工段，共 5 个 DCS 点。",
        ],
        executor,
    )
    conversation = store.get_or_create("t1")

    # 第一步先真实跑一次，拿到真实 ID 再回填脚本（不写死任何业务 ID）
    probe = await executor.execute(
        build_ontology_registry().require("query_equipment_list"),
        "probe",
        json.dumps({"keyword": "一层排渣泵", "limit": 1}),
    )
    equipment_id = (probe.result or {}).get("items", [{}])[0].get("id")
    llm.script[1] = [("query_equipment_detail", {"equipment_id": equipment_id})]
    llm.script[2] = [("query_object_relations", {"object_id": equipment_id})]

    events = await collect(runtime, conversation, "介绍一下一层排渣泵")
    tool_results = [event for event in events if event.type == TOOL_RESULT]
    answers = [event for event in events if event.type == ANSWER]
    done = [event for event in events if event.type == DONE][0]

    ok &= check(len(tool_results) == 3, f"执行了 3 次工具调用（实际 {len(tool_results)}）")
    ok &= check(all(event.data["status"] != "error" for event in tool_results), "三次工具调用均未报错")
    ok &= check(len(answers) == 1 and "一层排渣泵" in answers[0].data["text"], "产出了最终回答")
    ok &= check(done.data["llmRounds"] == 4, f"模型被调用 4 轮（实际 {done.data['llmRounds']}）")

    # 工具结果确实回灌进了下一轮的 messages
    last_messages = llm.seen_messages[-1]
    tool_messages = [m for m in last_messages if m.get("role") == "tool"]
    ok &= check(len(tool_messages) == 3, f"3 条 tool 结果回灌给了模型（实际 {len(tool_messages)}）")

    # ---------------------------------------------------------------- 用例 2
    print("\n[2] 实体上下文：第二轮无需重复设备名")
    ok &= check(conversation.current_equipment is not None, "当前设备已写入会话上下文")
    if conversation.current_equipment:
        ok &= check(
            conversation.current_equipment.identifier == equipment_id,
            f"当前设备 ID 正确（{conversation.current_equipment.identifier}）",
        )
    block = conversation.context_block() or ""
    ok &= check("当前设备" in block, "上下文块里带上了当前设备")

    runtime2, llm2 = build_runtime([[("query_tags", {"equipmentId": equipment_id, "limit": 5})], "它有 5 个测点。"], executor)
    await collect(runtime2, conversation, "它有哪些DCS点？")
    injected = [m for m in llm2.seen_messages[0] if m.get("role") == "system"]
    ok &= check(
        any("当前设备" in (m.get("content") or "") for m in injected),
        "第二轮提问时，当前设备上下文被注入 system 消息",
    )

    # ---------------------------------------------------------------- 用例 3
    print("\n[3] 工具预算：超过上限后强制收口")
    endless = [[("query_ontology_overview", {})] for _ in range(20)]
    runtime3, _ = build_runtime(endless, executor, max_tool_calls_per_turn=4)
    events3 = await collect(runtime3, store.get_or_create("t3"), "一直查")
    done3 = [event for event in events3 if event.type == DONE][0]
    ok &= check(done3.data["toolCalls"] == 4, f"工具调用被限制在 4 次（实际 {done3.data['toolCalls']}）")
    ok &= check(any(event.type == ANSWER for event in events3), "预算耗尽后仍给出了最终回答")

    # ---------------------------------------------------------------- 用例 4
    print("\n[4] 异常处理：不存在的工具 / 非法参数 / 404 都不能把 Agent 打崩")
    runtime4, llm4 = build_runtime(
        [
            [("query_nonexistent_tool", {"x": 1})],
            [("query_equipment_detail", {})],  # 缺必填参数
            [("query_equipment_detail", {"equipment_id": "一层排渣泵"})],  # 传名称 → 404
            "三次都失败了，我如实告诉你查不到。",
        ],
        executor,
    )
    events4 = await collect(runtime4, store.get_or_create("t4"), "故意触发异常")
    results4 = [event for event in events4 if event.type == TOOL_RESULT]
    ok &= check(len(results4) == 3 and all(e.data["status"] == "error" for e in results4), "三次失败均被捕获为 error")
    kinds = [m.get("content", "") for m in llm4.seen_messages[-1] if m.get("role") == "tool"]
    ok &= check(any("unknown_tool" in c for c in kinds), "未知工具错误回灌给了模型")
    ok &= check(any("not_found" in c for c in kinds), "404 错误回灌给了模型")
    ok &= check(any(event.type == ANSWER for event in events4), "失败后仍能作答，未抛异常")

    # ---------------------------------------------------------------- 用例 5
    print("\n[5] 大返回体防护：默认分页 + 超大返回体裁剪")
    registry = build_ontology_registry()

    # 5a. 模型不给 limit 时，ToolSpec 的默认值兜住，不会把全量列表拉回来
    unbounded = await executor.execute(registry.require("query_equipment_list"), "c", json.dumps({}))
    ok &= check(unbounded.arguments.get("limit") == 30, f"未给 limit 时自动补默认分页（limit={unbounded.arguments.get('limit')}）")
    ok &= check(
        (unbounded.result or {}).get("total", 0) > len((unbounded.result or {}).get("items") or []),
        "total 仍是真实总数，大于本次返回条数",
    )

    # 5b. 无分页参数的详情接口可能返回几十万字符，必须被裁剪且如实告知模型
    biggest = max(
        (unbounded.result or {}).get("items") or [],
        key=lambda item: item.get("tagCount") or 0,
        default=None,
    )
    if biggest:
        detail = await executor.execute(
            registry.require("query_equipment_detail"), "c", json.dumps({"equipment_id": biggest["id"]})
        )
        content = detail.to_llm_content()
        ok &= check(detail.raw_bytes > 50_000, f"原始返回确实很大（{detail.raw_bytes}B，设备 {biggest['name']}）")
        ok &= check(len(content) < 20_000, f"回灌给模型的内容被压到 {len(content)} 字符")
        ok &= check(detail.truncated and "truncationNote" in content, "裁剪事实已如实告知模型")

    # ---------------------------------------------------------------- 用例 6
    print("\n[6] 历史裁剪：超长会话按整轮丢弃，不破坏 tool 消息配对")
    long_conversation = store.get_or_create("t6")
    for index in range(6):
        runtime6, _ = build_runtime([[("query_ontology_overview", {})], f"第 {index} 轮回答"], executor)
        await collect(runtime6, long_conversation, f"第 {index} 个问题")
    long_conversation.compact(max_messages=8, max_chars=100_000)
    wire = long_conversation.wire_messages()
    orphan = False
    for position, message in enumerate(wire):
        if message.get("role") == "tool":
            previous = wire[position - 1] if position else {}
            if previous.get("role") not in ("assistant", "tool"):
                orphan = True
    ok &= check(not orphan, "裁剪后没有出现孤立的 tool 消息")
    ok &= check(long_conversation.dropped_turns > 0, f"确实丢弃了 {long_conversation.dropped_turns} 轮早期对话")

    # ---------------------------------------------------------------- 用例 7
    print("\n[7] 同一轮里原样重复的工具调用不再执行")
    runtime7, llm7 = build_runtime(
        [
            [("query_ontology_overview", {})],
            [("query_ontology_overview", {})],
            [("query_equipment_list", {"limit": 2, "keyword": "泵"})],
            [("query_equipment_list", {"keyword": "泵", "limit": 2})],
            "全车间设备数见概览。",
        ],
        executor,
    )
    events7 = await collect(runtime7, store.get_or_create("t7"), "车间有多少设备？")
    results7 = [e.data for e in events7 if e.type == "tool_result"]
    ok &= check([r["status"] for r in results7] == ["ok", "empty", "ok", "empty"], f"重复调用标记为未执行：{[r['status'] for r in results7]}")
    ok &= check("重复" in (results7[1].get("resultSummary") or ""), "执行面板写明是重复调用")
    duplicate_msgs = [m for m in llm7.seen_messages[-1] if m.get("role") == "tool" and '"duplicate": true' in (m.get("content") or "")]
    ok &= check(len(duplicate_msgs) == 2, "回灌给模型的是一句提示，而不是第二份完整结果（参数顺序不同也能识别）")

    # ---------------------------------------------------------------- 用例 8
    print("\n[8] 用到模拟数据而回答没声明时，Runtime 兜底补上声明")
    footer = "模拟数据服务，不是现场真实读数"
    cases = [
        ("漏写声明 → 补上", [("investigate_process_anomaly", {"target": "釜内反应温度", "symptom": "偏高"})], "釜温全天偏高。", 1),
        ("已写声明 → 不重复", [("investigate_process_anomaly", {"target": "釜内反应温度", "symptom": "偏高"})], "釜温全天偏高（模拟数据）。", 0),
        ("没用到模拟数据 → 不加", [("query_ontology_overview", {})], "共 1340 台设备。", 0),
    ]
    for label, step, text, expected in cases:
        runtime8, _ = build_runtime([step, text], executor)
        conversation8 = store.get_or_create(f"t8-{label}")
        events8 = await collect(runtime8, conversation8, "问题")
        answer = next(e.data["text"] for e in events8 if e.type == "answer")
        streamed = "".join(e.data["text"] for e in events8 if e.type == "answer_delta")
        ok &= check(answer.count(footer) == expected and streamed.count(footer) == expected, f"{label}（流式与最终回答一致）")
        ok &= check(conversation8.wire_messages()[-1]["content"] == answer, f"{label}：写入会话历史的是同一份回答")

    await executor.aclose()
    print("\n全部通过" if ok else "\n存在失败用例")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
