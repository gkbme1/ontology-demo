# 6-APA 生产线工业本体 Demo

把现场 **DCS 点表 Excel** 与 **工业关系 Excel** 统一加载为工业本体实例与关系数据，
通过 REST API 对外提供访问，并在前端以工业本体的方式展示。

本仓库中**没有任何 Mock 设备、Mock DCS 点或硬编码关系**，页面上的每一个数字、
每一台设备、每一条关系都能追溯到 `data/source/` 下的某个 Excel 文件的某一行。

---

## 一、当前数据规模

来自 `data/source/6APA_DCS.xlsx` 与 `data/source/6APA_工业关系.xlsx` 的实际统计：

| 项目 | 数量 |
| --- | --- |
| 生产工段 | **24**（流程图工艺口径 S01–S23 + S99 备用） |
| 控制站 | 14（已降级为设备属性，不再作为工段划分依据） |
| 标准设备组 | **120** |
| 设备 / 装置 | **1,222**（点表原有 1,340 种设备写法，按设备归并表合并 118 种，见下文；46 台的点位跨多个工段） |
| 参数语义 | 10,336（归并时同一设备上的同名参数合并） |
| DCS 点位 | 10,680 |
| 工业关系 | **2,252**（含 622 条测点绑定、40 条工段衔接、15 条报警联锁） |
| 关系对象 | **1,174**（已匹配本体实例 619，未匹配 555） |
| 测量锚点 | **974** |
| 工段衔接 | **40** 条（带衔接物料与位号） |
| 工艺限值 | 68 条（18 条带数值，均为「待现场确认」） |
| 推理规则 | **71** 条（其中 37 条阈值引用限值表「见 PLxxx」） |

DCS 点位构成：PV 2,309、OP 701、MOT 528、VAL 1,228、DI/DO 5,914。

### 设备名称统一（设备归并表）

DCS 点表按位号描述里的设备名前缀切设备，同一台设备常被写成好几种名字。例如水解罐A：
搅拌、温度写作「水解罐A…」，硼酸/氨水进料阀写作「A罐…」，RB 进料阀写作「A罐RB…」，
两支 pH 电极写作「水解罐A1/A2」，液位点挂在 20 站的「水解罐A」下——加载后成了 6 台设备。

`data/source/6APA_设备归并.xlsx` 把这些写法归并成一台、统一名称，本体服务加载 DCS 点表时自动按表合并，
**DCS Excel 本身不改**。合并后水解罐A 一台设备带 17 个点（控制站 13、20），两支 pH 电极合为一个 pH 参数。

- 表由 `python3 -m backend.tools.build_equipment_merge` 按规则生成（已存在时不覆盖，`--force` 按规则重建），
  规则限定在同一标准设备组内：本名 / 同名异写（配置·配制）/ 简称（A罐→水解罐A）/ 冗余后缀（浓硫酸储罐A罐）/
  省略设备位号（水洗离心机X2141A→水洗离心机A）/ 附属点位（水解罐A1、A罐RB、…泵GZ/YC/YX、…PH）/ 同名跨站（须同工段）。
  「公用测量管线」「其他工艺单元」「管网阀门系统」不参与。当前 120 行：同一设备 55、附属点位 63、只改名 2。
- 表可直接编辑：「启用」改成 否 即不归并；也可以照格式手工追加行（例如结晶罐A1–A14 与 R112–R125 的对应，
  规则推不出来，需要人工补）。
- 旧的设备 ID、OWL Subject、名称都登记为别名：`/api/ontology/equipment/{旧ID}`、`:Dev_13_A罐`、
  按名称「A罐」都能查到合并后的水解罐A；点位上保留 `sourceEquipmentName` 原写法。
- 资产本体页的设备档案头部列出已归并的写法；继承自设备组的工艺属性只带本台设备自己的位号。

### 工段口径（v2 起的重要变化）

旧版的「生产工段名称 (Process Area)」实际是按 **DCS 控制站** 划分的，一个控制站里
混着多个工艺工段——站 13 同时含 S10 水解辅料配制、S11 酶法水解、S12 萃取与反萃、S15 结晶辅料。
v2 改用流程图口径的「工段编号(流程图口径)」+「工艺工段(流程图口径)」，点表、关系表、
限值表、规则表、对象映射全部对齐到它。

