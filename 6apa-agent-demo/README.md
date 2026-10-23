# 6-APA 生产车间智能 Agent

自然语言问答 Agent：用户随便问 6-APA 生产车间的事，LLM 自己判断需要什么信息、
自己选工具、自己决定连着查几次，最后基于**真实本体数据**作答。前端实时显示它的执行过程。

```
用户问题 → 读会话上下文 → 调 LLM → 模型要工具？
                                 ├─ 要：执行本体 API → 结果回灌 → 再调 LLM（循环）
                                 └─ 不要：输出最终回答
```

代码里**没有**任何 `if "E-101" in question` 这类分支，也没有为"查设备""查上游""查运行情况"
预设的固定 Workflow。走哪条路完全由模型根据 Tool Schema 自己决定。

---

## 1. 快速开始

### 前置条件

- Python 3.10+
- Node 18+（只有 Vue 前端需要；零依赖演示页不需要）
- **6-APA 本体服务已在运行**（本项目不包含本体系统，只消费它的 REST API）

### Windows（cmd / PowerShell）

`.sh` 是 Linux/macOS 脚本，Windows 请用同名的 `.bat`（双击或在 cmd 里直接输入文件名，**不要加 `./`**）：

```bat
copy .env.example .env
notepad .env                      :: 填 LLM_API_KEY，确认 ONTOLOGY_BASE_URL
pip install -r requirements.txt

run_backend.bat                   :: Agent 服务 8800
run_mock_dcs.bat                  :: 模拟 DCS 服务 8900（可选）
run_frontend.bat                  :: Vue 前端 5174（可选，需要 Node）
run_demo.bat                      :: 一键：本体 8700 + 模拟 DCS + Agent + 演示页，各开一个窗口
```

Windows 上 Python 命令通常是 `python` 而不是 `python3`，文档里的 `python3 -m xxx` 请换成 `python -m xxx`
（`.bat` 会自动选 `python`，没有则用 `py -3`）。
`run_demo.bat` 默认本体服务目录在同级的 `..\6apa-ontology-demo`，不在那里时先 `set ONTOLOGY_HOME=D:\路径\6apa-ontology-demo`。

### Linux / macOS：三步跑起来

```bash
# 1) 配置
cp .env.example .env
#    编辑 .env：填 LLM_API_KEY，确认 ONTOLOGY_BASE_URL 指向你的本体服务

# 2) 装依赖 + 起 Agent 服务（默认 8800）
pip install -r requirements.txt
./run_backend.sh

# 3) 打开界面（二选一）
#    a. 零依赖演示页：浏览器打开 demo/index.html
#    b. Vue 前端：./run_frontend.sh  → http://localhost:5174
```

本体服务、Agent 服务、演示页一起拉起：

```bash
ONTOLOGY_HOME=../6apa-ontology-demo ./run_demo.sh
# → http://localhost:8081/index.html?api=http://localhost:8800
```

命令行验收（不需要前端）：

```bash
python3 -m scripts.cli                        # 多轮交互
python3 -m scripts.cli "水解工段有哪些设备？"   # 单问单答
```

---

## 2. 配置

所有可变项走环境变量 / `.env`，**代码里没有任何密钥和硬编码地址**。

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | `https://api.deepseek.com/v1` |
| `LLM_API_KEY` | 模型 Key（**必填**） | 空 |
| `LLM_MODEL` | 模型名 | `deepseek-chat` |
| `LLM_STREAM` | 是否流式 | `true` |
| `ONTOLOGY_BASE_URL` | 本体服务根地址 | `http://localhost:8700` |
| `MAX_TOOL_CALLS_PER_TURN` | 单轮工具调用上限 | `15` |
| `MAX_TOOL_RESULT_CHARS` | 单次工具返回回灌上限（字符） | `10000` |
| `MAX_HISTORY_MESSAGES` / `MAX_CONTEXT_CHARS` | 上下文裁剪阈值 | `40` / `90000` |
| `AGENT_PORT` / `AGENT_HOST` / `CORS_ORIGINS` | 服务监听与跨域 | `8800` / `0.0.0.0` / `*` |
| `LOG_LEVEL` / `LOG_DIR` | 日志 | `INFO` / `./logs` |

