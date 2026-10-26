"""工具发现：让模型自己按需索取工具（渐进解锁）。

为什么要这个
------------
33 个工具的完整 schema 每次请求要发约 8,900 token。接云端长上下文模型时这只是
成本问题；换成本地 32k 上下文的模型（如千问 32B），光工具定义就吃掉三分之一的
上下文，工艺调查这类需要连续七八次工具调用的问题会在走到一半时被挤爆。

做法
----
第一轮只下发 core 组的 9 个工具（约 7,800 字符），外加本工具。模型发现手上的工具
不够用时，调用 `list_available_tools` 看还有哪些组、要某一组或按关键词要几个，
**要到的工具当轮立即生效**，后续请求就带上它们。

这里有意不做的事
----------------
不根据问题内容猜该给哪些工具：分组是按能力类别划分的静态属性
（结构 / 运行时值 / 限值 / 规则 / 元数据），选哪一组由模型自己判断，Runtime 不参与。
按问题类型走固定算法的是 analysis 组的确定性分析工具，它们一开始就和 core 组一起下发。
"""

from __future__ import annotations

from typing import Any

from backend.tools.registry import TOOL_GROUPS, ToolParameter, ToolRegistry, ToolSpec

DISCOVERY_TOOL_NAME = "list_available_tools"

# 一次最多解锁多少个，防止模型一句 "全都要" 把上下文重新撑满
MAX_UNLOCK_PER_CALL = 12


def _discover(registry: ToolRegistry, arguments: dict[str, Any], api: Any = None) -> dict[str, Any]:
    group = (arguments.get("group") or "").strip()
    keyword = (arguments.get("keyword") or "").strip()

    if not group and not keyword:
        # 什么都没给：只报有哪些组，不解锁——让模型先看菜单再点菜
        groups = registry.groups()
        return {
            "mode": "groups",
            "groups": [
                {"group": key, "covers": desc, "toolCount": len(groups.get(key, []))}
                for key, desc in TOOL_GROUPS.items()
                if groups.get(key)
            ],
            "note": (
                "这是工具分组菜单，本次没有解锁任何工具。"
                "确定要哪一类后，再调一次本工具并带上 group（或 keyword），"
                "要到的工具从下一步起就能直接调用。"
            ),
        }

    candidates = [
        spec
        for spec in registry
        if spec.name != DISCOVERY_TOOL_NAME
        and (not group or spec.group == group)
        and (
            not keyword
            or keyword in spec.name
            or keyword in spec.summary
            or keyword in spec.description
        )
    ]
    if not candidates:
        return {
            "mode": "empty",
            "unlocked": [],
            "emptyReason": (
                f"没有匹配的工具（group={group or '未指定'}，keyword={keyword or '未指定'}）。"
                f"可用的组：{'、'.join(k for k in TOOL_GROUPS if registry.groups().get(k))}。"
                "不带任何参数再调一次可以看到分组菜单。"
            ),
        }

    truncated = len(candidates) - MAX_UNLOCK_PER_CALL
    granted = candidates[:MAX_UNLOCK_PER_CALL]
    payload: dict[str, Any] = {
        "mode": "unlock",
        "unlocked": registry.brief(spec.name for spec in granted),
        "total": len(candidates),
        "note": "以上工具从下一步起可以直接调用，参数说明会随之下发。",
    }
    if truncated > 0:
        payload["truncationNote"] = (
            f"匹配到 {len(candidates)} 个，本次只解锁前 {MAX_UNLOCK_PER_CALL} 个；"
            "需要其余的请缩小 keyword 后再调一次。"
        )
    # Runtime 读这个字段决定下一步下发哪些工具；它不关心里面是什么名字
    payload["_unlock"] = [spec.name for spec in granted]
    return payload


DISCOVERY_TOOL = ToolSpec(
    name=DISCOVERY_TOOL_NAME,
    description=(
        "查看并获取当前还没下发给你的工具。你手上的工具不足以回答问题时调用它，"
        "不要因为没有合适的工具就直接说查不到。"
        "不带参数调用会返回工具分组菜单（只告诉你有哪些类别，不解锁）；"
        "带 group 或 keyword 调用会解锁匹配的工具，解锁后当轮即可直接调用。"
    ),
    path="",  # 本地执行，不打 HTTP
    parameters=(
        ToolParameter(
            "group",
            "string",
            "工具组名。取值：" + "、".join(f"{k}（{v.split('：')[0]}）" for k, v in TOOL_GROUPS.items()),
        ),
        ToolParameter("keyword", "string", "按关键词找工具，如 限值、历史、设备组、规则、工段。"),
    ),
    group="core",
    summary="查看并获取尚未下发的工具",
    returns="不带参数时返回 groups[]（组名 + 覆盖范围 + 工具数）；带 group/keyword 时返回 unlocked[]（工具名 + 一句话说明），这些工具随即可用。",
    handler=_discover,
)
