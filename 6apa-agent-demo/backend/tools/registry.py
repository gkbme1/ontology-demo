"""Tool Registry —— 声明式工具注册表。

设计要点：
1. 工具是"数据"而不是"代码"：一个工具 = 一条 ToolSpec 记录。
2. Registry 与 Agent Runtime 完全解耦：Agent 只问 Registry 要 schema、要 spec，
   从不认识任何一个具体工具的名字。
3. 新增本体接口 = 在 ontology_tools.py 里加一条 ToolSpec，Agent 核心逻辑零改动。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Literal

_PATH_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

JsonType = Literal["string", "integer", "number", "boolean"]

_PY_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}


class ToolValidationError(ValueError):
    """工具入参不满足 schema。由 Executor 捕获后作为结构化错误回灌给 LLM。"""


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type: JsonType = "string"
    description: str = ""
    required: bool = False
    enum: tuple[str, ...] | None = None
    example: Any = None

    def to_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.example is not None:
            schema["examples"] = [self.example]
        return schema


@dataclass(frozen=True)
class EntityCapture:
    """声明"这个工具调用成功后，会把什么实体变成当前上下文实体"。

    这是纯数据描述，不是业务分支——Agent 不需要知道"设备"两个字，
    它只是按 spec 说明从入参 / 返回体里取值写进会话上下文。
    """

    kind: str  # equipment / process_area / relation ...
    label: str  # 展示名，如 "设备"
    from_args: tuple[str, ...] = ()  # 优先从这些入参取标识
    from_result_paths: tuple[str, ...] = ()  # 其次从返回体这些点号路径取名称


@dataclass
class ToolSpec:
    name: str
    description: str
    path: str
    method: str = "GET"
    parameters: tuple[ToolParameter, ...] = ()
    returns: str = ""
    entity_capture: EntityCapture | None = None
    # 返回体里承载 nodes/edges 的键；命中则前端可渲染关系图
    graph_keys: tuple[str, ...] = ()
    # 模型未显式给出时补上的默认查询参数（例如分页上限），防止一次拉回几十万字符
    defaults: dict[str, Any] = field(default_factory=dict)
    # 返回体可能很大的接口：Executor 会更激进地裁剪列表
    heavy: bool = False
    # 所属工具组。渐进解锁模式下，只有 INITIAL_GROUPS 里的组一开始就下发给模型，
    # 其余组由模型通过元工具按需索取。分组是按"能力类别"划分的静态属性。
    group: str = "core"
    # 一句话摘要，元工具列清单时用（几十字，比完整 schema 便宜两个数量级）
    summary: str = ""
    # 本地执行的工具（不直接映射到某个本体接口）。handler(registry, arguments, api) -> dict，
    # 可以是 async；api 是 ToolExecutor，通过 api.get_json 访问本体服务。
    # Runtime 只看这个字段是否为空，仍然不认识任何具体工具名。
    handler: Any = None

    def apply_defaults(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """为未显式给出的参数补默认值（只补本工具声明过的参数）。"""
        known = {param.name for param in self.parameters}
        merged = dict(arguments)
        for key, value in self.defaults.items():
            if key in known and key not in merged:
                merged[key] = value
        return merged

    # ------------------------------------------------------------------ schema

    @property
    def path_params(self) -> tuple[str, ...]:
        return tuple(_PATH_PARAM_RE.findall(self.path))

    def to_openai_schema(self) -> dict[str, Any]:
        """转换成 OpenAI / DeepSeek function calling 的 tools[] 元素。"""
        properties = {param.name: param.to_schema() for param in self.parameters}
        required = [param.name for param in self.parameters if param.required]
        description = self.description
        if self.returns:
            description = f"{description}\n返回：{self.returns}"
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }

    # -------------------------------------------------------------- validation

    def validate_arguments(self, raw: dict[str, Any]) -> dict[str, Any]:
        """校验并归一化入参。

        - 缺必填 -> 抛 ToolValidationError（错误信息会回灌给 LLM，让它自己补参数）
        - 多余参数 -> 丢弃（模型偶尔会多给，不值得为此打断整轮对话）
        - 类型不符 -> 尽力转换，转不了才报错
        """
        if not isinstance(raw, dict):
            raise ToolValidationError(f"{self.name} 的参数必须是 JSON 对象，收到 {type(raw).__name__}")

        known = {param.name: param for param in self.parameters}
        cleaned: dict[str, Any] = {}
        dropped: list[str] = []

        for key, value in raw.items():
            param = known.get(key)
            if param is None:
                dropped.append(key)
                continue
            if value is None or value == "":
                continue
            cleaned[key] = _coerce(self.name, param, value)

        missing = [
            param.name
            for param in self.parameters
            if param.required and param.name not in cleaned
        ]
        if missing:
            raise ToolValidationError(
                f"{self.name} 缺少必填参数：{', '.join(missing)}。"
                f"可用参数：{', '.join(known) or '无'}"
            )

        if dropped:
            # 只记日志，不打断本轮对话——模型偶尔多给参数属于常态
            import logging

            logging.getLogger("agent.tools").debug(
                "%s 忽略未声明参数: %s", self.name, ", ".join(dropped)
            )

        return cleaned

    def split_arguments(self, arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """拆成 (路径参数, 查询参数)。"""
        path_keys = set(self.path_params)
        path_args = {key: value for key, value in arguments.items() if key in path_keys}
        query_args = {key: value for key, value in arguments.items() if key not in path_keys}
        return path_args, query_args

    def render_path(self, path_args: dict[str, Any]) -> str:
        missing = [key for key in self.path_params if key not in path_args]
        if missing:
            raise ToolValidationError(f"{self.name} 缺少路径参数：{', '.join(missing)}")
        rendered = self.path
        for key, value in path_args.items():
            rendered = rendered.replace("{" + key + "}", str(value))
        return rendered


def _coerce(tool_name: str, param: ToolParameter, value: Any) -> Any:
    expected = _PY_TYPES.get(param.type, (str,))
    if param.type == "boolean":
        if isinstance(value, bool):
            coerced: Any = value
        elif isinstance(value, str) and value.strip().lower() in {"true", "false", "1", "0", "yes", "no"}:
            coerced = value.strip().lower() in {"true", "1", "yes"}
        else:
            raise ToolValidationError(f"{tool_name}.{param.name} 应为布尔值，收到 {value!r}")
    elif isinstance(value, bool) and param.type != "boolean":
        raise ToolValidationError(f"{tool_name}.{param.name} 应为 {param.type}，收到布尔值")
    elif isinstance(value, expected):
        coerced = value
    else:
        try:
            if param.type == "integer":
                coerced = int(str(value).strip())
            elif param.type == "number":
                coerced = float(str(value).strip())
            else:
                coerced = str(value)
        except (TypeError, ValueError) as exc:
            raise ToolValidationError(
                f"{tool_name}.{param.name} 应为 {param.type}，收到 {value!r}"
            ) from exc

    if param.enum and str(coerced) not in param.enum:
        raise ToolValidationError(
            f"{tool_name}.{param.name} 只能取 {', '.join(param.enum)}，收到 {coerced!r}"
        )
    return coerced


# 工具组的中文说明。元工具把它原样报给模型，让模型自己判断该要哪一组。
TOOL_GROUPS: dict[str, str] = {
    "core": "核心：本体概览、设备检索与详情、参数、点位、任意对象的关联信息",
    "analysis": "确定性分析：异常溯源、影响验证、工段关系结构统计（程序按本体通用算法一次给出完整证据链）",
    "structure": "结构与关系：工段、关系清单与详情、关系对象、关系图、测量锚点、因果关系、标准设备组、工段衔接",
    "values": "运行时数据：测点当前值与历史趋势",
    "limits": "工艺限值与越限判断",
    "rules": "生产规则、约束、能力、模型注册",
    "meta": "元数据：本体分类、类与属性、语义绑定、数据来源、数据质量、OWL 规范",
}


# 渐进解锁模式下一开始就下发的组：核心查询 + 确定性分析。
# 分析工具必须首批下发，模型识别到分析类问题时才能直接调用，不用先去工具发现里找。
INITIAL_GROUPS: tuple[str, ...] = ("core", "analysis")


class ToolRegistry:
    """工具注册表。Agent 通过它拿 schema 和 spec，不直接持有工具实现。"""

    def __init__(self, specs: Iterable[ToolSpec] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"工具重名：{spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def require(self, name: str) -> ToolSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise KeyError(name)
        return spec

    def names(self) -> list[str]:
        return list(self._specs)

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for spec in self._specs.values():
            out.setdefault(spec.group, []).append(spec.name)
        return out

    def in_group(self, group: str) -> list[ToolSpec]:
        return [spec for spec in self._specs.values() if spec.group == group]

    def to_openai_schemas(self, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """不传 names 时下发全部工具；传了就只下发这些（渐进解锁用）。"""
        if names is None:
            return [spec.to_openai_schema() for spec in self._specs.values()]
        wanted = [n for n in names if n in self._specs]
        return [self._specs[n].to_openai_schema() for n in wanted]

    def brief(self, names: Iterable[str] | None = None) -> list[dict[str, str]]:
        """一句话清单。元工具用它列可用工具，比完整 schema 便宜得多。"""
        specs = (
            [self._specs[n] for n in names if n in self._specs]
            if names is not None
            else list(self._specs.values())
        )
        return [
            {
                "name": spec.name,
                "group": spec.group,
                "summary": spec.summary or spec.description.split("。")[0] + "。",
            }
            for spec in specs
        ]

    def catalog(self) -> list[dict[str, Any]]:
        """给前端 / 文档用的可读清单。"""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "method": spec.method,
                "endpoint": spec.path,
                "returns": spec.returns,
                "parameters": [
                    {
                        "name": param.name,
                        "type": param.type,
                        "required": param.required,
                        "description": param.description,
                    }
                    for param in spec.parameters
                ],
            }
            for spec in self._specs.values()
        ]

    def __len__(self) -> int:
        return len(self._specs)

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._specs.values())