换模型只改 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`。
LLM 客户端只实现 OpenAI 兼容协议，不依赖 DeepSeek SDK，Qwen / Moonshot / vLLM / Ollama 都能直接接。

当前生效配置（不含 Key）可在 `GET /api/health` 查看。

---

## 3. 工程结构

```
backend/
├── config.py              环境变量配置（含极简 .env 读取，不引 python-dotenv）
├── main.py                FastAPI 应用 + SSE；FastAPI 缺失时自动回退 Starlette
├── logging_setup.py       结构化日志 + 密钥打码过滤器
├── llm/
│   ├── base.py            LLMClient 协议、ToolCall、LLMResponse（不承载思维链）
│   └── openai_compatible.py  流式 / 非流式、tool_calls 分片累积、重试
├── tools/
│   ├── registry.py        ToolSpec / ToolRegistry / 参数校验（声明式）
│   ├── ontology_tools.py  30 个本体 API 的 Tool 定义——全项目唯一知道接口长什么样的地方
│   └── executor.py        HTTP 执行、异常分级、超大返回体裁剪
├── agent/
│   ├── runtime.py         Agent Loop（自己写的，无任何 Agent Framework）
│   ├── context.py         会话、当前实体、Tool 历史、按整轮裁剪
│   ├── events.py          执行过程事件定义
│   └── prompt.py          System Prompt 装配
└── prompts/system_prompt.txt   Prompt 与代码分离，改完调 /api/prompt/reload 即可生效

