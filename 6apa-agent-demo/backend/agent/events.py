"""Agent 执行过程事件。

前端只消费这些事件来渲染"执行过程"面板。
这里只暴露可观察的外部动作（调了哪个工具、参数是什么、返回了多少条），
绝不承载模型的隐藏思维过程——那是产品硬要求。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# 事件类型
TURN_START = "turn_start"
STATUS = "status"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
GRAPH = "graph"
ANSWER_DELTA = "answer_delta"
# 本轮流式文本最终被判定为"执行说明"而非最终回答时发出，
# 前端据此清空正在流式显示的回答缓冲区
ANSWER_RESET = "answer_reset"
ANSWER = "answer"
CONTEXT = "context"
ERROR = "error"
DONE = "done"


@dataclass
class AgentEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        body = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"event: {self.type}\ndata: {body}\n\n"


def status(text: str, phase: str = "running", done: bool = False) -> AgentEvent:
    """一条人类可读的执行状态，例如"正在查询设备关系"。"""
    return AgentEvent(STATUS, {"text": text, "phase": phase, "done": done})


def error(message: str, kind: str = "agent") -> AgentEvent:
    return AgentEvent(ERROR, {"message": message, "kind": kind})
