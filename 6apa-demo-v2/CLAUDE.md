# 6apa-demo-v2：项目上下文（给新会话的交接说明）

工业本体界面 Demo 第二版，**当前场景：油气深冷装置（北I-2 深冷装置）**。原为国药威奇达 105 车间（6-APA），6APA 版数据存档在 `data/archive/6apa/`。
导航：装置 → 单元 → 画面（DCS 流程画面）→ 设备组 / 设备；设备 / 设备组 9 个页签；现象（带判定规则）与根因影响关系（现象导致现象）。
设计细节见 `docs/设计说明.md`，本体梳理见 `docs/深冷装置本体梳理.md`，使用见 `README.md`。

**口径（用户确认）：DCS 流程画面与点表为准**；操作规程是旧版，只在画面 / 点表没有的内容上作参考（限值数值、PID 设定、处置步骤），
这些条目一律「草案·待工艺确认」，依据写「规程（旧版）」。

## 工作约定

- 本 Demo 的最新代码在分支 `claude/quirky-ritchie-2awtw4`；新会话先从该分支切出自己的开发分支（或直接在其上继续）。

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
| `hierarchy.py` | 读 `data/config/空间层级.xlsx`，设备按「工段编号 + 设备匹配正则」归到画面（工序） |
| `nav.py` | 左侧树：空间层级、工艺段内树、其他分类（复用 `asset_model.tree`） |
| `drawing.py` | 工序图纸：现场图纸（`data/drawings/<OP>.json` 热区按设备名落到对象）+ 本体示意图（设备组 + 物理拓扑 + 进出物料，分层布局） |
| `tabs.py` | 9 个页签（「参数 · 仪表」合并：基本信息 / 设计参数 / 工艺属性 / 测量 / 状态 / 控制） |
| `phenomena.py` | 现象 / 根因关系的模型、校验、JSON 持久化、导致链追溯 |
| `rule_eval.py` | 判定规则求值（逐台、持续时长、与 / 或、change）、计算组态试算 |
| `calculations.py` | 计算组态 = 作用范围 + 引用算法（algorithmId）+ 参数绑定（bindings），不写算法本身 |
| `algorithms.py` | 算法库（`data/config/算法库.json` 的调用契约）+ 内置实现（代替算法服务） |
| `simulator.py` | 确定性模拟数据（无限值时按点表量程或 `data/config/模拟基准.json` 取值；报警 / 故障类开关量平时为 0） |
| `design_params.py` | 设备设计参数（`data/config/设备设计参数.xlsx`；设备位号取画面编号，其余待补充） |
| `global_graph.py` | 全局图谱数据（层级 / 设备 / 参数 / 物料 / 现象 + 7 类关系），前端 `views/GlobalGraph.vue` 用 ECharts 渲染 |
| `documents.py` | 文档提取（规程文档登记 + 数据源统计） |

- 数据链（离线工具在 `backend/tools/`，需要 openpyxl、python-docx、Pillow，Demo 运行时不需要）：
  `data/cryo/source/`（DCS 点表、操作规程原件）+ 仓库根目录 `深冷装置工艺流程图/`（只读）
  → `cryo_knowledge.py`（人工梳理：单元、画面、设备、拓扑、回路、联锁、现象…）+ `build_cryo_ontology.py`（位号自动归属）
  → `data/cryo/北I-2深冷_本体.xlsx`（本体梳理成果）
  → `build_cryo_sources.py` → `data/source/*.xlsx`（DCS、工业关系、工艺限值、能力、处置规程，结构同 6APA 版）+ `data/config/空间层级.xlsx`、`设备设计参数.xlsx`
  → `build_cryo_seed.py` → `data/seed/*.json`（已存在不覆盖，`--force` 覆盖）→ `data/store/*.json`（运行时编辑，不进 git；测试用 `V2_STORE_DIR`）。
  `build_cryo_drawings.py` 生成 `data/drawings/`（截图 + 热区，`--overlay <目录>` 出核对图）。改了 seed 要删掉 `data/store/*.json` 才生效。
- 数据文件名已去掉 `6APA_` 前缀（`DCS.xlsx`、`工业关系.xlsx`、`空间层级.xlsx`、`算法库.json`…）。

## Windows 运行注意

