# 6APA 本体 Demo v2

国药威奇达 105 车间（6-APA 原料药合成）工业本体界面 Demo，第二版。

与第一版（`../6apa-ontology-demo`）的区别：按「车间 → 工艺段 → 工序（P&ID）→ 装置 → 设备组 / 设备」重新组织导航，
设备信息按 10 个页签展示，并新增**现象定义（带判定规则）**、**根因影响关系（现象导致现象）**、**计算组态**三块。
本目录自成一体：数据与需要复用的代码都已复制进来，不引用原 Demo 的任何文件。

## 单文件版（推荐用于展示）

`release/6APA本体Demo_v2.html` 是一个独立的 HTML 文件，**双击用 Chrome / Edge 打开即可**，不需要 Python、后端或网络，
可以直接拷给别人或发邮件。

- 包含全部导航、现场图纸、10 个页签、文档、其他分类，以及导出时预先算好的试算结果（模拟数据）；
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

1. 左侧「空间层级」第一屏只有 **105车间** 和 6 个工艺段。**双击工艺段**（如 6A_水解）进入工艺段内的层级树，顶部「返回车间导航」退回；
2. 工艺段内：**单击工序**选中看概览，**双击工序**（或点「进入」）打开图纸。水解A-F 显示现场流程画面，单击图上的设备打开它；
   其余工序暂无原图，显示本体示意图（顶部写子工序）；
3. 工序下有 4 个节点：**装置**（设备组 / 设备）、**计算组态**、**工况与根因**、**文档提取**；
4. 选中设备或设备组，右侧按页签显示：图纸位置与外观、参数、仪表、参数约束、拓扑关系、现象定义、根因影响关系、工艺影响关系、计算/指标、处置规程；
5. **现象定义**：每个现象有判定规则（与 / 或任意嵌套，条件 = 参数 运算 阈值 持续时长，阈值可引用工艺限值），可新增、编辑、在模拟数据上试算；
6. **根因影响关系**：一条记录 = 「A 现象 导致 B 现象」，列表或关系图谱展示。点一个结果现象，弹窗查看它由哪些现象导致（可逐层往上追）。

推荐演示路径：6A_水解 → 水解A-F → 水解罐C → 现象定义（试算「水解罐pH偏高」，编辑「反应期搅拌停止」看嵌套规则）
→ 根因影响关系 → 点「水解终点异常 / 氨耗偏低」看导致链。

> 试算用的测点数据由内置模拟器生成，界面上标「模拟数据」。现象、导致关系、计算组态的种子数据都是「草案·待工艺确认」。

## 目录

```
6apa-demo-v2/
├── README.md / CLAUDE.md
├── run_demo.bat / run_demo.sh / start_demo.py   启动（bat 只负责找 Python，检查与启动都在 start_demo.py）
├── requirements.txt
├── data/
│   ├── source/       复制自原 Demo 的 Excel 数据源（点表、工业关系、限值、规则、处置规程…）
│   ├── config/       6APA_空间层级.xlsx：车间 / 工艺段 / 工序 定义与设备归属规则
│   ├── seed/         现象、根因关系、计算组态的种子数据（JSON）
│   ├── drawings/     现场图纸：图片 + 同名 JSON 热区（目前只有 OP-09 水解A-F）
│   └── store/        运行时编辑结果（不进 git，首次启动从 seed 复制）
├── backend/
│   ├── main.py       FastAPI 入口（8710），托管 frontend/dist
│   ├── api/routes.py /api/v2 接口
│   ├── v2/           本 Demo 新写的逻辑：层级、图纸、页签、现象 / 根因、判定规则求值、计算组态、模拟数据、文档
│   ├── ontology/ services/   复制自原 Demo 的本体加载代码（原样，见 services/README.md）
│   └── tools/        build_config.py（层级配置表）、build_seed.py（种子数据）、export_static.py（单文件版）
├── frontend/         Vue 3 + Vite + Tailwind + ECharts（浅色主题；src/api/static.ts = 单文件版的浏览器内「后端」）
├── release/          6APA本体Demo_v2.html：单文件版
├── docs/
│   ├── 设计说明.md    界面、数据模型、判定规则语义、待确认项
│   └── source-docs/  规程类文档（SOP-S11-ALARM-001，模拟规程）
└── tests/test_v2.py
```

## 测试

```bash
python3 -m unittest tests.test_v2 -v
cd frontend && npm run build   # 含 vue-tsc 类型检查
```

## 重新生成配置与种子

```bash
python3 -m backend.tools.build_config --force   # 覆盖 data/config/6APA_空间层级.xlsx
python3 -m backend.tools.build_seed --force     # 覆盖 data/seed/*.json（不影响 data/store 里的编辑）
```

界面顶栏「恢复种子数据」会把 data/store 还原为种子数据。

## 主要接口

| 接口 | 说明 |
|---|---|
| `GET /api/v2/nav/space` | 车间 → 工艺段 |
| `GET /api/v2/nav/segment/{SEG}` | 工艺段内的层级树 |
| `GET /api/v2/nav/domain/{key}?parent=` | 其他分类（工业资产、工艺参数…） |
| `GET /api/v2/drawings/{OP}/image` | 现场图纸图片 |
| `GET /api/v2/ops/{OP}` · `/drawing` · `/conditions` · `/calculations` · `/documents` | 工序概览、图纸、工况与根因、计算组态、文档提取 |
| `GET /api/v2/objects/{id}?op=` · `/tabs/{key}?op=` | 设备 / 设备组头部与 10 个页签 |
| `GET/POST /api/v2/phenomena` · `GET/PUT/DELETE /api/v2/phenomena/{id}` | 现象 |
| `GET /api/v2/phenomena/{id}/chain?direction=up|down` | 由什么导致 / 会导致什么 |
| `POST /api/v2/phenomena/{id}/evaluate` · `POST /api/v2/rules/evaluate` | 试算（已保存的现象 / 未保存的规则） |
| `GET/POST /api/v2/causal-links` · `PUT/DELETE /api/v2/causal-links/{id}` | 根因影响关系 |
| `GET/POST /api/v2/calculations` · `POST /api/v2/calculations/{id}/run` | 计算组态与试算 |
| `GET /api/v2/search?keyword=` | 搜索工序 / 设备组 / 设备 / 位号 / 现象 |
