"""OpenAI-compatible LLM 客户端（DeepSeek / Qwen / Moonshot / vLLM / Ollama 等通用）。

只依赖 httpx，不依赖任何厂商 SDK。通过 LLM_BASE_URL / LLM_MODEL 切换模型。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Sequence

import httpx

from .base import LLMClient, LLMError, LLMResponse, TextDeltaHandler, ToolCall

logger = logging.getLogger("agent.llm")

# 这些字段一旦出现在响应里，必须直接丢弃：属于模型隐藏思维过程，禁止外泄到前端
_HIDDEN_THOUGHT_FIELDS = ("reasoning_content", "reasoning", "thinking")

# 有些模型（如开了 thinking 模式的千问 3）不走 reasoning_content 字段，
# 而是把思维链**内联在 content 里**用标签裹起来。需求文档明令禁止展示思维链，
# 所以这里连标签内容一起剥掉。流式场景下标签可能跨 chunk 到达，
# 因此还要单独维护一个"是否正处在思维链里"的状态。
_THINK_TAGS = ("think", "thinking", "reasoning", "thought")
_THINK_OPEN = re.compile(r"<(%s)\b[^>]*>" % "|".join(_THINK_TAGS), re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</(%s)\s*>" % "|".join(_THINK_TAGS), re.IGNORECASE)
_THINK_BLOCK = re.compile(
    r"<(%s)\b[^>]*>.*?</\1\s*>" % "|".join(_THINK_TAGS), re.IGNORECASE | re.DOTALL
)


def strip_think_blocks(text: str) -> str:
    """去掉完整的 <think>…</think> 段落；未闭合的开标签之后一律丢弃。"""
    if not text or "<" not in text:
        return text
    cleaned = _THINK_BLOCK.sub("", text)
    open_match = _THINK_OPEN.search(cleaned)
    if open_match:
        cleaned = cleaned[: open_match.start()]
    return cleaned


class _ThinkFilter:
    """流式文本的思维链过滤器：按 chunk 进来，吐出可以安全显示的部分。

    标签可能被切在两个 chunk 之间（"<thi" + "nk>"），所以尾部疑似标签开头的
    残片要留到下一次再判断，不能直接放行。
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        out: list[str] = []
        while self._buffer:
            if self._inside:
                close = _THINK_CLOSE.search(self._buffer)
                if not close:
                    self._buffer = self._buffer[-16:]  # 只留可能含闭标签的尾巴
                    break
                self._buffer = self._buffer[close.end():]
                self._inside = False
                continue
            open_match = _THINK_OPEN.search(self._buffer)
            if not open_match:
                # 尾部可能是半个标签，留着等下一段
                keep = 0
                tail = self._buffer[-16:]
                idx = tail.rfind("<")
                if idx >= 0 and ">" not in tail[idx:]:
                    keep = len(tail) - idx
                if keep:
                    out.append(self._buffer[:-keep])
                    self._buffer = self._buffer[-keep:]
                else:
                    out.append(self._buffer)
                    self._buffer = ""
                break
            out.append(self._buffer[: open_match.start()])
            self._buffer = self._buffer[open_match.end():]
            self._inside = True
        return "".join(out)

    def flush(self) -> str:
        if self._inside:
            self._buffer = ""
            self._inside = False
            return ""
        rest, self._buffer = self._buffer, ""
        return rest

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class OpenAICompatibleClient(LLMClient):
    """最小可用的 Chat Completions 客户端，支持流式与 function calling。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 120.0,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        stream: bool = True,
        max_retries: int = 2,
    ) -> None:
        if not base_url:
            raise ValueError("LLM_BASE_URL 未配置")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.default_stream = stream
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(15.0, timeout)),
            headers={"Content-Type": "application/json"},
        )

    # ------------------------------------------------------------------ public

    async def chat(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        on_text_delta: TextDeltaHandler | None = None,
        stream: bool | None = None,
    ) -> LLMResponse:
        use_stream = self.default_stream if stream is None else stream
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": use_stream,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"

        last_error: LLMError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if use_stream:
                    return await self._chat_stream(payload, on_text_delta)
                return await self._chat_once(payload)
            except LLMError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.max_retries:
                    raise
                backoff = 1.5 * (2**attempt)
                logger.warning("LLM 调用失败(%s)，%.1fs 后重试 %d/%d", exc, backoff, attempt + 1, self.max_retries)
                await asyncio.sleep(backoff)
        raise last_error or LLMError("LLM 调用失败")

    async def aclose(self) -> None:
        await self._client.aclose()

    # ----------------------------------------------------------------- private

    @property
    def _headers(self) -> dict[str, str]:
        # API Key 只在这里出现，绝不写入日志
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _url(self) -> str:
        # 兼容 base_url 带或不带 /v1 的两种写法
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    async def _chat_once(self, payload: dict[str, Any]) -> LLMResponse:
        try:
            response = await self._client.post(self._url(), json=payload, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise LLMError(f"LLM 请求超时: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 网络错误: {exc}", retryable=True) from exc

        self._raise_for_status(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("LLM 返回内容不是合法 JSON") from exc

        choices = data.get("choices") or []
        if not choices:
            raise LLMError("LLM 返回体缺少 choices")
        message = choices[0].get("message") or {}
        self._strip_hidden_thoughts(message)

        tool_calls = [
            ToolCall(
                id=item.get("id") or f"call_{index}",
                name=((item.get("function") or {}).get("name") or ""),
                arguments=((item.get("function") or {}).get("arguments") or "{}"),
            )
            for index, item in enumerate(message.get("tool_calls") or [])
        ]
        return LLMResponse(
            content=strip_think_blocks(message.get("content") or ""),
            tool_calls=[call for call in tool_calls if call.name],
            finish_reason=choices[0].get("finish_reason") or "",
            usage=data.get("usage") or {},
            model=data.get("model") or self.model,
        )

    async def _chat_stream(
        self,
        payload: dict[str, Any],
        on_text_delta: TextDeltaHandler | None,
    ) -> LLMResponse:
        content_parts: list[str] = []
        # 思维链可能内联在 content 里且跨分片到达，逐片过滤
        think_filter = _ThinkFilter()
        # tool_calls 按 index 累积：id / name 只在首个分片出现，arguments 分多片拼接
        pending: dict[int, dict[str, str]] = {}
        finish_reason = ""
        usage: dict[str, Any] = {}
        model = self.model

        try:
            async with self._client.stream(
                "POST", self._url(), json=payload, headers=self._headers
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")
                    self._raise_for_status(response, body)

                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except ValueError:
                        logger.debug("忽略无法解析的流式分片")
                        continue

                    model = chunk.get("model") or model
                    if chunk.get("usage"):
                        usage = chunk["usage"]

                    for choice in chunk.get("choices") or []:
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                        delta = choice.get("delta") or {}
                        self._strip_hidden_thoughts(delta)

                        text = delta.get("content")
                        if text:
                            visible = think_filter.feed(text)
                            if visible:
                                content_parts.append(visible)
                                if on_text_delta is not None:
                                    await on_text_delta(visible)

                        for item in delta.get("tool_calls") or []:
                            index = int(item.get("index", 0))
                            slot = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
                            if item.get("id"):
                                slot["id"] = item["id"]
                            function = item.get("function") or {}
                            if function.get("name"):
                                slot["name"] += function["name"]
                            if function.get("arguments"):
                                slot["arguments"] += function["arguments"]
        except httpx.TimeoutException as exc:
            raise LLMError(f"LLM 流式请求超时: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 流式网络错误: {exc}", retryable=True) from exc

        tail = think_filter.flush()
        if tail:
            content_parts.append(tail)
            if on_text_delta is not None:
                await on_text_delta(tail)

        tool_calls = [
            ToolCall(
                id=slot["id"] or f"call_{index}",
                name=slot["name"],
                arguments=slot["arguments"] or "{}",
            )
            for index, slot in sorted(pending.items())
            if slot["name"]
        ]
        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            model=model,
        )

    @staticmethod
    def _strip_hidden_thoughts(node: dict[str, Any]) -> None:
        for key in _HIDDEN_THOUGHT_FIELDS:
            node.pop(key, None)

    @staticmethod
    def _raise_for_status(response: httpx.Response, body: str | None = None) -> None:
        if response.status_code < 400:
            return
        text = body if body is not None else response.text
        snippet = (text or "").strip()[:400]
        retryable = response.status_code in _RETRYABLE_STATUS
        hint = ""
        if response.status_code in (401, 403):
            hint = "（请检查 LLM_API_KEY 是否正确、是否有余额/权限）"
        elif response.status_code == 400:
            hint = _hint_for_bad_request(snippet)
        raise LLMError(
            f"LLM 返回 HTTP {response.status_code}{hint}: {snippet}",
            status_code=response.status_code,
            retryable=retryable,
        )


# 本地推理服务（vLLM / Xinference / LMDeploy 等）的 400 大多是几个固定原因，
# 直接把排查方向写在错误里，省得对着一句英文猜。
_BAD_REQUEST_HINTS: tuple[tuple[str, str], ...] = (
    (
        "system message must be at the beginning",
        "（该服务只接受开头的唯一一条 system 消息。本 Demo 已把系统提示/当前时间/会话上下文合并成一条，"
        "若仍报此错，请确认用的是最新版 backend/agent/runtime.py）",
    ),
    (
        "tool",
        "（该服务可能没开启工具解析。vLLM 需要加 --enable-auto-tool-choice --tool-call-parser hermes；"
        "确认模型本身支持 function calling）",
    ),
    (
        "context",
        "（超出模型上下文长度。把 .env 的 LLM_PROFILE 改成 local32k，"
        "会自动收紧工具下发量与单轮返回体）",
    ),
    (
        "max_tokens",
        "（LLM_MAX_TOKENS 超过该服务允许的上限，调小后重试）",
    ),
    (
        "temperature",
        "（该服务不接受当前的 temperature/top_p 取值，检查 LLM_TEMPERATURE）",
    ),
)


def _hint_for_bad_request(body: str) -> str:
    lowered = (body or "").lower()
    for needle, hint in _BAD_REQUEST_HINTS:
        if needle in lowered:
            return hint
    return "（请求被服务端拒绝；常见原因：多条 system 消息、未开启工具解析、超出上下文长度）"


def build_llm_client(settings) -> OpenAICompatibleClient:
    """按配置装配默认 LLM 客户端。"""
    return OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        stream=settings.llm_stream,
    )
