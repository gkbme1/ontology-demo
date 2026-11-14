# 6apa-demo-v2：项目上下文（给新会话的交接说明）

国药威奇达 105 车间工业本体界面 Demo 第二版。需求原文：车间 → 工艺段 → 工序（P&ID）导航；设备 / 设备组 9 个页签；
现象（带判定规则）与根因影响关系（现象导致现象）。设计细节见 `docs/设计说明.md`，使用见 `README.md`。

## 工作约定

- 本 Demo 的最新代码在分支 `claude/quirky-ritchie-2awtw4`；新会话先从该分支切出自己的开发分支（或直接在其上继续）。
- 当前场景是国药威奇达 105 车间（6APA）。曾切换过的油气深冷（北I-2）场景版本保存在提交 `501bc3e`，需要时从 git 历史取回。

- 用中文汇报。用户说「先澄清 / 只分析 / 不需要修改代码」时不改代码；否则认可的方案直接实现。
- **只改 `6apa-demo-v2/` 里的文件**。仓库里的 `6apa-ontology-demo/`、`6apa-agent-demo/`、根目录文件都只读参考；
  需要复用就复制进本目录再改，不跨目录 import 或引用。
- 提交后推送到指定开发分支，不主动建 PR。提交信息、代码里不写模型名称。
- 不编造现场数据：种子数据一律标「草案·待工艺确认」，占位阈值在 note 里写「占位阈值，待现场提供」。
- 模拟数据必须声明是模拟的（接口带 `dataSource.simulated`，前端标「模拟数据」）。

## 架构

- 后端 FastAPI，端口 **8710**（`V2_PORT`），入口 `backend/main.py`，接口都在 `/api/v2`（`backend/api/routes.py`）；
  `frontend/dist` 存在时由后端一并托管。
- 前端 Vue 3 + Vite + Tailwind + ECharts，开发端口 **5180**，`/api` 代理到 8710。端口都避开原 Demo（8700 / 5173 / 8800 / 8900）。
- `backend/ontology/`、`backend/services/`：**原样复制**自原 Demo 的本体加载代码（`OntologyStore`、`asset_model.profile` 等），
  尽量不改；v2 逻辑全部在 `backend/v2/`：

| 模块 | 职责 |
|---|---|
| `context.py` | `AppContext` 单例：OntologyStore + 层级 + 现象仓库 + 计算组态仓库 + 位号 / 限值索引 + 档案缓存 |
| `hierarchy.py` | 读 `data/config/6APA_空间层级.xlsx`，设备按「工段编号 + 设备匹配正则」归到工序 |
| `nav.py` | 左侧树：空间层级、工艺段内树、其他分类（复用 `asset_model.tree`） |
| `drawing.py` | 工序图纸：现场图纸（`data/drawings/<OP>.json` 热区按设备名落到对象）+ 本体示意图（设备组 + 物理拓扑 + 进出物料，分层布局） |
| `tabs.py` | 9 个页签（「参数 · 仪表」合并：基本信息 / 设计参数 / 工艺属性 / 测量 / 状态 / 控制） |
| `phenomena.py` | 现象 / 根因关系的模型、校验、JSON 持久化、导致链追溯 |
| `rule_eval.py` | 判定规则求值（逐台、持续时长、与 / 或、change）、计算组态试算 |
| `calculations.py` | 计算组态 = 作用范围 + 引用算法（algorithmId）+ 参数绑定（bindings），不写算法本身 |
| `algorithms.py` | 算法库（`data/config/6APA_算法库.json` 的调用契约）+ 内置实现（代替算法服务） |
| `simulator.py` | 确定性模拟数据 |
| `design_params.py` | 设备设计参数（`data/config/6APA_设备设计参数.xlsx`，`build_design_params.py` 生成；值未填显示待补充） |
| `global_graph.py` | 全局图谱数据（层级 / 设备 / 参数 / 物料 / 现象 + 7 类关系），前端 `views/GlobalGraph.vue` 用 ECharts 渲染 |
| `documents.py` | 文档提取（规程文档登记 + 数据源统计） |
| `search.py` | 全局搜索：静态索引（`ctx.search_index()`，单文件版导出同一份）+ 现象现算；拼音首字母用 pypinyin |
| `validation.py` | 一致性校验（需求 SW-059），`GET /api/v2/validation`，左侧树「一致性校验」 |
| `userdata.py` | 在线编辑的补充数据（`data/store/` 下，无种子）：变更记录 `audit.json`、继承覆盖 `overrides.json`、人工关系 `user_relations.json`、处置规程编辑 `procedure_edits.json` |
| `procedures.py` | 处置规程视图：按现象 / 导致关系的 source.ref、basis（`ARP-xx 可能原因 n` 或 `ARP-xx #n`）匹配拆分状态；拆分可能原因；步骤 / 检查项 / 执行边界 |

- 数据：`data/source/*.xlsx`（复制来的数据源）→ `data/config/`（层级配置，`build_config.py` 生成）→
  `data/seed/*.json`（`build_seed.py` 生成，已存在不覆盖，`--force` 覆盖）→ `data/store/*.json`（运行时编辑，不进 git；
  测试用 `V2_STORE_DIR` 指到临时目录）。改了 seed 生成逻辑后要 `--force` 重新生成并删掉 `data/store/*.json` 才生效。

## Windows 运行注意