- 工段 ID 形如 `area-S01`；凡接受 `areaId` 的接口，`area-S11` / `S11` / `酶法水解` 三种写法等价。
- 控制站与工段是多对多：S11 跨站 13 与 20，站 13 的点位分到 5 个工段。
- **设备可以跨工段**：`areaId` / `areaCode` 是主工段（取自设备统计表的声明），
  `areaCodes` / `areaSpan` 是它的点位实际覆盖的全部工段；按 `areaId` 过滤时按任一命中。

---

## 二、四类数据源，职责严格分离

| sourceType | 文件 | 回答什么问题 |
| --- | --- | --- |
| `DCS_EXCEL` | `6APA_DCS.xlsx` | 现场有哪些工段、设备、参数、DCS 点 |
| `RELATION_EXCEL` | `6APA_工业关系.xlsx` | 这些对象之间是什么关系，工艺机理是什么 |
| `MAPPING_FILE` | `6APA_对象映射.xlsx` | 工艺抽象名称与现场位号名称如何对齐 |
| `RULE_FILE` | `6APA_规则.xlsx`（待提供） | 满足什么条件可以得出什么结论 |

每个 API 返回体都带 `sourceType` 与 `source`（文件 / Sheet / 行号 / 原始字段 / 原始值），
前端「数据来源」面板直接展示这些字段。

### 关于对象映射表

关系 Excel 使用工艺抽象名称（水解反应釜、水洗碟片离心机组、釜内反应温度），
DCS 点表使用现场位号命名（水解罐A、离心机B1、温度）。两者**精确匹配数为 0**。

按需求文档 9.3 节，系统禁止模糊自动匹配。因此仓库提供
`data/source/6APA_对象映射.xlsx`（123 行），由工艺语义人工编制并在生成时
逐行校验目标对象确实存在于 DCS 点表中。

> ⚠️ **这一版映射是推断结果，全部标记为「待现场确认」，需要现场工艺人员逐条核对后
> 才能作为正式对齐依据。** 置信度分「高 / 中 / 低」三档，低置信度条目在「映射说明」
> 列写明了替代测点的理由（例如：现场无冷盐水流量计，暂以调节阀开度反馈作为间接锚点）。

映射示例：

```
水解反应釜      → :Dev_13_水解罐A … :Dev_13_水解罐K   （11 台并联酶法水解罐，置信度 高）
釜内反应温度    → 水解罐A 温度 → TI_1301A（AI，℃）    （置信度 高）
反应体系pH      → 水解罐A1 pH → AT_1301A1（AI，ph）   （置信度 高）
换热器冷盐水流量 → 水解液缓冲罐 去萃取换热器冷盐水调节阀a反馈（置信度 低，替代测点）
```

未匹配的 47 个关系对象（物料流股、控制仪表、质量指标、业务指标等）保留为
**外部关系对象**，界面上标记「未匹配DCS实例」，关系数据不会被丢弃。

### 关于规则数据源

需求文档第十三、二十四章规定：规则必须来自独立规则 Excel / 规则文件，
**禁止根据参数名称或关系谓词自动生成生产判断规则**。

现场已提供 `data/source/6APA_规则.xlsx`，当前加载 71 条：

- 分层：通用层 12 条（R-G-xx，设备启停/阀位/冗余仪表这类与工艺无关的），其余按工段编号分组（R-S11-xx 等）；
- 阈值不写死：37 条规则的阈值写成「见 PLxxx」，直接引用工艺限值表，接口返回里用 `limitRefs` 给出；
- 说明以「【草案·待现场确认】」开头的条目尚未经现场确认，接口用 `draft: true` 标出，引用时必须说明。

规则文件缺失时仍退回空状态（`total: 0` + `emptyReason`），**任何情况下都不会从参数名称自动生成规则**。
约束、能力、模型注册三类目前仍无数据源，显示空状态，不使用 Mock。

---

## 三、目录结构

