# 深冷装置本体 Demo v2（北I-2 深冷装置）

油气行业深冷装置（油气加工三大队 北I-2 深冷站：原料气压缩 + 分子筛脱水 + 膨胀机与丙烷辅助制冷）的工业本体界面 Demo。
在 6APA 本体 Demo v2 的界面上换了场景：导航为「装置 → 单元 → 画面（DCS 流程画面）→ 设备组 / 设备」，
设备信息按 9 个页签展示，并有**现象定义（带判定规则）**、**根因影响关系（现象导致现象）**、**计算组态**。
6APA 版的数据、种子与图纸存档在 `data/archive/6apa/`。

**口径：DCS 流程画面与点表为准**（设备编号、台数、位号含义）；操作规程是旧版，只在画面 / 点表没有的内容上作参考
（限值数值、PID 设定、开停车与故障处置步骤），这些条目一律「草案·待工艺确认」。本体梳理见 `docs/深冷装置本体梳理.md`。

## 单文件版（推荐用于展示）

`release/深冷装置本体Demo_v2.html` 是一个独立的 HTML 文件，**双击用 Chrome / Edge 打开即可**，不需要 Python、后端或网络，
可以直接拷给别人或发邮件。
- 包含全部导航、现场图纸、9 个页签、文档、其他分类，以及导出时预先算好的试算结果（模拟数据）；
- 现象和根因影响关系可以新增 / 编辑 / 删除，保存在当前浏览器里（顶栏「恢复种子数据」清除）；
- 局限：新写或改过的判定规则无法在单文件版里重新试算（会提示到完整版试算）；顶栏标有「单文件版 · 数据快照时间」。

改了数据或代码后重新生成（需要 Node.js 18+，约 2 分钟）：

```bash
python3 -m backend.tools.export_static --build
```

## 快速开始（完整版）

**Windows**：双击 `run_demo.bat`。窗口里依次检查 Python、依赖、数据、页面，后端就绪后自动打开浏览器
（<http://localhost:8710/>）。**不要关这个黑窗口**，关掉就停止 Demo。

- 只需要 Python 3.9+（安装时勾选「Add python.exe to PATH」）；前端页面已构建好放在 `frontend/dist`，不需要 Node.js；
- 首次运行会自动 `pip install -r requirements.txt`，公司网络装不上时手动加镜像：
  `python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`；
- 启动失败时窗口会停住并给出中文原因（端口被占用、缺依赖、缺文件等），截图即可定位；端口冲突可先 `set V2_PORT=8711`。

**Linux / macOS**：

```bash
./run_demo.sh            # 或 python3 start_demo.py
```

改前端代码时用开发模式（后端 8710 + vite 5180，需要 Node 18+），改完 `npm run build` 更新 `frontend/dist` 一并提交：

```bash
./run_demo.sh dev
```

## 使用

1. 左侧「空间层级」第一屏只有 **北I-2深冷装置** 和 6 个单元。**双击单元**（如 冷冻分离单元）进入单元内的层级树，顶部「返回装置导航」退回；
2. 单元内：**单击画面**选中看概览，**双击画面**（或点「进入」）打开图纸。14 张画面都有 DCS 流程画面截图，单击图上的设备 / 阀门打开它；
   紫色虚线框是对应关系靠推断的热区（如画面编号冲突）；循环水厂、ESD、可燃气体报警器、APC控制没有截图，显示本体示意图；
3. 画面下直接是设备组 / 设备（阀门按画面归到「××阀门」组）。**计算组态、算法库、工况与根因、文档提取**是全局的，挂在「北I-2深冷装置」下；
4. 选中设备或设备组，右侧按页签显示：图纸位置与外观、参数、拓扑关系、参数约束、现象/工况定义、根因影响关系、工艺影响关系、计算组态、处置规程；
5. **现象定义**：判定规则（与 / 或嵌套，条件 = 参数 运算 阈值 持续时长，阈值可引用工艺限值），可新增、编辑、在模拟数据上试算；
   设备组上的现象（如 膨胀压缩机组「膨胀机振动高」）对组内每台分别判定；
6. **根因影响关系**：「A 现象 导致 B 现象」，列表或关系图谱；点结果现象可逐层往上追；
7. 顶栏「全局图谱」：整个本体一张图。

推荐演示路径：冷冻分离单元 → 冷冻单元（图纸）→ 脱甲烷塔 → 现象/工况定义（试算「脱甲烷塔顶温度过低（CO2冻塔先兆）」）
→ 根因影响关系；冷冻分离单元 → 1号膨胀机 → 1#膨胀压缩机 → 现象「膨胀机停机」看导致链（压缩机停机 ← 轴振动高 / 轴承温度高）。

> 试算用的测点数据由内置模拟器生成，界面上标「模拟数据」：有限值的按限值正常区间、没有的按点表量程或 `data/config/模拟基准.json`
> （只给模拟器用，不是工艺限值）。现象、导致关系、计算组态、限值都是「草案·待工艺确认」。

## 目录

