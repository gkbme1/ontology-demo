"""逐个把 Tool 打到真实本体 API 上，验证契约是否对得上。

用法：
    ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.verify_tools

不需要 LLM Key——这一步只验证 Tool Registry / Executor 与本体服务之间的契约。
"""

from __future__ import annotations

import asyncio
import json
import sys

from backend.config import settings
from backend.tools.executor import ToolExecutor
from backend.tools.ontology_tools import build_ontology_registry

# 需要具体 ID 的工具，先通过列表类工具动态取一个真实 ID，不写死任何业务值。
# 第三项是点号路径（填进第一个必填参数），或 {参数名: 点号路径}（一次填多个参数）。
ID_PROVIDERS: dict[str, tuple[str, dict, str | dict[str, str]]] = {
    "query_process_area_detail": ("query_process_areas", {}, "items.0.id"),
    "query_equipment_detail": ("query_equipment_list", {"limit": 1}, "items.0.id"),
    "query_parameter_detail": ("query_parameters", {"limit": 1}, "items.0.id"),
    "query_relation_detail": ("query_relations", {"limit": 1}, "items.0.id"),
    "query_object_relations": ("query_equipment_list", {"limit": 1}, "items.0.id"),
    "query_realtime_values": ("query_equipment_list", {"keyword": "一层排渣泵", "limit": 1}, "items.0.id"),
    "query_history_values": ("query_equipment_list", {"keyword": "一层排渣泵", "limit": 1}, "items.0.id"),
    "query_object_limits": ("query_equipment_list", {"keyword": "水解罐A", "limit": 1}, "items.0.id"),
    "query_equipment_group_detail": ("query_equipment_groups", {"limit": 1}, "items.0.id"),
    "query_limit_check": ("query_equipment_list", {"keyword": "水解罐A", "limit": 1}, "items.0.id"),
    "investigate_process_anomaly": ("query_relation_entities", {"type": "工艺属性", "matched": True, "limit": 1}, "items.0.id"),
    "verify_process_influence": (
        "query_relations",
        {"category": "影响关系", "predicate": "正向影响", "limit": 1},
        {"cause": "items.0.subject.id", "effect": "items.0.object.id"},
    ),
    "summarize_area_relations": ("query_process_areas", {}, "items.0.id"),
    "check_limit_exceedance": ("query_process_limits", {"hasValues": True, "appliesToType": "工艺属性"}, "items.0.appliesTo"),
    "map_causal_neighborhood": ("query_relations", {"category": "影响关系", "limit": 1}, "items.0.object.id"),
    "describe_equipment_links": ("query_equipment_list", {"keyword": "水解罐A", "limit": 1}, "items.0.id"),
    "analyze_switch_signals": ("query_equipment_list", {"keyword": "一层排渣泵", "limit": 1}, "items.0.id"),
}

EXTRA_ARGS: dict[str, dict] = {
    "list_available_tools": {"group": "limits"},
    "query_equipment_list": {"keyword": "泵", "limit": 3},
    "query_parameters": {"limit": 3},
    "query_tags": {"limit": 3},
    "query_relations": {"limit": 3},
    "query_ontology_graph": {"depth": 1},
    "query_semantics": {"limit": 3},
    "query_measurement_anchors": {"limit": 3},
    "query_history_values": {"startTime": "__ONE_HOUR_AGO__", "interval": 600000},
    "query_process_limits": {"hasValues": "true"},
    "query_equipment_groups": {"limit": 3},
    "query_area_flow": {"areaId": "S11"},
    "check_limit_exceedance": {"startTime": "__ONE_HOUR_AGO__"},
    "map_causal_neighborhood": {"withValues": True},
    "audit_data_gaps": {"kind": "无测点"},
    "analyze_switch_signals": {"startTime": "__ONE_HOUR_AGO__"},
}


def resolve(data, dotted):
    node = data
    for part in dotted.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list):
            index = int(part)
            node = node[index] if index < len(node) else None
        else:
            return None
        if node is None:
            return None
    return node


async def main() -> int:
    registry = build_ontology_registry()
    executor = ToolExecutor(
        settings.ontology_base_url,
        timeout=settings.ontology_timeout,
        max_result_chars=settings.max_tool_result_chars,
        registry=registry,
    )
    rows = []
    failures = 0

    print(f"本体服务：{settings.ontology_base_url}")
    print(f"工具数量：{len(registry)}\n")

    for spec in registry:
        args = dict(EXTRA_ARGS.get(spec.name, {}))
        if args.get("startTime") == "__ONE_HOUR_AGO__":
            import datetime as _dt

            args["startTime"] = (_dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))) - _dt.timedelta(hours=1)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        if spec.name in ID_PROVIDERS:
            provider_name, provider_args, path = ID_PROVIDERS[spec.name]
            provider = registry.require(provider_name)
            probe = await executor.execute(provider, "probe", json.dumps(provider_args))
            required = [p.name for p in spec.parameters if p.required]
            targets = path if isinstance(path, dict) else ({required[0]: path} if required else {})
            found = {name: resolve(probe.result, dotted) if probe.status != "error" else None for name, dotted in targets.items()}
            if not all(found.values()):
                rows.append((spec.name, "SKIP", 0, "取不到可用 ID"))
                continue
            args.update(found)

        execution = await executor.execute(spec, "verify", json.dumps(args, ensure_ascii=False))
        note = execution.error or execution.to_public_dict()["resultSummary"]
        if execution.truncated:
            note += " [已裁剪]"
        state = {"ok": "OK", "empty": "EMPTY", "error": "FAIL"}[execution.status]
        if execution.status == "error":
            failures += 1
        rows.append((spec.name, state, execution.duration_ms, f"{execution.raw_bytes}B → {note}"))

    width = max(len(row[0]) for row in rows)
    for name, state, ms, note in rows:
        print(f"{name:<{width}}  {state:<5} {ms:>5}ms  {note[:110]}")

    await executor.aclose()
    print(f"\n失败 {failures} / {len(rows)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
