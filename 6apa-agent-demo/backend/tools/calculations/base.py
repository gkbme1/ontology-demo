"""计算模块骨架：算法注册表与公共上下文。

一种"计算"= 一个 CalcMethod，回答两个问题：
1. detect —— 这个本体对象能不能用我来算？能的话从哪个对象取数、依据是什么（返回 CalcSource，不能算返回 None）。
   只看本体结构（对象名称、描述、关系），不碰历史数据，要便宜；
2. run —— 真正取数计算，返回给模型的结构化结果（必须带 conclusion，数字全部由程序算好）。

新增一种计算：在本目录新建一个模块，定义 detect / run，用 register(CalcMethod(...)) 登记，
再在 calculations/__init__.py 里 import 一下即可。工具入口 calculate_quantity 的参数说明、
方法清单和分发逻辑都从注册表生成，不用改。

约定：
- 不认识具体设备、位号或工艺量名，只按本体结构判断（例如"液位量""以液位为原因的负向影响"）；
- 判定口径（死区、默认时间窗等）写成模块级常量，属于需要现场标定的参数；
- 结果里写明计算口径（method）与本体依据（basis），用到模拟数据时在 conclusion 里声明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class CalcSource:
    """某个算法判定"能算"时给出的取数依据。"""

    method: str  # 算法 key
    source: dict[str, Any]  # 实际取数的本体对象 {id, name}
    derived: dict[str, Any] | None  # 被求的派生量 {id, name}；就是 source 本身时为 None
    basis: str  # 本体依据：关系路径、描述原文、来源行号
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CalcContext:
    """run 拿到的全部输入。"""

    api: Any  # ToolExecutor，用 api.get_json 访问本体服务
    target: dict[str, Any]  # 用户要算的对象（解析后），含 id / name / matchedBy
    source: CalcSource
    arguments: dict[str, Any]  # 工具原始入参（startTime / endTime / focus …）


@dataclass(frozen=True)
class CalcMethod:
    key: str
    title: str  # 中文名，进结果的 analysisType
    summary: str  # 一句话说明能算什么，自动拼进工具描述
    detect: Callable[[Any, dict[str, Any], dict[str, Any]], Awaitable[CalcSource | None]]
    run: Callable[[CalcContext], Awaitable[dict[str, Any]]]


CALC_METHODS: dict[str, CalcMethod] = {}


def register(method: CalcMethod) -> CalcMethod:
    if method.key in CALC_METHODS:
        raise ValueError(f"计算方法重名：{method.key}")
    CALC_METHODS[method.key] = method
    return method