```
6apa-ontology-demo/
├── backend/                     本体服务（Python + FastAPI）
│   ├── api/routes.py            REST 路由表（框架无关声明）
│   ├── api/asset_routes.py      资产本体视图接口（导航树 / 搜索 / 对象本体档案）
│   ├── ontology/
│   │   ├── models.py            12 分类 / 9 核心内容 / 节点边样式（可配置）
│   │   ├── identifiers.py       稳定 ID 生成
│   │   └── indexes.py           内存索引层（可替换为 PG / Neo4j / Jena）
│   ├── services/
│   │   ├── dcs_loader.py            DCS 点表导入
│   │   ├── relation_excel_loader.py 工业关系导入
│   │   ├── mapping_loader.py        对象映射导入
│   │   ├── rule_loader.py           规则导入
│   │   ├── object_matcher.py        三级对象匹配
│   │   ├── graph_builder.py         局部语义图构建
│   │   ├── asset_model.py           资产本体视图：本体域分类树 + 对象本体档案（属性/关系/能力/约束/规则）
│   │   ├── equipment_merge.py       设备名称统一：归并规则 + 加载时按设备归并表合并
│   │   └── data_quality.py          数据一致性检查
│   ├── tools/                   映射表 / 规则模板 / 离线演示构建脚本
│   ├── export_static.py         导出静态 API 快照
│   └── main.py                  FastAPI 入口（含 Starlette 回退）
│
├── frontend/                    Vue 3 + TypeScript + Vite + Tailwind + ECharts
│   └── src/{api,components,views,composables,router}
│
├── demo/                        离线演示（零依赖，双击即开）
│   ├── index.html               构建产物
│   ├── src/                     演示页源码（api / graph / app）
│   └── data/                    API 快照数据包
│
└── data/
    ├── source/                  现场 Excel 与模板
    └── snapshot/                导出的静态 API 快照
```

---

## 四、运行方式

### 方式 A：离线演示（无需任何环境）

直接用浏览器打开 `demo/index.html`。

页面通过前端 API 适配层读取 `demo/data/*.js` 中的 API 快照，
数据契约与真实 REST 接口完全一致，页面代码路径也完全一致。

### 方式 B：本体服务 + Vue 前端

```bash
# 后端（默认端口 8700）
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8700
# 校验：curl http://localhost:8700/api/ontology/overview

# 前端
cd frontend
npm install
npm run dev        # http://localhost:5173，/api 已代理到 8700 端口
```

也可以直接用脚本：`run_service.bat`（后端）+ `run_frontend.bat`（前端，首次自动 `npm install`，
起来后自动打开浏览器）；Linux / macOS 用 `bash run_frontend.sh`。
Agent 目录下的 `run_demo.bat` / `run_demo.sh` 一键启动时也会拉起本前端（5173）。

> `package-lock.json` 里的下载地址是 npmmirror 镜像。所在网络访问不了时，
> 改用 `npm install --registry=https://registry.npmjs.org/`。

打开 http://localhost:5173 默认进入 **资产本体** 页（见下节），原来的本体总览、工段与设备、
关系图谱、关系清单、数据治理等页面都还在，从顶栏「本体总览」进入。

### 资产本体页：导航树 + 对象本体

左侧是资产导航树，按本体域分类，每个域再按各自的层级展开，可以一路点到具体设备；
顶部搜索框支持设备名、DCS 位号、工段编号、工艺量名称，命中后自动展开到该对象。

| 本体域 | 层级 |
|---|---|
| 空间与层级 | 工段 → 设备组 / 设备 |
| 工业资产 | 设备大类 → 设备类型 → 标准设备组 → 设备（未入组设备按名称归到大类下的「未入组设备」） |
| 工艺 / 物料与产品 / 质量 / 生产业务与经营指标 / 安全与风险 | 对象类型 → 工段 → 工业关系中的对象 |
| 自动化与控制 | 控制站 → 设备；控制系统 / 仪表 / 执行机构 |
| 组织与人员、设备维护与可靠性、能源、环保、成本与经营 | 暂无数据源，显示为 0 |

选中对象后右侧是它的本体档案，按下面的定义组织（关联不单列，直接体现在属性里）：

| 部分 | 内容 | 数据来源 |
|---|---|---|
| 类与层级 | 类名、父类路径、编码、工段、控制站、出处 | DCS 点表 / 工业关系 |
| 属性 | 固有属性（编码、类型、所属…）、工艺属性、测量 / 状态 / 控制参数；每个属性直接带出关联的 DCS 位号 | DCS 点表 + 对象映射 + 工业关系 |
| 关系 | 类间关系（所属、上下游、部件、实例、控制、报警联锁）与属性间关系（计算 / 传递 / 关联） | 工业关系 + DCS 层级 |
| 能力 | 数据·时序、诊断、分析、动作、模型等挂载点，状态为 已挂载 / 具备挂载点 / 未挂载；只按对象已有点位与本体内置接口判断，不虚构 | 本体内置接口 + 点位类型 |
| 约束 | 结构约束（加载器校验结果）、运行约束（工艺限值）、安全约束（报警联锁关系） | 工艺限值 + 工业关系 |
| 规则 | 适用的推理规则（专属 / 同工段 / 通用层） | 规则表 |