frontend/    Vue3 + TS + Vite + Tailwind + Pinia + Axios + ECharts
demo/        零依赖单文件演示页（无需 npm，内置 SVG 力导向关系图）
mock_dcs/    模拟 DCS 数据服务：实时值 / 历史值（模拟数据，独立进程 8900）
scripts/cli.py               命令行 Agent
tests/verify_tools.py        30 个 Tool 逐个打真实本体 API
tests/test_agent_loop.py     Agent Loop 自测（脚本化假 LLM，无需 Key）
tests/stub_llm_server.py     假 LLM 模式起真实服务，用于无 Key 环境验证前端
tests/test_mock_dcs.py       模拟 DCS 服务自测
```

---

## 4. 核心设计

### 4.1 Tool Registry 与 Agent 解耦

一个工具就是一条 `ToolSpec` 数据记录：

```python
ToolSpec(
    name="query_equipment_detail",
    description="查询指定设备的完整本体信息……equipment_id 必须是 equip-xxxxxxxx 形式……",
    path="/api/ontology/equipment/{equipment_id}",
    parameters=(ToolParameter("equipment_id", "string", "设备 ID……", required=True),),
    entity_capture=EntityCapture(kind="equipment", label="设备", ...),
    heavy=True,
)
```

Registry 负责生成 OpenAI function schema、校验参数、拆分路径参数与查询参数；
Executor 负责发请求。**Agent Runtime 从头到尾不认识任何一个具体工具的名字。**

新增一个本体接口 = 在 `ontology_tools.py` 里加一条记录，其余代码零改动。

### 4.2 当前实体上下文（让"它"能被理解）

`ToolSpec.entity_capture` 声明"这个工具调用成功后，把什么写进当前实体上下文"。
Runtime 只是照着这条声明去取值——它不知道"设备""工段"是什么概念。

每轮对话前，会话上下文以 system 消息注入：

```
【当前会话上下文】
当前设备 → 设备：一层排渣泵（equip-8170434d）
最近的工具调用 → query_equipment_detail(ok) 对象：一层排渣泵；query_tags(ok) 命中 5 条，本次返回 5 条
用户说"它""这个设备""上游""这些"等指代时，通常指向上面列出的对象；若存在歧义，先向用户澄清而不是猜。
```

指代消解由模型完成，我们只负责把候选实体摆出来 + 在界面上把"当前设备"显示出来，方便现场核对。

### 4.3 超大返回体防护（这是真实踩到的坑）

本体里一台设备可能挂 347 个测点，`GET /api/ontology/equipment/{id}` 实测返回 **334 KB**。
直接回灌会把模型上下文打爆。处理方式：

1. **默认分页**：列表类工具在 `ToolSpec.defaults` 里声明默认 `limit`，模型不给就自动补上；
2. **逐级裁剪**：超预算时按"每个数组最多保留 N 条"逐级收紧（80 → 60 → … → 1），直到落进预算；
3. **如实告知**：裁剪结果附 `truncationNote`，说明省了多少条、怎么分页拿全，
   并且 `total` 字段原样保留——模型永远知道真实总数是多少，不会把样本当全部；
4. System Prompt 里明确要求：看到 `truncationNote` 必须继续查或声明这是基于样本的观察。

实测：334 KB → 5,974 字符，`total` 保留，模型收到明确的裁剪说明。

### 4.4 异常处理

Executor 区分 `validation / not_found / bad_request / server_error / timeout / network / invalid_json / unknown_tool`，
每种都转成结构化的 `{ok:false, error, errorKind, hint}` 回灌给模型，Agent 不崩溃。
典型场景：模型把设备中文名当 ID 传 → 404 → hint 告诉它"先用列表工具检索 ID" → 模型自己改路。

### 4.5 禁止输出思维链

`LLMResponse` 结构体里**没有**承载思维链的字段；客户端在流式与非流式两条路径上都会丢弃
`reasoning_content` / `reasoning` / `thinking`。前端只显示可观察的外部动作：
调了哪个工具、参数是什么、HTTP 状态、耗时、返回了多少条。

---

## 5. Agent 服务接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 服务状态、工具数、本体连通性、生效配置（不含 Key） |
| GET | `/api/tools` | 工具清单（前端工具面板的数据源） |
| POST | `/api/chat` | **一轮对话，SSE 流式返回执行过程与最终回答** |
| GET | `/api/conversations` | 会话列表 |
| GET | `/api/conversations/{id}` | 会话详情（含当前实体、Tool 历史） |
| DELETE | `/api/conversations/{id}` | 删除会话 |
| POST | `/api/prompt/reload` | 热加载 System Prompt，无需重启 |
| GET | `/api/examples` | 内置示例问题（含工艺调查案例），前端渲染成可点击的问题 |
| POST | `/api/examples/reload` | 热加载示例问题文件，无需重启 |

`POST /api/chat` 请求体：`{"message": "……", "conversationId": "可选"}`

SSE 事件：

| 事件 | 含义 |
| --- | --- |
| `turn_start` | 本轮开始，带 conversationId / turn |
| `status` | 可读执行状态（"理解用户问题""综合已获取的本体数据"） |
| `tool_call` | 模型决定调某个工具，带参数 |
| `tool_result` | 工具返回：状态、HTTP 码、耗时、原始字节数、结果摘要、裁剪说明 |
| `graph` | 工具返回了 nodes/edges，可渲染关系图 |
| `answer_delta` | 最终回答的流式片段 |
| `answer_reset` | 刚才流出的文字其实是执行说明，不是回答，前端清空缓冲 |
| `answer` | 最终回答全文 |
| `context` | 当前会话上下文（当前设备/工段/实体/Tool 历史） |
| `error` | 本轮出错 |
| `done` | 本轮结束：模型调用轮数、工具调用次数、总耗时 |

> `/api/chat` 是 POST + SSE，浏览器原生 `EventSource` 只支持 GET，
> 因此两个前端都用 `fetch` + `ReadableStream` 手工解析 SSE 帧。

---

## 6. 已封装的本体工具（30 个）

| 工具 | 本体接口 |
| --- | --- |
| `query_ontology_overview` | `/api/ontology/overview` |
| `query_process_areas` / `query_process_area_detail` | `/process-areas`、`/process-areas/{id}` |
| `query_equipment_list` / `query_equipment_detail` | `/equipment`、`/equipment/{id}` |
| `query_parameters` / `query_parameter_detail` | `/parameters`、`/parameters/{id}` |
| `query_tags` | `/tags` |
| `query_ontology_categories` / `query_ontology_classes` / `query_ontology_properties` | `/categories`、`/classes`、`/properties` |
| `query_relations` / `query_relation_detail` / `query_relation_entities` | `/relations`、`/relations/{id}`、`/relation-entities` |
| `query_ontology_graph` | `/graph` |
| `query_object_relations` | `/{objectId}/relations` |
| `query_rules` / `query_capabilities` / `query_constraints` / `query_model_registry` | `/rules`、`/capabilities`、`/constraints`、`/model-registry` |
| `query_semantics` / `query_measurement_anchors` / `query_causal_relations` | `/semantics`、`/measurement-anchors`、`/causal-relations` |
| `query_data_sources` / `query_data_quality` | `/data-sources`、`/data-quality` |
| `query_realtime_values` / `query_history_values` | `/{objectId}/realtime`、`/{objectId}/history`（需本体服务加装实时历史接口补丁） |
| `query_process_limits` / `query_object_limits` / `query_limit_check` | `/process-limits`、`/{objectId}/limits`、`/{objectId}/limit-check`（需本体服务加装工艺限值补丁） |

需求文档列的 19 个接口全部覆盖；另外 6 个（工段详情、参数详情、关系对象、模型注册、数据来源、数据质量）
是本体服务实际提供、且对开放式提问明显有用的接口，一并封装。
`/api/ontology/turtle` 故意没有封装——它一次返回整份 RDF，对模型上下文是净损害。

**参数名严格对齐本体服务真实的 query 参数**（如设备列表是 `sn`/`processArea`/`areaId`/`keyword`/`limit`/`offset`），
不是按文档猜的，已逐个打真实接口核对过。

---

## 7. ID 约定（现场最容易踩的坑）

本体对象用带前缀的 ID：`area-` 工段、`equip-` 设备、`param-` 参数、`tag-` DCS 点、
`robj-` 关系对象、`relation-` 关系。

**详情类接口只接受 ID，传中文名会 404。** 所以"介绍一下一层排渣泵"的正确路径是：

```
query_equipment_list(keyword="一层排渣泵")  →  equip-8170434d
       ↓
