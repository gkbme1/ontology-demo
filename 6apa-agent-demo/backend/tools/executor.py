"""Tool Executor —— 把一次 Tool Call 真正打到本体 REST API 上。

职责：
1. 解析 + 校验模型给的参数（失败不崩溃，转成结构化错误回灌 LLM）
2. 发 HTTP 请求，区分 400 / 404 / 5xx / 超时 / 网络错误 / 非 JSON / 空结果
3. 压缩超大返回体，保证不把 30 万字符塞进模型上下文，同时如实告知模型"被截断了"
4. 产出统一的 ToolExecution 记录，供 Agent 回灌、前端展示、日志落库

这里没有任何针对具体问题的业务分支——所有接口走同一条执行路径。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .registry import ToolSpec, ToolValidationError

logger = logging.getLogger("agent.tools")

# 逐级收紧列表长度，直到序列化结果落进预算
_LIST_CAP_LADDER = (80, 60, 45, 35, 25, 20, 15, 12, 10, 8, 6, 5, 4, 3, 2, 1)
# 每轮只收紧一个数组，够大的返回体需要多轮；给个上限防止极端结构下空转
_MAX_COMPACT_ROUNDS = 400


@dataclass
class ToolExecution:
    """一次工具调用的完整记录。前端执行过程面板与日志都读它。"""

    tool_name: str
    call_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | empty | error
    http_status: int | None = None
    url: str = ""
    duration_ms: int = 0
    result: Any = None
    error: str | None = None
    error_kind: str | None = None
    raw_bytes: int = 0
    truncated: bool = False
    truncation_note: str = ""
    graph: dict[str, Any] | None = None
    # 本地工具可以要求把某些工具下发给模型（渐进解锁）。
    # Executor 只是把它原样带出来，不判断里面是什么。
    unlocked: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ 对 LLM 的视图

    def to_llm_content(self) -> str:
        """回灌给 LLM 的 tool 消息内容。失败也要说人话，让模型能自己换路。"""
        if self.status == "error":
            payload: dict[str, Any] = {
                "ok": False,
                "error": self.error,
                "errorKind": self.error_kind,
                "httpStatus": self.http_status,
                "hint": _ERROR_HINTS.get(self.error_kind or "", "可以尝试更换工具或调整参数后重试。"),
            }
        else:
            payload = {"ok": True, "data": self.result}
            if self.status == "empty":
                payload["note"] = (
                    "查询成功但结果为空。请确认过滤条件的取值与本体中的真实取值一致"
                    "（可先不带过滤条件调用一次本工具，观察实际可用取值），或改用其他工具。"
                )
            if self.truncated:
                payload["truncationNote"] = self.truncation_note
        return json.dumps(payload, ensure_ascii=False, default=str)

    # ------------------------------------------------------------ 对前端的视图

    def to_public_dict(self) -> dict[str, Any]:
        summary = _summarize(self.result) if self.status != "error" else (self.error or "")
        return {
            "callId": self.call_id,
            "tool": self.tool_name,
            "arguments": self.arguments,
            "status": self.status,
            "httpStatus": self.http_status,
            "url": self.url,
            "durationMs": self.duration_ms,
            "rawBytes": self.raw_bytes,
            "truncated": self.truncated,
            "truncationNote": self.truncation_note,
            "unlocked": self.unlocked,
            "resultSummary": summary,
            "resultPreview": _preview(self.result) if self.status != "error" else None,
            "error": self.error,
            "hasGraph": self.graph is not None,
        }


_ERROR_HINTS = {
    "validation": "参数不合法。请按工具 schema 修正参数后重试。",
    "not_found": "对象不存在。多半是把名称当成了 ID：先用列表类工具（如 query_equipment_list 的 keyword）检索到正确 ID 再查详情。",
    "bad_request": "本体服务认为请求参数有问题，请检查取值后重试。",
    "server_error": "本体服务内部错误，本次查询不可用。可改用其他工具，或如实告知用户该项数据暂不可得。",
    "timeout": "本体服务响应超时。可缩小查询范围（加 limit / 过滤条件）后重试一次。",
    "network": "无法连接本体服务。请如实告知用户本体服务当前不可达，不要凭空作答。",
    "invalid_json": "本体服务返回的不是合法 JSON，本次结果不可用。",
    "unknown_tool": "该工具不存在。请只使用工具列表里给出的工具名。",
}


class ToolExecutor:
    """所有工具共用的执行器。"""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 20.0,
        max_result_chars: int = 8000,
        client: httpx.AsyncClient | None = None,
        registry: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_result_chars = max_result_chars
        # 本地工具的 handler 需要拿到 Registry（例如列出还有哪些工具）
        self.registry = registry
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------ execute

    async def execute(self, spec: ToolSpec, call_id: str, raw_arguments: str) -> ToolExecution:
        started = time.perf_counter()
        execution = ToolExecution(tool_name=spec.name, call_id=call_id)

        # 1) 解析模型给的 JSON 参数
        try:
            parsed = json.loads(raw_arguments) if raw_arguments.strip() else {}
        except ValueError:
            execution.status = "error"
            execution.error_kind = "validation"
            execution.error = f"工具参数不是合法 JSON：{raw_arguments[:200]}"
            execution.duration_ms = _elapsed(started)
            return execution

        # 2) 校验 + 补默认值
        try:
            arguments = spec.validate_arguments(parsed if isinstance(parsed, dict) else {})
            arguments = spec.apply_defaults(arguments)
            path_args, query_args = spec.split_arguments(arguments)
            path = spec.render_path(path_args)
        except ToolValidationError as exc:
            execution.status = "error"
            execution.error_kind = "validation"
            execution.error = str(exc)
            execution.duration_ms = _elapsed(started)
            return execution

        execution.arguments = arguments

        # 2.5) 本地执行的工具（如工具发现）：不打 HTTP，直接调 spec 自带的 handler。
        # Executor 不认识任何具体工具名，只看 handler 字段是否为空。
        if spec.handler is not None:
            try:
                result = spec.handler(self.registry, arguments)
            except Exception as exc:  # pragma: no cover - handler 自身出错不应打断整轮
                execution.status = "error"
                execution.error_kind = "server_error"
                execution.error = f"本地工具执行失败：{exc}"
                execution.duration_ms = _elapsed(started)
                return execution
            execution.url = f"local://{spec.name}"
            execution.unlocked = list(result.pop("_unlock", []) or [])
            execution.result = result
            execution.raw_bytes = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            execution.status = "empty" if _is_empty(result) else "ok"
            execution.duration_ms = _elapsed(started)
            return execution

        url = f"{self.base_url}{path}"
        execution.url = url

        # 3) 发请求
        try:
            response = await self._client.request(spec.method, url, params=query_args or None)
        except httpx.TimeoutException as exc:
            return _fail(execution, started, "timeout", f"请求本体服务超时：{exc}")
        except httpx.HTTPError as exc:
            return _fail(execution, started, "network", f"请求本体服务失败：{exc}")

        execution.http_status = response.status_code
        execution.raw_bytes = len(response.content or b"")

        if response.status_code == 404:
            return _fail(execution, started, "not_found", f"本体服务返回 404：{_body_snippet(response)}")
        if 400 <= response.status_code < 500:
            return _fail(
                execution, started, "bad_request", f"本体服务返回 {response.status_code}：{_body_snippet(response)}"
            )
        if response.status_code >= 500:
            return _fail(
                execution, started, "server_error", f"本体服务返回 {response.status_code}：{_body_snippet(response)}"
            )

        # 4) 解析返回体
        try:
            data = response.json()
        except ValueError:
            return _fail(execution, started, "invalid_json", "本体服务返回内容不是合法 JSON")

        if data is None:
            return _fail(execution, started, "not_found", "本体服务返回空对象（对象不存在）")

        # 5) 关系图数据单独留一份完整的给前端（不进 LLM 上下文）
        if spec.graph_keys and isinstance(data, dict) and all(key in data for key in spec.graph_keys):
            execution.graph = {key: data.get(key) for key in ("nodes", "edges", "rootId", "depth", "truncated")}

        # 6) 压缩超大返回体
        budget = self.max_result_chars if not spec.heavy else self.max_result_chars
        compacted, truncated, note = compact_json(data, budget)
        execution.result = compacted
        execution.truncated = truncated
        execution.truncation_note = note
        execution.status = "empty" if _is_empty(data) else "ok"
        execution.duration_ms = _elapsed(started)

        logger.info(
            "tool=%s status=%s http=%s bytes=%s truncated=%s %dms",
            spec.name,
            execution.status,
            execution.http_status,
            execution.raw_bytes,
            execution.truncated,
            execution.duration_ms,
        )
        return execution


# --------------------------------------------------------------------- helpers


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _fail(execution: ToolExecution, started: float, kind: str, message: str) -> ToolExecution:
    execution.status = "error"
    execution.error_kind = kind
    execution.error = message
    execution.duration_ms = _elapsed(started)
    logger.warning("tool=%s failed kind=%s msg=%s", execution.tool_name, kind, message[:300])
    return execution


def _body_snippet(response: httpx.Response, limit: int = 300) -> str:
    try:
        return (response.text or "").strip()[:limit]
    except Exception:  # pragma: no cover - 极端情况下的编码问题
        return "<无法读取响应体>"


def _is_empty(data: Any) -> bool:
    if isinstance(data, dict):
        if "total" in data and isinstance(data["total"], int):
            return data["total"] == 0
        if "items" in data and isinstance(data["items"], list):
            return len(data["items"]) == 0
        return not data
    if isinstance(data, list):
        return len(data) == 0
    return data in (None, "")


def compact_json(data: Any, budget: int) -> tuple[Any, bool, str]:
    """把返回体压进字符预算。

    策略是通用的、与业务无关的：**按体积裁大数组，而不是一刀切**。
    每一轮找出当前占字节数最多的那个数组，把它的保留条数收紧一档，再看总长度；
    这样一个返回体里同时有「11 条重的」和「7 条轻的」数组时，
    不会为了压缩前者而把后者一起砍掉——而一刀切会。

    被裁掉的数组会留下 _omitted 标记，让模型清楚地知道自己只看到了一部分。
    """
    serialized = json.dumps(data, ensure_ascii=False, default=str)
    if len(serialized) <= budget:
        return data, False, ""

    caps: dict[str, int] = {}
    for _ in range(_MAX_COMPACT_ROUNDS):
        weights = _list_weights(data, caps)
        if not weights:
            break
        # 挑当前最占体积的数组，收紧一档；同样体积时优先裁条数多的
        path = max(weights, key=lambda key: (weights[key][1], weights[key][0]))
        count, _bytes = weights[path]
        current = caps.get(path, count)
        nxt = next((cap for cap in _LIST_CAP_LADDER if cap < current), None)
        if nxt is None:
            caps[path] = 1
            weights.pop(path, None)
            continue
        caps[path] = nxt

        omitted_fields: dict[str, int] = {}
        reduced = _cap_lists_by_path(data, caps, omitted_fields)
        serialized = json.dumps(reduced, ensure_ascii=False, default=str)
        if len(serialized) <= budget:
            return reduced, True, _build_note(caps, omitted_fields)

    # 仍然超预算：最后兜底，直接截断字符串（极少发生）
    truncated_text = serialized[:budget]
    note = (
        "返回体过大，已强制截断为文本片段。请加上更严格的过滤条件或 limit 后重新查询，"
        "不要基于这段不完整内容下结论。"
    )
    return {"_truncatedText": truncated_text}, True, note


def _list_weights(node: Any, caps: dict[str, int], path: str = "") -> dict[str, tuple[int, int]]:
    """收集每个数组路径当前保留的条数与序列化字节数，用于决定先裁谁。

    同一路径下的同名数组（例如 items[].targets）合并统计，裁剪时也一起收紧，
    这样规则始终是"按字段裁"，与具体业务字段无关。
    """
    weights: dict[str, tuple[int, int]] = {}

    def walk(current: Any, current_path: str) -> None:
        if isinstance(current, dict):
            for key, value in current.items():
                walk(value, f"{current_path}.{key}" if current_path else key)
        elif isinstance(current, list):
            name = current_path or "(root)"
            kept = current[: caps.get(name, len(current))]
            size = len(json.dumps(kept, ensure_ascii=False, default=str))
            prev = weights.get(name, (0, 0))
            weights[name] = (prev[0] + len(kept), prev[1] + size)
            for item in kept:
                walk(item, current_path)

    walk(node, path)
    # 只剩一条的数组没有继续裁的余地
    return {key: value for key, value in weights.items() if value[0] > 1}


def _cap_lists_by_path(node: Any, caps: dict[str, int], omitted: dict[str, int], path: str = "") -> Any:
    """按字段路径分别收紧数组；没被点名的数组原样保留。"""
    if isinstance(node, dict):
        return {
            key: _cap_lists_by_path(value, caps, omitted, f"{path}.{key}" if path else key)
            for key, value in node.items()
        }
    if isinstance(node, list):
        name = path or "(root)"
        cap = caps.get(name)
        if cap is not None and len(node) > cap:
            omitted[name] = omitted.get(name, 0) + (len(node) - cap)
            kept = [_cap_lists_by_path(item, caps, omitted, path) for item in node[:cap]]
            kept.append({"_omitted": len(node) - cap, "_totalInThisList": len(node)})
            return kept
        return [_cap_lists_by_path(item, caps, omitted, path) for item in node]
    return node


def _build_note(caps: dict[str, int], omitted: dict[str, int]) -> str:
    fields = "、".join(
        f"{name} 只保留 {caps.get(name, 0)} 条(省略 {count} 条)" for name, count in sorted(omitted.items())[:6]
    )
    return (
        f"返回体过大，已裁剪其中体积最大的数组：{fields}。"
        "其余字段完整。返回体中的 total 字段仍是真实总数。"
        "若需要看完整内容，请用 limit/offset 分页，或加上更精确的过滤条件重新查询；"
        "回答用户时不要把被裁剪的样本当成全部。"
    )


def _summarize(result: Any) -> str:
    """给前端执行过程面板用的一句话摘要。"""
    if isinstance(result, dict):
        if isinstance(result.get("total"), int):
            shown = len(result.get("items") or []) if isinstance(result.get("items"), list) else None
            if shown is not None:
                return f"命中 {result['total']} 条，本次返回 {shown} 条"
            return f"命中 {result['total']} 条"
        if "nodeCount" in result and "edgeCount" in result:
            return f"{result.get('nodeCount')} 个节点 / {result.get('edgeCount')} 条边"
        if "name" in result:
            return f"对象：{result['name']}"
        if "objectName" in result:
            return f"对象：{result['objectName']}"
        return f"{len(result)} 个字段"
    if isinstance(result, list):
        return f"{len(result)} 条记录"
    return "已返回"


def _preview(result: Any, limit: int = 1200) -> str:
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + "\n…（已截断，完整内容见本体 API）"
