"""工具清单（GET /api/tools）自测：前端「固定工具」页依赖这些字段。

    python3 -m tests.test_tool_catalog
"""
from __future__ import annotations

import sys

from backend.main import registry

results: list[bool] = []


def check(ok, label: str) -> None:
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label)


def main() -> int:
    cat = {c["name"]: c for c in registry.catalog()}
    fixed = [c for c in cat.values() if c["kind"] == "固定程序"]
    check(len(cat) == len(registry) and all({"group", "summary", "kind", "parameters", "returns"} <= set(c) for c in cat.values()),
          f"{len(cat)} 个工具都带分组、摘要、类型、参数、返回")
    check({"investigate_process_anomaly", "check_limit_exceedance", "calculate_quantity"} <= {c["name"] for c in fixed}
          and all(cat[n]["kind"] == "本体接口" for n in cat if cat[n]["endpoint"].startswith("/api/")),
          f"固定程序 {len(fixed)} 个（本地执行），其余为本体接口")
    calc = cat["calculate_quantity"]
    check(calc.get("methods") and calc["methods"][0]["key"] == "level_consumption", "计算模块列出计算方法")
    check(any(p.get("enum") for p in cat["investigate_process_anomaly"]["parameters"]), "参数带可选值（enum）")
    check(all({"name", "description", "returns"} <= set(c) for c in cat.values()), "原有字段保留")
    passed = sum(results)
    print(f"\n通过 {passed} / {len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
