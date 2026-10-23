"""命令行版 Agent（Phase 1 验收用）。

    python3 -m scripts.cli                     # 进入多轮交互
    python3 -m scripts.cli "水解工段有哪些设备？"  # 单问单答

在没有前端的情况下验证：用户问题 → Agent → Tool → Tool Result → Agent → 最终回答。
"""

from __future__ import annotations

import asyncio
import sys

from backend.agent.context import ConversationStore
from backend.agent.events import ANSWER, ANSWER_DELTA, ANSWER_RESET, DONE, ERROR, GRAPH, STATUS, TOOL_CALL, TOOL_RESULT
from backend.agent.runtime import AgentRuntime
from backend.config import settings
from backend.llm.openai_compatible import build_llm_client
from backend.logging_setup import setup_logging
from backend.tools.executor import ToolExecutor
from backend.tools.ontology_tools import build_ontology_registry

if sys.platform == "win32":
    import os

    os.system("")  # 让 Windows 控制台识别 ANSI 颜色转义

DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


async def ask(runtime: AgentRuntime, conversation, question: str) -> None:
    streaming = False
    async for event in runtime.run_turn(conversation, question):
        if event.type == STATUS:
            print(f"{DIM}· {event.data['text']}{RESET}")
        elif event.type == TOOL_CALL:
            print(f"{CYAN}→ {event.data['tool']}{RESET} {event.data['arguments']}")
        elif event.type == TOOL_RESULT:
            mark = GREEN if event.data["status"] != "error" else RED
            detail = event.data.get("error") or event.data.get("resultSummary")
            extra = " [已裁剪]" if event.data.get("truncated") else ""
            print(f"{mark}← {event.data['tool']}{RESET} {event.data['durationMs']}ms {detail}{extra}")
        elif event.type == GRAPH:
            print(f"{DIM}  关系图：{len(event.data.get('nodes') or [])} 节点 / {len(event.data.get('edges') or [])} 边{RESET}")
        elif event.type == ANSWER_DELTA:
            if not streaming:
                print()
                streaming = True
            sys.stdout.write(event.data["text"])
            sys.stdout.flush()
        elif event.type == ANSWER_RESET:
            streaming = False
            print()
        elif event.type == ANSWER:
            if not streaming:
                print(f"\n{event.data['text']}")
            streaming = False
            print()
        elif event.type == ERROR:
            print(f"{RED}[错误] {event.data['message']}{RESET}")
        elif event.type == DONE:
            data = event.data
            print(f"{DIM}（{data['llmRounds']} 轮模型调用 / {data['toolCalls']} 次工具调用 / {data['elapsedMs']}ms）{RESET}\n")


async def main() -> int:
    setup_logging(settings.log_level, settings.log_dir)
    if not settings.llm_api_key:
        print("LLM_API_KEY 未配置：复制 .env.example 为 .env 并填入 Key 后重试。")
        return 2

    registry = build_ontology_registry()
    executor = ToolExecutor(
        settings.ontology_base_url,
        timeout=settings.ontology_timeout,
        max_result_chars=settings.max_tool_result_chars,
    )
    llm = build_llm_client(settings)
    runtime = AgentRuntime(
        llm,
        registry,
        executor,
        max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
        max_history_messages=settings.max_history_messages,
        max_context_chars=settings.max_context_chars,
    )
    conversation = ConversationStore().get_or_create(None)

    print(f"6-APA 生产车间智能 Agent（CLI）  模型 {settings.llm_model}  本体 {settings.ontology_base_url}")
    print(f"已加载 {len(registry)} 个工具。输入问题开始，Ctrl-C 退出。\n")

    try:
        if len(sys.argv) > 1:
            await ask(runtime, conversation, " ".join(sys.argv[1:]))
            return 0
        while True:
            try:
                question = input("你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not question:
                continue
            if question in {"exit", "quit", ":q"}:
                return 0
            await ask(runtime, conversation, question)
    finally:
        await llm.aclose()
        await executor.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
