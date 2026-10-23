"""模拟 DCS 服务配置。全部走环境变量，与 Agent 服务共用项目根目录下的 .env。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return default if not raw else raw in {"1", "true", "yes", "on"}


@dataclass
class MockSettings:
    host: str = field(default_factory=lambda: os.environ.get("MOCK_DCS_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _int("MOCK_DCS_PORT", 8900))
    # 点表元数据来源：本体服务。取不到时退化为按位号名推断，服务照常可用
    ontology_base_url: str = field(
        default_factory=lambda: (
            os.environ.get("MOCK_DCS_ONTOLOGY_URL") or os.environ.get("ONTOLOGY_BASE_URL") or "http://localhost:8700"
        ).rstrip("/")
    )
    # true：点表里查不到的 nodeId 返回 q=0 / v=null；false：按位号名推断生成
    strict_nodes: bool = field(default_factory=lambda: _bool("MOCK_DCS_STRICT_NODES", False))
    # 同一套种子生成同一套数据；换种子相当于换一个"工厂"
    seed: str = field(default_factory=lambda: os.environ.get("MOCK_DCS_SEED", "6apa"))
    max_nodes_per_request: int = field(default_factory=lambda: _int("MOCK_DCS_MAX_NODES", 500))
    max_points_per_node: int = field(default_factory=lambda: _int("MOCK_DCS_MAX_POINTS", 10000))
    # 时间字符串（如 "2026-09-22 08:00:00"）按此时区解析；现场在国内，默认东八区
    tz_offset_hours: int = field(default_factory=lambda: _int("MOCK_DCS_TZ_OFFSET", 8))


settings = MockSettings()
