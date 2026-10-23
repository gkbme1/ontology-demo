"""LLM 抽象层。

Agent Runtime 只依赖本文件中的协议与数据结构，不依赖任何具体厂商。
更换模型 = 换一个实现了 LLMClient 的类，Agent 代码一行不改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, Sequence

# 文本增量回调：用于把最终回答逐字推给前端
TextDeltaHandler = Callable[[str], Awaitable[None]]


@dataclass
class ToolCall:
    """模型请求的一次工具调用。arguments 保持原始 JSON 字符串，由上层解析与校验。"""

    id: str
    name: str
    arguments: str


@dataclass
class LLMResponse:
    """一次 LLM 调用的结果。

    注意：实现类必须丢弃模型的隐藏推理内容（如 DeepSeek 的 reasoning_content），
    本结构体不提供承载思维链的字段——这是产品硬性要求，不是可选项。
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)

    def to_assistant_message(self) -> dict[str, Any]:
        """转换成可以追加回 messages 的 assistant 消息（OpenAI 线格式）。"""
        message: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        return message


class LLMError(RuntimeError):
    """LLM 调用失败。携带可读原因，供上层决定重试或向用户报错。"""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class LLMClient(Protocol):
    """Agent 依赖的唯一 LLM 接口。"""

    model: str

    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        on_text_delta: TextDeltaHandler | None = None,
        stream: bool | None = None,
    ) -> LLMResponse:
        ...

    async def aclose(self) -> None:
        ...
