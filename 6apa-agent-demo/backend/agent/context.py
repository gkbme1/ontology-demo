"""会话上下文与多轮对话管理（Phase 2）。

第一版刻意保持简单：最近若干轮对话 + 当前实体上下文 + 当前任务 + Tool 调用历史，
超长时按"整轮"丢弃最早的对话并留一条省略说明。不做向量检索、不做复杂 Memory。

关键约束：OpenAI 协议要求 role=tool 的消息必须紧跟在带 tool_calls 的 assistant 消息之后。
因此裁剪只能以"整轮"为单位，绝不能把一轮对话从中间切开——否则模型直接 400。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class EntityRef:
    """当前上下文实体。用户说"它"时指的就是这里最近的一个。"""

    kind: str
    label: str
    identifier: str
    name: str
    from_tool: str
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "id": self.identifier,
            "name": self.name,
            "fromTool": self.from_tool,
        }

    def describe(self) -> str:
        if self.name and self.identifier and self.name != self.identifier:
            return f"{self.label}：{self.name}（{self.identifier}）"
        return f"{self.label}：{self.name or self.identifier}"


@dataclass
class ToolHistoryItem:
    turn: int
    tool: str
    arguments: dict[str, Any]
    status: str
    summary: str
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "tool": self.tool,
            "arguments": self.arguments,
            "status": self.status,
            "summary": self.summary,
            "durationMs": self.duration_ms,
        }


@dataclass
class Message:
    turn: int
    payload: dict[str, Any]


@dataclass
class Conversation:
    conversation_id: str
    messages: list[Message] = field(default_factory=list)
    current_entities: list[EntityRef] = field(default_factory=list)
    current_process_area: EntityRef | None = None
    current_equipment: EntityRef | None = None
    current_task: str | None = None
    tool_history: list[ToolHistoryItem] = field(default_factory=list)
    turn_index: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    dropped_turns: int = 0
    shrunk_tool_results: int = 0

    # ------------------------------------------------------------- 写入

    def begin_turn(self, user_message: str) -> int:
        self.turn_index += 1
        self.current_task = user_message.strip()
        self.messages.append(Message(self.turn_index, {"role": "user", "content": user_message}))
        self.updated_at = time.time()
        return self.turn_index

    def add_assistant(self, payload: dict[str, Any]) -> None:
        self.messages.append(Message(self.turn_index, payload))
        self.updated_at = time.time()

    def add_tool_result(self, call_id: str, tool_name: str, content: str) -> None:
        self.messages.append(
            Message(
                self.turn_index,
                {"role": "tool", "tool_call_id": call_id, "name": tool_name, "content": content},
            )
        )
        self.updated_at = time.time()

    def record_tool(self, item: ToolHistoryItem) -> None:
        self.tool_history.append(item)
        if len(self.tool_history) > 200:
            del self.tool_history[:-200]

    def remember_entity(self, entity: EntityRef) -> None:
        """记住当前实体。同一实体重复出现时提到最前，不重复堆积。"""
        self.current_entities = [
            existing for existing in self.current_entities if existing.identifier != entity.identifier
        ]
        self.current_entities.insert(0, entity)
        del self.current_entities[6:]
        if entity.kind == "equipment":
            self.current_equipment = entity
        elif entity.kind == "process_area":
            self.current_process_area = entity

    # ------------------------------------------------------------- 读出

    def wire_messages(self) -> list[dict[str, Any]]:
        return [message.payload for message in self.messages]

    def context_block(self) -> str | None:
        """拼出注入给模型的"当前上下文"说明。

        注意这里只陈述事实，不替模型做指代判断——"它"到底指谁由模型自己结合
        对话历史决定，我们只是把候选实体摆出来。
        """
        lines: list[str] = []
        if self.current_equipment:
            lines.append(f"当前设备 → {self.current_equipment.describe()}")
        if self.current_process_area:
            lines.append(f"当前工段 → {self.current_process_area.describe()}")

        others = [
            entity
            for entity in self.current_entities
            if entity is not self.current_equipment and entity is not self.current_process_area
        ]
        if others:
            lines.append("最近涉及的对象 → " + "；".join(entity.describe() for entity in others[:4]))

        if self.tool_history:
            recent = self.tool_history[-5:]
            lines.append(
                "最近的工具调用 → "
                + "；".join(f"{item.tool}({item.status}) {item.summary}" for item in recent)
            )

        if self.dropped_turns:
            lines.append(f"提示 → 更早的 {self.dropped_turns} 轮对话已因长度限制省略。")
        if self.shrunk_tool_results:
            lines.append(
                f"提示 → 本轮有 {self.shrunk_tool_results} 条工具结果因长度被压成摘要；"
                "需要其中的细节请缩小范围后重新查询，不要凭印象作答。"
            )

        if not lines:
            return None
        lines.append(
            "用户说“它”“这个设备”“上游”“这些”等指代时，通常指向上面列出的对象；"
            "若存在歧义，先向用户澄清而不是猜。"
        )
        return "【当前会话上下文】\n" + "\n".join(lines)

    def public_state(self) -> dict[str, Any]:
        return {
            "conversationId": self.conversation_id,
            "turn": self.turn_index,
            "currentTask": self.current_task,
            "currentEquipment": self.current_equipment.to_dict() if self.current_equipment else None,
            "currentProcessArea": self.current_process_area.to_dict() if self.current_process_area else None,
            "currentEntities": [entity.to_dict() for entity in self.current_entities],
            "toolHistory": [item.to_dict() for item in self.tool_history[-20:]],
            "droppedTurns": self.dropped_turns,
            "shrunkToolResults": self.shrunk_tool_results,
        }

    # ------------------------------------------------------------- 裁剪

    def compact(self, *, max_messages: int, max_chars: int) -> None:
        """按整轮裁剪历史，保证 tool 消息永远不与它的 assistant 消息分离。"""
        while self._needs_trim(max_messages, max_chars):
            oldest_turn = self.messages[0].turn
            if oldest_turn >= self.turn_index:
                break  # 当前轮不能丢
            before = len(self.messages)
            self.messages = [message for message in self.messages if message.turn != oldest_turn]
            if len(self.messages) == before:
                break
            self.dropped_turns += 1

        # 丢完历史轮仍然超预算，说明**本轮**的工具结果就撑满了——
        # 这在小上下文模型上很常见（工艺调查要连查七八次）。
        # 此时把本轮最早的几条工具结果压成摘要：消息还在（不破坏 assistant/tool 配对），
        # 但内容换成"查过什么、拿到多少"，腾出空间给后面的调用和最终作答。
        if self._needs_trim(max_messages, max_chars):
            self._shrink_current_turn(max_chars)

    def _shrink_current_turn(self, max_chars: int) -> None:
        for message in self.messages:
            if not self._needs_trim(10**9, max_chars):
                return
            payload = message.payload
            if payload.get("role") != "tool" or message.turn != self.turn_index:
                continue
            content = payload.get("content") or ""
            if len(content) <= _SHRUNK_TOOL_CHARS or content.startswith(_SHRUNK_MARK):
                continue
            payload["content"] = (
                f'{_SHRUNK_MARK}{{"ok": true, "note": "这条工具结果因上下文预算被压缩，'
                f'只保留开头片段。需要完整内容请缩小查询范围后重新调用。", "excerpt": '
                f'{json.dumps(content[:_SHRUNK_TOOL_CHARS], ensure_ascii=False)}}}'
            )
            self.shrunk_tool_results += 1

    def _needs_trim(self, max_messages: int, max_chars: int) -> bool:
        if not self.messages:
            return False
        if len(self.messages) > max_messages:
            return True
        size = sum(len(json.dumps(message.payload, ensure_ascii=False, default=str)) for message in self.messages)
        return size > max_chars


_SHRUNK_TOOL_CHARS = 400
_SHRUNK_MARK = "__shrunk__"


class ConversationStore:
    """进程内会话存储。Demo 规模够用；要持久化换掉这个类即可，Agent 不感知。"""

    def __init__(self, max_conversations: int = 200) -> None:
        self._items: dict[str, Conversation] = {}
        self._max = max_conversations

    def get_or_create(self, conversation_id: str | None) -> Conversation:
        if conversation_id and conversation_id in self._items:
            return self._items[conversation_id]
        new_id = conversation_id or uuid.uuid4().hex[:16]
        conversation = Conversation(conversation_id=new_id)
        self._items[new_id] = conversation
        self._evict()
        return conversation

    def get(self, conversation_id: str) -> Conversation | None:
        return self._items.get(conversation_id)

    def drop(self, conversation_id: str) -> bool:
        return self._items.pop(conversation_id, None) is not None

    def list(self) -> list[dict[str, Any]]:
        items = sorted(self._items.values(), key=lambda item: item.updated_at, reverse=True)
        return [
            {
                "conversationId": item.conversation_id,
                "turn": item.turn_index,
                "currentTask": item.current_task,
                "updatedAt": item.updated_at,
                "currentEquipment": item.current_equipment.to_dict() if item.current_equipment else None,
            }
            for item in items
        ]

    def _evict(self) -> None:
        if len(self._items) <= self._max:
            return
        ordered = sorted(self._items.values(), key=lambda item: item.updated_at)
        for stale in ordered[: len(self._items) - self._max]:
            self._items.pop(stale.conversation_id, None)


def resolve_path(data: Any, dotted: str) -> Any:
    """按点号路径从返回体取值，取不到返回 None。"""
    node = data
    for part in dotted.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.isdigit():
            index = int(part)
            node = node[index] if index < len(node) else None
        else:
            return None
        if node is None:
            return None
    return node


def first_non_empty(values: Iterable[Any]) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None