地址栏 `?id=` 记录当前对象，可以直接分享或刷新恢复，例如 `http://localhost:5173/?id=area-S11`。

离线演示页也可以切换到实时后端：打开
`demo/index.html?api=http://localhost:8700` 即可。

### 改端口

端口都是环境变量可配的，不需要改代码：

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `ONTOLOGY_PORT` | 本体服务监听端口 | `8700` |
| `ONTOLOGY_HOST` | 本体服务监听地址 | `0.0.0.0` |
| `VITE_API_PROXY` | 前端开发期 `/api` 代理目标 | `http://localhost:8700` |
| `VITE_DEV_PORT` | 前端开发服务器端口 | `5173` |
| `VITE_API_BASE` | 前端直连的 API 根地址（留空则走代理） | 空 |

```bash
# 后端换到 9100
ONTOLOGY_PORT=9100 python3 -m backend.main
# 或者
uvicorn backend.main:app --reload --port 9100

# 前端跟着改：把 frontend/.env.example 复制成 frontend/.env 后改这一行
VITE_API_PROXY=http://localhost:9100
```

用 `uvicorn --port` 指定时以命令行为准；`python3 -m backend.main` 走 `ONTOLOGY_PORT`。
当前端口可在 `GET /api/health` 的返回体中确认。

### 重建演示数据

修改 `data/source/` 下的 Excel 之后：

```bash
./run_demo.sh
```

会重新生成对象映射表、规则模板、API 快照与 `demo/index.html`。

---

## 五、REST API

全部 36 个只读接口（含 5 个实时值 / 历史值接口、4 个工艺限值接口、v2 新增的 4 个），
前端不允许绕过 API 直接读取数据文件。

```
GET /api/ontology/asset-tree?parent=            资产导航树：不带 parent 返回本体域，带上返回该节点的子节点
GET /api/ontology/asset-tree/search             资产搜索 ?keyword= ?limit=，结果带逐级展开路径
GET /api/ontology/asset-profile/{id}            对象本体档案（属性 / 关系 / 能力 / 约束 / 规则）
                                                id 可传设备、设备组、工艺对象、工段、位号或 OWL Subject
GET /api/ontology/overview                      本体概览（全部统计值动态计算）
GET /api/ontology/categories                    12 个本体分类 + 9 项核心内容 + 图样式
GET /api/ontology/process-areas                 工段列表（24 个，按编号排序）
GET /api/ontology/process-areas/{id}            工段详情（设备 + 设备组 + 上下游衔接 + 关系概览）
                                                id 可传 area-S11 / S11 / 酶法水解
GET /api/ontology/process-areas/{id}/flow       单个工段的上下游衔接            ← v2 新增
GET /api/ontology/area-flow                     全流程工段衔接（40 条）         ← v2 新增
GET /api/ontology/equipment-groups              标准设备组（120 个）            ← v2 新增
                                                ?areaId= ?equipmentType= ?keyword=
GET /api/ontology/equipment-groups/{id}         设备组详情（实例 / 部件 / 关联点位）← v2 新增
GET /api/ontology/equipment                     设备列表   ?sn= ?areaId= ?keyword= ?groupId=
GET /api/ontology/equipment/{id}                设备详情（参数 / DCS点 / 关系 / 规则 / 来源）
GET /api/ontology/parameters                    参数语义   ?equipmentId= ?category=
GET /api/ontology/parameters/{id}               参数详情（含测量锚点）
GET /api/ontology/tags                          DCS 点     ?equipmentId= ?type= ?blockType=
                                                           ?areaId= ?variableCategory= ?confidence= ?groupId=
GET /api/ontology/classes                       类
GET /api/ontology/properties                    属性
GET /api/ontology/relations                     关系 ?area= ?category= ?subjectType= ?objectType=
                                                     ?predicate= ?scenario= ?minWeight= ?maxWeight= ?matched=
                                                     ?entityId= ?keyword= ?limit= ?offset=
                                                     ?view=compact（精简视图，遍历因果链时用）
GET /api/ontology/relations/{id}                关系详情（含稳定键与行号）
GET /api/ontology/relation-entities             关系对象（1174 个，含匹配状态）
                                                ?type= ?areaId= ?keyword= ?matched= ?limit= ?offset=
GET /api/ontology/relation-entities/{id}        关系对象详情（匹配实例 + 测量锚点）
GET /api/ontology/graph                         关系图数据 ?rootId= ?depth=1..3 ?includeDcs= + 全部关系筛选参数
GET /api/ontology/rules                         规则（71 条）?area= ?appliesToType= ?severity= ?keyword=
GET /api/ontology/capabilities                  能力
GET /api/ontology/constraints                   约束
GET /api/ontology/model-registry                模型注册
GET /api/ontology/semantics                     语义（DCS 描述 → 参数语义 → 工业对象）
GET /api/ontology/measurement-anchors           测量锚点（含无锚点对象清单）
GET /api/ontology/causal-relations              因果 / 影响 / 质量关系
GET /api/ontology/{id}/relations                通用对象关系查询（支持 OWL Subject URI）
GET /api/ontology/data-sources                  数据源管理
GET /api/ontology/data-quality                  数据质量报告
GET /api/ontology/turtle                        OWL / Turtle 三元组规范（来自关系 Excel）

GET /api/ontology/{id}/realtime                 对象实时值（设备 / 参数 / DCS点 / 关系对象 / 工段）
GET /api/ontology/{id}/history                  对象历史值 ?startTime= ?endTime= ?interval= ?sampleMode=
GET /api/ontology/realtime                      实时值集合查询 ?tagIds= ?equipmentId= ?parameterId= ?areaId= ?keyword=
GET /api/ontology/history                       历史值集合查询（选点参数同上 + 时间参数）
GET /api/ontology/timeseries/status             实时库 / 历史库连接状态
```