query_equipment_detail(equipment_id="equip-8170434d")
```

这条约定写在 System Prompt 和每个工具的 description 里，由模型自己遵守——
代码里没有"名称转 ID"的硬编码兜底。
`query_object_relations` 额外接受 `:Dev_10_一层排渣泵` 这样的 OWL Subject。

---

## 8. 日志

`logs/agent.log` 运行日志；`logs/turns.jsonl` 每轮一行结构化轨迹：

```json
{"conversation_id":"...","user_message":"...","tools":[{"tool_name":"query_equipment_list",
"tool_arguments":{...},"tool_result_summary":"命中 4 条，本次返回 4 条","execution_time_ms":6,
"status":"ok","error":null}],"final_answer":"...","elapsed_ms":8421,"tool_calls":3}
```

API Key 不写日志。除此之外还挂了一道 `SecretRedactingFilter`：
任何日志里出现 `Bearer xxx` / `sk-xxx` / `api_key=xxx` 都会被打码，防止将来有人不小心把 headers 丢进日志。

---

## 9. 自测

```bash
# 25 个 Tool 逐个打真实本体 API（不需要 LLM Key）
ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.verify_tools

# Agent Loop 自测：多步调用 / 结果回灌 / 实体上下文 / 工具预算 / 异常 / 裁剪 / 历史裁剪
ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.test_agent_loop

# 示例问题与工艺调查案例：文件结构 + 案例在本体里查得通
ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.test_examples

