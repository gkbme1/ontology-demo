"""System Prompt 装配。

Prompt 本身放在 backend/prompts/system_prompt.txt，与代码分离，方便现场调优。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT_FILE = PROMPT_DIR / "system_prompt.txt"


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    if not SYSTEM_PROMPT_FILE.is_file():
        raise FileNotFoundError(f"缺少 System Prompt 文件：{SYSTEM_PROMPT_FILE}")
    return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()


def reload_system_prompt() -> str:
    """改完 prompt 文件后无需重启进程。"""
    load_system_prompt.cache_clear()
    return load_system_prompt()
