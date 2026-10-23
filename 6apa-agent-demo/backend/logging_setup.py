"""日志配置。

要求：
- 记录 conversation_id / user_message / tool_name / tool_arguments /
  tool_result_summary / execution_time / error / final_answer
- 绝不记录 API Key

实现上除了"我们自己不打印 key"，还加了一道过滤器兜底：任何一条日志里
出现疑似密钥的串（Authorization 头、Bearer xxx、sk-xxx）都会被打码，
防止将来有人不小心把 headers 丢进日志。
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import time
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"(sk-)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(\"?(?:api[_-]?key|authorization)\"?\s*[:=]\s*\"?)([^\"\s,}]{8,})", re.IGNORECASE),
]


class SecretRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(lambda m: m.group(1) + "***REDACTED***", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(level: str = "INFO", log_dir: str | None = None) -> None:
    root = logging.getLogger()
    if getattr(root, "_agent_configured", False):
        return

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
    redactor = SecretRedactingFilter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redactor)
    root.addHandler(console)

    if log_dir:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            directory / "agent.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        root.addHandler(file_handler)

        trace_handler = logging.handlers.RotatingFileHandler(
            directory / "turns.jsonl", maxBytes=10_000_000, backupCount=3, encoding="utf-8"
        )
        trace_handler.setFormatter(logging.Formatter("%(message)s"))
        trace_handler.addFilter(redactor)
        trace_logger = logging.getLogger("agent.trace")
        trace_logger.setLevel(logging.INFO)
        trace_logger.propagate = False
        trace_logger.addHandler(trace_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    root._agent_configured = True  # type: ignore[attr-defined]


def log_turn(record: dict[str, Any]) -> None:
    """把一轮对话的结构化轨迹写进 turns.jsonl（一行一轮）。"""
    payload = dict(record)
    payload.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    logging.getLogger("agent.trace").info(json.dumps(payload, ensure_ascii=False, default=str))