对象关系查询支持直接用 OWL Subject URI：

```bash
curl 'http://localhost:8700/api/ontology/:Dev_13_水解罐A/relations'
```


### 实时值 / 历史值

本体**不存储、不生成**任何实时值或历史值。它的角色是语义网关：

```
本体对象 (equip- / param- / tag- / robj- / area- / :Dev_…)
   → 解析出 DCS 点（关系对象经人工映射表）
   → 按 RTDB_NODE_ID_TEMPLATE 拼 nodeId，默认 {station}:{name}.PV，如 10:P_PZ_DO.PV
   → 调外部实时库 / 历史库
   → 值 + 本体语义（设备、参数、现场描述、单位、工段）一起返回
```

```bash
curl 'http://localhost:8700/api/ontology/equip-8170434d/realtime'
curl 'http://localhost:8700/api/ontology/:Dev_10_一层排渣泵/realtime'
curl 'http://localhost:8700/api/ontology/param-5fc7af33/history?startTime=2026-09-22%2008:00:00&interval=600000'
curl 'http://localhost:8700/api/ontology/equip-8170434d/history?startTime=2026-09-22&sampleMode=raw&keyword=启停'
```

| 参数 | 说明 |
| --- | --- |
| `type` / `blockType` / `keyword` | 在对象下再筛点（如 `type=过程测量(PV)`） |
| `limit` / `offset` | 点的分页，默认 50，上限 `RTDB_MAX_TAGS`（200）；备用点排在最后 |
| `startTime` / `endTime` | 毫秒时间戳或 `yyyy-MM-dd HH:mm:ss`（东八区）；`endTime` 默认当前 |
| `interval` | 采样间隔（毫秒）；不填由历史库自动选 |
| `sampleMode` | `interpolated`（默认）/ `avg` / `max` / `min` / `raw`（开关量只返回变位点） |
| `maxPoints` | 每个点最多样本数，透传给历史库 |

实时值返回每个点的 `value / quality / qualityLabel / timestamp / timeText`；历史值返回 `values[{t,q,v}]` 并附 `stats`（min/max/avg/first/last）。
每个响应都带 `dataSource`（实时库或历史库地址）；上游 `/api/health` 声明自己是模拟服务时，还会带 `simulated: true` 和明确提示。
关系对象经映射查点时，`notes` 会写明"映射条目待现场确认"；未匹配 DCS 实例的关系对象返回空并说明原因。

错误：对象不存在 404；参数错误 400；集合接口不带任何选点条件 400（防止一次查全厂 1 万多个点）；实时库 / 历史库不可达或返回错误 502。
实时库挂掉只影响这 5 个接口，本体其余接口照常。

上游地址全部走环境变量，接真实实时库 / 时序库只改配置：

