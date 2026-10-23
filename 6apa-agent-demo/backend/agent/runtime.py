"""Agent Runtime —— 自己实现的最小 Agent Loop。

不使用任何 Agent Framework（LangChain / LangGraph / Dify / AutoGen / CrewAI / SK）。

循环本身完全与业务无关：

    用户问题 → 读上下文 → 调 LLM → 模型要工具？
                              ├─ 要：执行工具 → 结果回灌 → 再调 LLM（循环）
                              └─ 不要：输出最终回答

代码里没有任何 `if "E-101" in question` 这类针对具体问题的分支，
也没有为"查设备""查上游""查运行情况"预设的固定 Workflow。
走哪条路径完全由模型根据 Tool Schema 自行决定。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, AsyncIterator

from ..llm.base import LLMClient, LLMError, LLMResponse
from ..tools.executor import ToolExecution, ToolExecutor
from ..tools.registry import ToolRegistry, ToolSpec
from . import events
from .context import Conversation, EntityRef, ToolHistoryItem, first_non_empty, resolve_path
from .events import AgentEvent
from .prompt import load_system_prompt

logger = logging.getLogger("agent.runtime")


class AgentRuntime:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        executor: ToolExecutor,
        *,
        max_tool_calls_per_turn: int = 15,
        max_history_messages: int = 40,
        max_context_chars: int = 90000,
        initial_tools: list[str] | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.executor = executor
        self.max_tool_calls_per_turn = max_tool_calls_per_turn
        self.max_history_messages = max_history_messages
        self.max_context_chars = max_context_chars
        # 渐进解锁：只有这批工具一开始就下发；为空表示一次下发全部。
        # Runtime 不关心里面是哪些名字，名单由装配层给。
        self.initial_tools = list(initial_tools) if initial_tools else None

    # ------------------------------------------------------------------ 主循环

    async def run_turn(self, conversation: Conversation, user_message: str) -> AsyncIterator[AgentEvent]:
        turn = conversation.begin_turn(user_message)
        started = time.perf_counter()
        tool_budget = self.max_tool_calls_per_turn
        tool_calls_used = 0
        rounds = 0

        yield AgentEvent(events.TURN_START, {"conversationId": conversation.conversation_id, "turn": turn})
        yield events.status("理解用户问题", phase="understanding", done=True)

        # 本轮下发给模型的工具名单。渐进解锁模式下从 initial_tools 起步，
        # 模型通过工具发现要到新工具后，本轮后续请求就带上它们。
        active_tools = list(self.initial_tools) if self.initial_tools else None
        tool_schemas = self.registry.to_openai_schemas(active_tools)

        while True:
            rounds += 1
            conversation.compact(
                max_messages=self.max_history_messages,
                max_chars=self.max_context_chars,
            )
            messages = self._build_messages(conversation)

            # 工具预算用完后，最后再调一次模型，但不给工具——强制它收口作答
            budget_left = tool_budget - tool_calls_used
            tools = tool_schemas if budget_left > 0 else None

            streamed_text: list[str] = []
            response: LLMResponse | None = None
            failure: BaseException | None = None

            # 真流式：文本片段在模型还在生成时就推给前端，不等整轮结束
            async for kind, payload in self._stream_llm(messages, tools):
                if kind == "delta":
                    streamed_text.append(payload)
                    yield AgentEvent(events.ANSWER_DELTA, {"text": payload})
                elif kind == "done":
                    response = payload
                else:
                    failure = payload

            if failure is not None:
                if isinstance(failure, LLMError):
                    message, kind_name = str(failure), "llm"
                else:
                    logger.exception("Agent 轮次异常", exc_info=failure)
                    message, kind_name = f"Agent 内部错误：{failure}", "agent"
                yield events.error(message, kind=kind_name)
                conversation.add_assistant({"role": "assistant", "content": f"（本轮失败：{message}）"})
                yield AgentEvent(
                    events.DONE, self._done_payload(conversation, tool_calls_used, rounds, started, ok=False)
                )
                return

            assert response is not None

            if not response.wants_tools:
                answer = (response.content or "").strip()
                if not answer:
                    answer = "（模型未返回内容。请重试，或换一种问法。）"
                conversation.add_assistant({"role": "assistant", "content": answer})
                yield AgentEvent(events.ANSWER, {"text": answer})
                yield AgentEvent(events.CONTEXT, conversation.public_state())
                yield AgentEvent(events.DONE, self._done_payload(conversation, tool_calls_used, rounds, started, ok=True))
                return

            # 本轮模型决定调工具：此前流出的文字不是最终回答，转成执行说明
            if streamed_text:
                note = "".join(streamed_text).strip()
                yield AgentEvent(events.ANSWER_RESET, {"text": note})
                if note:
                    yield events.status(note, phase="planning", done=True)

            conversation.add_assistant(response.to_assistant_message())

            for call in response.tool_calls:
                if tool_calls_used >= tool_budget:
                    # 超预算的调用不执行，但必须回一条 tool 消息，否则协议不合法
                    conversation.add_tool_result(
                        call.id,
                        call.name,
                        '{"ok": false, "error": "已达到本轮工具调用上限，请基于已获得的信息直接作答。"}',
                    )
                    yield events.status(
                        f"已达到本轮工具调用上限（{tool_budget} 次），转入综合分析",
                        phase="limit",
                        done=True,
                    )
                    continue

                tool_calls_used += 1
                spec = self.registry.get(call.name)

                yield AgentEvent(
                    events.TOOL_CALL,
                    {
                        "callId": call.id,
                        "tool": call.name,
                        "index": tool_calls_used,
                        "arguments": _safe_json(call.arguments),
                        "label": _tool_label(spec, call.name),
                    },
                )

                if spec is None:
                    # 模型幻觉出一个不存在的工具：告诉它，让它自己纠正
                    available = active_tools if active_tools is not None else self.registry.names()
                    message = f"工具 {call.name} 不存在。当前可用：{', '.join(available)}"
                    if active_tools is not None:
                        message += "。需要别的工具时，先调用工具发现类工具按组或关键词取用。"
                    conversation.add_tool_result(
                        call.id, call.name, f'{{"ok": false, "errorKind": "unknown_tool", "error": "{message}"}}'
                    )
                    yield AgentEvent(
                        events.TOOL_RESULT,
                        {
                            "callId": call.id,
                            "tool": call.name,
                            "status": "error",
                            "error": message,
                            "durationMs": 0,
                        },
                    )
                    continue

                execution = await self.executor.execute(spec, call.id, call.arguments)

                # 工具发现类工具可能要求下发更多工具，本轮后续请求立即带上。
                # 另外：模型凭记忆直接调了一个尚未下发的工具且调成功了，
                # 就把它补进名单——让它后续能看到该工具的参数说明，少犯参数错。
                newly = list(execution.unlocked)
                if active_tools is not None and execution.status != "error" and call.name not in active_tools:
                    newly.append(call.name)
                if newly and active_tools is not None:
                    added = [n for n in newly if n not in active_tools]
                    if added:
                        active_tools.extend(added)
                        tool_schemas = self.registry.to_openai_schemas(active_tools)
                        yield events.status(
                            f"已取用 {len(added)} 个工具：{'、'.join(added)}",
                            phase="tool_unlock",
                            done=True,
                        )

                conversation.add_tool_result(call.id, call.name, execution.to_llm_content())
                conversation.record_tool(
                    ToolHistoryItem(
                        turn=turn,
                        tool=call.name,
                        arguments=execution.arguments,
                        status=execution.status,
                        summary=execution.to_public_dict()["resultSummary"],
                        duration_ms=execution.duration_ms,
                    )
                )
                self._capture_entity(conversation, spec, execution)

                yield AgentEvent(events.TOOL_RESULT, execution.to_public_dict())
                if execution.graph:
                    yield AgentEvent(
                        events.GRAPH,
                        {"callId": call.id, "tool": call.name, **execution.graph},
                    )

            yield AgentEvent(events.CONTEXT, conversation.public_state())
            yield events.status("综合已获取的本体数据", phase="analyzing")

    # ------------------------------------------------------------------ 内部

    async def _stream_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """把一次 LLM 调用变成事件流。

        LLM 客户端通过回调吐出文本增量，而 run_turn 需要的是一个可以 yield 的流。
        用一个队列把两者接起来：回调往队列里塞，这里从队列里取。
        调用结束时塞一个终止项，保证循环一定能退出。
        """
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def on_delta(text: str) -> None:
            await queue.put(("delta", text))

        async def pump() -> None:
            try:
                response = await self.llm.chat(messages, tools, on_text_delta=on_delta)
                await queue.put(("done", response))
            except BaseException as exc:  # noqa: BLE001 - 必须把任何异常送回主流程
                await queue.put(("error", exc))

        task = asyncio.create_task(pump())
        try:
            while True:
                kind, payload = await queue.get()
                yield kind, payload
                if kind in ("done", "error"):
                    return
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _build_messages(self, conversation: Conversation) -> list[dict[str, Any]]:
        """拼出发给模型的消息列表。

        三段系统级内容（系统提示 / 当前时间 / 会话上下文）**合并成一条 system 消息**。
        OpenAI 与 DeepSeek 允许多条 system，但不少本地推理服务（vLLM 的部分 chat template、
        Xinference、LMDeploy 等）只接受开头的唯一一条，多发会直接 400：
        "System message must be at the beginning."。合并后两边都能跑，也不损失信息。
        """
        parts = [load_system_prompt()]
        # 模型不知道现在几点；查历史值、理解"过去一小时"都需要它
        parts.append(f"【当前时间】{_now_text()}（东八区）")
        context_block = conversation.context_block()
        if context_block:
            parts.append(context_block)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "\n\n".join(p for p in parts if p)}
        ]
        messages.extend(conversation.wire_messages())
        return messages

    @staticmethod
    def _capture_entity(conversation: Conversation, spec: ToolSpec, execution: ToolExecution) -> None:
        """按 ToolSpec 的声明把"当前实体"写进会话上下文。

        注意这是数据驱动的：Runtime 不认识"设备""工段"这些概念，
        它只是照着 spec.entity_capture 说的去取值。
        """
        capture = spec.entity_capture
        if capture is None or execution.status == "error" or execution.result is None:
            return

        identifier = first_non_empty(execution.arguments.get(key) for key in capture.from_args)
        name = first_non_empty(resolve_path(execution.result, path) for path in capture.from_result_paths)
        if not identifier and not name:
            return

        kind = capture.kind
        label = capture.label
        # 通用对象工具返回体自带 objectKind，按它归位，比静态 kind 更准
        object_kind = resolve_path(execution.result, "objectKind")
        if kind == "object" and isinstance(object_kind, str):
            kind = {"equipment": "equipment", "area": "process_area"}.get(object_kind, object_kind)
            label = {"equipment": "设备", "process_area": "工段", "parameter": "参数"}.get(kind, "对象")

        conversation.remember_entity(
            EntityRef(
                kind=kind,
                label=label,
                identifier=str(identifier or ""),
                name=str(name or identifier or ""),
                from_tool=spec.name,
            )
        )

    @staticmethod
    def _done_payload(
        conversation: Conversation,
        tool_calls: int,
        rounds: int,
        started: float,
        *,
        ok: bool,
    ) -> dict[str, Any]:
        return {
            "conversationId": conversation.conversation_id,
            "turn": conversation.turn_index,
            "toolCalls": tool_calls,
            "llmRounds": rounds,
            "elapsedMs": int((time.perf_counter() - started) * 1000),
            "ok": ok,
        }


def _safe_json(raw: str) -> Any:
    import json

    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {"_raw": raw[:500]}


def _tool_label(spec: ToolSpec | None, name: str) -> str:
    if spec is None:
        return name
    # 取描述第一句作为可读标签，避免前端写死一份工具中文名映射
    head = spec.description.split("。")[0].strip()
    return head or name


def _now_text() -> str:
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def new_call_id() -> str:
    return "call_" + uuid.uuid4().hex[:12]


__all__ = ["AgentRuntime", "new_call_id"]
