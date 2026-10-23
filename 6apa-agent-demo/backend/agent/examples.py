"""示例问题装配。

示例问题放在 backend/data/examples.json，与代码分离——它是一份**纯数据**：
前端点一下，只是把问题文本填进输入框，Agent 照常自己规划工具链。
这里不做任何「问题 → 工具」的绑定，也不把 referenceToolChain 下发给模型，
否则就成了针对具体问题写死业务流程，违背本项目的硬性约束。

改完 JSON 后调 POST /api/examples/reload，或直接重启进程。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "examples.json"

_EMPTY: dict[str, Any] = {
    "version": None,
    "groups": [],
    "total": 0,
    "available": False,
    "emptyReason": "未找到示例问题文件 backend/data/examples.json；不影响对话，输入框照常可用。",
}


@lru_cache(maxsize=1)
def load_examples() -> dict[str, Any]:
    if not DATA_FILE.is_file():
        return dict(_EMPTY)
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # 文件被改坏时不能把对话服务一起拖垮
        payload = dict(_EMPTY)
        payload["emptyReason"] = f"示例问题文件解析失败：{exc}"
        return payload

    groups = []
    for group in raw.get("groups") or []:
        items = [item for item in (group.get("items") or []) if (item.get("question") or "").strip()]
        if not items:
            continue
        groups.append({**group, "items": items, "count": len(items)})

    return {
        "version": raw.get("version"),
        "notice": raw.get("notice"),
        "groups": groups,
        "total": sum(group["count"] for group in groups),
        "available": bool(groups),
    }


def reload_examples() -> dict[str, Any]:
    load_examples.cache_clear()
    return load_examples()


def all_questions() -> list[str]:
    """扁平化的问题文本列表，供测试与命令行使用。"""
    return [item["question"] for group in load_examples()["groups"] for item in group["items"]]