```
6apa-demo-v2/
├── README.md / CLAUDE.md
├── run_demo.bat / run_demo.sh / start_demo.py   启动（bat 只负责找 Python，检查与启动都在 start_demo.py）
├── requirements.txt
├── data/
│   ├── cryo/         深冷本体梳理：source/（DCS 点表、操作规程原件）、北I-2深冷_本体.xlsx（本体梳理成果）
│   ├── source/       Demo 数据源（由本体梳理生成，结构同 6APA 版）：DCS、工业关系、工艺限值、能力、处置规程
│   ├── config/       空间层级.xlsx（装置 / 单元 / 画面，表名沿用 车间 / 工艺段 / 工序）、设备设计参数.xlsx、算法库.json、模拟基准.json
│   ├── seed/         现象、根因关系、计算组态的种子数据（JSON）
│   ├── drawings/     现场图纸：DCS 画面截图 + 同名 JSON 热区（14 张）
│   ├── archive/6apa/ 6APA 版的数据源、配置、种子、图纸、生成脚本、单文件版（只读存档）
│   └── store/        运行时编辑结果（不进 git，首次启动从 seed 复制）
├── backend/
│   ├── main.py       FastAPI 入口（8710），托管 frontend/dist
│   ├── api/routes.py /api/v2 接口
│   ├── v2/           层级、图纸、页签、现象 / 根因、判定规则求值、计算组态、模拟数据、文档
│   ├── ontology/ services/   本体加载代码（复制自原 Demo；dcs_loader 加了量程列与 0 点设备）
│   └── tools/        cryo_knowledge.py（人工梳理的本体知识）、build_cryo_ontology.py（本体梳理 Excel）、
│                     build_cryo_sources.py（数据源与配置）、build_cryo_seed.py（种子）、build_cryo_drawings.py（图纸热区）、
│                     export_static.py（单文件版）
├── frontend/         Vue 3 + Vite + Tailwind + ECharts（浅色主题；src/api/static.ts = 单文件版的浏览器内「后端」）
├── release/          深冷装置本体Demo_v2.html：单文件版
├── docs/
│   ├── 设计说明.md         界面、数据模型、判定规则语义、待确认项
│   ├── 深冷装置本体梳理.md  本体梳理口径与 Excel 各 sheet 说明
│   └── source-docs/       北I-2装置操作规程（旧版，转成 Markdown，供「文档提取」查看原文）
└── tests/test_v2.py
```

## 测试

```bash
python3 -m unittest tests.test_v2 -v
cd frontend && npm run build   # 含 vue-tsc 类型检查
```

## 重新生成（离线整理工具，需要 openpyxl、python-docx、Pillow）

```bash
python3 -m backend.tools.build_cryo_ontology      # 本体梳理 data/cryo/北I-2深冷_本体.xlsx
python3 -m backend.tools.build_cryo_sources       # data/source/*.xlsx、data/config/空间层级.xlsx、设备设计参数.xlsx
python3 -m backend.tools.build_cryo_seed --force  # data/seed/*.json（不影响 data/store 里的编辑）
python3 -m backend.tools.build_cryo_drawings      # data/drawings/（截图取自仓库根目录 深冷装置工艺流程图/）
```

改本体内容（设备、拓扑、联锁、现象…）改 `backend/tools/cryo_knowledge.py`，再依次重新生成；改了 seed 要删掉 `data/store/*.json` 才生效。

界面顶栏「恢复种子数据」会把 data/store 还原为种子数据。

## 主要接口

| 接口 | 说明 |
|---|---|
| `GET /api/v2/nav/space` | 装置 → 单元 |
| `GET /api/v2/nav/segment/{SEG}` | 单元内的层级树 |
| `GET /api/v2/nav/domain/{key}?parent=` | 其他分类（工业资产、工艺参数…） |
| `GET /api/v2/drawings/{OP}/image` | 现场图纸图片 |
| `GET /api/v2/ops/{OP}` · `/drawing` · `/conditions` · `/calculations` · `/documents` | 画面概览、图纸、工况与根因、计算组态、文档提取 |
| `GET /api/v2/objects/{id}?op=` · `/tabs/{key}?op=` | 设备 / 设备组头部与 9 个页签 |
| `GET/POST /api/v2/phenomena` · `GET/PUT/DELETE /api/v2/phenomena/{id}` | 现象 |
| `GET /api/v2/phenomena/{id}/chain?direction=up|down` | 由什么导致 / 会导致什么 |
| `POST /api/v2/phenomena/{id}/evaluate` · `POST /api/v2/rules/evaluate` | 试算（已保存的现象 / 未保存的规则） |
| `GET/POST /api/v2/causal-links` · `PUT/DELETE /api/v2/causal-links/{id}` | 根因影响关系 |
| `GET/POST /api/v2/calculations` · `POST /api/v2/calculations/{id}/run` | 计算组态与试算 |
| `GET /api/v2/global-graph` | 全局图谱（全部节点与关系） |
| `GET /api/v2/search?keyword=` | 搜索画面 / 设备组 / 设备 / 位号 / 现象 |
