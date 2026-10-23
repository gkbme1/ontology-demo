"""运行期配置。

所有可变项一律走环境变量 / .env，代码中不出现任何密钥与硬编码地址。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """极简 .env 读取器（不引入 python-dotenv 依赖）。

    已存在的真实环境变量优先级更高，不会被 .env 覆盖。
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


# 模型档位：把"给多长上下文的模型用"这件事收到一处，换模型只改一行。
# 档位只决定上下文预算与工具下发方式，不改变任何业务行为。
LLM_PROFILES: dict[str, dict] = {
    # 云端长上下文模型（DeepSeek、GPT 等）：维持原有余量
    "cloud": {
        "max_tool_calls_per_turn": 15,
        "max_tool_result_chars": 10000,
        "max_history_messages": 40,
        "max_context_chars": 90000,
        "progressive_tools": False,
        "compact_relations": False,
        "note": "云端长上下文模型；一次下发全部工具。",
    },
    # 本地 32k 上下文模型（如千问 32B）：工具定义约 8,900 token 就占掉三分之一，
    # 必须同时压工具下发量与单轮返回体，否则工艺调查类问题会中途撑爆上下文。
    "local32k": {
        "max_tool_calls_per_turn": 8,
        "max_tool_result_chars": 4000,
        "max_history_messages": 24,
        "max_context_chars": 20000,
        "progressive_tools": True,
        "compact_relations": True,
        "note": "本地 32k 模型；只先发核心工具，其余由模型按需取用。",
    },
    # 本地模型 + YaRN 扩到 128k：可以放宽，但长程注意力质量下降，仍比云端保守
    "local128k": {
        "max_tool_calls_per_turn": 12,
        "max_tool_result_chars": 8000,
        "max_history_messages": 32,
        "max_context_chars": 80000,
        "progressive_tools": True,
        "compact_relations": True,
        "note": "本地长上下文模型；仍走渐进解锁以省注意力。",
    },
}

DEFAULT_PROFILE = "cloud"


def _profile() -> dict:
    name = (os.environ.get("LLM_PROFILE", "") or DEFAULT_PROFILE).strip().lower()
    return LLM_PROFILES.get(name, LLM_PROFILES[DEFAULT_PROFILE])


def _profile_name() -> str:
    name = (os.environ.get("LLM_PROFILE", "") or DEFAULT_PROFILE).strip().lower()
    return name if name in LLM_PROFILES else DEFAULT_PROFILE


def _tuned_int(env_name: str, profile_key: str) -> int:
    """显式设了环境变量就用环境变量，否则用档位值。"""
    raw = os.environ.get(env_name, "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return int(_profile()[profile_key])


def _tuned_bool(env_name: str, profile_key: str) -> bool:
    raw = os.environ.get(env_name, "").strip().lower()
    if raw:
        return raw in {"1", "true", "yes", "on"}
    return bool(_profile()[profile_key])


@dataclass
class Settings:
    # ---------- LLM ----------
    llm_base_url: str = field(
        default_factory=lambda: os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    )
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "deepseek-chat"))
    llm_timeout: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT", 120.0))
    llm_temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.2))
    llm_max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 4096))
    llm_stream: bool = field(default_factory=lambda: _env_bool("LLM_STREAM", True))

    # ---------- 本体 API ----------
    ontology_base_url: str = field(
        default_factory=lambda: os.environ.get("ONTOLOGY_BASE_URL", "http://localhost:8700").rstrip("/")
    )
    ontology_timeout: float = field(default_factory=lambda: _env_float("ONTOLOGY_TIMEOUT", 20.0))

    # ---------- Agent ----------
    # ---------- 模型档位（决定下面四个预算与工具下发方式）----------
    llm_profile: str = field(default_factory=_profile_name)
    max_tool_calls_per_turn: int = field(
        default_factory=lambda: _tuned_int("MAX_TOOL_CALLS_PER_TURN", "max_tool_calls_per_turn")
    )
    max_history_messages: int = field(
        default_factory=lambda: _tuned_int("MAX_HISTORY_MESSAGES", "max_history_messages")
    )
    max_tool_result_chars: int = field(
        default_factory=lambda: _tuned_int("MAX_TOOL_RESULT_CHARS", "max_tool_result_chars")
    )
    max_context_chars: int = field(
        default_factory=lambda: _tuned_int("MAX_CONTEXT_CHARS", "max_context_chars")
    )
    # 渐进解锁：只先下发核心工具，其余由模型通过工具发现按需取用
    progressive_tools: bool = field(
        default_factory=lambda: _tuned_bool("PROGRESSIVE_TOOLS", "progressive_tools")
    )
    # 关系查询默认走精简视图（一条约 300 字节而不是 1.8 KB）
    compact_relations: bool = field(
        default_factory=lambda: _tuned_bool("COMPACT_RELATIONS", "compact_relations")
    )

    # ---------- 服务 ----------
    agent_host: str = field(default_factory=lambda: os.environ.get("AGENT_HOST", "0.0.0.0"))
    agent_port: int = field(default_factory=lambda: _env_int("AGENT_PORT", 8800))
    cors_origins: str = field(default_factory=lambda: os.environ.get("CORS_ORIGINS", "*"))

    # ---------- 日志 ----------
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())
    log_dir: str = field(default_factory=lambda: os.environ.get("LOG_DIR", str(PROJECT_ROOT / "logs")))

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw in {"", "*"}:
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    def describe(self) -> dict:
        """用于 /api/health —— 绝不包含 API Key。"""
        return {
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_api_key_configured": bool(self.llm_api_key),
            "llm_stream": self.llm_stream,
            "ontology_base_url": self.ontology_base_url,
            "llm_profile": self.llm_profile,
            "max_tool_calls_per_turn": self.max_tool_calls_per_turn,
            "max_tool_result_chars": self.max_tool_result_chars,
            "max_context_chars": self.max_context_chars,
            "progressive_tools": self.progressive_tools,
            "compact_relations": self.compact_relations,
            "agent_port": self.agent_port,
        }


settings = Settings()