- `run_demo.bat` 必须保持**纯 ASCII + CRLF**（`.gitattributes` 已约束），中文提示放在 `start_demo.py` 里；
- `requirements.txt` 保持纯 ASCII：中文 Windows 上 pip 按 GBK 读它，含 UTF-8 中文会解码失败；
- `backend/main.py` 里强制注册 `.js → text/javascript` 等 MIME：Windows 注册表常把 .js 登记成 text/plain，页面会一片空白；
- `frontend/dist` 是提交进仓库的（用户机器不一定有 Node.js）：改了前端必须 `npm run build` 并提交 dist。

## 单文件版

- `release/深冷装置本体Demo_v2.html` 由 `python3 -m backend.tools.export_static --build` 生成：前端 `--mode single` 内联成一个 HTML，
  后端用**种子数据**跑一遍，把只读接口应答、试算结果、图纸 data URL 打包（JSON → gzip → base64）注入 `<script id="v2-data">`；
- 前端 `src/api/static.ts`：有内嵌数据时 `client.ts` 的请求全部走它。只读接口查表（键 = 路径?参数排序、不编码，
  与 `export_static.key()` 一致）；现象 / 根因关系在浏览器里现算并存 localStorage；试算只认导出时的规则；
- **新增前端会请求的只读接口时，要在 `export_static.py` 里同步收集**，否则单文件版会报「未包含该数据」；
  改了数据、种子或前端后要重新导出并提交 release 文件。
- 主题为浅色：颜色在 `tailwind.config.js`（ink / line / fg 等），SVG / 图表里的颜色写在各组件内。

## 结构口径

- 界面文案：装置 / 单元 / 画面（代码与配置表里仍叫 workshop / segment / op、车间 / 工艺段 / 工序）；原「跨装置」改为「跨设备」，画面下的节点叫「设备」。
- 左侧树图标在 `frontend/src/components/NodeIcon.vue`：设备按名称关键字（压缩机 / 膨胀 / 塔 / 分离器 / 空冷器 / 阀 / 管线…）选。
- 画面下直接是设备组 / 设备；阀门按画面归到「××阀门」组；计算组态、算法库、工况与根因、文档提取是全局的，挂在左侧树「北I-2深冷装置」下。

## 关键口径

- 工段编号 = 画面：S01 集配气 … S15 循环水厂、S16 ESD、S17 可燃气体报警器、S18 APC控制、S99 系统与未归属点（不进导航）；
  1号 / 2号膨胀机两张画面共用 S08，按名称 `^1#` / `^2#` 认领，膨胀压缩机组是两张画面共用的文件夹。
- 设备编号以画面为准（规程编号作别名）；同组各台参数同名（去台号），组上的现象逐台判定。
- 画面上有、点表无测点的设备在 `设备统计` 里声明（总点位数 0），`dcs_loader` 会建成 0 点设备。
- 工艺限值都挂点表位号（`DCS点`），同位号的运行区间与报警值合并成 `PL-<位号>`；开车 `-S`、控制设定 `-C`、热吹 / 冷吹 `-R`。
- 热区对应靠推断的标 `confirmed: false`（虚线框），见 `build_cryo_drawings.INFERRED`。
- 现场异常排查表（现象 → 排查方式 → 处置方式）的转法：现象建在点位所属设备上；每条排查 = 原因现象（规则落到要看的位号）+ 「导致」关系；
  处置方式进处置卡（阶段 排查 / 处置 / 汇报）。示例 PH-36～42、CALC-07/08、ARP-09（`cryo_knowledge.PHENOMENA/CAUSAL`、`build_cryo_seed`、`build_cryo_sources.write_procedures`）。
- 从图纸 / 图谱打开对象：`openObject` 按 `meta.opSegment` 把左侧树切到对象所在单元，`NavPanel.expandKeys` 沿树找祖先节点展开，`TreeNode` 滚到选中行。

## 回归测试

```bash
python3 -m unittest tests.test_v2 -v      # 不需要外部服务
cd frontend && npm run build              # vue-tsc 类型检查 + 构建
```

## 已知问题 / 待确认

见 `docs/设计说明.md` 第 7 节与本体梳理 Excel「待确认」：点表报警限当前值为 0（暂用规程旧版数值）、无描述通讯点未纳入、
同名 VAL2 / MOT2 阀门合并、全局图谱「工艺流程」视图只画组间拓扑（深冷多为设备间）、运行上下文未接入、组织与人员 / 能源无数据源。
