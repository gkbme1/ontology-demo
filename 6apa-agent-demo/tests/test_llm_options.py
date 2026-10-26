"""LLM 客户端请求体自测（不需要任何服务）。

    python3 -m tests.test_llm_options

验证 LLM_ENABLE_THINKING：留空时不传 enable_thinking（兼容不认识该参数的服务端），
设为 true / false 时原样传给服务端。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx

from backend.config import Settings
from backend.llm.openai_compatible import OpenAICompatibleClient

results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


async def captured_payload(enable_thinking) -> dict:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})

    client = OpenAICompatibleClient("http://llm.test/v1", "k", "m", stream=False, enable_thinking=enable_thinking)
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await client.chat([{"role": "user", "content": "hi"}])
    await client.aclose()
    return seen


def main() -> int:
    print("[enable_thinking 请求参数]")
    check("enable_thinking" not in asyncio.run(captured_payload(None)), "留空时不传 enable_thinking")
    check(asyncio.run(captured_payload(False)).get("enable_thinking") is False, "false 时传 enable_thinking=false")
    check(asyncio.run(captured_payload(True)).get("enable_thinking") is True, "true 时传 enable_thinking=true")

    print("[环境变量解析]")
    backup = os.environ.get("LLM_ENABLE_THINKING")
    try:
        for raw, expected in (("", None), ("false", False), ("0", False), ("true", True)):
            os.environ["LLM_ENABLE_THINKING"] = raw
            check(Settings().llm_enable_thinking is expected, f"LLM_ENABLE_THINKING={raw!r} → {expected}")
        check("llm_enable_thinking" in Settings().describe(), "/api/health 的生效配置里能看到思考开关")
    finally:
        if backup is None:
            os.environ.pop("LLM_ENABLE_THINKING", None)
        else:
            os.environ["LLM_ENABLE_THINKING"] = backup

    passed = sum(results)
    print(f"\n通过 {passed} / {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
