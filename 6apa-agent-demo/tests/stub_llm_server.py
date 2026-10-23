"""仅供开发自测：用一个"假 LLM"启动真实的 Agent 服务。

用途：在没有 LLM_API_KEY 的环境里验证 HTTP 层、SSE 事件流与前端渲染。
它替换的只是 LLM 客户端，Agent Runtime / Tool Registry / Tool Executor /
本体 API 调用全部是真实的。

    ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.stub_llm_server

⚠️ 这是测试替身，不参与生产路径。生产走 backend/llm/openai_compatible.py。
   它里面的关键词分支是"假装成模型"的权宜之计，正式 Agent 里没有、也不允许有这种分支。
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from backend.llm.base import LLMResponse, ToolCall


class StubLLM:
    model = "stub-llm(dev-only)"

    def __init__(self) -> None:
        self._counter = 0

    async def chat(self, messages: Sequence[dict[str, Any]], tools=None, *, on_text_delta=None, stream=None):
        self._counter += 1
        question = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                question = message.get("content") or ""
                break

        tool_messages = [m for m in messages if m.get("role") == "tool"]
        if tools is None:
            return await self._answer("（工具预算用尽，这里是收口回答。）", on_text_delta)

        # 第一步：还没查过任何东西 → 挑一个工具去查
        if not tool_messages:
            name, args = self._pick_first_tool(question)
            return self._call(name, args)

        # 第二步：如果拿到了设备列表，就再查一次详情，演示多步链路
        last = tool_messages[-1]
        if last.get("name") == "query_equipment_list":
            try:
                data = json.loads(last.get("content") or "{}").get("data") or {}
                items = data.get("items") or []
                if items and isinstance(items[0], dict) and items[0].get("id"):
                    return self._call("query_object_relations", {"object_id": items[0]["id"]})
            except ValueError:
                pass

        summary = "、".join(m.get("name") or "?" for m in tool_messages)
        return await self._answer(
            f"（测试替身回答）本轮共调用了 {len(tool_messages)} 个工具：{summary}。\n\n"
            f"原始问题：{question}\n\n"
            "真实回答由配置的 DeepSeek 模型生成，此处仅用于验证前端与 SSE 链路。",
            on_text_delta,
        )

    @staticmethod
    def _pick_first_tool(question: str) -> tuple[str, dict[str, Any]]:
        if any(word in question for word in ("工段", "车间由", "有哪些工段")):
            return "query_process_areas", {}
        if any(word in question for word in ("关系图", "结构图", "画图", "拓扑")):
            return "query_ontology_graph", {"depth": 1}
        if any(word in question for word in ("关系", "上游", "下游", "关联")):
            return "query_relations", {"limit": 5}
        if any(word in question for word in ("知识", "分类", "覆盖")):
            return "query_ontology_categories", {}
        for token in ("泵", "釜", "离心机", "换热器", "塔", "罐"):
            if token in question:
                return "query_equipment_list", {"keyword": token, "limit": 5}
        return "query_ontology_overview", {}

    @staticmethod
    def _call(name: str, args: dict[str, Any]) -> LLMResponse:
        return LLMResponse(
            content="",
            tool_calls=[ToolCall(id=f"stub_{name}", name=name, arguments=json.dumps(args, ensure_ascii=False))],
            finish_reason="tool_calls",
        )

    @staticmethod
    async def _answer(text: str, on_text_delta) -> LLMResponse:
        if on_text_delta:
            for index in range(0, len(text), 6):
                await on_text_delta(text[index : index + 6])
        return LLMResponse(content=text, finish_reason="stop")

    async def aclose(self) -> None:
        return None


def build_app():
    import os

    os.environ.setdefault("LLM_API_KEY", "stub-key-for-dev")
    from backend import main as backend_main

    backend_main.runtime.llm = StubLLM()
    backend_main.settings.llm_api_key = "stub-key-for-dev"
    return backend_main.app


app = build_app()


if __name__ == "__main__":
    import uvicorn

    from backend.config import settings

    print("⚠️  假 LLM 模式，仅用于自测前端与 SSE。")
    uvicorn.run(app, host="127.0.0.1", port=settings.agent_port)
