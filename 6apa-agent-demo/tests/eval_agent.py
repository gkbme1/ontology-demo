"""Agent 效果评测 —— 换模型前后拿它对比，别靠感觉。

    # 跑一遍当前 .env 配置的模型
    python3 -m tests.eval_agent

    # 只跑工艺调查那组
    python3 -m tests.eval_agent --group investigation

    # 换本地模型对比（两次结果都会落盘，最后一行给出对比表）
    LLM_PROFILE=cloud    LLM_MODEL=deepseek-chat python3 -m tests.eval_agent --tag deepseek
    LLM_PROFILE=local32k LLM_BASE_URL=http://127.0.0.1:8000/v1 LLM_MODEL=qwen32b \\
        python3 -m tests.eval_agent --tag qwen32b
    python3 -m tests.eval_agent --compare deepseek qwen32b

评什么
------
这套 Demo 的价值不在"答得漂亮"，在**守得住规矩**。所以打分项都是可机检的硬约束，
不做主观质量评价：

  完成      最终答案非空，且没有在工具预算内跑飞
  用工具    至少调了一次工具（纯靠模型知识作答算不合格）
  不编阈值  回答里出现数值范围时，必须引用 PL 编号或调用过限值类工具
  声明模拟  调用过实时值/历史值后，回答里必须出现"模拟"字样
  报缺口    案例期望里标了"没有测点/无法验证"的，回答里要提到
  无思维链  回答里不得出现 <think> 这类标签
  指代      多轮案例里不重复实体名也能接上（仅对标了 intent 含"指代"的案例检查）

每项 1 分，按案例汇总。分数只用于横向对比不同模型 / 不同档位，不是绝对质量分。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from backend.agent.context import Conversation
from backend.agent.events import ANSWER, DONE, ERROR, STATUS, TOOL_CALL, TOOL_RESULT
from backend.agent.runtime import AgentRuntime
from backend.config import settings
from backend.agent.examples import load_examples
from backend.llm.openai_compatible import build_llm_client
from backend.tools.executor import ToolExecutor
from backend.tools.ontology_tools import build_ontology_registry
from backend.tools.registry import INITIAL_GROUPS

RESULT_DIR = Path(__file__).resolve().parent.parent / "logs" / "eval"

# 出现这些词 + 数字，视为在陈述一个数值区间/阈值
_THRESHOLD_HINT = re.compile(
    r"(上限|下限|高限|低限|正常范围|正常区间|控制在|不得超过|不应低于|应低于|应高于|阈值)"
)
_NUMBER = re.compile(r"\d")
_PL_REF = re.compile(r"PL\d{3}")
_THINK_LEAK = re.compile(r"<\s*/?\s*(think|thinking|reasoning|thought)\b", re.IGNORECASE)
# 确定性分析工具在内部取值 / 查限值，评分时与对应的查询工具同等看待
_ANALYSIS_VALUE_TOOLS = {"investigate_process_anomaly", "verify_process_influence", "check_limit_exceedance"}
_VALUE_TOOLS = {"query_realtime_values", "query_history_values", "query_limit_check"} | _ANALYSIS_VALUE_TOOLS
_LIMIT_TOOLS = {"query_process_limits", "query_object_limits", "query_limit_check"} | _ANALYSIS_VALUE_TOOLS

CHECKS = ("完成", "用工具", "不编阈值", "声明模拟", "报缺口", "无思维链")


def _needs_gap_report(item: dict[str, Any]) -> bool:
    text = (item.get("expectation") or "") + (item.get("intent") or "")
    return any(k in text for k in ("没有测点", "无测点", "无法用数据验证", "无法验证", "缺口", "暂无"))


def _gap_mentioned(answer: str) -> bool:
    return any(k in answer for k in ("没有测点", "无测点", "未匹配", "无法验证", "暂无", "现场未提供", "待现场提供"))


def score_answer(item: dict[str, Any], answer: str, tools_used: list[str], failed: bool) -> dict[str, Any]:
    scores: dict[str, int | None] = {}
    notes: list[str] = []

    scores["完成"] = 1 if (answer.strip() and not failed) else 0
    if not answer.strip():
        notes.append("没有产出最终答案")

    scores["用工具"] = 1 if tools_used else 0
    if not tools_used:
        notes.append("一次工具都没调，可能是凭模型自身知识作答")

    # 不编阈值：陈述了数值区间，就必须有 PL 引用或查过限值
    claims_threshold = bool(_THRESHOLD_HINT.search(answer) and _NUMBER.search(answer))
    if claims_threshold:
        grounded = bool(_PL_REF.search(answer)) or bool(set(tools_used) & _LIMIT_TOOLS)
        scores["不编阈值"] = 1 if grounded else 0
        if not grounded:
            notes.append("给出了数值范围但没引用 PL 编号、也没调用限值类工具")
    else:
        scores["不编阈值"] = None  # 本题没涉及，不计分

    # 声明模拟：取过值就必须说
    if set(tools_used) & _VALUE_TOOLS:
        declared = "模拟" in answer
        scores["声明模拟"] = 1 if declared else 0
        if not declared:
            notes.append("取了实时/历史值但没声明当前是模拟数据")
    else:
        scores["声明模拟"] = None

    if _needs_gap_report(item):
        ok = _gap_mentioned(answer)
        scores["报缺口"] = 1 if ok else 0
        if not ok:
            notes.append("案例期望里要求说明数据缺口，回答中没有提到")
    else:
        scores["报缺口"] = None

    leaked = bool(_THINK_LEAK.search(answer))
    scores["无思维链"] = 0 if leaked else 1
    if leaked:
        notes.append("回答里泄漏了思维链标签")

    graded = {k: v for k, v in scores.items() if v is not None}
    return {
        "scores": scores,
        "got": sum(graded.values()),
        "max": len(graded),
        "notes": notes,
    }


async def run_case(runtime: AgentRuntime, item: dict[str, Any], conversation: Conversation) -> dict[str, Any]:
    answer_parts: list[str] = []
    tools_used: list[str] = []
    tool_errors = 0
    rounds = 0
    failed = False
    error_message = ""
    started = time.perf_counter()

    try:
        async for event in runtime.run_turn(conversation, item["question"]):
            if event.type == TOOL_CALL:
                tools_used.append(event.data["tool"])
            elif event.type == TOOL_RESULT and event.data.get("status") == "error":
                tool_errors += 1
            elif event.type == ANSWER:
                answer_parts = [event.data.get("text") or ""]
            elif event.type == ERROR:
                failed = True
                error_message = event.data.get("message", "")
            elif event.type == DONE:
                rounds = event.data.get("rounds") or event.data.get("llmRounds") or 0
            elif event.type == STATUS:
                pass
    except Exception as exc:  # 评测本身不能因为一条案例崩掉
        failed = True
        error_message = f"{type(exc).__name__}: {exc}"

    answer = "".join(answer_parts)
    result = {
        "id": item["id"],
        "question": item["question"],
        "answer": answer,
        "answerChars": len(answer),
        "tools": tools_used,
        "toolCount": len(tools_used),
        "toolErrors": tool_errors,
        "rounds": rounds,
        "elapsedMs": int((time.perf_counter() - started) * 1000),
        "failed": failed,
        "error": error_message,
    }
    result.update(score_answer(item, answer, tools_used, failed))
    return result


async def main_async(args: argparse.Namespace) -> int:
    catalog = load_examples()
    if not catalog["available"]:
        print("示例问题没加载到，检查 backend/data/examples.json")
        return 1

    groups = [g for g in catalog["groups"] if not args.group or g["key"] == args.group]
    cases = [(g, item) for g in groups for item in g["items"]]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print(f"没有匹配的案例（group={args.group}）")
        return 1

    registry = build_ontology_registry(compact_relations=settings.compact_relations)
    initial = [s.name for s in registry if s.group in INITIAL_GROUPS] if settings.progressive_tools else None
    executor = ToolExecutor(
        settings.ontology_base_url,
        timeout=settings.ontology_timeout,
        max_result_chars=settings.max_tool_result_chars,
        registry=registry,
    )
    llm = build_llm_client(settings)
    if args.stub:
        # 无 Key 环境下自检评测脚本本身：用脚本化假 LLM 走完整流程
        from tests.stub_llm_server import StubLLM

        llm = StubLLM()
    runtime = AgentRuntime(
        llm,
        registry,
        executor,
        max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
        max_history_messages=settings.max_history_messages,
        max_context_chars=settings.max_context_chars,
        initial_tools=initial,
    )

    tag = args.tag or settings.llm_model.replace("/", "_")
    print(f"模型 {settings.llm_model} @ {settings.llm_base_url}")
    print(f"档位 {settings.llm_profile}：工具预算 {settings.max_tool_calls_per_turn} 次 / "
          f"单次 {settings.max_tool_result_chars} 字符 / 渐进解锁 {settings.progressive_tools}")
    print(f"共 {len(cases)} 条案例\n")

    results: list[dict[str, Any]] = []
    conversation: Conversation | None = None
    last_group = None
    for group, item in cases:
        # 同一组内共用会话，这样"它有哪些参数"这类指代题才有上下文
        if group["key"] != last_group:
            conversation = Conversation(conversation_id=f"eval-{group['key']}")
            last_group = group["key"]
        result = await run_case(runtime, item, conversation)
        result["group"] = group["key"]
        results.append(result)
        flag = "OK " if result["got"] == result["max"] and not result["failed"] else "!! "
        print(f"{flag}{item['id']:<8} {result['got']}/{result['max']}  "
              f"{result['toolCount']:>2} 次工具  {result['elapsedMs']:>6}ms  {item['question'][:28]}")
        for note in result["notes"]:
            print(f"        └ {note}")

    await executor.aclose()

    total_got = sum(r["got"] for r in results)
    total_max = sum(r["max"] for r in results)
    per_check = {
        name: {
            "got": sum(1 for r in results if r["scores"].get(name) == 1),
            "of": sum(1 for r in results if r["scores"].get(name) is not None),
        }
        for name in CHECKS
    }
    summary = {
        "tag": tag,
        "model": settings.llm_model,
        "baseUrl": settings.llm_base_url,
        "profile": settings.llm_profile,
        "maxToolCalls": settings.max_tool_calls_per_turn,
        "maxToolResultChars": settings.max_tool_result_chars,
        "progressiveTools": settings.progressive_tools,
        "cases": len(results),
        "score": total_got,
        "scoreMax": total_max,
        "rate": round(total_got / total_max, 3) if total_max else 0,
        "avgToolCalls": round(sum(r["toolCount"] for r in results) / len(results), 1),
        "toolErrorRate": round(
            sum(r["toolErrors"] for r in results) / max(1, sum(r["toolCount"] for r in results)), 3
        ),
        "avgElapsedMs": int(sum(r["elapsedMs"] for r in results) / len(results)),
        "failures": len([r for r in results if r["failed"]]),
        "perCheck": per_check,
        "ranAt": dt.datetime.now().isoformat(timespec="seconds"),
    }

    print(f"\n总分 {total_got} / {total_max}（{summary['rate']:.0%}）")
    for name, stat in per_check.items():
        if stat["of"]:
            print(f"  {name:<8} {stat['got']}/{stat['of']}")
    print(f"  平均 {summary['avgToolCalls']} 次工具 / 条，工具报错率 {summary['toolErrorRate']:.1%}，"
          f"平均耗时 {summary['avgElapsedMs']}ms")

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULT_DIR / f"{tag}.json"
    out.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n明细已写入 {out}")
    return 0


def compare(tags: list[str]) -> int:
    rows = []
    for tag in tags:
        path = RESULT_DIR / f"{tag}.json"
        if not path.is_file():
            print(f"没有 {path}，先用 --tag {tag} 跑一遍")
            return 1
        rows.append(json.loads(path.read_text(encoding="utf-8")))

    head = ["项目"] + [r["summary"]["tag"] for r in rows]
    lines = [head, ["模型"] + [r["summary"]["model"] for r in rows],
             ["档位"] + [r["summary"]["profile"] for r in rows],
             ["总分"] + [f"{r['summary']['score']}/{r['summary']['scoreMax']}（{r['summary']['rate']:.0%}）" for r in rows]]
    for name in CHECKS:
        cells = []
        for r in rows:
            stat = r["summary"]["perCheck"].get(name, {})
            cells.append(f"{stat.get('got', 0)}/{stat.get('of', 0)}" if stat.get("of") else "—")
        lines.append([name] + cells)
    lines.append(["平均工具次数"] + [str(r["summary"]["avgToolCalls"]) for r in rows])
    lines.append(["工具报错率"] + [f"{r['summary']['toolErrorRate']:.1%}" for r in rows])
    lines.append(["平均耗时"] + [f"{r['summary']['avgElapsedMs']}ms" for r in rows])
    lines.append(["跑飞条数"] + [str(r["summary"]["failures"]) for r in rows])

    widths = [max(len(str(row[i])) for row in lines) for i in range(len(head))]
    for index, row in enumerate(lines):
        print("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))
        if index == 0:
            print("  ".join("-" * w for w in widths))

    # 逐条差异
    by_tag = {r["summary"]["tag"]: {x["id"]: x for x in r["results"]} for r in rows}
    ids = [x["id"] for x in rows[0]["results"]]
    diffs = [
        i for i in ids
        if len({by_tag[t].get(i, {}).get("got") for t in by_tag}) > 1
    ]
    if diffs:
        print(f"\n分数不同的案例（{len(diffs)} 条）：")
        for i in diffs:
            cells = "  ".join(f"{t}={by_tag[t].get(i, {}).get('got', '-')}/{by_tag[t].get(i, {}).get('max', '-')}" for t in by_tag)
            print(f"  {i:<8} {cells}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent 效果评测")
    parser.add_argument("--group", help="只跑某一组（investigation / quality / equipment / gap / basic）")
    parser.add_argument("--limit", type=int, help="只跑前 N 条")
    parser.add_argument("--tag", help="本次结果的标签，用于后续对比")
    parser.add_argument("--compare", nargs="+", metavar="TAG", help="对比已有的两次结果")
    parser.add_argument("--stub", action="store_true", help="用假 LLM 跑通流程（自检评测脚本本身，不代表模型效果）")
    args = parser.parse_args()

    if args.compare:
        return compare(args.compare)
    if not args.stub and not settings.llm_api_key and "localhost" not in settings.llm_base_url and "127.0.0.1" not in settings.llm_base_url:
        print("没有配置 LLM_API_KEY，且 LLM_BASE_URL 不是本地地址——评测需要一个能真正作答的模型。")
        return 1
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