- `run_demo.bat` 必须保持**纯 ASCII + CRLF**（`.gitattributes` 已约束），中文提示放在 `start_demo.py` 里；
- `requirements.txt` 保持纯 ASCII：中文 Windows 上 pip 按 GBK 读它，含 UTF-8 中文会解码失败；
- `backend/main.py` 里强制注册 `.js → text/javascript` 等 MIME：Windows 注册表常把 .js 登记成 text/plain，页面会一片空白；
- `frontend/dist` 是提交进仓库的（用户机器不一定有 Node.js）：改了前端必须 `npm run build` 并提交 dist。

## 单文件版

- `release/6APA本体Demo_v2.html` 由 `python3 -m backend.tools.export_static --build` 生成：前端 `--mode single` 内联成一个 HTML，
  后端用**种子数据**跑一遍，把只读接口应答、试算结果、图纸 data URL 打包（JSON → gzip → base64）注入 `<script id="v2-data">`；
- 前端 `src/api/static.ts`：有内嵌数据时 `client.ts` 的请求全部走它。只读接口查表（键 = 路径?参数排序、不编码，
  与 `export_static.key()` 一致）；现象 / 根因关系在浏览器里现算并存 localStorage；试算只认导出时的规则；
- **新增前端会请求的只读接口时，要在 `export_static.py` 里同步收集**，否则单文件版会报「未包含该数据」；
  改了数据、种子或前端后要重新导出并提交 release 文件。
- 主题为浅色：颜色在 `tailwind.config.js`（ink / line / fg 等），SVG / 图表里的颜色写在各组件内。

## 结构口径

- 左侧树图标在 `frontend/src/components/NodeIcon.vue`：按节点类型给图标；设备按名称关键字（罐 / 泵 / 离心机 / 阀…）选，其他分类按所在分类选。

- 工序下直接是设备组 / 设备；计算组态、算法库、工况与根因、文档提取是全局的（`/api/v2/scope/*?seg=&op=`、`/api/v2/algorithms`），
  挂在左侧树「105车间」下（工艺段之后）；设备页签只显示与本对象相关的条目（页签名：现象/工况定义、计算组态）。

## 需求对齐（系统需求规格 V0.5）

- 对照需求逐批优化 Demo，计划与已完成项见 `docs/需求对齐计划.md`（第 1～3 批已完成）；开发态修改触发工程态更新的联动不做。
- 参数页签：`section` 属性 / 参数，`category` 按位号 `variableCategory` / 块类型归类（`tabs._param_category`），`binding` 绑定状态（`tabs._binding`）。
- 继承覆盖：设备上的覆盖存 `ctx.overrides`；`rule_eval.evaluate(..., phenomenon_id=)` 逐台套用覆盖规则 / 禁用，`threshold(th, target)` 取本台覆盖限值。
- 计算组态：`execution`（周期 / 事件触发 / 按需…）与 `output`（输出测点、写回）在 `calculations._clean` 校验并补默认值；
  绑定引用的参数 / 位号在 `routes._check_calc_refs` 校验；运行记录 `ctx.calcs.log_run`（内存）。
- 写操作都经 `routes._audit` / `ctx.audit.record` 记变更；新写接口要记一条。单文件版对覆盖 / 人工关系只读（`static.ts` 把 `canEdit / canOverride` 置 false）。
- 状态口径：现象 / 导致关系 / 计算组态 = 草案·待工艺确认 / 生效 / 停用（旧数据「已确认」读入时转「生效」）；层级配置表的「已确认」不变。
- 页签顺序同需求 SW-041：图纸位置与外观、参数、参数约束、拓扑关系、现象/工况定义、根因影响关系、工艺影响关系、计算组态、处置规程；
  页头 `counts` 给出全部页签条目数。「继承」列改为「来源」（类 / 设备组 / 本对象），`InheritBox.vue`。
- 图纸：单击显示摘要、双击打开对象详情（`DrawingView.vue`，`PidCanvas` 发 select / pick 两个事件）。
- 单文件版的 `static.ts` 要同步实现：搜索打分（与 `search.score` 一致）、因果环路（`inCycle` / 新增时 `warnings`）、页签计数。

## 关键口径

- 工序 = 一张 DCS 流程画面；子工序写在图纸上，不单独成层。工序下直接是设备组 / 设备（计算组态等已移到全局，见上节）。
- 设备组是文件夹，成员可分属两道工序（水解 A-F / G-K、结晶北排 / 南排），各工序只列本工序认领的成员。
- 点表台号跳过 I：水解罐I/J/K 的氨水计量罐写作 J/K/L（`水解G-K` 的匹配正则已处理）。
- 现象挂在设备组上时对组内每台分别判定；`parameter` 主体通过 `asset_model.profile` 的属性 dataLinks 落到本台测点。
- 同一位号落到多条限值时（如 TI_1303），模拟器优先取与位号同工段的限值。

## 回归测试

```bash
python3 -m unittest tests.test_v2 -v      # 不需要外部服务
cd frontend && npm run build              # vue-tsc 类型检查 + 构建
```

## 已知问题 / 待确认

见 `docs/设计说明.md` 第 7 节与 1.4（水解A-F 画面与点表的位号核对项）：北排 / 南排拆分、结晶罐多种写法未归并、只有水解A-F 有原图、「反应期」近似、
试算用模拟数据且限值按 V0 取值、组织与人员 / 能源无数据源。