# 无 Key 环境下验证前端与 SSE（用假 LLM 起真实服务）
ONTOLOGY_BASE_URL=http://localhost:8700 python3 -m tests.stub_llm_server
```

验收测试清单见 `docs/验收测试.md`，内置案例说明见 `docs/工艺调查案例.md`。

---

## 9.1 内置工艺调查案例

打开对话页就能看到 23 条示例问题，分 5 组：工艺调查（异常溯源，6 条）、pH 与质量指标、
设备与开关量、工艺调查缺口、本体基础问答。点一下把问题填进输入框，比如
「昨天水解罐温度异常，帮我调查一下原因」。

案例数据在 `backend/data/examples.json`，是**纯数据**：点击只做填充输入框这一件事，
Agent 收到的和手敲进去完全一样，工具选哪个、调几次全部由模型自己规划——
没有任何针对具体问题的流程分支。案例里的 `referenceToolChain` 只给演示和验收对照用，
不下发给模型。

调查型问题的通用做法写在 `backend/prompts/system_prompt.txt` 的
「工艺调查类问题的通用做法」一节，同样是通用方法，不绑定具体设备或参数：
先确认异常成不成立（限值 + 历史值），再沿本体因果关系找候选原因，把原因落到测点，
取同一时间窗的历史值比时间/方向/幅度，最后分三层给结论并列出数据缺口。

每条案例的考察点、本体里实际能查到什么、什么样的回答算合格，见 `docs/工艺调查案例.md`。

---

## 9.2 换本地模型（千问 32B 等）

代码不用改，`.env` 里改两处：

```bash
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_API_KEY=EMPTY
LLM_MODEL=Qwen3-32B
LLM_PROFILE=local32k          # ← 关键：切到本地 32k 上下文的预算档位
```

**为什么必须切档位。** 34 个工具的完整 schema 每次请求约 9,200 token，
加系统提示 2,700，固定开销就 11,800——32k 上下文直接去掉三分之一，
工艺调查这类要连查七八次的问题会在中途撑爆。`local32k` 档做三件事：

| | cloud | local32k |
| --- | --- | --- |
| 首轮下发工具 | 34 个（9,200 token） | 10 个核心（3,600 token） |
| 单轮工具次数 | 15 | 8 |
| 单次返回体 | 10,000 字符 | 4,000 字符 |
| 上下文上限 | 90,000 字符 | 20,000 字符 |
| 关系查询 | 完整视图 | 精简视图（1/6 大小） |

固定开销从 11,800 降到 6,300 token。

**工具不是被砍掉了，是按需取用。** 模型手上只有核心工具时，调用
`list_available_tools` 就能看到还有哪些组（结构 / 运行时值 / 限值 / 规则 / 元数据），
按组或关键词取用，**取到的工具当轮立即可调**。分组是按能力类别划的静态属性，
与具体问题无关——不构成"针对具体问题写死流程"。模型若凭记忆直接调了一个
尚未下发的工具且调成功了，该工具也会自动补进名单，后续它就能看到参数说明。

**单轮内的兜底。** 历史可以按整轮丢，但**当前轮**丢不了。所以当本轮工具结果
把预算撑满时，最早的几条会被压成 400 字的摘要（消息本身保留，不破坏
assistant/tool 配对），并在上下文块里明确告诉模型"这几条被压缩了，需要细节请重新查"。

**vLLM 两个必须做的配置：**

```bash
vllm serve Qwen3-32B --enable-auto-tool-choice --tool-call-parser hermes
```

不开工具解析，模型会把工具调用当普通文本吐出来，`tool_calls` 永远是空的——
不是效果差，是根本不工作。另外千问 3 开着 thinking 时，思维链可能**内联在
`content` 里**（`<think>…</think>`），需求文档禁止展示思维链，本 Demo 已经会
自动剥掉这类标签（流式下跨分片的半截标签也能处理），但更省 token 的做法是直接关掉。

---

## 9.3 效果评测：换模型前后拿数据说话

```bash
# 跑当前 .env 配置的模型
python3 -m tests.eval_agent --tag deepseek

# 换本地模型再跑一遍
LLM_PROFILE=local32k LLM_BASE_URL=http://127.0.0.1:8000/v1 LLM_MODEL=Qwen3-32B \
    python3 -m tests.eval_agent --tag qwen32b

