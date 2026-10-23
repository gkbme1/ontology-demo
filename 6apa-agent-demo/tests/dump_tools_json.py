"""把 Tool Registry 导出成 OpenAI 兼容的 tools 数组，供其他 Agent 直接复用。

    python3 -m tests.dump_tools_json > docs/agent-tools.json
"""

from __future__ import annotations

import json
import sys

from backend.tools.ontology_tools import build_ontology_registry


def main() -> int:
    registry = build_ontology_registry()
    payload = [spec.to_openai_schema() for spec in registry]
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
