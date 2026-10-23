"""Agent 服务入口。

优先使用 FastAPI；若运行环境中 FastAPI 不可用，自动回退到 Starlette 装配同一份
路由表与同一批 handler，保证 API 契约完全一致（FastAPI 本身就是构建在 Starlette 之上）。

启动：
    uvicorn backend.main:app --reload --port 8800
    python3 -m backend.main          # 等价，端口取自 AGENT_PORT
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from .agent.context import ConversationStore
from .agent.events import AgentEvent, DONE, ERROR
from .agent.examples import load_examples, reload_examples
from .agent.prompt import load_system_prompt, reload_system_prompt
from .agent.runtime import AgentRuntime
from .config import settings
from .llm.openai_compatible import build_llm_client
from .logging_setup import log_turn, setup_logging
from .tools.executor import ToolExecutor
from .tools.ontology_tools import build_ontology_registry

setup_logging(settings.log_level, settings.log_dir)
logger = logging.getLogger("agent.api")

# ------------------------------------------------------------------ 组件装配

registry = build_ontology_registry(compact_relations=settings.compact_relations)
store = ConversationStore()
_llm = build_llm_client(settings)
_executor = ToolExecutor(
    settings.ontology_base_url,
    timeout=settings.ontology_timeout,
    max_result_chars=settings.max_tool_result_chars,
    registry=registry,
)
# 渐进解锁模式下，一开始只下发 core 组（含工具发现），其余由模型按需取用
_initial_tools = (
    [spec.name for spec in registry if spec.group == "core"]
    if settings.progressive_tools
    else None
)

runtime = AgentRuntime(
    _llm,
    registry,
    _executor,
    max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
    max_history_messages=settings.max_history_messages,
    max_context_chars=settings.max_context_chars,
    initial_tools=_initial_tools,
)


# ------------------------------------------------------------------- handlers


async def handle_health(request: Request) -> JSONResponse:
    ontology_ok, ontology_detail = await _probe_ontology()
    return JSONResponse(
        {
            "service": "6-APA 生产车间智能 Agent",
            "status": "ok",
            "framework": FRAMEWORK,
            "toolCount": len(registry),
            "initialToolCount": len(_initial_tools) if _initial_tools else len(registry),
            "config": settings.describe(),
            "ontology": {"reachable": ontology_ok, "detail": ontology_detail},
            "systemPromptChars": len(load_system_prompt()),
            "exampleCount": load_examples()["total"],
        }
    )


async def handle_tools(request: Request) -> JSONResponse:
    return JSONResponse({"items": registry.catalog(), "total": len(registry)})


async def handle_list_conversations(request: Request) -> JSONResponse:
    return JSONResponse({"items": store.list()})


async def handle_get_conversation(request: Request) -> JSONResponse:
    conversation_id = request.path_params["conversation_id"]
    conversation = store.get(conversation_id)
    if conversation is None:
        return JSONResponse({"detail": "会话不存在"}, status_code=404)
    return JSONResponse(
        {
            **conversation.public_state(),
            "messages": [
                message.payload
                for message in conversation.messages
                if message.payload.get("role") in ("user", "assistant")
                and message.payload.get("content")
            ],
        }
    )


async def handle_delete_conversation(request: Request) -> JSONResponse:
    conversation_id = request.path_params["conversation_id"]
    return JSONResponse({"deleted": store.drop(conversation_id)})


async def handle_reload_prompt(request: Request) -> JSONResponse:
    return JSONResponse({"chars": len(reload_system_prompt())})


async def handle_examples(request: Request) -> JSONResponse:
    """示例问题清单。纯数据，点击后只是把问题文本填进输入框，不绑定任何工具或流程。"""
    return JSONResponse(load_examples())


async def handle_reload_examples(request: Request) -> JSONResponse:
    data = reload_examples()
    return JSONResponse({"total": data["total"], "groups": len(data["groups"])})


async def handle_chat(request: Request) -> StreamingResponse:
    """核心接口：一轮对话，以 SSE 把 Agent 执行过程与最终回答实时推给前端。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    message = (body.get("message") or "").strip()
    conversation_id = body.get("conversationId") or None

    if not message:
        return StreamingResponse(
            _single_event(AgentEvent(ERROR, {"message": "message 不能为空", "kind": "request"})),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )
    if not settings.llm_api_key:
        return StreamingResponse(
            _single_event(
                AgentEvent(
                    ERROR,
                    {
                        "message": "LLM_API_KEY 未配置。请复制 .env.example 为 .env 并填入 DeepSeek Key 后重启服务。",
                        "kind": "config",
                    },
                )
            ),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    conversation = store.get_or_create(conversation_id)
    return StreamingResponse(
        _chat_stream(conversation, message),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 防止 nginx 缓冲把流式憋死
}


async def _single_event(event: AgentEvent) -> AsyncIterator[bytes]:
    yield event.to_sse().encode("utf-8")
    yield AgentEvent(DONE, {"ok": False}).to_sse().encode("utf-8")


async def _chat_stream(conversation, message: str) -> AsyncIterator[bytes]:
    trace: dict[str, Any] = {
        "conversation_id": conversation.conversation_id,
        "user_message": message,
        "tools": [],
        "error": None,
        "final_answer": None,
    }
    try:
        async for event in runtime.run_turn(conversation, message):
            if event.type == "tool_result":
                trace["tools"].append(
                    {
                        "tool_name": event.data.get("tool"),
                        "tool_arguments": event.data.get("arguments"),
                        "tool_result_summary": event.data.get("resultSummary"),
                        "execution_time_ms": event.data.get("durationMs"),
                        "status": event.data.get("status"),
                        "error": event.data.get("error"),
                    }
                )
            elif event.type == "answer":
                trace["final_answer"] = event.data.get("text")
            elif event.type == ERROR:
                trace["error"] = event.data.get("message")
            elif event.type == DONE:
                trace["elapsed_ms"] = event.data.get("elapsedMs")
                trace["tool_calls"] = event.data.get("toolCalls")
            yield event.to_sse().encode("utf-8")
    except asyncio.CancelledError:  # 前端断开
        trace["error"] = "client_disconnected"
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("chat 流异常")
        trace["error"] = str(exc)
        yield AgentEvent(ERROR, {"message": f"服务内部错误：{exc}", "kind": "server"}).to_sse().encode("utf-8")
        yield AgentEvent(DONE, {"ok": False}).to_sse().encode("utf-8")
    finally:
        log_turn(trace)


async def _probe_ontology() -> tuple[bool, str]:
    import httpx

    url = f"{settings.ontology_base_url}/api/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
        if response.status_code < 400:
            data = response.json()
            return True, f"{data.get('service', '本体服务')} @ {settings.ontology_base_url}"
        return False, f"{url} 返回 HTTP {response.status_code}"
    except Exception as exc:
        return False, f"无法连接 {url}：{exc}"


# ------------------------------------------------------------------ 路由表

ROUTES: list[dict[str, Any]] = [
    {"path": "/api/health", "methods": ["GET"], "handler": handle_health, "name": "健康检查"},
    {"path": "/api/tools", "methods": ["GET"], "handler": handle_tools, "name": "工具清单"},
    {"path": "/api/chat", "methods": ["POST"], "handler": handle_chat, "name": "对话(SSE)"},
    {"path": "/api/conversations", "methods": ["GET"], "handler": handle_list_conversations, "name": "会话列表"},
    {
        "path": "/api/conversations/{conversation_id}",
        "methods": ["GET"],
        "handler": handle_get_conversation,
        "name": "会话详情",
    },
    {
        "path": "/api/conversations/{conversation_id}",
        "methods": ["DELETE"],
        "handler": handle_delete_conversation,
        "name": "删除会话",
    },
    {"path": "/api/prompt/reload", "methods": ["POST"], "handler": handle_reload_prompt, "name": "重载Prompt"},
    {"path": "/api/examples", "methods": ["GET"], "handler": handle_examples, "name": "示例问题"},
    {"path": "/api/examples/reload", "methods": ["POST"], "handler": handle_reload_examples, "name": "重载示例问题"},
]


# --------------------------------------------------------------- 应用装配


def _build_fastapi():
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="6-APA 生产车间智能 Agent", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    for route in ROUTES:
        app.add_api_route(
            route["path"],
            route["handler"],
            methods=route["methods"],
            name=route["name"],
            summary=route["name"],
        )

    @app.on_event("shutdown")
    async def _shutdown() -> None:  # pragma: no cover
        await _llm.aclose()
        await _executor.aclose()

    return app


def _build_starlette():
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.routing import Route

    routes = [
        Route(route["path"], route["handler"], methods=route["methods"], name=f"{route['name']}-{index}")
        for index, route in enumerate(ROUTES)
    ]

    import contextlib

    @contextlib.asynccontextmanager
    async def lifespan(_app):  # pragma: no cover
        yield
        await _llm.aclose()
        await _executor.aclose()

    return Starlette(
        routes=routes,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=settings.cors_origin_list,
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=["*"],
            )
        ],
        lifespan=lifespan,
    )


try:  # pragma: no cover
    app = _build_fastapi()
    FRAMEWORK = "fastapi"
except ImportError:  # pragma: no cover
    app = _build_starlette()
    FRAMEWORK = "starlette"

logger.info(
    "Agent 服务已装配：framework=%s tools=%d ontology=%s model=%s",
    FRAMEWORK,
    len(registry),
    settings.ontology_base_url,
    settings.llm_model,
)


def main() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host=settings.agent_host, port=settings.agent_port)


if __name__ == "__main__":  # pragma: no cover
    main()