| 变量 | 默认 |
| --- | --- |
| `RTDB_BASE_URL` | `http://localhost:8900`（模拟 DCS 服务） |
| `RTDB_REALTIME_PATH` | `/api/hsm-db-rtserver/v1/rtdata/node/read` |
| `HISTORIAN_BASE_URL` | 同 `RTDB_BASE_URL` |
| `HISTORIAN_PATH` | `/api/timing-svc/v1/history/findAll` |
| `RTDB_NODE_ID_TEMPLATE` | `{station}:{name}.PV` |
| `RTDB_TIMEOUT` / `RTDB_MAX_TAGS` / `RTDB_TZ_OFFSET` | `15` / `200` / `8` |

Windows：`set RTDB_BASE_URL=http://10.0.0.5:9000` 后再启动；Linux：`RTDB_BASE_URL=… uvicorn …`。
实现集中在两个新文件：`backend/services/timeseries.py`（选点、拼 nodeId、调上游、拼语义）与
`backend/api/timeseries_routes.py`（5 个路由）；`backend/main.py` 只在末尾加了一行挂载，`routes.py` 未改动。

自测：`ONTOLOGY_URL=http://localhost:8700 python3 -m tests.test_timeseries`。

---

## 六、标识符约定

| 对象 | 标识依据 |
| --- | --- |
| 工段 | **工段编号本身**（`area-S01`）——编号是流程图口径的稳定键，可读且不会漂移 |
| 标准设备组 | 设备组 URI 哈希（`egrp-xxxxxxxx`） |
| 设备 | **OWL Subject URI**（`:Dev_13_水解罐A`），不用设备名 |
| 参数 | OWL Subject + 参数语义名称 |
| DCS 点 | 点名 |
| 关系 | 关系表自带的「关系ID」（R0001…）哈希；旧文件无该列时退回 `工段\|起始类型\|起始对象\|谓词\|目标类型\|目标对象\|子场景` |

设备名在不同工段会重复（1,340 个 OWL Subject 对应 1,190 个不同名称），
因此设备身份以 OWL Subject URI 为准，避免同名覆盖。关系的稳定键在关系详情面板中可见。

---

## 七、数据质量检查

导入时自动执行 17 项检查，只报告问题、不修改原始数据。当前结果：
**0 项错误，310 项告警，191 项提示**。典型发现：

- **Sheet1 与 Sheet2 点位数量不一致**——设备统计声明的点数与点位明细实际点数有出入；
- **一个参数语义对应多个 DCS 点**——例如 `离心机B1 / 稀碱进口控制阀指令` 同时绑定
  `XV_1018A_DO` 与 `XV_1027A_DO`；
- **同名设备跨工段重复**——同一设备名对应多个 OWL Subject；
- **Overview Sheet 声明的关系数量与关系明细实际数量不一致**；
- **人工映射条目待现场确认**。

这些问题一律保留原样上报，不做任何"修正"，报告可在前端「数据质量」页查看，
也可通过 `GET /api/ontology/data-quality` 获取。

---

## 八、可扩展性

- **换存储**：所有数据访问经过 `backend/ontology/indexes.py`，
  替换为 PostgreSQL / Neo4j / GraphDB / Jena 时前端 API 契约不变。
- **加数据源**：新增关系 Excel 只需在 `indexes.py` 中追加一个 loader；
  规则、约束、能力、模型注册的接口与空状态已就位，放入文件即生效。
- **接 AI Agent**：`/api/ontology/{id}/relations` 与 `/api/ontology/graph`
  可直接作为 Agent 的本体查询入口，返回体自带 `sourceType` 便于溯源。
- **接实时数据**：当前本体只包含知识结构，不含运行值、趋势、预测、健康度；
  运行时数据应作为独立数据服务接入，不混入本体实例数据。

---

## 九、已知限制

1. **对象映射需要现场确认。** 123 行映射全部是基于工段与工艺语义的推断，
   确认状态均为「待现场确认」。在现场核对之前，测量锚点部分不应作为正式依据。
2. **规则、约束、能力、模型注册四类数据源尚未提供**，页面显示空状态。
3. **离线演示页（`demo/`）没有资产本体页。** 资产导航树与对象本体档案只在 Vue 前端里，
   需要本体服务在线。Vue 前端已能通过 `npm run build`（含 `vue-tsc` 类型检查），
   并在 Chromium 中验证过导航树、搜索、档案与深链接。