# 对比
python3 -m tests.eval_agent --compare deepseek qwen32b
```

跑的就是内置的 23 条案例，打分项都是**可机检的硬约束**，不做主观质量评价：

| 项 | 判据 |
| --- | --- |
| 完成 | 有最终答案，且没在工具预算内跑飞 |
| 用工具 | 至少调了一次工具（纯靠模型知识作答不算） |
| 不编阈值 | 回答里出现数值范围时，必须引用 PL 编号或调用过限值类工具 |
| 声明模拟 | 调用过实时值/历史值后，回答里必须出现"模拟" |
| 报缺口 | 案例期望标了"没有测点"的，回答里要提到 |
| 无思维链 | 回答里不得出现 `<think>` 这类标签 |

输出还带平均工具调用次数、工具报错率、平均耗时、跑飞条数——
本地模型的问题通常先体现在"工具报错率"和"跑飞条数"上，而不是总分。

`--compare` 会列出两次跑分不同的具体案例，方便直接去看是哪一步走岔了。
`--stub` 用假 LLM 走一遍流程，用来自检评测脚本本身（不代表模型效果）。

---

## 10. 已知限制

1. **真实 DeepSeek 调用未在开发环境验证过**——开发环境出口策略拦截了 `api.deepseek.com`（403）。
   已验证的是：25 个 Tool 对真实本体 API 的契约、Agent Loop 的全部控制流（用脚本化假 LLM）、
   SSE 事件流、两个前端的渲染。模型的实际选工具质量需要你填 Key 后现场跑一遍。
2. **Vue 前端未构建验证**——同样的出口策略拦掉了 npm registry（403），无法 `npm install`。
   `frontend/` 是经审阅的源码；`demo/` 零依赖演示页已在 Chromium 里逐项验证过交互。
   两者功能等价，演示可以直接用 `demo/`。
3. 会话存在进程内存里，重启即清空。要持久化，替换 `ConversationStore` 即可，Agent 不感知。
4. 上下文压缩是"按整轮丢弃最早对话"，没有做摘要式压缩。第一版够用，也最不容易出错
   （OpenAI 协议要求 `tool` 消息必须紧跟对应的 `assistant` 消息，从中间切会直接 400）。
5. 关系图：Vue 版用 ECharts graph，与本体服务前端保持同一套视觉；
   `demo/` 版用内置 SVG 力导向（保持零依赖）。需求文档提的是 G6 / Cytoscape，
   替换只需改 `GraphModal.vue` 一个文件，其余代码不受影响。

---

## 11. 模拟 DCS 数据服务（实时值 / 历史值）

> ⚠️ 返回的是**模拟数据**：按每个测点的量纲和工艺位置生成合理数值，不是现场真实读数。

独立进程，端口 8900，与本体服务、Agent 服务互不依赖：

```bash
./run_mock_dcs.sh      # 或 python3 -m mock_dcs.main
```

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/hsm-db-rtserver/v1/rtdata/node/read` | 实时值，格式与现场实时库接口示例一致 |
| POST | `/api/timing-svc/v1/history/findAll` | 历史值，**暂定格式**，待拿到真实时序库示例后对齐 |

nodeId 约定 `{控制站号}:{位号}.PV`（如 `10:PT_1003.PV`），与本体点表一一对应。
数值按单位 / 描述 / 位号推断量纲与合理范围（如水解 pH 7.7~8.1、结晶温度 2~12 ℃），
同一设备的相关测点互相一致（开关反馈互补、停机时电流归零、阀位反馈跟随给定），
实时与历史出自同一条确定性曲线，查多少次都对得上。

本体服务已通过 `/api/ontology/{对象ID}/realtime`、`/history` 把它对外暴露（本体做语义网关，本服务充当实时库 / 历史库）。
Agent 通过 `query_realtime_values` / `query_history_values` 两个工具经本体查值（不直连本服务）；每轮对话会注入【当前时间】，供模型换算“过去一小时”等相对时间；数据源为模拟服务时，System Prompt 要求回答中明确说明。完整说明见 `docs/模拟DCS接口.md`，自测：

```bash
MOCK_DCS_URL=http://localhost:8900 python3 -m tests.test_mock_dcs   # 34 / 34
```
